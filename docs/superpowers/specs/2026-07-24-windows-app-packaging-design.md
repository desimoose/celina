# Reveriebot as a native Windows app — design

**Date:** 2026-07-24
**Status:** Approved, ready for implementation plan
**Milestone:** Package the existing web app as a single-file native Windows desktop app.

## Goal

Turn the working Reveriebot web app (stdlib Python server + plain HTML/JS UI) into a
double-click Windows application: a native, chromeless window with no terminal and no
browser, distributable as a single `Reveriebot.exe`. Nothing about the product's
features changes in this milestone — this is a desktop shell around what already works,
plus the one architectural change that freezing forces.

Chosen stack (decided during brainstorming, alternatives rejected):

- **Window:** `pywebview` over the WebView2 runtime already installed on the machine
  (Edge Chromium, v150 present). One Python process, native window, no Rust, no Node.
- **Packaging:** PyInstaller `--onefile`, `console=False`.
- **Rejected:** Tauri + Python sidecar (two toolchains, two build pipelines, and the
  known "Windows python.exe won't die cleanly" sidecar-cleanup footgun). pywebview and
  Tauri both just load the same local web UI over a loopback API, so nothing built here
  is wasted if we graduate to Tauri later.

### Verified feasibility facts (measured on this machine, not assumed)

- Python 3.14.6, pip 26.1.2.
- `pyinstaller` 6.21.0 — wheel available.
- `pywebview` 6.2.1 — wheel available.
- `pythonnet` 3.1.0 — ships a prebuilt **cp314** wheel
  (`pythonnet-3.1.0-cp310.cp311.cp312.cp313.cp314-none-win32.win_amd64.whl`). No
  source compile. This is pywebview's Windows (EdgeChromium) backend.
- WebView2 runtime present at v150 — the window renderer, already installed.

## The core idea: split "bundled" from "user data"

Today every path is derived from `__file__`-relative `ROOT`:

- `server/app.py`: `ROOT`, `WEB = ROOT/web`, `WORKSPACE = ROOT/workspace`,
  `PORT = 8765`, `.env` read from `ROOT/.env`.
- `server/tools.py`: `ROOT`, `VENDOR = ROOT/vendor`, `find_obscura()` checks
  `vendor/obscura/obscura.exe`.

Once frozen into an `.exe` (which may sit in a read-only location like Program Files),
the app can no longer write next to itself, and bundled files live inside PyInstaller's
extraction dir, not the repo. So the design draws one clean line between **read-only
bundled assets** and **writable user data**, centralized in a single new module.

### `server/paths.py` (new)

The only place that knows where things are. Frozen-aware.

- `is_frozen()` → `getattr(sys, "frozen", False)`.
- `resource_path(rel)` → **read-only bundled assets** (the `web/` UI).
  - Frozen: `os.path.join(sys._MEIPASS, rel)`.
  - Dev: repo path (`<repo>/rel`).
