"""Per-run composition for Celina's bounded search orchestration."""

import json
import threading

import gateway
import orchestrator
import redaction
import scanner
import tokens
import tools
import traffic
import verification


_FALLBACK_ANSWER = (
    "Celina could not produce a structured answer from the read evidence."
)


class SearchRuntime:
    """Build the real, shared dependencies for one bounded search run."""

    def __init__(
        self,
        event_bus,
        session_store,
        *,
        chat_fn=None,
        scan_fn=None,
        fetch_fn=None,
        recorder=None,
        redactor=None,
        accountant_factory=None,
        verifier_factory=None,
    ):
        self.event_bus = event_bus
        self.session_store = session_store
        self.chat_fn = chat_fn or gateway.chat
        self.scan_fn = scan_fn or scanner.scan
        self.fetch_fn = fetch_fn or tools.fetch
        self.recorder = recorder or traffic.TrafficRecorder(session_store)
        self.redactor = redactor or redaction.Redactor()
        self.accountant_factory = accountant_factory or tokens.TokenAccountant
        self.verifier_factory = verifier_factory or verification.Verifier
        self._engines = {}
        self._contexts = {}
        self._accountants = {}
        self._lock = threading.RLock()

    def start(self, request):
        """Start a run with adapters that all close over one TrafficContext."""
        if not isinstance(request, orchestrator.SearchRequest):
            raise TypeError("request must be a SearchRequest")
        if self.session_store.get(request.session_id) is None:
            raise KeyError("unknown session")

        run = orchestrator.SearchRun.create(
            request.session_id,
            request.query.strip(),
        )
        context = traffic.TrafficContext(
            session_id=request.session_id,
            run_id=run.run_id,
            correlation_id=run.run_id,
            recorder=self.recorder,
            redactor=self.redactor,
            cancellation=run._cancellation,
        )
        accountant = self.accountant_factory(self.session_store, request.session_id)
        engine = orchestrator.SearchOrchestrator(
            event_bus=self.event_bus,
            planner=self._planner(request, context, accountant),
            retriever=self._retriever(context),
            reader=self._reader(context),
            gap_checker=self._gap_checker(request, context, accountant),
            synthesizer=self._synthesizer(request, context, accountant),
            verifier=self.verifier_factory(),
        )
        with self._lock:
            if any(
                item.session_id == request.session_id
                and item.state not in {"completed", "stopped", "failed"}
                for item in self._runs()
            ):
                raise RuntimeError("session already has an active search run")
            self._engines[run.run_id] = engine
            self._contexts[run.run_id] = context
            self._accountants[run.run_id] = accountant
        try:
            return engine.start(request, run=run)
        except Exception:
            with self._lock:
                self._engines.pop(run.run_id, None)
                self._contexts.pop(run.run_id, None)
                self._accountants.pop(run.run_id, None)
            raise

    def get(self, run_id):
        engine = self._engine_for(run_id)
        return engine.get(run_id)

    def wait(self, run_id, timeout=None):
        engine = self._engine_for(run_id)
        return engine.wait(run_id, timeout)

    def stop(self, run_id):
        engine = self._engine_for(run_id)
        return engine.stop(run_id)

    def traffic_context(self, run_id):
        with self._lock:
            context = self._contexts.get(run_id)
        if context is None:
            raise KeyError("unknown search run")
        return context

    def token_accountant(self, run_id):
        with self._lock:
            accountant = self._accountants.get(run_id)
        if accountant is None:
            raise KeyError("unknown search run")
        return accountant

    def _runs(self):
        for engine in self._engines.values():
            yield from engine._runs.values()

    def _engine_for(self, run_id):
        with self._lock:
            engine = self._engines.get(run_id)
        if engine is None:
            raise KeyError("unknown search run")
        return engine

    def _planner(self, request, context, accountant):
        def plan(_request):
            try:
                payload = self._provider_json(
                    request.provider,
                    context,
                    accountant,
                    """Return strict JSON only. Plan public search actions without """
                    """hidden reasoning or chain-of-thought. The JSON object must """
                    """contain direct_query (exactly the user's question), """
                    """additional_queries (an array of at most four focused public """
                    """queries), evidence_angles (an array of public evidence angles), """
                    """and summary (one concise public plan summary).""",
                    request.query,
                )
                return _validated_plan(payload, request.query)
            except Exception:
                return {"queries": [], "angles": [], "summary": ""}

        return plan

    def _retriever(self, context):
        def retrieve(query, query_id, _request, cancellation):
            _ensure_active(context, cancellation)
            result = self.scan_fn(query, traffic_context=context)
            _ensure_active(context, cancellation)
            rows = result.get("results", ()) if isinstance(result, dict) else ()
            normalized = []
            for item in rows:
                if isinstance(item, dict):
                    normalized.append({**item, "query_id": query_id})
            return normalized

        return retrieve

    def _reader(self, context):
        def read(candidate, _request, cancellation):
            _ensure_active(context, cancellation)
            page = self.fetch_fn(candidate.url, traffic_context=context)
            _ensure_active(context, cancellation)
            if not isinstance(page, dict):
                raise ValueError("page reader returned an invalid result")
            text = str(page.get("text") or "").strip()
            content_type = str(page.get("content_type") or "text/plain")
            if not text:
                raise ValueError("page reader returned an empty body")
            if content_type.lower() == "search/snippet":
                raise ValueError("search-result snippets are not readable pages")
            if candidate.snippet and text == candidate.snippet.strip():
                raise ValueError("search-result snippets are not readable pages")
            return {"text": text, "content_type": content_type}

        return read

    def _gap_checker(self, request, context, accountant):
        def check(_request, evidence_rows, angles):
            try:
                payload = self._provider_json(
                    request.provider,
                    context,
                    accountant,
                    """Return strict JSON only, with covered_angles, gaps, conflicts, """
                    """and follow_up_query. Assess only the supplied read evidence and """
                    """public evidence angles. Use at most one follow-up query and name """
                    """the missing evidence angle in it. Do not provide hidden reasoning """
                    """or chain-of-thought.""",
                    json.dumps({
                        "question": request.query,
                        "evidence_angles": list(angles),
                        "read_evidence": _evidence_payload(evidence_rows),
                    }, ensure_ascii=False),
                )
                return _validated_gaps(payload)
            except Exception:
                return {"covered_angles": [], "gaps": [], "conflicts": []}

        return check

    def _synthesizer(self, request, context, accountant):
        def synthesize(_request, evidence_rows, _gaps):
            try:
                payload = self._provider_json(
                    request.provider,
                    context,
                    accountant,
                    """Return strict JSON only, with answer, claims, citations, """
                    """uncertainties, conflicts, and gaps. Use only the supplied read """
                    """evidence and its stable citation IDs. Claims must contain claim_id, """
                    """text, and citation_ids. citations must be a flat array of the """
                    """citation ID strings actually used, not objects. Respond with the """
                    """raw JSON object only - no markdown code fences and no prose """
                    """before or after it. Do not provide hidden reasoning or """
                    """chain-of-thought.""",
                    json.dumps({
                        "question": request.query,
                        "read_evidence": _evidence_payload(evidence_rows),
                    }, ensure_ascii=False),
                )
                return _validated_synthesis(payload)
            except Exception:
                return _fallback_synthesis()

        return synthesize

    def _provider_json(self, provider, context, accountant, system, user):
        _ensure_active(context)
        result = self.chat_fn(
            provider,
            [{"role": "user", "content": user}],
            system=system,
            traffic_context=context,
        )
        if not isinstance(result, dict):
            raise ValueError("provider returned an invalid response")
        accountant.record(
            str(result.get("provider") or provider),
            str(result.get("model") or "unknown"),
            result.get("usage") if isinstance(result.get("usage"), dict) else {},
            context.correlation_id,
        )
        text = result.get("text")
        if not isinstance(text, str):
            raise ValueError("provider returned non-text structured output")
        parsed = json.loads(_strip_code_fence(text))
        if not isinstance(parsed, dict):
            raise ValueError("provider structured output must be an object")
        return parsed


