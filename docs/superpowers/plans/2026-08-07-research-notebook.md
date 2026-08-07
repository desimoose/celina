# Research Notebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first, NotebookLM-inspired research notebook for adult self-learners, with source capture, evidence notes, grounded tutor context, and a generated learning-path view inside Celina.

**Architecture:** Add a small file-backed notebook domain under `workspace/notebooks`, exposed through narrow JSON endpoints in the existing stdlib server. Add a new notebook surface to the vanilla UI while preserving Search and Library; the existing `/api/chat` gateway receives notebook source context so the current assistant becomes the notebook tutor without adding a second model path.

**Tech Stack:** Python 3 standard library, `http.server`, JSON files under the existing `CELINA_HOME` data root, vanilla HTML/CSS/JavaScript, stdlib `unittest`.

## Global Constraints

- Preserve Celina's local-first behavior: notebook files and notes stay under the configured local data directory; no new telemetry, hosted storage, or account system.
- Preserve existing Search, Library, session privacy, CSRF, and provider gateway behavior.
- Use the existing visual system: Manrope reading UI, IBM Plex Mono for machine metadata, paper/obsidian surfaces, restrained ember accent, cardless editorial layout, and WCAG AA keyboard accessibility.
- Notebook tutor context must be source-limited and visibly labeled as grounded in the active notebook; it must not claim unsupported certainty.
- All new write endpoints must require the existing local mutation guard and reject traversal, malformed JSON, oversized fields, and invalid notebook IDs.
- Keep the implementation stdlib-only on the server and build-step-free in the browser.

## File Map

- Create `server/notebooks.py`: notebook schema, validation, safe IDs, JSON persistence, source/note/path mutations.
- Create `tests/test_notebooks.py`: store-level validation, persistence, ordering, and learning-path tests.
- Modify `server/app.py`: import notebook store, route notebook GET/POST requests, build bounded tutor context for `/api/chat` callers.
- Modify `tests/test_app_server.py`: endpoint coverage for notebook create/read/source/note/path operations and mutation rejection.
- Modify `web/index.html`: Notebook navigation and notebook workspace markup.
- Modify `web/app.js`: notebook state, API calls, rendering, source/note/path interactions, notebook-aware assistant context.
- Modify `web/styles.css`: notebook workspace layout, source list, evidence blocks, path rows, active/live states, responsive behavior.
- Modify `README.md`: document the first notebook workflow and local data location.

### Task 1: Notebook domain and local persistence

**Files:**
- Create: `server/notebooks.py`
- Create: `tests/test_notebooks.py`

**Interfaces:**
- `list_notebooks() -> list[dict]`
- `create_notebook(title: str, goal: str = "") -> dict`
- `read_notebook(notebook_id: str) -> dict`
- `add_source(notebook_id: str, payload: dict) -> dict`
- `add_note(notebook_id: str, payload: dict) -> dict`
- `generate_learning_path(notebook_id: str, payload: dict) -> dict`

- [ ] Write tests for creating a notebook, rejecting empty/oversized titles, and returning deterministic IDs.
- [ ] Write tests for source validation: required title, optional URL, excerpt length limit, and safe source IDs.
- [ ] Write tests for note validation and newest-first ordering.
- [ ] Write tests for learning-path generation from the notebook goal and source titles.
- [ ] Run `python -m unittest tests.test_notebooks -v` and confirm the new tests fail before implementation.
- [ ] Implement atomic JSON writes below `paths.data_dir()/workspace/notebooks/<id>.json` with a schema containing `id`, `title`, `goal`, `created_at`, `updated_at`, `sources`, `notes`, and `learning_path`.
- [ ] Implement path validation using the same safe-component style as `server/paths.py`; never join an unvalidated ID into a file path.
- [ ] Implement the minimal learning-path generator with three sections: foundations, source synthesis, and application/review; derive source references from saved source IDs.
- [ ] Run `python -m unittest tests.test_notebooks -v` and confirm all store tests pass.

### Task 2: Notebook API integration

**Files:**
- Modify: `server/app.py`
- Modify: `tests/test_app_server.py`

**Interfaces:**
- `GET /api/notebooks` returns `{ "notebooks": [...] }`.
- `POST /api/notebooks` accepts `{ "title": string, "goal": string }`.
- `GET /api/notebooks/{id}` returns `{ "notebook": {...} }`.
- `POST /api/notebooks/{id}/sources` accepts `{ "title": string, "url": string, "kind": string, "excerpt": string }`.
- `POST /api/notebooks/{id}/notes` accepts `{ "title": string, "body": string, "source_ids": string[] }`.
- `POST /api/notebooks/{id}/learning-path` accepts `{ "goal": string, "depth": "survey"|"college"|"graduate" }`.

