# Secure Local Search API and Live Trace Plan

**Scope:** Connect the completed session ledger, EventBus, Traffic Controller,
Token Watchtower, bounded SearchOrchestrator, and citation verifier to the
desktop application through a secure loopback API and resumable server-sent
event stream.

**Outcome:** A user can start Celina, ask a question, watch factual search
actions arrive live, stop safely, inspect local traffic and token usage, resume
after an SSE reconnect, and end/delete the temporary session.

**Effort:** Three to five focused engineering days for the backend and browser
bridge. The finished visual workspace and traffic/session screens remain the
following milestone.

**Risk:** High. This milestone joins every privacy-sensitive subsystem and
creates the authorization boundary for localhost.

## 1. Current facts

- The desktop server binds to `127.0.0.1` on an ephemeral port.
- The server uses `ThreadingHTTPServer` and no third-party web framework.
- The UI and API share one origin.
- Search sessions use one SQLite ledger each.
- Event sequence numbers are persisted transactionally.
- Search runs execute in background threads and support cooperative Stop.
- Provider, research, scanner, and Obscura boundaries can receive a
  `TrafficContext`.
- Token accounting accepts authoritative provider usage.
- The current `/api/explore` route remains available during migration.
- Existing packaging changes are uncommitted and must stay isolated from this
  milestone.

## 2. Decisions most likely to change

### 2.1 Local authorization

**Recommendation:** Generate two random values when the server starts:

1. A same-site `HttpOnly` launch cookie used automatically by normal API and
   SSE requests.
2. A CSRF token injected into the served `index.html` as an in-memory meta
   value. JavaScript sends it in `X-Celina-CSRF` for every state-changing
   request.

Also require an expected loopback `Origin` for mutations and reject CORS.

**Why:** Native `EventSource` cannot attach a custom authorization header.
Putting a launch token in the SSE URL would expose it to request logs and
browser history. A same-site `HttpOnly` cookie supports EventSource without
making the secret readable by JavaScript. The second token prevents a local or
remote page from causing authenticated mutations.

**Alternative:** A single query-string launch token. Simpler, but easier to
leak and therefore not recommended.

**Decision needed:** None unless we intentionally prefer simpler but weaker
query-string authorization.

### 2.2 Session creation

**Recommendation:** Create a temporary research session when the user submits
their first search, not at application boot.

**Why:** Opening Celina should not create disk state. A session exists only
when the user starts work that needs a ledger.

**Alternative:** Create at boot, which simplifies the frontend slightly but
leaves empty crash-recovery sessions.

### 2.3 Search concurrency

**Recommendation:** Permit one active search run per session. Return `409` if a
second search is submitted before the first completes or stops.

**Why:** This keeps Stop, token totals, trace order, and deletion behavior
unambiguous in the first release.

**Alternative:** Multiple concurrent runs per session. Useful later, but it
requires per-run filtering throughout the UI.

### 2.4 Stop versus deletion

**Recommendation:**

- **Stop:** set cancellation, preserve the ledger and evidence, return the
  stopped run.
- **End and delete:** mark the session `ending`, stop and drain its run, close
  subscriptions, delete SQLite/WAL/SHM/extracted content, then return an
  in-memory deletion result.

Deletion must never remove deliberately kept workspace artifacts.

### 2.5 Event payloads

**Recommendation:** SSE sends the already-persisted observable event envelope.
It never sends prompts, model scratch work, hidden reasoning, API keys, or raw
unredacted traffic.

The browser can separately request redacted traffic details after a deliberate
user action.

### 2.6 Runtime adapter strategy

**Recommendation:** Add a small `SearchRuntime` composition layer rather than
placing provider/search logic directly in HTTP handlers.

It will construct per-run:

- `TrafficContext`
- `TokenAccountant`
- planner adapter
- retrieval adapter
- page-reader adapter
- gap-check adapter
- synthesis adapter
- `Verifier`

This keeps the HTTP layer transport-only and lets offline tests replace every
external boundary.

## 3. Proposed API

All JSON responses below include:

```http
Cache-Control: no-store
Content-Type: application/json; charset=utf-8
```

### Sessions

```text
POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{session_id}
POST   /api/sessions/{session_id}/end
DELETE /api/sessions/{session_id}
GET    /api/sessions/{session_id}/traffic
GET    /api/sessions/{session_id}/traffic/{traffic_event_id}
GET    /api/sessions/{session_id}/usage
```

Create request:

```json
{
  "content_recording": true
}
```

Session response:

