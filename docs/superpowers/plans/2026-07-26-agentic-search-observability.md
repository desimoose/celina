# Agentic search and local observability implementation plan

**Design:** `docs/superpowers/specs/2026-07-26-agentic-search-observability-design.md`

**Goal:** Replace the single blocking `/api/explore` request with a bounded,
event-driven research run whose traffic, token usage, evidence, and deletion
behavior are locally inspectable.

**Estimated effort:** 12 to 18 focused engineering days.

**Risk:** High. This changes the network boundary, search orchestration, local
storage, API, and primary application surface.

## 1. Scope and assumptions

### Facts

- The server is stdlib Python using `ThreadingHTTPServer`.
- The UI is plain HTML, CSS, and JavaScript.
- SQLite, threads, queues, and `urllib` are available in the standard library.
- Provider adapters already return usage when the provider supplies it.
- External requests currently originate in `gateway.py`, `finder.py`,
  `scanner.py`, and `tools.py`.
- Existing user data consists of `.env` and deliberately saved workspace files.

### Approved decisions

- Windows desktop first; Ubuntu and macOS follow.
- BYOK or local Ollama only.
- Full redacted request and response recording for an active research session.
- Session records remain local and temporary.
- Stop preserves the session; End and delete removes its temporary files.
- Crash-interrupted sessions require an explicit Resume or Delete decision.
- SSE streams observable events.
- Manrope carries all reading and UI text; IBM Plex Mono is limited to
  instrumentation.
- No telemetry and no Celina-operated network service.

### Preferences

- Preserve stdlib-only server code.
- Keep each commit independently testable.
- Keep the legacy `/api/explore` route working until the new search-run path
  reaches feature parity.

## 2. High-tweak decisions

The design review already resolved the consequential choices. They are repeated
here so implementation does not silently reopen them.

### 2.1 Session content recording

**Decision:** Full redacted bodies are recorded by default for research
sessions.

**Alternative:** Metadata-only by default.

**Tradeoff:** Full content provides the requested complete local ledger but
creates a larger temporary privacy footprint. The visible session header and
End and delete control make that footprint explicit.

### 2.2 Crash recovery

**Decision:** Interrupted sessions persist until the next launch and are never
silently resumed.

**Alternative:** Delete all sessions on process exit.

**Tradeoff:** Recovery protects long research runs. It also means a crash can
leave sensitive temporary files behind until the user decides.

### 2.3 Search follow-up budget

**Decision:** At most one automatic gap-filling retrieval round.

**Alternative:** Continue until the model declares itself finished.

**Tradeoff:** A single follow-up is predictable and testable. Unlimited
iteration creates uncontrolled cost, latency, and failure behavior.

### 2.4 Storage

**Decision:** One SQLite ledger per session directory.

**Alternative:** JSONL events plus separate body files.

**Tradeoff:** SQLite provides transactional ordering, filtering, and atomic
queries with no new dependency. Per-session databases make deletion and crash
recovery easier to reason about.

### 2.5 Streaming

**Decision:** Server-Sent Events.

**Alternative:** Polling or WebSockets.

**Tradeoff:** SSE matches the one-way event stream and works in the existing
stack. Mutations remain ordinary authenticated HTTP requests.

## 3. Target modules

New server modules:

```text
server/
  redaction.py
  sessions.py
  events.py
  traffic.py
  tokens.py
  orchestrator.py
  evidence.py
  verification.py
```

New tests:

```text
tests/
  test_redaction.py
  test_sessions.py
  test_events.py
  test_traffic.py
  test_tokens.py
  test_orchestrator.py
  test_evidence.py
  test_search_api.py
  test_local_security.py
```

Existing modules modified:

```text
server/paths.py
server/gateway.py
server/finder.py
server/scanner.py
server/tools.py
server/app.py
web/index.html
web/app.js
web/styles.css
celina.spec
README.md
```

## 4. Milestone order

### Milestone 0: Fix known correctness gaps

This isolates existing defects before the architecture changes.

**Files**

- Modify `server/finder.py`
- Modify `server/scanner.py`
- Modify `web/app.js`
- Modify or add focused tests

