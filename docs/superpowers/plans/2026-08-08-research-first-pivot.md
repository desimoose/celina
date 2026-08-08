# Research-First Product Pivot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Restore Celina’s primary identity as a private Google-style research workspace while preserving the existing notebook, learning, privacy, and guided-study capabilities.

**Architecture:** Make an additive HTML, CSS, JavaScript, documentation, and static-test pass. Search remains the default surface and becomes the strongest navigation action. Workspace/Home and Notebook remain available as secondary research tools. No routes, stored data, providers, or learning APIs are removed.

**Tech Stack:** Existing stdlib Python server, vanilla JavaScript, static HTML/CSS, unittest, and the Node test runner.

## Global Constraints

- Preserve Search, Library, Notebook, privacy, session, citation, import, study-set, and Guided Study Session behavior.
- Do not delete or migrate notebook or study data.
- Do not add runtime dependencies, a frontend build step, or a new database.
- Search is the default first surface and primary action.
- Product copy describes research first; learning remains an optional depth layer.
- Keep CSRF, launch-cookie, provider disclosure, session retention, and Incognito behavior unchanged.

---

### Task 1: Record direction and add the failing pivot contract

**Files:**
- Create: docs/PRODUCT_DIRECTION.md
- Modify: tests/test_settings.py

**Interfaces:**
- The direction document defines the product language used by the UI.
- Static tests verify navigation and copy without requiring a browser or new API.