- [ ] Write endpoint tests for list/create/read and the two mutation endpoints using a temporary `CELINA_HOME`.
- [ ] Write tests proving notebook writes without the existing local mutation guard return `403`.
- [ ] Write tests proving invalid IDs and malformed bodies return `400` without creating files.
- [ ] Run `python -m unittest tests.test_app_server -v` and confirm the new endpoint tests fail before routing exists.
- [ ] Add route dispatch before the existing workspace/project routes, preserving all current paths.
- [ ] Require `_allows_session_mutation(parsed.query)` for POST notebook mutations and return the existing `_forbidden()` response when absent.
- [ ] Bound request fields before passing them to the store; return JSON errors consistent with existing endpoints.
- [ ] Run `python -m unittest tests.test_app_server -v tests.test_notebooks -v` and confirm all backend tests pass.

### Task 3: Notebook workspace interface

**Files:**
- Modify: `web/index.html`
- Modify: `web/styles.css`

**Visual thesis:** A quiet editorial study desk: a narrow notebook rail, a paper-white evidence canvas, and a focused learning path with one ember accent for the active item.

**Content plan:** Notebook title and goal first; source/evidence list second; learning path and saved notes third; tutor remains in the existing assistant rail as contextual support.

**Interaction thesis:** Source selection changes the active evidence context; path rows reveal the next useful action; the live ember marker moves only while a notebook action is saving or generating.

- [ ] Add a `Notebook` nav button using the existing inline SVG and `data-view="notebook"` convention.
- [ ] Add `#s-notebook` with a toolbar containing notebook title, goal, notebook selector, and create-notebook action.
- [ ] Add a three-region content layout: source rail (`#notebook-sources`), center workspace (`#notebook-main`), and path/notes inspector (`#notebook-inspector`).
- [ ] Add accessible empty states for no notebooks, no sources, no notes, and no learning path.
- [ ] Add source and note forms with labels, field limits, and explicit save buttons.
- [ ] Add a learning-path form with goal and depth controls and a list container for generated sections.
- [ ] Add `.notebook-*` styles using existing tokens, sharp evidence separators, readable measures, no dashboard card mosaic, responsive stacking below 960px, and visible focus states.
- [ ] Verify the static page loads without missing IDs by running the existing app server smoke test.

### Task 4: Notebook behavior and tutor context

**Files:**
- Modify: `web/app.js`

**Interfaces:**
- `state.notebooks: []`, `state.activeNotebook: null`, `state.activeNotebookSourceId: null`.
- `loadNotebooks()`, `selectNotebook(id)`, `createNotebook()`, `addNotebookSource()`, `addNotebookNote()`, `generateNotebookPath()`.
- `notebookContextText()` returns a bounded plain-text context containing notebook goal, selected source excerpts, saved notes, and path headings.

- [ ] Add notebook state without removing existing search/project/session state.
- [ ] Extend `nav()` with the `notebook` surface and load notebooks when selected.
- [ ] Load and render notebooks; preserve the selected notebook across refreshes within the current browser session.
- [ ] Add create notebook flow with adult-oriented copy such as “What are you trying to understand?” rather than gamified onboarding.
- [ ] Add source capture flow that accepts a title, URL, kind, and excerpt; show source metadata and evidence text in the main workspace.
- [ ] Add note capture flow with optional source references; render notes as plain editorial entries with timestamps.
- [ ] Add learning-path generation flow and render foundations/synthesis/application sections with referenced source titles.
- [ ] Update `contextText()` to prefer notebook context while the notebook view is active, capped at 40,000 characters to match the existing chat guard.
- [ ] Update assistant header/placeholder when notebook view is active to say “Ask about this notebook” and “Ask about the sources, gaps, or next step”.
- [ ] Add explicit loading/error states and restore the existing assistant behavior when leaving the notebook.
- [ ] Run a manual browser smoke test against `python server/app.py`: create notebook, add source, add note, generate path, ask tutor question, switch to Search, and return.

### Task 5: Documentation, regression coverage, and review

**Files:**
- Modify: `README.md`
- Modify: `tests/test_app_server.py` as needed for final regressions.

- [ ] Document the notebook workflow, local storage location, and the distinction between kept notebook work and temporary search-session traffic.
- [ ] Run `python -m unittest discover -s tests -v` and record the exact result.
- [ ] Run `python -m py_compile server/*.py` and record the exact result.
- [ ] Run the server smoke test with `CELINA_HOME` pointed at a temporary directory and verify notebook files are created only under `workspace/notebooks`.
- [ ] Review the final diff for unrelated changes, unsafe path joins, missing CSRF/mutation checks, unbounded context, and broken existing navigation.
- [ ] Run the full verification commands again after any fixes before reporting completion.