**Tests first**

1. Prove `FINDER_CONTACT_EMAIL` is read after `.env` loading rather than cached
   at import time.
2. Prove web search tries DuckDuckGo HTML, DuckDuckGo Lite, then Bing.
3. Prove clearing a model override writes an empty value.

**Verification**

```powershell
python -m unittest discover -s tests -v
```

**Commit**

```text
fix: close search and settings correctness gaps
```

### Milestone 1: Session paths and redaction

**Files**

- Modify `server/paths.py`
- Create `server/redaction.py`
- Create `tests/test_redaction.py`
- Extend `tests/test_paths.py`

**Interfaces**

```python
paths.sessions_dir() -> str
paths.session_dir(session_id: str) -> str

redaction.Redactor(secret_values: Iterable[str])
redaction.Redactor.redact_headers(headers: Mapping[str, str]) -> dict
redaction.Redactor.redact_url(url: str) -> str
redaction.Redactor.redact_body(content_type: str, body: bytes) -> RedactedBody
redaction.Redactor.redact_text(text: str) -> tuple[str, list[Redaction]]
```

**Tests first**

- Reject session IDs containing separators or traversal.
- Create session directories only beneath `CELINA_HOME/sessions`.
- Redact authorization, API-key, cookie, and proxy-authorization headers.
- Redact configured canary secrets in JSON, form, URL, plain-text, and error
  bodies.
- Preserve valid nonsecret data and byte counts.
- Never include the original secret in `repr`, exceptions, or redaction
  metadata.

**Commit**

```text
feat: add session paths and secret redaction
```

### Milestone 2: Transactional SessionStore

**Files**

- Create `server/sessions.py`
- Create `tests/test_sessions.py`

**Interfaces**

```python
SessionStore.create(content_recording=True) -> Session
SessionStore.get(session_id) -> Session
SessionStore.list_recoverable() -> list[Session]
SessionStore.mark_active(session_id) -> None
SessionStore.mark_stopped(session_id) -> None
SessionStore.delete(session_id) -> DeleteResult
SessionStore.append_event(event) -> int
SessionStore.append_traffic(record) -> None
SessionStore.append_usage(record) -> None
```

**Implementation notes**

- Open SQLite with WAL enabled.
- Create schema and version table transactionally.
- Allocate event sequence numbers in the same transaction as insertion.
- Store UTC timestamps with millisecond precision.
- Never maintain a global permanent session index. Discover session directories
  locally and validate each database.

**Tests first**

- Create and reopen a session.
- Assign monotonically increasing event sequences across threads.
- Recover an active session after a simulated process restart.
- Delete DB, WAL, SHM, and extracted content.
- Preserve workspace artifacts.
- Return a precise partial-failure result when a file cannot be removed.

**Commit**

```text
feat: add transactional local session store
```

### Milestone 3: Event schema and in-process EventBus

**Files**

- Create `server/events.py`
- Create `tests/test_events.py`

**Interfaces**

```python
Event.create(session_id, run_id, correlation_id, kind, phase,
             summary, details=None, severity="info") -> Event
EventBus.publish(event) -> Event
EventBus.subscribe(session_id, after_sequence=0) -> Subscription
Subscription.get(timeout=None) -> Event | None
Subscription.close() -> None
```

**Rules**

- Validate kind, phase, severity, IDs, and JSON-serializable details.
- Persist before publishing.
- Backfill stored events before subscribing to live events.
- Bound subscriber queues and emit a resync marker rather than growing memory
  without limit.
- Keep user-facing summaries in reviewed templates.

**Tests first**

- Reject unknown kinds and invalid envelopes.
- Persist before a subscriber receives the event.
- Preserve ordering under concurrent publishers.
- Resume from an event sequence without duplicates.
- Clean up closed and overflowed subscribers.

**Commit**

```text
feat: add observable event stream
```

### Milestone 4: TokenAccountant

**Files**

- Create `server/tokens.py`
- Modify `server/gateway.py`
- Create `tests/test_tokens.py`
- Extend gateway tests

**Interfaces**

