# Architecture — what actually ships

*Last updated: 2026-08-07. Supersedes the earlier Tauri/Agent-Reach/last30days
draft below this line's predecessor — that plan was written before the build
started and none of those specific tools ended up in the product. This
documents the code as it exists in the repo today, not the aspiration.*

## What the product actually is

A **local-first research app for Windows**. One process, stdlib Python,
serving a plain HTML/CSS/JS UI over a loopback HTTP server. No servers we
operate, no accounts. At launch it's BYOK (five providers) or fully local via
Ollama.

The one thing we write and maintain is the engine — the server. Everything
else is either stdlib, a small bundled binary (Obscura), or the browser
running the shipped UI.

## The pieces (as built, not as planned)

| Component | What it is | Role |
|---|---|---|
| **Window** | pywebview over the system WebView2 runtime | The desktop `.exe` a user launches. Chosen over Tauri — see "Superseded decisions" below. |
| **Web UI** | plain HTML/CSS/JS, no build step, no framework | Served by the engine on a loopback port. Fonts self-hosted (Manrope), no external requests. |
| **Engine** (`server/`) | Python, stdlib only (`http.server`) | The orchestrator. One `ThreadingHTTPServer`, one process. |
| **Obscura** | Rust stealth browser, prebuilt binary | Bundled in `vendor/obscura/` (hash-verified against `third_party/obscura/manifest.json`, never "latest"). Spawned as a subprocess for unprofiled fetch + render. |
| **Model gateway** (`gateway.py`) | Python, stdlib `urllib` | BYOK across Anthropic, OpenAI, OpenRouter, xAI, plus local Ollama — one call shape, no vendor lock-in. |

No Docker, no Node/Go runtime dependency, no V8 compile — Obscura ships as a
binary, and the desktop shell doesn't need a JS toolchain at all.

### What was planned but dropped

The original plan named **Agent-Reach** (15-platform social reader),
**last30days** (engagement-scored digest engine), **Archify** (diagram
renderer), and **Mr.Holmes** (OSINT TUI) as sidecars. None of them shipped.
Zero-login web/research/news/context search (see Scanner, below) covers what
Search actually needed without a login-gated dependency; Sources and Trails
— which is where Agent-Reach/last30days would have mattered — are still
unbuilt (see "Not built yet").

## How Search actually works

One box fans out and comes back with a cited, verified answer. Two paths
exist in the codebase right now:

```
web/app.js
  -> POST /api/sessions              create a local session ledger
  -> POST /api/search-runs           start a bounded, observable run
  -> GET  /api/search-runs/{id}/events   live trace over SSE (resumable)
  -> GET  /api/search-runs/{id}      final state once a terminal event lands
```

**The orchestrated path** (`orchestrator.py` + `search_runtime.py`, wired
into `app.py` and driving the UI): plan → retrieve → select → read →
check-gaps → synthesize → verify, as an explicit state machine
(`SearchOrchestrator`/`SearchRun`). Every phase transition publishes an
`Event` (`events.py`) to a per-session `EventBus`, persisted to that
session's SQLite ledger (`sessions.py`) and streamed live over SSE
(`sse.py`). A citation verifier (`verification.py`) runs after synthesis and
visibly corrects unsupported claims rather than passing them through.

- **Retrieval** goes through `scanner.py` — a zero-login blend across
  **Research** (OpenAlex, Europe PMC, Crossref via `finder.py`), **Web**
  (Obscura-driven DuckDuckGo → Bing fallback), **Recent** (Google News RSS),
  and **Context** (Wikipedia full-text search).
- **Reading** goes through `tools.fetch()` — Obscura's stealth text-dump for
  ordinary pages, a byte/PDF path (`pdf.py`, stdlib inflate + optional
  `pypdf`) for anything that looks like a PDF (including query-string
  indicators like `?pdf=render`, not just the URL path). Extracted text is
  capped (600k chars) regardless of source, and evidence sent to a model is
  capped again (6k chars/source) — both defend against a page whose DOM
  legitimately contains megabytes of text.