- [ ] Step 1: Add this failing test to SettingsUiSourceTest:

    def test_research_first_navigation_keeps_learning_as_secondary_depth(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-tooltip="Search and read"', html)
        self.assertIn('aria-label="Research workspace"', html)
        self.assertIn(">Workspace<", html)
        self.assertIn("Optional learning", html)
        self.assertIn("Save useful research", html)
        self.assertIn("Save and query sources", html)

- [ ] Step 2: Run the focused test and verify it fails:

    python -m unittest tests.test_settings.SettingsUiSourceTest.test_research_first_navigation_keeps_learning_as_secondary_depth -v

Expected: FAIL because the current rail and Home/Notebook copy foreground learning.

- [ ] Step 3: Create docs/PRODUCT_DIRECTION.md with:

    # Celina Product Direction

    ## North star

    Celina is a private research workspace: ask a question, find real sources, inspect the evidence, keep useful work, and return to it later.

    ## Primary loop

    1. Ask a question or paste a link.
    2. Search across real sources.
    3. Read the answer and inspect supporting evidence.
    4. Save useful research to Library or a Notebook.
    5. Return to the question, source, or notebook when the work continues.

    ## Product hierarchy

    - Search is the default surface and primary action.
    - Library is the return path for saved outputs and research.
    - Notebook is the source-grounded workspace for a question or line of inquiry.
    - Learning tools are an optional depth layer inside Notebook.

    ## Preserved capabilities

    Notebooks, URL/PDF import, citations, Search-to-Notebook capture, privacy controls, Incognito sessions, provider disclosure, study sets, spaced review, and Guided Study Sessions remain supported. This pivot changes emphasis and navigation language; it does not delete underlying features or data.

    ## Non-goals for the next pass

    - No course-management system.
    - No mastery dashboard expansion.
    - No new social, account, or collaboration layer.
    - No additional learning workflow until the research loop is stable and clearly useful.

- [ ] Step 4: Run the same focused test again. Expected: still FAIL only on the not-yet-updated UI copy.

### Task 2: Make Search the dominant navigation path

**Files:**
- Modify: web/index.html
- Test: tests/test_settings.py

**Interfaces:**
- Keep data-view="work" and all existing element IDs unchanged.
- Reorder only rail buttons and update visible labels/tooltips.

- [ ] Step 1: Move the existing Search button before Home. Update the rail metadata to:

    Search: data-view="work", aria-label="Search and read", data-tooltip="Search and read", visible label Search
    Workspace: data-view="home", aria-label="Research workspace", data-tooltip="Return to saved research", visible label Workspace
    Library: data-view="library", aria-label="Library", data-tooltip="Open saved research", visible label Library
    Notebook: data-view="notebook", aria-label="Notebook", data-tooltip="Save and query sources", visible label Notebook

Keep each SVG body unchanged.

- [ ] Step 2: Change the Home surface’s visible copy while preserving every existing rendering ID:

    aria-label: Research workspace
    eyebrow: Research workspace
    heading: Keep the thread.
    description: Return to active questions, saved research, and the sources you want to understand better.
    guided button: Optional learning review
    queue eyebrow: Optional learning
    queue heading: Review queue
    next-step heading: Research next steps

Change the guided button class from btn--primary to btn--ghost so learning is accessible but not the primary action. Keep id guided-session-start and its click behavior unchanged.

- [ ] Step 3: Change the Notebook toolbar copy:

    eyebrow: Research notebook
    goal: Bring a question, a paper, or a line of inquiry you want to keep building.

Keep the study section and Guided Study Session markup available.

- [ ] Step 4: Run the focused test:

    python -m unittest tests.test_settings.SettingsUiSourceTest.test_research_first_navigation_keeps_learning_as_secondary_depth -v

Expected: PASS.

### Task 3: Align client copy and presentation without changing behavior

**Files:**
- Modify: web/app.js
- Modify: web/styles.css
- Modify: tests/test_settings.py

**Interfaces:**
- Keep nav("home"), /api/learning-home, startGuidedSession, and all existing IDs unchanged.
- Change only status, heading, placeholder, and presentation text.

- [ ] Step 1: Extend the static test:

    with open(os.path.join(root, "web", "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    self.assertIn('head.textContent = "Ask about your research"', js)
    self.assertIn('input").placeholder = "Ask a research question or paste a link"', js)
    self.assertIn("Research workspace", html)

- [ ] Step 2: Run the focused test and verify the new assertions fail.

- [ ] Step 3: In web/app.js, leave all endpoint calls, state transitions, and payloads unchanged. For the Home branch use:

    const head = document.querySelector(".asst-head span");
    if (head) head.textContent = "Ask about your research";
    $("input").placeholder = "Ask a research question or paste a link";

Keep Notebook copy as:

    if (head) head.textContent = "Ask about this notebook";
    $("input").placeholder = "Ask about the sources and notes";

- [ ] Step 4: Add to web/styles.css:

    .learning-home-head-actions .btn:first-child { border-color: var(--ash); color: var(--graphite); }
    .learning-home-head-actions .btn:first-child:hover:not(:disabled) { border-color: var(--ember); color: var(--ember-text); }

- [ ] Step 5: Run:

    python -m unittest tests.test_settings.SettingsUiSourceTest.test_research_first_navigation_keeps_learning_as_secondary_depth -v
    node --check web/app.js
    git diff --check

Expected: all commands PASS.

### Task 4: Full verification, scope review, and push

**Files:**
- Modify: .superpowers/sdd/progress.md

**Interfaces:**
- No runtime interfaces change.
- The progress ledger records that the pivot preserves learning features.

- [ ] Step 1: Append this ledger entry:

    - [x] Follow-up: Research-first product pivot; Search restored as primary navigation while learning remains optional and preserved (implemented, verified, pushed)

- [ ] Step 2: Run:

    python -m unittest discover -s tests -v
    $jsTests = Get-ChildItem tests -Filter *.js | ForEach-Object FullName
    node --test $jsTests
    $pyFiles = Get-ChildItem server -Filter *.py | ForEach-Object FullName
    python -m py_compile $pyFiles
    node --check web/app.js
    git diff --check

Expected: all tests and syntax/compile checks pass, with no diff-check output.

- [ ] Step 3: Review the diff and confirm no server files, notebook data, study data, endpoint names, or learning controls changed.

- [ ] Step 4: Commit and push:

    git add docs/PRODUCT_DIRECTION.md docs/superpowers/plans/2026-08-08-research-first-pivot.md tests/test_settings.py web/index.html web/app.js web/styles.css
    git commit -m "refactor: restore research-first product focus"
    git push origin main

- [ ] Step 5: Confirm clean synchronized state:

    git status --short
    git rev-parse HEAD
    git rev-parse origin/main

Expected: clean status and matching hashes.