```python
TokenAccountant.record(provider, model, usage, correlation_id) -> UsageRecord
TokenAccountant.summary(session_id) -> UsageSummary
```

**Rules**

- Provider-reported counts are authoritative.
- `None` remains unknown; it is never converted to zero.
- Context percentage is absent when the model limit is unknown.
- No cost display in this milestone.
- Normalize Anthropic cache usage and OpenAI-compatible prompt/completion
  fields without changing the public `gateway.chat` result.

**Tests first**

- Normalize each provider shape.
- Preserve unknown usage.
- Sum usage across calls and models.
- Calculate context percentage only with a configured limit.
- Store `is_estimated=False` for provider usage.

**Commit**

```text
feat: account for provider-reported token usage
```

### Milestone 5: Central TrafficRecorder and HTTP adapter

**Files**

- Create `server/traffic.py`
- Create `tests/test_traffic.py`
- Modify `server/gateway.py`
- Modify `server/finder.py`

**Interfaces**

```python
TrafficContext(session_id, run_id, correlation_id, recorder, redactor)
http_request(context, request, timeout, action_type) -> HttpResult
provider_request(context, provider, payload, headers, timeout) -> dict
```

**Implementation notes**

- Record the outbound row before opening the connection.
- Complete the row with response status, headers, size, duration, and redacted
  body.
- Record HTTP and URL errors without storing secret-bearing exception text.
- Keep the low-level adapter transport-focused; provider parsing remains in
  `gateway.py`.
- Allow `context=None` for legacy routes during migration, but cover every new
  search-run path.

**Tests first**

- Use an in-process test HTTP server; no internet.
- Record success, HTTP failure, timeout, malformed JSON, and cancellation.
- Confirm request and response bodies are inspectable.
- Confirm canary secrets do not occur anywhere in the SQLite file bytes after
  checkpoints and connection close.
- Confirm provider behavior and returned shapes remain unchanged.

**Commit**

```text
feat: record redacted provider and research traffic
```

### Milestone 6: Obscura and scanner traffic coverage

**Files**

- Modify `server/tools.py`
- Modify `server/scanner.py`
- Extend `tests/test_scanner.py`
- Extend `tests/test_tools_obscura.py`
- Add TrafficRecorder integration tests

**Interfaces**

```python
tools.obscura_dump(..., traffic_context=None, action_type="page.fetch")
scanner.scan(..., traffic_context=None, event_sink=None)
finder.search(..., traffic_context=None, event_sink=None)
```

**Tests first**

- Each search backend produces a traffic event.
- DuckDuckGo fallback attempts remain individually visible.
- Obscura command metadata, duration, exit status, and redacted output are
  recorded.
- The ledger never stores process environment values or a complete command
  line containing secrets.
- A failing source produces a source-specific event and does not abort the
  scan.

**Enforcement**

Add a repository test that scans `server/` and rejects new direct
`urllib.request.urlopen` use outside `traffic.py` and explicitly grandfathered
legacy compatibility code.

**Commit**

```text
feat: cover scanner and Obscura traffic
```

### Milestone 7: Evidence model and bounded SearchOrchestrator

**Files**

- Create `server/evidence.py`
- Create `server/orchestrator.py`
- Create `tests/test_evidence.py`
- Create `tests/test_orchestrator.py`

**Interfaces**

```python
SearchRequest(query, provider, constraints, session_id)
SearchRun(run_id, state, query_plan, candidates, evidence, answer)
SearchOrchestrator.start(request) -> SearchRun
SearchOrchestrator.stop(run_id) -> None
SearchOrchestrator.get(run_id) -> SearchRun
```

**State machine**

```text
created -> planning -> retrieving -> selecting -> reading
-> checking_gaps -> follow_up? -> synthesizing -> verifying -> completed
```

**Implementation order**

1. Implement deterministic state transitions with fake adapters.
2. Add direct query plus structured planner result.
3. Normalize and deduplicate candidates.
4. Read selected sources.
5. Add one bounded follow-up decision.
6. Synthesize from retrieved evidence only.

**Tests first**