```json
{
  "session_id": "opaque UUID",
  "state": "active",
  "created_at": "ISO timestamp",
  "last_active_at": "ISO timestamp",
  "content_recording": true,
  "recovery_required": false
}
```

Traffic list responses are metadata-first. A body is returned only from the
single-record endpoint.

### Search runs

```text
POST /api/search-runs
GET  /api/search-runs/{run_id}
POST /api/search-runs/{run_id}/stop
GET  /api/search-runs/{run_id}/events
```

Start request:

```json
{
  "session_id": "opaque UUID",
  "query": "Does caffeine affect sleep?",
  "provider": "ollama",
  "constraints": {
    "date_from": null,
    "date_to": null,
    "jurisdiction": null,
    "source_types": []
  }
}
```

Start response uses `202 Accepted`:

```json
{
  "run_id": "opaque UUID",
  "session_id": "opaque UUID",
  "state": "created",
  "events_url": "/api/search-runs/{run_id}/events"
}
```

Run responses expose only serializable product state:

```json
{
  "run_id": "opaque UUID",
  "state": "reading",
  "query": "Does caffeine affect sleep?",
  "query_plan": {
    "queries": [],
    "angles": [],
    "summary": ""
  },
  "candidates": [],
  "evidence": [],
  "answer": null,
  "gaps": [],
  "conflicts": [],
  "follow_up_count": 0,
  "error_class": null
}
```

Thread objects, cancellation events, internal locks, provider secrets, and raw
exception text are never serialized.

## 4. SSE contract

Request:

```http
GET /api/search-runs/{run_id}/events
Last-Event-ID: 17
Accept: text/event-stream
```

Response:

```text
id: 18
event: trace
data: {"sequence":18,"kind":"source.read.completed",...}

```

Rules:

- Backfill events after `Last-Event-ID`, then continue live without gaps.
- The EventBus registers the subscriber while holding its publish lock so
  backfill and live delivery cannot race.
- Send a comment heartbeat every 15 seconds while idle.
- Set `Cache-Control: no-store`, `X-Accel-Buffering: no`, and
  `Connection: keep-alive`.
- On a bounded subscriber-queue overflow, send `stream.resync`; the browser
  reconnects with its last successfully rendered event ID.
- A broken pipe closes the subscription immediately.
- Completing or stopping a run sends the terminal event, then the server may
  close the stream.

## 5. SearchRuntime adapter behavior

### Planner

- Input: user query and explicit constraints.
- Provider response: strict JSON only.
- Output: direct query, up to four additional focused queries, evidence angles,
  and one concise public plan summary.
- Never request or persist chain-of-thought.
- If structured planning fails, fall back to the direct query rather than
  failing the run.

### Retriever

- Use the scanner/finder boundaries with the run's `TrafficContext`.
- Normalize each returned candidate with its query ID.
- Emit source failure outcomes without ending the whole run.
- Enforce existing query and follow-up bounds.

### Reader

- Use `tools.fetch(..., traffic_context=context)` after its remaining traffic
  parameter is added.
- Return extracted full-page text and content type.
- Reject empty bodies and search snippets.
- Respect cancellation before each new page read.

### Gap checker

- Receives the question, public evidence angles, and read evidence.
- Returns structured covered angles, gaps, conflicts, and at most one specific
  follow-up query.
- A follow-up must name a missing evidence angle.
- Invalid output results in no follow-up, never an unbounded retry.

### Synthesizer

- Receives read evidence only, with stable citation IDs.
- Returns answer markdown, structured claims, citation IDs, uncertainties,
  conflicts, and gaps.
- Provider-reported usage is immediately handed to `TokenAccountant`.

### Verifier

- Runs as a separate deterministic gate.
- Rejects missing/unread citations.
- Finds supporting passages.
- Flags obvious overstatement.
- Preserves corrections and unresolved conflicts in both run state and trace.

## 6. Execution order

### Phase A: Security and serialization primitives

**Files**

- Create `server/local_security.py`
- Create `server/serialization.py`
- Add `tests/test_local_security.py`

**Tests first**

- Cookie and CSRF tokens are random and memory-only.
- Correct same-origin mutation succeeds.
- Missing/wrong cookie, CSRF header, or Origin fails.
- Query strings and error bodies never contain tokens.
- Run/session serializers exclude locks, threads, cancellation objects, and
  secrets.

**Verification:** focused tests plus raw response inspection.

### Phase B: Runtime composition

**Files**

- Create `server/search_runtime.py`
- Modify `server/tools.py` to accept traffic context on page reads
- Extend `server/gateway.py` only where structured provider calls need usage
  capture