- `data_dir()` → **writable user data** at `%USERPROFILE%\Documents\Reveriebot\`.
  - Resolved via `os.path.expanduser("~")` + `Documents\Reveriebot`. If a
    `REVERIEBOT_HOME` env var is set, use that instead (testing / power users).
  - Created on first call (`os.makedirs(..., exist_ok=True)`).
  - Holds `workspace/`, `.env`, and `vendor/`.
- Convenience: `web_dir()` = `resource_path("web")`, `workspace_dir()` =
  `data_dir()/workspace` (created), `vendor_dir()` = `data_dir()/vendor`,
  `env_file()` = `data_dir()/.env`.

Why this seam does triple duty:

1. Makes freezing work (read-only bundle vs. writable state).
2. Satisfies "all on local drive, human-readable" — your work lands in *Documents*,
   browsable in Explorer, no lock-in.
3. `Documents\Reveriebot\` is exactly where the future **Project folders** will live, so
   this milestone lays that foundation without building it.

## Components

### 1. `server/paths.py` (new)
The resolver described above. ~30–40 lines, stdlib only.

### 2. `server/app.py` (refactor, not rewrite)
- Replace module globals `WEB`, `WORKSPACE`, `PORT`, and the `.env` path with `paths`
  calls: `paths.web_dir()`, `paths.workspace_dir()`, `paths.env_file()`.
- `load_env()` reads `paths.env_file()`.
- `safe_workspace_path()` and `_serve_static()` resolve against `paths.workspace_dir()`
  / `paths.web_dir()` (the containment checks stay identical).
- **Extract `make_server(port=0, host="127.0.0.1")`** returning a configured
  `ThreadingHTTPServer` (bound but not yet serving). Binding port `0` picks an
  **ephemeral free port**; the caller reads the real port from
  `server.server_address[1]`.
- Keep `main()` for `python server/app.py` dev/browser mode: it calls
  `make_server(PORT)` with the existing 8765 default (via `REVERIEBOT_PORT` env),
  prints the banner, and `serve_forever()`. Unchanged developer experience.

### 3. `server/tools.py` (small edit)
- `find_obscura()` also checks `paths.vendor_dir()` locations
  (`<data>/vendor/obscura/obscura.exe`, `<data>/vendor/obscura.exe`) in addition to the
  existing repo `vendor/` and `shutil.which("obscura")`. Obscura is dropped beside the
  user's data — swappable, and kept out of the frozen bundle (it is ~43 MB and optional).
- `VENDOR`/`ROOT` in `tools.py` stay for dev, but detection prefers the data dir when
  frozen. Keep the change minimal: add data-dir candidates to the `find_obscura()`
  search list.

### 4. `server/desktop.py` (new) — the app entry point
Flow:
1. `app.load_env()` (reads `data_dir()/.env`); ensure `workspace_dir()` exists.
2. `srv = app.make_server(0)`; `port = srv.server_address[1]`.
3. Start `srv.serve_forever()` in a **daemon thread**.
4. `webview.create_window("Reveriebot", f"http://127.0.0.1:{port}",
   background_color="#0B0F19", width=1280, height=820, min_size=(940, 600))`.
5. `webview.start()` on the **main thread** (required on Windows).
6. When the window closes, `webview.start()` returns; the process exits and the daemon
   thread dies with it. No explicit server teardown needed (loopback, in-process).

`background_color="#0B0F19"` matches the app's `--bg` token so there is no white flash
before the UI paints.

### 5. `reveriebot.spec` (new) — PyInstaller config
- Entry: `server/desktop.py`.
- `console=False` (no terminal), `--onefile` (single `Reveriebot.exe`).
- `datas`: bundle the entire `web/` tree to `web/` inside the bundle (so
  `resource_path("web")` resolves under `_MEIPASS`).
- `hiddenimports` / explicit imports: ensure `finder`, `gateway`, `studio`, `tools`,
  `pdf`, `paths` are all collected (they are imported after a runtime
  `sys.path.insert`; PyInstaller's static analysis may miss them, so name them
  explicitly).
- **Excluded from the bundle:** `vendor/` (Obscura) and `workspace/` — both live in the
  data dir, created/managed at runtime.
- Icon: optional (`icon=` left unset for now; nice-to-have polish, not core).

### 6. `build.ps1` (new) + `requirements-desktop.txt` (new)
- `requirements-desktop.txt`: `pywebview` (pulls `pythonnet` on Windows). Kept separate
  from the existing optional `pypdf` in `requirements.txt`.
- `build.ps1`:
  1. `python -m pip install -r requirements-desktop.txt pyinstaller`
  2. `python -m PyInstaller reveriebot.spec --noconfirm`
  3. Report the path to `dist\Reveriebot.exe`.

## First-run & BYOK keys

On first launch, `data_dir()` and `workspace/` are created, and if `.env` is absent a
template is seeded with commented-out key slots (Anthropic, OpenAI, OpenRouter, xAI,
Ollama base URL) plus `FINDER_CONTACT_EMAIL`. **For this milestone, BYOK = editing
`Documents\Reveriebot\.env`.** The app's empty state / model dropdown should point the
user there when no provider is ready. An in-app Settings panel to paste keys is an
obvious follow-up, explicitly out of scope here.

## What does NOT change

The web UI (`web/`), the gateway, Finder, Studio, and the entire `/api/*` surface are
untouched. This milestone is a shell plus the read-only/writable path split. No feature
work, no Project model yet (that is a later milestone this quietly prepares for).

## Verification plan

1. **Dev smoke (no build):** `python server/desktop.py` → a native window opens and
   loads the UI from the in-process server on an ephemeral port. Proves the
   server-in-thread + pywebview wiring without a full build.
2. **Dev regression:** `python server/app.py` still serves at
   `http://localhost:8765` in the browser (unchanged dev path), and reads/writes
   workspace under `Documents\Reveriebot\workspace\`.
3. **Build:** `build.ps1` → produces `dist\Reveriebot.exe`.
4. **Frozen run:** launch `Reveriebot.exe` →
   - window opens, no terminal, no white flash;
   - `/api/config` lists providers + detected tools;
   - a search returns real papers;
   - reading a paper (HTML and PDF) works via Obscura detected from
     `Documents\Reveriebot\vendor\`;
   - saving a brief lands a file in `Documents\Reveriebot\workspace\` and reopens from
     the Library.

## Risks & mitigations

- **PyInstaller misses the dynamically-imported server modules.** Mitigation: name them
  in `hiddenimports`; the dev-smoke step won't catch this (only the frozen run will), so
  the frozen run must exercise every API route.
- **WebView2 absent on a target machine.** Present here (v150). For distribution to
  other machines, the Evergreen WebView2 runtime is standard on Windows 11; note as a
  documented prerequisite, not solved in this milestone.
- **`Documents` relocated/OneDrive-redirected.** `expanduser("~")` +
  `Documents\Reveriebot` follows the user's real profile; `REVERIEBOT_HOME` overrides if
  needed. Acceptable.
- **Onefile temp-extraction startup lag (~1s).** Accepted in exchange for a single
  handout-able exe. Workspace/vendor live outside the bundle, so extraction contains no
  writable state — clean.

## Out of scope (named, deferred)

- The Project-folder model and idea-first workspace reconception (next milestone; this
  prepares the data-dir home for it).
- In-app Settings panel for pasting API keys.
- App icon / installer / code-signing / auto-update.
- The B-roll + real-footage Editor (still the north-star placeholder).
- Tauri.