- Reject invalid transitions.
- Stop prevents a later phase from starting.
- Late traffic responses cannot restart a stopped run.
- One source failure is isolated.
- Follow-up count never exceeds one.
- Snippets are not marked as read evidence.
- All status summaries originate from observable event templates.

**Commit**

```text
feat: orchestrate bounded agentic search runs
```

### Milestone 8: Citation verification

**Files**

- Create `server/verification.py`
- Extend `server/orchestrator.py`
- Add fixtures with supported, overstated, missing, and conflicting claims
- Add verification tests

**Interfaces**

```python
Verifier.verify(answer, evidence) -> VerificationResult
VerificationResult.claims
VerificationResult.rejected_citations
VerificationResult.corrected_answer
```

**Tests first**

- Reject a nonexistent citation ID.
- Reject a citation whose page was not read.
- Locate a supporting passage for a valid claim.
- Flag an overstated claim.
- Preserve a visible correction event.
- Never silently drop a conflict or unresolved material gap.

**Commit**

```text
feat: verify cited claims against retrieved evidence
```

### Milestone 9: Local API, launch token, origin checks, and SSE

**Files**

- Modify `server/app.py`
- Modify `server/desktop.py`
- Create `tests/test_search_api.py`
- Create `tests/test_local_security.py`

**Endpoints**

```text
POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{id}
POST   /api/sessions/{id}/end
DELETE /api/sessions/{id}
GET    /api/sessions/{id}/traffic
GET    /api/sessions/{id}/traffic/{event_id}
GET    /api/sessions/{id}/usage

POST   /api/search-runs
GET    /api/search-runs/{id}
POST   /api/search-runs/{id}/stop
GET    /api/search-runs/{id}/events
```

**Security**

- Generate a random launch token in memory.
- Inject it into the initial app document or pywebview URL without writing it
  to disk.
- Require it for state-changing routes.
- Reject unexpected `Origin` values.
- Bind only to `127.0.0.1`.
- Add `Cache-Control: no-store` to session, traffic, and usage responses.

**Tests first**

- Reject missing and incorrect launch tokens.
- Reject malicious origins.
- Accept the expected local origin and token.
- SSE resumes after `Last-Event-ID`.
- SSE disconnect cleans up the subscription.
- End and delete returns only after temporary files are gone.

**Migration**

Keep `/api/explore` operational and unstreamed until Milestone 11 replaces its
UI consumer.

**Commit**

```text
feat: expose secure local search session API
```

### Milestone 10: Search-quality benchmark

**Files**

- Create `tests/quality/cases.json`
- Create `tests/quality/fixtures/`
- Create `tests/quality/run_quality.py`
- Create `tests/test_quality_contract.py`
- Add benchmark documentation

**First benchmark**

- At least 40 questions.
- Deterministic offline retrieval fixtures for CI.
- Optional live mode for manual release evaluation.
- Categories from the approved design: stable facts, current events, science,
  comparisons, ambiguity, conflict, and weak evidence.

**Metrics**

- Citation existence.
- Citation entailment.
- Unsupported material claims.
- Source diversity.
- Primary-source rate.
- Stated uncertainty.
- Latency and provider-reported tokens in live mode.

**Release-blocking tests**

- Zero fabricated citation IDs.
- Zero snippet-only evidence treated as read.
- All unsupported material claims are corrected or marked unresolved.

**Commit**

```text
test: add agentic search quality benchmark
```

### Milestone 11: Approved search workspace

**Files**

- Modify `web/index.html`
- Modify `web/styles.css`
- Rewrite relevant search sections of `web/app.js`
- Add self-hosted IBM Plex Mono files and license
- Keep existing Manrope files
- Add browser-level behavior tests if the existing test environment supports
  them; otherwise add DOM contract tests plus a manual desktop checklist

**UI sequence**

1. Create a session on first search.
2. Start a search run.
3. Open one EventSource.
4. Render the current action from the newest active event.
5. Render completed trace events.
6. Update the Token Watchtower.
7. Increment the local traffic event count.
8. Render evidence only after a page has been read.
9. Render the verified answer and corrections.
10. Implement Stop, Keep this, Open local traffic log, and End and delete.

**Accessibility**