- Add `tests/test_search_runtime.py`

**Tests first**

- Planner fallback uses the direct query.
- Every provider call records traffic and token usage.
- Retriever and reader receive the same run/session/correlation context.
- Snippets cannot cross into synthesis.
- Malformed structured provider output degrades safely.
- No adapter begins after cancellation.

**Verification:** deterministic fake-provider end-to-end run.

### Phase C: Session routes

**Files**

- Modify `server/app.py`
- Extend `server/sessions.py` only for missing lookup/list helpers
- Add `tests/test_search_api.py`

**Tests first**

- Create/get/list session.
- Recovery-required sessions are visible.
- Traffic list omits bodies.
- Traffic detail returns redacted bodies.
- Usage endpoint preserves unknown token values.
- End/delete waits for filesystem removal.
- Workspace siblings survive deletion.

### Phase D: Search-run routes

**Files**

- Modify `server/app.py`
- Wire one application-scoped `SearchRuntime`

**Tests first**

- Start returns `202`.
- Unknown session/run returns `404`.
- Second active run returns `409`.
- Stop returns the terminal stopped state.
- Late adapter completion cannot advance a stopped run.
- Legacy `/api/explore` still works.

### Phase E: Resumable SSE

**Files**

- Create `server/sse.py`
- Modify `server/app.py`
- Extend `tests/test_search_api.py`

**Tests first**

- Initial stream receives persisted backfill.
- `Last-Event-ID` resumes without duplicates.
- A publish during subscription setup is not lost.
- Heartbeat keeps an idle stream alive.
- Disconnect removes the subscriber.
- Terminal event is delivered.
- Overflow produces a resync instruction.

### Phase F: Minimal browser bridge

This is functional wiring, not the final visual pass.

**Files**

- Modify `web/app.js`
- Add only necessary semantic hooks to `web/index.html`

**Behavior**

1. On Search, create a session if none is active.
2. Start the search run.
3. Open one EventSource.
4. Render the newest active event as the current action.
5. Append completed events to the trace.
6. Poll or fetch run state only at phase boundaries/terminal events.
7. Update token and traffic counts from local endpoints.
8. Stop closes future work but keeps the session.
9. End and delete closes the stream, removes local records, and resets the UI.
10. On reconnect, resume from the last rendered event ID.

The full premium workspace, motion, traffic browser, recovery screen, and
accessibility polish remain the following UI milestone.

## 7. User-visible flow

```text
User presses Search
  -> temporary local session created
  -> bounded search run accepted
  -> trace stream opens
  -> “Planning focused searches”
  -> each query/source/read appears as an action or outcome
  -> Token Watchtower and traffic count update locally
  -> answer appears only after synthesis and citation verification

User presses Stop
  -> queued/new traffic is cancelled
  -> in-flight response may finish recording
  -> no later phase starts
  -> gathered evidence and trace remain visible

User presses End and delete
  -> active work drains
  -> SSE subscription closes
  -> session SQLite/WAL/SHM/extracted files are deleted
  -> deliberately kept workspace notes remain
```

## 8. Test strategy

- Unit tests for token/cookie validation, serializers, SSE formatting, and
  runtime adapters.
- In-process `ThreadingHTTPServer` integration tests; no internet.
- Real EventBus/SessionStore tests for SSE resume and sequence ordering.
- Canary secrets checked against response bodies, logs, SQLite/WAL/SHM bytes,
  and exception strings.
- Resource warnings treated as test failures.
- Full existing suite after every phase.
- One manual desktop test at the end: Search, disconnect/reconnect SSE, Stop,
  inspect traffic, End and delete, confirm files are gone.

## 9. Rollout and rollback

- Keep `/api/explore` intact until the new browser bridge is proven.
- Put the new UI path behind an internal source constant during development.
- If live streaming is unstable, the browser can temporarily poll the run
  endpoint without changing the orchestrator or ledger.
- API changes are additive until the final UI migration.
- Each phase is independently committed and revertible.

## 10. Definition of done

- Every state-changing route requires same-site launch authorization, CSRF, and
  expected Origin.
- No launch secret is written to disk, placed in a URL, or printed in logs.
- Every new run has one temporary local session ledger.
- The UI can resume events without missing or duplicating trace entries.
- Stop cannot be undone by a late response.
- Only read evidence reaches synthesis.
- Citation corrections remain visible.
- Traffic and token endpoints remain local and `no-store`.
- End and delete removes all temporary session files before success returns.
- Existing `/api/explore` remains operational through the transition.
- Full automated suite passes with resource warnings treated as errors.