def _strip_code_fence(text):
    """Providers sometimes wrap strict-JSON output in a markdown code fence
    despite being told not to; tolerate it rather than treating a well-formed
    answer as a synthesis failure."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _ensure_active(context, cancellation=None):
    event = cancellation if cancellation is not None else context.cancellation
    if event is not None and event.is_set():
        raise traffic.TrafficCancelled("search run cancelled before adapter work")


def _string_list(value, limit=None):
    if not isinstance(value, list):
        raise ValueError("structured field must be an array")
    items = [str(item).strip() for item in value if str(item).strip()]
    if limit is not None and len(items) > limit:
        raise ValueError("structured field exceeds its bound")
    return items


def _citation_id_list(value):
    """Some providers return citation objects ({citation_id, title, url})
    instead of the requested flat ID strings; pull the ID out either way."""
    if not isinstance(value, list):
        raise ValueError("structured field must be an array")
    items = []
    for item in value:
        candidate = item
        if isinstance(item, dict):
            candidate = item.get("citation_id") or item.get("id")
        text = str(candidate or "").strip()
        if text:
            items.append(text)
    return items


def _validated_plan(payload, question):
    if not isinstance(payload, dict):
        raise ValueError("plan must be an object")
    direct_query = str(payload.get("direct_query") or "").strip()
    if direct_query != question.strip():
        raise ValueError("plan direct query must match the user question")
    queries = _string_list(payload.get("additional_queries"), limit=4)
    angles = _string_list(payload.get("evidence_angles"))
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("plan summary is required")
    return {"queries": queries, "angles": angles, "summary": summary}


def _validated_gaps(payload):
    if not isinstance(payload, dict):
        raise ValueError("gap analysis must be an object")
    covered = _string_list(payload.get("covered_angles"))
    gaps = _string_list(payload.get("gaps"))
    conflicts = _string_list(payload.get("conflicts"))
    follow_up = payload.get("follow_up_query")
    if follow_up is None or not str(follow_up).strip():
        follow_up = None
    else:
        follow_up = str(follow_up).strip()
        if not gaps or not any(gap.lower() in follow_up.lower() for gap in gaps):
            raise ValueError("follow-up must name a missing evidence angle")
    return {
        "covered_angles": covered,
        "gaps": gaps,
        "conflicts": conflicts,
        "follow_up_query": follow_up,
    }


def _validated_synthesis(payload):
    if not isinstance(payload, dict):
        raise ValueError("synthesis must be an object")
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise ValueError("synthesis answer is required")
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise ValueError("synthesis claims must be an array")
    clean_claims = []
    for index, claim in enumerate(claims, 1):
        if not isinstance(claim, dict):
            raise ValueError("synthesis claim must be an object")
        text = str(claim.get("text") or "").strip()
        citation_ids = _string_list(claim.get("citation_ids"))
        if not text:
            raise ValueError("synthesis claim text is required")
        clean_claims.append({
            "claim_id": str(claim.get("claim_id") or f"claim-{index}"),
            "text": text,
            "citation_ids": citation_ids,
        })
    return {
        "answer": answer,
        "claims": clean_claims,
        "citations": _citation_id_list(payload.get("citations")),
        "uncertainties": _string_list(payload.get("uncertainties")),
        "conflicts": _string_list(payload.get("conflicts")),
        "gaps": _string_list(payload.get("gaps")),
    }


def _fallback_synthesis():
    return {
        "answer": _FALLBACK_ANSWER,
        "claims": [],
        "citations": [],
        "uncertainties": ["Structured synthesis was unavailable."],
        "conflicts": [],
        "gaps": [],
    }


_MAX_EVIDENCE_CHARS_PER_SOURCE = 6000


def _evidence_payload(evidence_rows):
    # A page read can legitimately extract hundreds of thousands of
    # characters (a PDF-viewer page, for one, dumps every page's text into
    # the DOM) - sending that whole to a provider blows past any request or
    # context limit and makes the structured-JSON call fail outright. Cap
    # what goes into the prompt; the full text stays on Evidence for local,
    # tokenless citation verification.
    return [{
        "citation_id": item.citation_id,
        "title": item.title,
        "url": item.url,
        "content_type": item.content_type,
        "text": _capped_for_prompt(item.text),
    } for item in evidence_rows]


def _capped_for_prompt(text):
    text = text or ""
    if len(text) <= _MAX_EVIDENCE_CHARS_PER_SOURCE:
        return text
    return text[:_MAX_EVIDENCE_CHARS_PER_SOURCE] + "\n\n[truncated for length]"