- Polite, batched live region.
- Full keyboard path.
- Visible focus.
- Reduced-motion static current.
- Status words and shapes accompany gradient states.
- Stop and End and delete remain distinct.

**Verification**

- Compare at 1280 x 820, minimum 940 x 600, 125% Windows scaling, and 200%
  browser zoom.
- Exercise long queries, long titles, empty evidence, source failures, unknown
  token usage, and crash-recovered sessions.
- Run the Impeccable detector once after the finished UI.

**Commit**

```text
feat: ship observable search workspace
```

### Milestone 12: Traffic and Sessions screens

**Files**

- Modify `web/index.html`
- Modify `web/styles.css`
- Modify `web/app.js`
- Extend API and UI tests

**Traffic screen**

- Metadata-first chronological rows.
- Direction, destination, action, status, duration, sizes, and redaction state.
- Filters for direction, destination, action, failures, and status.
- Expand one row to reveal redacted request and response bodies.
- No network request leaves the machine for filtering or search.

**Sessions screen**

- Show active and crash-recovered sessions only.
- Show created time, last activity, and local size.
- Resume and Delete actions.
- No permanent behavioral history.

**Tests**

- Filtering remains local.
- Secret canaries never render.
- End and delete removes the row only after deletion succeeds.
- Partial deletion failure produces a specific recovery action.

**Commit**

```text
feat: add local traffic and session controls
```

### Milestone 13: Packaging, documentation, and release audit

**Files**

- Modify `celina.spec`
- Modify `README.md`
- Modify `.env.example`
- Extend CI and packaging checks

**Packaging**

- Include IBM Plex Mono and its license.
- Ensure session directories remain writable and are never bundled.
- Verify frozen path behavior.
- Verify no automatic update or telemetry call.

**Privacy audit**

- Scan binaries and source for analytics SDKs and undeclared network hosts.
- Run canary-secret integration tests against a frozen build.
- Verify End and delete on a fresh temporary `CELINA_HOME`.
- Document IP, provider, file-deletion, and crash-recovery boundaries.

**Platform gates**

- Windows packaged smoke test is release-blocking.
- Ubuntu and macOS run source tests in CI but packaging remains separate
  follow-on work.

**Commit**

```text
docs: document local observability and privacy boundaries
```

## 5. Test strategy

Run focused tests after each red-green-refactor loop:

```powershell
python -m unittest tests.test_redaction -v
python -m unittest tests.test_sessions -v
python -m unittest tests.test_events -v
```

Run the full suite before every milestone commit:

```powershell
python -m unittest discover -s tests -v
```

Network tests use local in-process servers or fixtures. CI must not depend on
external search engines or paid model providers.

Live quality evaluation is a separate release activity using the user's chosen
provider and is never executed automatically in CI.

## 6. Migration and rollback

- Existing `.env` and workspace files remain unchanged.
- Session storage is additive beneath `CELINA_HOME/sessions`.
- `/api/explore` remains available until the approved UI no longer uses it.
- Each milestone is a separate commit and can be reverted independently.
- Before the first public release there is no session schema compatibility
  promise; during development, schema changes may delete only test or
  explicitly disposable sessions.
- After release, schema changes require versioned migrations and rollback tests.

## 7. Mechanical work after the core path

- Replace stale architecture documents with links to `PRODUCT.md`, `DESIGN.md`,
  and the approved technical specification.
- Update endpoint comments in `server/app.py`.
- Document new modules and contributor test commands.
- Add type annotations where they materially clarify boundary contracts.
- Keep source files small enough that storage, transport, orchestration, and UI
  concerns do not collapse back into `app.py`.

## 8. Plan review checklist

- Privacy primitives precede traffic capture.
- Traffic capture precedes the observability claim.
- Event persistence precedes streaming.
- Search state transitions are tested with fakes before live adapters.
- Citation verification precedes the new answer UI.
- The quality benchmark precedes release polish.
- Legacy search remains available during migration.
- Every milestone has a focused test surface and independent commit.
- No milestone requires cloud infrastructure, accounts, or telemetry.
- No user workspace artifact is deleted by session cleanup.
