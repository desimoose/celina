# Agentic search, local observability, and session privacy

**Status:** Design for review

**Date:** 2026-07-26

**Scope:** Search quality, observable trace, Token Watchtower, Traffic
Controller, and session deletion
**Supersedes where conflicting:** `.agents/architecture.md`,
`.agents/build-plan.md`, and `.agents/visual-system.md`

## 1. Outcome

Celina will turn one user question into a bounded research run that:

1. Plans a small set of focused searches.
2. Retrieves candidates from multiple public sources.
3. Selects and reads the strongest evidence.
4. Checks material gaps and contradictions.
5. Produces a cited answer.
6. Verifies that citations support their claims.
7. Shows the user an observable record of the work.
8. Records Celina-managed traffic and token usage locally for the active
   session.
9. Deletes the temporary record when the user ends the session.

The implementation remains stdlib Python with plain HTML, CSS, and JavaScript.
SQLite is permitted because `sqlite3` is part of the Python standard library.

## 2. Architectural boundaries

The engine gains four internal services:

```text
SearchOrchestrator
  |-- EventBus
  |-- TrafficRecorder
  |-- TokenAccountant
  `-- SessionStore
```

### SearchOrchestrator

Owns the research state machine. It is the only component allowed to decide
which search phase runs next.

### EventBus

Accepts structured observable events and streams them to the UI. Events are
facts about execution, not prose reasoning.

### TrafficRecorder

Wraps every Celina-managed network and subprocess boundary. It records
redacted request and response facts before publishing corresponding events.

### TokenAccountant

Normalizes usage reported by providers. It never pretends an estimate is
exact.

### SessionStore

Creates, recovers, lists, ends, and deletes temporary local sessions. Durable
workspace artifacts remain separate.

## 3. Required refactor

Network access is currently distributed across `server/gateway.py`,
`server/finder.py`, `server/scanner.py`, and `server/tools.py`. A reliable
Traffic Controller cannot be implemented by inspecting only `/api/explore`.

All outbound activity must pass through typed adapters:

- `traffic.http_json(...)`
- `traffic.http_text(...)`
- `traffic.provider_call(...)`
- `traffic.obscura_call(...)`

These adapters accept a session and correlation ID, redact headers and bodies,
record timing and byte counts, and return the original response shape. Direct
`urllib.request.urlopen` calls outside the traffic module become a test
failure.

The local HTTP server that serves Celina's own UI is not included in research
traffic totals. The ledger records external provider, source, and tool
boundaries.

## 4. Search state machine

```text
created
  -> planning
  -> retrieving
  -> selecting
  -> reading
  -> checking_gaps
  -> follow_up? -> retrieving
  -> synthesizing
  -> verifying
  -> completed

Any active state -> stopped
Any active state -> failed
```

The orchestrator allows at most one automatic follow-up retrieval round in the
first release. This keeps cost, latency, and trace complexity bounded.

### 4.1 Planning

Input:

- User question.
- User constraints such as date range, jurisdiction, or source type.

Output:

- One direct query.
- Up to four focused subqueries.
- A short list of evidence angles.

The planner returns structured JSON. Private chain-of-thought is neither
requested nor stored. The visible explanation is a concise artifact such as:
"Separated timing, dose, sleep quality, and clinical evidence."

### 4.2 Retrieving

Run available source adapters concurrently within bounded worker and timeout
limits:

- Scholarly sources.
- General web search.
- Recent news.
- Context sources.

Every adapter degrades independently. A failed source produces an event and
does not fail the whole search.

### 4.3 Normalizing and selecting

Normalize candidates into:

```json
{
  "candidate_id": "local opaque id",
  "title": "string",
  "url": "string",
  "canonical_url": "string",
  "source_kind": "research|web|news|context",
  "published_at": "ISO timestamp or null",
  "authors": ["string"],
  "snippet": "string or null",
  "open_access": true,
  "retrieval_query_ids": ["query id"]
}
```

Deduplicate by DOI, canonical URL, then normalized title. Selection uses
explicit features:

- Query relevance.
- Source authority appropriate to the question.
- Recency when the question requires it.
- Primary evidence preference.
- Source diversity.
- Accessibility of full content.

Selection events expose these features, not hidden model reasoning.

### 4.4 Reading

Celina opens selected pages and extracts clean text. A page is considered
"read" only when usable body content was retrieved. Search-result snippets do
not qualify as evidence.

Each read produces:

- Retrieval status.
- Content type.
- Extracted character count.
- Publication metadata found.
- Redaction summary.
- Failure or access boundary when applicable.

### 4.5 Gap and contradiction check

The checker receives the question, evidence angles, and extracted source
content. It returns structured findings:

- Covered angles.
- Material uncovered angles.
- Claims with conflicting evidence.
- Whether one follow-up search is justified.

A follow-up query must name the missing evidence angle. It cannot be an
unbounded request to "search more."

### 4.6 Synthesis

The model receives only retrieved evidence selected for the answer. Each source
is assigned a stable citation ID. The response format contains:

- Answer markdown.
- Claim-to-citation mapping.
- Explicit uncertainties.
- Evidence gaps.

### 4.7 Citation verification

Verification is a separate pass. For every material cited claim, verify:

1. The citation ID exists.
2. Celina retrieved usable content for it.
3. A supporting passage can be located.
4. The claim does not overstate the passage.

Unsupported claims are removed, softened, or marked unresolved. Corrections
remain visible in the trace.

## 5. Observable event contract

Every event has this envelope:

```json
{
  "event_id": "uuid",
  "session_id": "uuid",
  "run_id": "uuid",
  "correlation_id": "uuid",
  "sequence": 17,
  "occurred_at": "2026-07-26T21:30:00.000Z",
  "kind": "source.read.completed",
  "phase": "reading",
  "severity": "info",
  "summary": "I read the fourth selected source.",
  "details": {},
  "traffic_event_ids": ["uuid"]
}
```

Required event families:

- `session.created`
- `session.recovered`
- `session.ending`
- `session.deleted`
- `search.started`
- `plan.completed`
- `query.started`
- `query.completed`
- `query.failed`
- `candidate.selected`
- `source.read.started`
- `source.read.completed`
- `source.read.blocked`
- `gap.detected`
- `conflict.detected`
- `follow_up.started`
- `synthesis.started`
- `synthesis.completed`
- `citation.verified`
- `citation.rejected`
- `answer.corrected`
- `search.stopped`
- `search.completed`
- `search.failed`

User-facing summaries are selected from reviewed templates populated only with
event fields. Arbitrary model prose is not used for system status.

## 6. Local session ledger

Each active session is stored under:

```text
CELINA_HOME/
  sessions/
    <session-id>/
      ledger.sqlite3
      ledger.sqlite3-wal
      ledger.sqlite3-shm
      extracted/
