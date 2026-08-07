# Push Checkpoint, Privacy Controls, and Research-to-Notebook Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Push the current completed Celina work to `main`, then finish privacy controls, Search-to-Notebook capture, URL/PDF ingestion, citations, and verification.

**Architecture:** Preserve Celina’s stdlib Python + vanilla JavaScript architecture. Extend the existing session store, settings API, notebook API, Search result renderer, and PDF extraction path without adding a framework, database, or frontend build step.

## Global Constraints

- Push the current dirty workspace to `origin/main` before new feature work.
- Keep local-first behavior and preserve existing CSRF, launch-cookie, provider gateway, and session privacy controls.
- Hosted AI providers must be labeled as receiving the user’s question/context; Ollama remains local-only.
- Default stopped-session retention remains 24 hours.
- Incognito sessions are deleted on end, page close, and server restart.
- No new runtime dependencies or frontend build step.
- Use TDD for every production change and run a focused test before broad verification.

---

### Task 0: Checkpoint and push current work

**Files:** all currently modified/untracked files.

- Run the current full tests, Python compilation, JavaScript syntax check, and diff check.
- Stage all current workspace changes, including the existing notebook, session privacy, project, and UI work.
- Commit on `main` with `feat: add research notebook and privacy sessions`.
- Push with `git push origin main`.
- Confirm the working tree is clean and local `HEAD` matches `origin/main`.

### Task 1: Privacy settings and live session cleanup

**Interfaces:**

- `GET /api/settings` exposes `session_retention_seconds` and provider privacy metadata.
- `POST /api/settings` accepts only retention values `0`, `3600`, `86400`, or `604800`.
- Add `SessionJanitor(store, retention_provider, interval_seconds=3600)` with `start()`, `stop()`, and `run_once()`.

- Persist the selected retention through the existing `.env` settings path.
- Run cleanup at startup and hourly while the server is running.
- Stop and join the janitor on server shutdown.
- Add a current-session deletion control and visible session status.
- Test invalid retention, persistence, janitor cleanup/preservation, orphaned Incognito cleanup, and clean shutdown.

### Task 2: Add Search results directly to Notebook

- Extend captured notebook sources with `origin: "search"` and a bounded `source_result` metadata object.
- Add an Add to Notebook action to every Search result.
- Add a target-notebook selector populated from `GET /api/notebooks`.
- If no notebook exists, open the existing creation flow with the search query prefilled.
- Capture title, canonical URL, source kind, and abstract/snippet as a clearly labeled search excerpt.
- Preserve Read and Library behavior and mark a captured result as Added.

### Task 3: URL/PDF ingestion and citations

- Add `POST /api/notebooks/{id}/sources/import` with `{url, title?, kind?}`.
- Reuse the existing fetch and PDF pipeline.
- Add bounded page extraction when the installed PDF backend exposes pages; cap at 50 pages and 2,000 characters per page.
- Fall back to one document-level citation when page extraction is unavailable.
- Store only bounded excerpts and citation text in notebook JSON.
- Require the existing mutation guard and reject unsafe URLs, oversized URLs, malformed notebooks, and unknown IDs.
- Add Notebook controls for URL/PDF import, progress/errors, citation labels, and tutor context inclusion.

### Task 4: Privacy UX and provider disclosure

- Show Ollama as local-only and hosted providers as sending question/context to the provider.
- Show Incognito and retention badges near Search and in Settings.
- Add concise copy that does not promise provider-side deletion.
- Add Delete current session to Search and Settings.
- Clear browser `state.sessionId` after deletion while preserving Notebook data.
- Manually verify normal retention, immediate retention, Incognito end/close/restart deletion, provider labels, Search capture, URL/PDF import, and citations.

### Task 5: TDD, delegated implementation, and final verification

- Use a fresh implementer subagent and separate task reviewer for each independent task.
- Review Critical/Important findings with a fix pass and re-review before moving on.
- Record completed tasks in `.superpowers/sdd/progress.md`.
- Run:

```bash
python -m unittest discover -s tests -v
python -m py_compile server/*.py
node --check web/app.js
git diff --check
```

Acceptance target: all existing tests plus privacy, janitor, Search-to-Notebook, import, citation, and settings tests pass with no unrelated regressions.

## Assumptions

- The current dirty workspace is intentionally committed and pushed directly to `main`.
- Retention defaults to 24 hours and cleanup runs hourly plus at startup.
- Incognito protects Celina-local session data, not retention policies of external AI providers.
- Page-level PDF citations are used when available; otherwise the UI shows a document-level citation.
