# Windows App Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the existing Reveriebot web app (stdlib server + HTML/JS UI) as a single-file native Windows desktop app (`Reveriebot.exe`) using pywebview + PyInstaller, with no feature changes.

**Architecture:** Introduce a frozen-aware `paths` module that splits read-only bundled assets (`web/`) from writable user data. Refactor `app.py` to resolve paths through it and to expose a `make_server()` that binds an ephemeral loopback port. A new `desktop.py` runs that server in a daemon thread and opens a native pywebview window pointed at it. In dev, data paths resolve to the repo root (unchanged behavior); only the frozen exe writes to `Documents\Reveriebot`.

**Tech Stack:** Python 3.14 (stdlib `http.server`, `unittest`), pywebview 6.x over WebView2, pythonnet (cp314 wheel), PyInstaller 6.x (`--onefile`, `console=False`).

## Global Constraints

- **Zero runtime dependencies in the core app.** The web app must still run with nothing pip-installed. Desktop deps (`pywebview`, `pythonnet`) are additive and live in a separate `requirements-desktop.txt`; PyInstaller is build-time only.
- **Tests use stdlib `unittest` only.** Never add pytest.
- **Python floor: 3.12+** (matches the existing codebase; verified on 3.14.6).
- **No em dashes in user-facing copy** (seeded `.env` comments, README). Use plain hyphens or rephrase.
- **Loopback only.** The server binds `127.0.0.1`. Never `0.0.0.0`.
- **Dev behavior must not change.** `python server/app.py` still serves at `http://localhost:8765` reading `.env`, `workspace/`, `vendor/` from the repo root.
- **Windows shell is PowerShell.** Do not background `python app.py &` + `pkill`; it does not kill Windows `python.exe`. Use `Start-Process -PassThru` then `Stop-Process -Id`, or a foreground run you Ctrl-C.

---

## File Structure

- **Create `server/paths.py`** — frozen-aware path resolver. Single source of truth for where the web assets, workspace, `.env`, and vendor dir live. One responsibility.
- **Modify `server/app.py`** — resolve paths via `paths`; extract `make_server()`; add `.env` template seeding. Keep `main()` for dev/browser mode.
- **Modify `server/tools.py`** — `find_obscura()` also searches `paths.vendor_dir()`.
- **Create `server/desktop.py`** — desktop entry point: start server in a daemon thread, open the pywebview window.
- **Create `reveriebot.spec`** — PyInstaller build config.
- **Create `requirements-desktop.txt`** — desktop runtime deps.
- **Create `build.ps1`** — one-command build to `dist\Reveriebot.exe`.
- **Create `tests/test_paths.py`, `tests/test_app_server.py`, `tests/test_tools_obscura.py`, `tests/test_desktop.py`** — stdlib unittest.
- **Modify `.gitignore`** — ignore `build/`, `dist/`, `tests/__pycache__/`.

---

### Task 1: `paths.py` frozen-aware resolver

**Files:**
- Create: `server/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `is_frozen() -> bool`
  - `resource_path(rel: str = "") -> str` (read-only bundled base; `web/` lives here)
  - `data_dir() -> str` (writable base; creates it)
  - `web_dir() -> str` = `resource_path("web")`
  - `workspace_dir() -> str` (creates `<data>/workspace`)
  - `vendor_dir() -> str` = `<data>/vendor` (not auto-created)
  - `env_file() -> str` = `<data>/.env`

- [ ] **Step 1: Write the failing test**

Create `tests/test_paths.py`:

```python
import importlib
import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)


