"""Bounded, observable search orchestration without private reasoning traces."""

from dataclasses import dataclass, field
import re
import threading
import uuid

import evidence as evidence_model
import events


class InvalidTransition(Exception):
    pass


class _StoppedRun(Exception):
    pass


@dataclass(frozen=True)
class StatusTemplate:
    text: str

    def render(self, **values):
        return self.text.format(**values)

    def matches(self, value):
        pattern = re.escape(self.text)
        pattern = re.sub(r"\\\{[^{}]+\\\}", r".+?", pattern)
        return re.fullmatch(pattern, value) is not None


STATUS_TEMPLATES = {
    "search.started": StatusTemplate("Started a bounded research run."),
    "plan.completed": StatusTemplate("Planned {query_count} focused searches."),
    "query.started": StatusTemplate("Searching for “{query}”."),
    "query.completed": StatusTemplate(
        "Found {candidate_count} candidates for “{query}”."
    ),
    "query.failed": StatusTemplate("Search source failed for “{query}”."),
    "candidate.selected": StatusTemplate("Selected “{title}” to read."),
    "source.read.started": StatusTemplate("Reading “{title}”."),
    "source.read.completed": StatusTemplate(
        "Read {character_count} characters from “{title}”."
    ),
    "source.read.blocked": StatusTemplate("Could not read “{title}”."),
    "gap.detected": StatusTemplate("Evidence gap: {gap}"),
    "conflict.detected": StatusTemplate("Evidence conflict: {conflict}"),
    "follow_up.started": StatusTemplate(
        "Running one follow-up for the missing evidence."
    ),
    "synthesis.started": StatusTemplate(
        "Synthesizing only from sources that were read."
    ),
    "synthesis.completed": StatusTemplate(
        "Drafted an answer from {evidence_count} read sources."
    ),
    "search.stopped": StatusTemplate("Stopped before starting another phase."),
    "search.completed": StatusTemplate("Research run completed."),
    "search.failed": StatusTemplate("Research run failed during {phase}."),
}


_TRANSITIONS = {
    "created": {"planning", "stopped", "failed"},
    "planning": {"retrieving", "stopped", "failed"},
    "retrieving": {"selecting", "stopped", "failed"},
    "selecting": {"reading", "stopped", "failed"},
    "reading": {"checking_gaps", "stopped", "failed"},
    "checking_gaps": {"follow_up", "synthesizing", "stopped", "failed"},
    "follow_up": {"retrieving", "stopped", "failed"},
    "synthesizing": {"verifying", "stopped", "failed"},
    "verifying": {"completed", "stopped", "failed"},
    "completed": set(),
    "stopped": set(),
    "failed": set(),
}


@dataclass(frozen=True)
class SearchRequest:
    query: str
    provider: str
    constraints: dict
    session_id: str

    def __post_init__(self):
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query is required")
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id is required")


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str, ...]
    angles: tuple[str, ...]
    summary: str


@dataclass
class SearchRun:
    run_id: str
    session_id: str
    query: str
    state: str = "created"
    query_plan: QueryPlan | None = None
    candidates: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    answer: object = None
    gaps: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    follow_up_count: int = 0
    error_class: str | None = None
    _lock: object = field(default_factory=threading.RLock, repr=False)
    _cancellation: object = field(default_factory=threading.Event, repr=False)
    _thread: object = field(default=None, repr=False)

    @classmethod
    def create(cls, session_id, query):
        return cls(str(uuid.uuid4()), session_id, query)

    def transition(self, state):
        with self._lock:
            if state not in _TRANSITIONS.get(self.state, set()):
                raise InvalidTransition(f"{self.state} cannot transition to {state}")
            self.state = state