- **Provider calls** (`gateway.py`) go through a shared `TrafficContext` so
  every request/response is redacted and recorded (`traffic.py`,
  `redaction.py`) and every token count is attributed
  (`tokens.py`/`TokenAccountant`) to the session, regardless of which of the
  five providers answered.
- **Every mutation** (creating a session, starting/stopping a run) requires a
  same-site launch cookie + CSRF token + matching Origin
  (`local_security.py`) — the loopback API isn't just "trust localhost."

**The legacy path** (`/api/explore` in `app.py`, calling `scanner.scan()`
directly) still exists and still works — single-shot search + synthesis, no
session, no live trace, no verification pass. `web/app.js` no longer calls
it; it's kept as a fallback per the rollout plan that shipped the SSE work,
not because it's still the primary path.

## Not built yet

- **Sources** (public social reads) and **Trails** (the retention engine —
  a saved topic Celina keeps watching on a schedule) — no code exists for
  either. This is the actual gap versus the original three-surface vision,
  not a missing sidecar integration.
- **`memory.py`** (local session capsules + approval-gated "skill"
  proposals) is built and tested but not imported by `app.py` — same
  situation the search-run/SSE code was in before it got wired up. Nothing
  in the running app calls it yet.

## Locked decisions

- **Launch inference: BYOK + local (Ollama) only.** No hosted tier.
- **Search first, proven end-to-end with real providers** before Sources or
  Trails get built — this shipped; the orchestrated path has been verified
  live against real OpenRouter/DeepInfra responses, including the
  degenerate-output cases that only show up under real traffic (see
  "Superseded decisions" for what that surfaced).
- **Shell: pywebview**, not Tauri (below).
- **The anonymity claim stays exact**: unprofiled — no login, no cookies, no
  history shaping results. IP is not hidden; that's out of scope for this
  product, and nothing in the build may imply otherwise.

## Superseded decisions (kept for the record)

- **Tauri → pywebview.** Tauri assumes a Rust/JS backend; this app's backend
  is stdlib Python, so Tauri would need a frozen Python sidecar — two
  toolchains plus a known sidecar-cleanup footgun. pywebview is one Python
  process over the already-installed WebView2 runtime. Both approaches point
  a webview at the same local HTTP API, so nothing about the web UI changed
  when this was decided.
- **Agent-Reach / last30days / Archify / Mr.Holmes → not integrated.** The
  zero-login Scanner covers Search's actual needs (open web, scholarly,
  news, reference) without a login-gated dependency. Agent-Reach and
  last30days remain the natural candidates *if* Sources/Trails get built,
  but nothing currently in the repo assumes them.
- **A single-shot `/api/explore` call → a session-backed, observable search
  run.** The simpler path shipped first and worked; real-provider testing
  after the SSE work landed found it was silently swallowing failures
  (oversized prompts, malformed JSON) that the observable path surfaced and
  fixed. Both still exist; only one is wired to the UI.

## Integration risk, updated

1. ~~Spawning + driving Obscura from Python on Windows~~ — done, verified
   live (subprocess + stdout capture, stealth text-dump and byte/PDF paths
   both exercised against real URLs).
2. ~~Bundling a Python runtime inside a native `.exe`~~ — done
   (PyInstaller + pywebview, `build.ps1`), Obscura bundled pinned and
   hash-verified.
3. **Provider output reliability** turned out to be the real integration
   risk, not anticipated in the original plan: real models (observed on
   openrouter/llama-3.3-70b via its DeepInfra backend) wrap JSON in
   markdown fences, return citation objects instead of ID strings, or
   emit a valid object and then degenerate into garbled trailing tokens.
   The provider-JSON boundary in `search_runtime.py` now tolerates all
   three; this is worth remembering as a class of bug, not just three
   one-off fixes, if new structured-output call sites get added.
4. **Sources/Trails scheduling** (a background thread re-running work on a
   cadence, surviving app restarts, no always-on daemon) — unstarted,
   still the open design question from the original plan.

## Explicitly out of scope

Hosted/managed inference, network-level anonymity (IP masking — users are
told to run a VPN), accounts/cloud sync/teams, push notifications,
OSINT/people-search. Unchanged from the original plan.