```

SQLite tables:

### `session`

- `session_id`
- `created_at`
- `last_active_at`
- `state`
- `content_recording`
- `recovery_required`

### `event`

- Event envelope fields.
- `details_json`.

### `traffic`

- `traffic_event_id`
- `correlation_id`
- `direction`
- `transport`
- `destination`
- `method_or_action`
- `started_at`
- `completed_at`
- `status`
- `duration_ms`
- `request_bytes`
- `response_bytes`
- `request_headers_json`
- `response_headers_json`
- `request_body`
- `response_body`
- `redactions_json`
- `error_class`
- `error_summary`

### `token_usage`

- `usage_id`
- `correlation_id`
- `provider`
- `model`
- `input_tokens`
- `output_tokens`
- `cached_input_tokens`
- `context_limit`
- `is_estimated`
- `recorded_at`

## 7. Recording and redaction

The Traffic Controller promises visibility into Celina-managed boundaries, not
packet capture for unrelated applications.

Never store:

- Authorization headers.
- API keys.
- Cookies.
- Proxy credentials.
- Environment variable values.
- Known secret query parameters.

Redaction happens before data reaches SQLite or an event subscriber. Tests use
canary secrets to prove that raw values never appear in the database, logs, API
responses, exceptions, or UI.

Session content recording has two levels:

- **Metadata:** destination, action, timing, status, sizes, token usage, and
  redaction summary.
- **Full local record:** metadata plus redacted request and response bodies.

The approved session model uses full local recording for research sessions so
the user can inspect everything that went in and out. The session header states
this plainly. A Settings control may switch future sessions to metadata-only.
The choice never changes an already-open session silently.

## 8. Deletion semantics

**Stop** and **End and delete** are different operations.

### Stop

- Cancels queued work.
- Prevents new outbound requests.
- Lets in-flight work reach a bounded cancellation point.
- Preserves the session ledger and gathered evidence.

### End and delete

1. Moves session state to `ending`.
2. Stops and drains active work.
3. Closes all database handles.
4. Deletes SQLite database, WAL, SHM, and temporary extracted files.
5. Removes the empty session directory.
6. Publishes only an in-memory completion result to the current UI.

Kept workspace artifacts are not deleted.

On SSDs and journaled file systems this is best-effort file deletion, not a
cryptographic secure erase guarantee. Documentation must use "delete local
session files," never "forensically erase."

Unexpectedly interrupted sessions remain recoverable. On next launch Celina
shows their creation time, last activity, and size with two actions: Resume or
Delete. Sessions are never silently reopened.

## 9. Token Watchtower

Provider-reported token usage is authoritative when present.

- Anthropic: `input_tokens`, `output_tokens`, and cache fields when returned.
- OpenAI-compatible providers: prompt and completion usage fields.
- Ollama: reported counts when present.

When counts are missing, Celina may show an estimate only if an appropriate
local tokenizer exists. Otherwise it shows "not reported." It never presents
character-count heuristics as exact tokens.

Context percentage is shown only when the selected model's context limit is
known from local configuration. Pricing is out of the critical path; any future
cost display must include the locally stored price date and an "estimate"
label.

## 10. Local API

Proposed endpoints:

```text
POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{id}
POST   /api/sessions/{id}/end
DELETE /api/sessions/{id}