class SearchOrchestrator:
    def __init__(
        self,
        event_bus,
        planner,
        retriever,
        reader,
        gap_checker,
        synthesizer,
        max_selected_sources=6,
    ):
        self.event_bus = event_bus
        self.planner = planner
        self.retriever = retriever
        self.reader = reader
        self.gap_checker = gap_checker
        self.synthesizer = synthesizer
        self.max_selected_sources = max(1, int(max_selected_sources))
        self._runs = {}
        self._lock = threading.RLock()

    def start(self, request):
        if not isinstance(request, SearchRequest):
            raise TypeError("request must be a SearchRequest")
        run = SearchRun.create(request.session_id, request.query.strip())
        with self._lock:
            if any(
                item.session_id == request.session_id
                and item.state not in {"completed", "stopped", "failed"}
                for item in self._runs.values()
            ):
                raise RuntimeError("session already has an active search run")
            self._runs[run.run_id] = run
        thread = threading.Thread(
            target=self._execute,
            args=(run, request),
            name=f"search-{run.run_id[:8]}",
            daemon=True,
        )
        run._thread = thread
        thread.start()
        return run

    def stop(self, run_id):
        run = self.get(run_id)
        if run is None:
            raise KeyError("unknown search run")
        run._cancellation.set()
        with run._lock:
            if run.state in {"completed", "stopped", "failed"}:
                return run
            run.state = "stopped"
        self._publish(run, "search.stopped", "stopped")
        return run

    def get(self, run_id):
        with self._lock:
            return self._runs.get(run_id)

    def wait(self, run_id, timeout=None):
        run = self.get(run_id)
        if run is None:
            raise KeyError("unknown search run")
        run._thread.join(timeout)
        return run

    def _execute(self, run, request):
        try:
            self._publish(run, "search.started", "planning")
            self._transition(run, "planning")
            run.query_plan = self._plan(request)
            self._publish(
                run,
                "plan.completed",
                "planning",
                query_count=len(run.query_plan.queries),
                details={"angles": list(run.query_plan.angles)},
            )

            queries = list(run.query_plan.queries)
            while True:
                self._transition(run, "retrieving")
                new_rows = self._retrieve(run, request, queries)
                self._ensure_active(run)

                self._transition(run, "selecting")
                run.candidates = evidence_model.normalize_candidates(
                    [*_candidate_dicts(run.candidates), *new_rows]
                )
                unread = [
                    item
                    for item in run.candidates
                    if item.candidate_id not in {
                        row.candidate_id for row in run.evidence
                    }
                ][:self.max_selected_sources]
                for item in unread:
                    self._publish(
                        run,
                        "candidate.selected",
                        "selecting",
                        title=item.title,
                        details={
                            "candidate_id": item.candidate_id,
                            "source_kind": item.source_kind,
                        },
                    )

                self._transition(run, "reading")
                self._read(run, request, unread)
                self._ensure_active(run)

                self._transition(run, "checking_gaps")
                findings = self.gap_checker(
                    request,
                    tuple(run.evidence),
                    run.query_plan.angles,
                ) or {}
                self._ensure_active(run)
                run.gaps = list(findings.get("gaps") or [])
                run.conflicts = list(findings.get("conflicts") or [])
                for gap in run.gaps:
                    self._publish(
                        run,
                        "gap.detected",
                        "checking_gaps",
                        gap=str(gap),
                    )
                for conflict in run.conflicts:
                    self._publish(
                        run,
                        "conflict.detected",
                        "checking_gaps",
                        conflict=str(conflict),
                    )
                follow_up = str(
                    findings.get("follow_up_query") or ""
                ).strip()
                if follow_up and run.follow_up_count == 0:
                    run.follow_up_count = 1
                    self._transition(run, "follow_up")
                    self._publish(
                        run,
                        "follow_up.started",
                        "checking_gaps",
                        details={"query": follow_up},
                    )
                    queries = [follow_up]
                    continue
                break

            self._transition(run, "synthesizing")
            self._publish(run, "synthesis.started", "synthesizing")
            run.answer = self.synthesizer(
                request,
                tuple(run.evidence),
                tuple(run.gaps),
            )
            self._ensure_active(run)
            self._publish(
                run,
                "synthesis.completed",
                "synthesizing",
                evidence_count=len(run.evidence),
            )
            self._transition(run, "verifying")
            self._transition(run, "completed")
            self._publish(run, "search.completed", "completed")
        except _StoppedRun:
            return
        except Exception as error:
            with run._lock:
                if run.state == "stopped":
                    return
                failed_phase = run.state
                if "failed" in _TRANSITIONS.get(run.state, set()):
                    run.state = "failed"
                run.error_class = type(error).__name__
            self._publish(
                run,
                "search.failed",
                "failed",
                phase=failed_phase,
                severity="error",
                details={"error_class": type(error).__name__},
            )

    def _plan(self, request):
        result = self.planner(request) or {}
        proposed = [
            str(item).strip()
            for item in result.get("queries") or ()
            if str(item).strip()
        ]
        queries = [request.query.strip()]
        for query in proposed:
            if query not in queries and len(queries) < 5:
                queries.append(query)
        return QueryPlan(
            queries=tuple(queries),
            angles=tuple(
                str(item).strip()
                for item in result.get("angles") or ()
                if str(item).strip()
            ),
            summary=str(result.get("summary") or "").strip(),
        )

    def _retrieve(self, run, request, queries):
        rows = []
        for index, query in enumerate(queries, 1):
            self._ensure_active(run)
            query_id = f"q{index + (run.follow_up_count * 100)}"
            self._publish(
                run,
                "query.started",
                "retrieving",
                query=query,
                details={"query_id": query_id},
            )
            try:
                found = self.retriever(
                    query,
                    query_id,
                    request,
                    run._cancellation,
                ) or []
                self._ensure_active(run)
                normalized = []
                for item in found:
                    copied = dict(item)
                    copied.setdefault("query_id", query_id)
                    normalized.append(copied)
                rows.extend(normalized)
                self._publish(
                    run,
                    "query.completed",
                    "retrieving",
                    query=query,
                    candidate_count=len(normalized),
                    details={"query_id": query_id},
                )
            except _StoppedRun:
                raise
            except Exception as error:
                self._publish(
                    run,
                    "query.failed",
                    "retrieving",
                    query=query,
                    severity="warning",
                    details={
                        "query_id": query_id,
                        "error_class": type(error).__name__,
                    },
                )
        return rows

    def _read(self, run, request, candidates):
        for item in candidates:
            self._ensure_active(run)
            self._publish(
                run,
                "source.read.started",
                "reading",
                title=item.title,
                details={"candidate_id": item.candidate_id},
            )
            try:
                result = self.reader(
                    item,
                    request,
                    run._cancellation,
                ) or {}
                self._ensure_active(run)
                citation_id = f"C{len(run.evidence) + 1}"
                read = evidence_model.Evidence.from_read(
                    item,
                    result.get("text"),
                    result.get("content_type"),
                    citation_id,
                )
                run.evidence.append(read)
                self._publish(
                    run,
                    "source.read.completed",
                    "reading",
                    title=item.title,
                    character_count=read.character_count,
                    details={
                        "candidate_id": item.candidate_id,
                        "citation_id": citation_id,
                    },
                )
            except _StoppedRun:
                raise
            except Exception as error:
                self._publish(
                    run,
                    "source.read.blocked",
                    "reading",
                    title=item.title,
                    severity="warning",
                    details={
                        "candidate_id": item.candidate_id,
                        "error_class": type(error).__name__,
                    },
                )

    def _transition(self, run, state):
        self._ensure_active(run)
        run.transition(state)

    @staticmethod
    def _ensure_active(run):
        if run._cancellation.is_set() or run.state == "stopped":
            raise _StoppedRun()

    def _publish(
        self,
        run,
        kind,
        phase,
        severity="info",
        details=None,
        **values,
    ):
        template = STATUS_TEMPLATES[kind]
        self.event_bus.publish(events.Event.create(
            session_id=run.session_id,
            run_id=run.run_id,
            correlation_id=run.run_id,
            kind=kind,
            phase=phase,
            severity=severity,
            summary=template.render(**values),
            details=details or {},
        ))


def _candidate_dicts(candidates):
    for item in candidates:
        yield {
            "title": item.title,
            "url": item.url,
            "kind": item.source_kind,
            "published_at": item.published_at,
            "authors": list(item.authors),
            "snippet": item.snippet,
            "is_oa": item.open_access,
            "query_id": (
                item.retrieval_query_ids[0]
                if item.retrieval_query_ids
                else ""
            ),
        }