class PathsTest(unittest.TestCase):
    def setUp(self):
        # Reload paths fresh each test so module-level state can't leak,
        # and clear the env override.
        os.environ.pop("REVERIEBOT_HOME", None)
        import paths
        self.paths = importlib.reload(paths)

    def tearDown(self):
        os.environ.pop("REVERIEBOT_HOME", None)

    def test_dev_data_dir_is_repo_root(self):
        # Not frozen (running under a normal interpreter) -> repo root.
        repo_root = os.path.abspath(os.path.join(SERVER, ".."))
        self.assertEqual(
            os.path.realpath(self.paths.data_dir()),
            os.path.realpath(repo_root),
        )

    def test_override_wins(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home")
        os.environ["REVERIEBOT_HOME"] = tmp
        self.assertEqual(
            os.path.realpath(self.paths.data_dir()),
            os.path.realpath(tmp),
        )
        self.assertTrue(os.path.isdir(tmp))

    def test_web_dir_ends_with_web(self):
        self.assertTrue(self.paths.web_dir().replace("\\", "/").endswith("/web"))

    def test_workspace_dir_is_created_under_data_dir(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home2")
        os.environ["REVERIEBOT_HOME"] = tmp
        ws = self.paths.workspace_dir()
        self.assertTrue(os.path.isdir(ws))
        self.assertEqual(
            os.path.realpath(os.path.dirname(ws)), os.path.realpath(tmp)
        )

    def test_env_file_under_data_dir(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home3")
        os.environ["REVERIEBOT_HOME"] = tmp
        self.assertEqual(
            os.path.realpath(self.paths.env_file()),
            os.path.realpath(os.path.join(tmp, ".env")),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_paths -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'paths'`.

- [ ] **Step 3: Write minimal implementation**

Create `server/paths.py`:

```python
"""Where things live - the one module that knows.

Splits read-only bundled assets (the web UI) from writable user data
(workspace, .env, vendor). Frozen-aware so the same code works whether we run
from source in dev or from a PyInstaller onefile exe.

In dev the writable base is the repo root, so `python server/app.py` behaves
exactly as before. Only the frozen exe writes to Documents\\Reveriebot.
Set REVERIEBOT_HOME to override the writable base (used by tests and power
users).
"""

import os
import sys

APP_NAME = "Reveriebot"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def _repo_root():
    # server/paths.py -> server -> repo root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel=""):
    """Read-only bundled asset base. The web/ tree lives under here."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = _repo_root()
    return os.path.join(base, rel) if rel else base


def data_dir():
    """Writable user-data base. Created on demand."""
    override = os.environ.get("REVERIEBOT_HOME")
    if override:
        base = override
    elif is_frozen():
        base = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME)
    else:
        base = _repo_root()
    os.makedirs(base, exist_ok=True)
    return base


def web_dir():
    return resource_path("web")


def workspace_dir():
    d = os.path.join(data_dir(), "workspace")
    os.makedirs(d, exist_ok=True)
    return d


def vendor_dir():
    return os.path.join(data_dir(), "vendor")


def env_file():
    return os.path.join(data_dir(), ".env")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_paths -v`
Expected: PASS (5 tests OK).

- [ ] **Step 5: Commit**

```bash
git add server/paths.py tests/test_paths.py
git commit -m "feat: add frozen-aware paths module"
```

---

### Task 2: Refactor `app.py` onto `paths` + `make_server()` + `.env` seeding

**Files:**
- Modify: `server/app.py`
- Test: `tests/test_app_server.py`

**Interfaces:**
- Consumes: `paths.web_dir()`, `paths.workspace_dir()`, `paths.env_file()` (Task 1).
- Produces:
  - `make_server(port=None, host="127.0.0.1") -> ThreadingHTTPServer` — bound, not yet serving. `port=0` binds an ephemeral free port; read it from `server.server_address[1]`. `port=None` uses `REVERIEBOT_PORT` (default 8765).
  - `seed_env(path: str) -> None` — writes a `.env` template if `path` is absent; never overwrites.
  - `load_env()` — now reads `paths.env_file()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_server.py`:

```python
import json
import os
import sys
import threading
import unittest
import urllib.request

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402


class MakeServerTest(unittest.TestCase):
    def test_ephemeral_port_is_bound(self):
        srv = app.make_server(port=0)
        try:
            port = srv.server_address[1]
            self.assertGreater(port, 0)
            self.assertEqual(srv.server_address[0], "127.0.0.1")
        finally:
            srv.server_close()

    def test_serves_config_endpoint(self):
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/config", timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertIn("providers", body)
                self.assertIn("tools", body)
        finally:
            srv.shutdown()
            srv.server_close()


class SeedEnvTest(unittest.TestCase):
    def test_seeds_when_absent_and_never_overwrites(self):
        tmp = os.path.join(
            os.environ.get("TEMP", "/tmp"), "reveriebot_seed_test.env"
        )
        if os.path.exists(tmp):
            os.remove(tmp)
        app.seed_env(tmp)
        self.assertTrue(os.path.isfile(tmp))
        with open(tmp, "r", encoding="utf-8") as fh:
            first = fh.read()
        self.assertIn("OPENROUTER_API_KEY", first)
        # Second call must not clobber user edits.
        with open(tmp, "a", encoding="utf-8") as fh:
            fh.write("\nUSER_EDIT=1\n")
        app.seed_env(tmp)
        with open(tmp, "r", encoding="utf-8") as fh:
            second = fh.read()
        self.assertIn("USER_EDIT=1", second)
        os.remove(tmp)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_app_server -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'make_server'`.

- [ ] **Step 3: Write minimal implementation**

In `server/app.py`, make these exact edits.

3a. Replace the imports/globals block. Change lines 22-33 (the `sys.path.insert`, the duplicate `import finder`, and the `ROOT`/`WEB`/`WORKSPACE`/`PORT` globals) to:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finder  # noqa: E402
import gateway  # noqa: E402
import paths  # noqa: E402
import studio  # noqa: E402
import tools  # noqa: E402
```

(Note: the duplicate `import finder` on the old line 25 is removed, and the four path globals are deleted - `paths` owns them now.)

3b. Add the `.env` template constant and `seed_env` just above `load_env` (old line 43). Keep copy free of em dashes:

```python
_ENV_TEMPLATE = """\
# Fill in whichever keys you have. This file stays on this machine - the app
# never sends keys anywhere except to the provider you select.
# You need ZERO keys to start if you run Ollama locally.

# --- Anthropic ---
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-4-8

# --- OpenAI ---
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# --- OpenRouter (one key, many open-weight models) ---
OPENROUTER_API_KEY=
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct

# --- xAI / Grok ---
XAI_API_KEY=
XAI_MODEL=grok-4

# --- Ollama (local, no key needed; requires Ollama running) ---
OLLAMA_MODEL=llama3.1:8b

# --- Finder ---
# Optional contact email. Unlocks Unpaywall and OpenAlex's faster polite pool.
FINDER_CONTACT_EMAIL=

# --- app ---
REVERIEBOT_PORT=8765
"""


def seed_env(path):
    """Write a starter .env if none exists. Never overwrites user edits."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_ENV_TEMPLATE)
```

3c. Rewrite `load_env` (old lines 43-54) to read the resolved env file:

```python
def load_env():
    """Minimal .env reader - avoids a python-dotenv dependency."""
    path = paths.env_file()
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
```

3d. Rewrite `safe_workspace_path` (old lines 57-64) to resolve against `paths.workspace_dir()`:

```python
def safe_workspace_path(rel):
    """Resolve a workspace-relative path, refusing anything that escapes it."""
    ws = paths.workspace_dir()
    target = os.path.realpath(os.path.join(ws, rel))
    root = os.path.realpath(ws)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError("path escapes the workspace")
    return target
```

3e. In `_list_workspace` (old lines 227-241), replace the two `WORKSPACE` references with a local `ws = paths.workspace_dir()`:

```python
    def _list_workspace(self):
        out = []
        ws = paths.workspace_dir()
        for dirpath, _dirs, names in os.walk(ws):
            for name in sorted(names):
                if name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ws).replace(os.sep, "/")
                out.append({
                    "path": rel,
                    "name": name,
                    "size": os.path.getsize(full),
                    "kind": "html" if name.endswith((".html", ".htm")) else "text",
                })
        return out
```

3f. In `_serve_static` (old lines 243-253), replace `WEB` with `paths.web_dir()`:

```python
    def _serve_static(self, route):
        rel = "index.html" if route in ("/", "") else route.lstrip("/")
        web_root = os.path.realpath(paths.web_dir())
        target = os.path.realpath(os.path.join(web_root, rel))
        if not (target == web_root or target.startswith(web_root + os.sep)):
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(target):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as fh:
            return self._send(200, fh.read(), ctype)
```

3g. Add `make_server` and rewrite `main` (old lines 256-276):

```python
def make_server(port=None, host="127.0.0.1"):
    """Build a bound (not-yet-serving) server. port=0 picks a free port;
    read it back from the returned server's .server_address[1]."""
    seed_env(paths.env_file())
    load_env()
    os.makedirs(paths.workspace_dir(), exist_ok=True)
    if port is None:
        port = int(os.environ.get("REVERIEBOT_PORT", "8765"))
    return ThreadingHTTPServer((host, port), Handler)


def main():
    srv = make_server()
    port = srv.server_address[1]

    ready = [p["id"] for p in gateway.available() if p["ready"]]
    present = [t["id"] for t in tools.status() if t["present"]]

    print("\n  Reveriebot")
    print(f"  http://localhost:{port}")
    print(f"  providers ready : {', '.join(ready) or 'none - add a key to .env'}")
    print(f"  tools detected  : {', '.join(present) or 'none (optional)'}\n")

    srv.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  stopped\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_app_server -v`
Expected: PASS (3 tests OK).

- [ ] **Step 5: Regression-check dev browser mode**

Run (PowerShell, foreground; Ctrl-C to stop):
`python server/app.py`
Expected: prints the banner with `http://localhost:8765` and a providers line that includes `openrouter` (the repo `.env` key is still read because dev `data_dir()` is the repo root). Open the URL in a browser, confirm the UI loads. Ctrl-C to stop.

- [ ] **Step 6: Commit**

```bash
git add server/app.py tests/test_app_server.py
git commit -m "refactor: resolve paths via paths module; add make_server + env seeding"
```

---

### Task 3: `tools.find_obscura()` searches the data-dir vendor folder

**Files:**
- Modify: `server/tools.py:21-41`
- Test: `tests/test_tools_obscura.py`

**Interfaces:**
- Consumes: `paths.vendor_dir()` (Task 1).
- Produces: `find_obscura()` now also checks `<data>/vendor/obscura/obscura.exe` and `<data>/vendor/obscura.exe` before falling back to PATH.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tools_obscura.py`:

```python
import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import paths  # noqa: E402
import tools  # noqa: E402


class FindObscuraTest(unittest.TestCase):
    def test_finds_binary_in_data_dir_vendor(self):
        tmp = os.path.join(
            os.environ.get("TEMP", "/tmp"), "reveriebot_obscura_test"
        )
        os.environ["REVERIEBOT_HOME"] = tmp
        try:
            vend = os.path.join(paths.vendor_dir(), "obscura")
            os.makedirs(vend, exist_ok=True)
            fake = os.path.join(vend, "obscura.exe")
            with open(fake, "w", encoding="utf-8") as fh:
                fh.write("stub")
            found = tools.find_obscura()
            self.assertEqual(
                os.path.realpath(found), os.path.realpath(fake)
            )
        finally:
            os.environ.pop("REVERIEBOT_HOME", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_tools_obscura -v`
Expected: FAIL - `find_obscura()` returns the repo `vendor/` binary (or `None`), not the data-dir stub.

- [ ] **Step 3: Write minimal implementation**

In `server/tools.py`, add `import paths` to the import block (after `import pdf` on line 21):

```python
import pdf
import paths
```

Then replace `find_obscura` (lines 37-41) with:

```python
def find_obscura():
    vend = paths.vendor_dir()
    return _first_existing(
        os.path.join(vend, "obscura", "obscura.exe"),
        os.path.join(vend, "obscura.exe"),
        os.path.join(VENDOR, "obscura", "obscura.exe"),
        os.path.join(VENDOR, "obscura.exe"),
    ) or shutil.which("obscura")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_tools_obscura -v`
Expected: PASS.

- [ ] **Step 5: Confirm no dev regression**

Run: `python -c "import sys; sys.path.insert(0,'server'); import tools; print(tools.find_obscura())"`
Expected: prints the path to the real `vendor/obscura/obscura.exe` in the repo (dev `vendor_dir()` == repo `vendor/`, so the existing binary is still found).

- [ ] **Step 6: Commit**

```bash
git add server/tools.py tests/test_tools_obscura.py
git commit -m "feat: find Obscura in the data-dir vendor folder"
```

---

### Task 4: `desktop.py` entry point (server thread + pywebview window)

**Files:**
- Create: `server/desktop.py`
- Test: `tests/test_desktop.py`

**Interfaces:**
- Consumes: `app.make_server()` (Task 2).
- Produces:
  - `start_server() -> tuple[ThreadingHTTPServer, int]` — makes the server, starts `serve_forever()` in a daemon thread, returns `(srv, port)`. Testable without a GUI.
  - `run() -> None` — calls `start_server()` then opens the pywebview window. Not unit-tested (GUI).

- [ ] **Step 1: Write the failing test**

Create `tests/test_desktop.py`:

```python
import json
import os
import sys
import unittest
import urllib.request

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import desktop  # noqa: E402


class StartServerTest(unittest.TestCase):
    def test_start_server_returns_live_loopback_server(self):
        srv, port = desktop.start_server()
        try:
            self.assertGreater(port, 0)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/config", timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("providers", json.loads(resp.read().decode("utf-8")))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_desktop -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'desktop'`.

- [ ] **Step 3: Write minimal implementation**

Create `server/desktop.py`:

```python
"""Reveriebot desktop - native Windows window over the local app.

Starts the in-process stdlib server on an ephemeral loopback port, then opens
a pywebview window pointed at it. Closing the window ends the process; the
server runs on a daemon thread and dies with it.

Run from source:  python server/desktop.py
Frozen exe:       Reveriebot.exe   (built via reveriebot.spec / build.ps1)
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402


def start_server():
    """Bind an ephemeral loopback port and serve on a daemon thread.
    Returns (server, port)."""
    srv = app.make_server(port=0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def run():
    import webview  # imported here so tests can load this module GUI-free

    _srv, port = start_server()
    webview.create_window(
        "Reveriebot",
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(940, 600),
        background_color="#0B0F19",
    )
    webview.start()


if __name__ == "__main__":
    run()
```

Note: `import webview` lives inside `run()` on purpose. The test imports `desktop` and calls only `start_server()`, so pywebview need not be installed for tests to pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_desktop -v`
Expected: PASS.

- [ ] **Step 5: Install desktop deps and dev-smoke the real window**

Create `requirements-desktop.txt`:

```
# Desktop packaging deps (the core web app does NOT need these).
pywebview>=5.0
pythonnet>=3.0.4 ; platform_system == "Windows"
```

Install and run the window from source:

```
python -m pip install -r requirements-desktop.txt
python server/desktop.py
```

Expected: a native window titled "Reveriebot" opens (dark background, no white flash, no terminal-only mode), showing the app UI. Interact briefly (the model dropdown populates from `/api/config`). Close the window; the process exits cleanly.

- [ ] **Step 6: Commit**

```bash
git add server/desktop.py tests/test_desktop.py requirements-desktop.txt
git commit -m "feat: add pywebview desktop entry point"
```

---

### Task 5: PyInstaller build (`reveriebot.spec` + `build.ps1`) and frozen-run verification

**Files:**
- Create: `reveriebot.spec`
- Create: `build.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `server/desktop.py` (Task 4), the `web/` tree, `pywebview`/`pythonnet`.
- Produces: `dist\Reveriebot.exe` (single file, no console).

- [ ] **Step 1: Add build artifacts to `.gitignore`**

Append to `.gitignore`:

```
# PyInstaller
build/
dist/
*.pyc
tests/__pycache__/
```

- [ ] **Step 2: Write the PyInstaller spec**

Create `reveriebot.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
# Build: powershell -File build.ps1   (or: python -m PyInstaller reveriebot.spec)
from PyInstaller.utils.hooks import collect_all

datas = [("web", "web")]          # bundle the UI; resource_path("web") finds it
binaries = []
hiddenimports = [
    "finder", "gateway", "studio", "tools", "pdf", "paths", "app",
]

# pywebview + its .NET bridge need their data/binaries/submodules collected.
for pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # pythonnet metadata name differs from import name; webview covers it

a = Analysis(
    ["server/desktop.py"],
    pathex=["server"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Reveriebot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,           # no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)
```

- [ ] **Step 3: Write the build script**

Create `build.ps1`:

```powershell
# Build Reveriebot.exe (single-file, no console).
$ErrorActionPreference = "Stop"

Write-Host "Installing build + desktop deps..."
python -m pip install -r requirements-desktop.txt
python -m pip install pyinstaller

Write-Host "Building..."
python -m PyInstaller reveriebot.spec --noconfirm --clean

$exe = Join-Path $PSScriptRoot "dist\Reveriebot.exe"
if (Test-Path $exe) {
    Write-Host "Built: $exe"
} else {
    Write-Error "Build finished but dist\Reveriebot.exe not found."
}
```

- [ ] **Step 4: Run the build**

Run: `powershell -File build.ps1`
Expected: PyInstaller completes; prints `Built: ...\dist\Reveriebot.exe`. Build takes a few minutes.

- [ ] **Step 5: Frozen-run verification (manual checklist)**

Before launching, put Obscura where the frozen app looks for it:
`New-Item -ItemType Directory -Force "$env:USERPROFILE\Documents\Reveriebot\vendor" ; Copy-Item -Recurse -Force "vendor\obscura" "$env:USERPROFILE\Documents\Reveriebot\vendor\obscura"`

Launch: `.\dist\Reveriebot.exe`

Verify each:
- [ ] Window opens, dark, no terminal window, no white flash.
- [ ] `Documents\Reveriebot\.env` was created (seeded template).
- [ ] Model dropdown lists providers (they will be "not ready" until keys are added to the seeded `.env`; that is expected).
- [ ] Add your OpenRouter key to `Documents\Reveriebot\.env`, relaunch, confirm `openrouter` shows ready.
- [ ] A search returns real papers.
- [ ] Reading a paper (HTML and a PDF) works - engine shows "via Obscura" (Obscura detected from the Documents vendor folder).
- [ ] Saving a brief writes a file under `Documents\Reveriebot\workspace\` and it reopens from the Library.

- [ ] **Step 6: Commit**

```bash
git add reveriebot.spec build.ps1 .gitignore
git commit -m "feat: PyInstaller onefile build for Reveriebot.exe"
```

---

### Task 6: Docs - README build/run section

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a "Desktop app" section to `README.md`**

Add this section (adjust to sit naturally with the existing structure; no em dashes):

```markdown
## Desktop app (Windows)

Run from source (dev):

    python server/app.py        # browser at http://localhost:8765
    python server/desktop.py    # native window (needs: pip install -r requirements-desktop.txt)

Build the single-file exe:

    powershell -File build.ps1   # produces dist\Reveriebot.exe

The packaged app keeps your data in `Documents\Reveriebot\`:

    Documents\Reveriebot\
      .env         your API keys (seeded on first run; edit to add keys)
      workspace\   saved briefs, papers, drafts
      vendor\      drop Obscura here (vendor\obscura\obscura.exe) for full-text reads

Prerequisite on other machines: the Microsoft Edge WebView2 runtime (standard on
Windows 11).
```

- [ ] **Step 2: Run the full test suite one last time**

Run: `python -m unittest discover -s tests -v`
Expected: all tests PASS (paths, app_server, tools_obscura, desktop).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: desktop build and run instructions"
```

---

## Self-Review

**Spec coverage:**
- paths.py read-only/writable split -> Task 1. ✓
- app.py refactor + make_server + ephemeral port -> Task 2. ✓
- .env seeding / first-run BYOK -> Task 2 (`seed_env`) + Task 5 checklist. ✓
- tools.find_obscura data-dir search -> Task 3. ✓
- desktop.py daemon-thread server + pywebview window + dark background -> Task 4. ✓
- reveriebot.spec onefile/console=False, web/ bundled, vendor+workspace excluded -> Task 5. ✓
- build.ps1 + requirements-desktop.txt -> Tasks 4 (requirements) + 5 (build). ✓
- Dev behavior unchanged -> Task 2 Step 5, Task 3 Step 5 regression checks. ✓
- Verification plan (dev smoke, frozen run) -> Task 4 Step 5, Task 5 Step 5. ✓
- Risk: PyInstaller misses dynamic imports -> hiddenimports in Task 5 spec; frozen run exercises every route. ✓
- Risk: pythonnet bundling -> collect_all("webview"/"clr_loader"/"pythonnet") in Task 5 spec. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code; every command has expected output. ✓

**Type consistency:** `make_server(port, host)` defined in Task 2, consumed identically in Task 4. `start_server() -> (srv, port)` defined and consumed consistently. `paths.*` names match across Tasks 1-4. `seed_env(path)` consistent. ✓

## Notes for the implementer

- The web UI, gateway, finder, studio, and pdf modules are NOT modified. If a change seems to require touching them, stop and re-read the spec - it is out of scope.
- Do not background the dev server with `&`/`pkill` on Windows; it leaves stale `python.exe` on the port. Use a foreground run and Ctrl-C, or PowerShell `Start-Process -PassThru` + `Stop-Process -Id`.
- If `collect_all("pythonnet")` errors during the build, that is fine - the `try/except` swallows it and `collect_all("webview")` already pulls the bridge. Only worry if the frozen run fails to open a window.
```