POST   /api/search-runs
POST   /api/search-runs/{id}/stop
GET    /api/search-runs/{id}
GET    /api/search-runs/{id}/events

GET    /api/sessions/{id}/traffic
GET    /api/sessions/{id}/traffic/{event_id}
GET    /api/sessions/{id}/usage
```

Search events stream over Server-Sent Events. SSE fits the one-way local event
flow, works with the current stdlib server and browser APIs, and avoids adding
a WebSocket dependency.

All state-changing endpoints require an unguessable per-launch local token
injected into the desktop webview. The HTTP server remains bound to
`127.0.0.1`. Requests with an unexpected `Origin` are rejected. These controls
prevent another local web page from driving Celina through the browser.

## 11. Concurrency and cancellation

- One active search run per session in the first release.
- Retrieval adapters may run concurrently through a bounded thread pool.
- Every outbound call has a timeout.
- Cancellation is cooperative and checked between phases and before follow-up
  requests.
- Late responses after Stop may be recorded as completed traffic but cannot
  trigger a new phase.
- Event sequence numbers are assigned transactionally by the SessionStore.

## 12. UI behavior

The search screen implements `DESIGN.md`.

Default reading order:

1. Query.
2. Answer state and evidence.
3. Working notes.
4. Session identity and deletion behavior.
5. Token usage.
6. Current action.
7. Trace.
8. Traffic log entry point.

The Traffic screen is metadata-first. Expanding a row reveals redacted bodies.
Filters include direction, destination, status, action type, and failures.
Search operates only on the local open ledger.

The Sessions screen lists only open or crash-recovered temporary sessions.
Celina does not create a permanent behavioral history.

## 13. Search-quality evaluation

Before release, maintain a versioned local benchmark with at least 40 questions
across:

- Stable factual research.
- Current events.
- Scientific evidence.
- Product and technical comparison.
- Ambiguous questions requiring clarification or scoped interpretation.
- Questions with conflicting evidence.
- Questions with weak or unavailable evidence.

For each run record:

- Answer coverage.
- Citation existence.
- Citation entailment.
- Source diversity.
- Primary-source rate.
- Unsupported material claim count.
- Correct uncertainty behavior.
- Retrieval and total latency.
- Provider-reported token usage.

The release gate is zero fabricated citations and no known path where a
search-result snippet is presented as read evidence.

## 14. Testing strategy

### Unit tests

- Event schema validation.
- Redaction against canary secrets.
- Token usage normalization.
- Session creation, crash recovery, and deletion.
- Search state transitions.
- Citation mapping and rejection.

### Integration tests

- All network adapters produce traffic rows.
- A stopped run makes no new requests.
- Failed sources remain isolated.
- SSE events preserve transactional ordering.
- End and delete removes DB, WAL, SHM, and extracted files.
- Kept workspace artifacts survive session deletion.
- Local-origin and launch-token protections reject unauthorized requests.

### UI tests

- Watchtower values update from streamed events.
- Traffic rows expand and redact correctly.
- Stop and End and delete have distinct outcomes.
- Keyboard and screen-reader paths work.
- Reduced motion keeps state understandable.

## 15. Migration and compatibility

Existing workspace files and `.env` remain valid. Session storage is additive.
The current `/api/explore` endpoint remains temporarily available while the UI
migrates to search runs, then is removed after equivalent coverage exists.

No existing saved work is imported into session traffic automatically.

## 16. Implementation sequence

1. SessionStore and redaction primitives.
2. Traffic adapters and enforcement tests.
3. TokenAccountant.
4. EventBus and SSE.
5. SearchOrchestrator state machine.
6. Retrieval and reading adapters.
7. Gap checker, synthesis, and citation verifier.
8. Search-quality benchmark.
9. Token Watchtower and trace integration.
10. Traffic and Sessions screens.
11. Windows packaging and privacy audit.

## 17. Acceptance criteria

The design is implemented when:

- Every Celina-managed external request has a corresponding local traffic
  record.
- No configured secret can appear in a traffic record.
- The user can inspect request and response bodies recorded for the session.
- Provider-reported token usage reaches the Watchtower without recomputation.
- Search status language is derived from observable events.
- Citations resolve to pages Celina read and support their claims.
- Stop prevents later phases from beginning.
- End and delete removes all temporary files for the session while preserving
  deliberately kept work.
- The app performs no telemetry or Celina-operated network call.
- The full test suite passes on Windows, Ubuntu, and macOS, with platform
  packaging tested separately.
