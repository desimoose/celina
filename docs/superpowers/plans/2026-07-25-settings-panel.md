# Settings Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-app Settings modal to manage provider API keys, the Finder contact email, and per-provider model overrides, writing the same `.env` and updating `os.environ` live.

**Architecture:** Two new stdlib routes (`GET`/`POST /api/settings`) backed by a `update_env()` file helper in `app.py` and a `settings_state()` read helper in `gateway.py`. A vanilla modal in `web/` reads masked state and posts only changed fields, then reuses the config loader to refresh provider readiness with no restart.

**Tech Stack:** stdlib Python (`http.server`, `os`), plain HTML/CSS/JS (no build step), stdlib `unittest`.

## Global Constraints

- Zero runtime dependencies: stdlib Python + plain HTML/JS only. No pip/npm/build step.
- Tests use stdlib `unittest` (never pytest). Run: `python -m unittest discover -s tests`.
- Tests MUST set `REVERIEBOT_HOME` to a temp dir so they never touch the real `.env`.
- Full API key values NEVER round-trip to the browser: GET returns `has_key` + last-4 hint only.
- Only env names present in `gateway.PROVIDERS` (plus `FINDER_CONTACT_EMAIL`) may be written — whitelist; ignore anything else.
- Empty-string value = clear that var. Only fields present in the POST body are touched.
- UI copy: no em-dashes, no hype words. Blue `--act` is the app accent; one `--radius`.
- Windows: this is the target OS; keep subprocess/file encoding UTF-8.

---

### Task 1: `update_env()` file helper

**Files:**
- Modify: `server/app.py` (add `update_env` near `load_env`/`seed_env`)
- Test: `tests/test_settings.py` (new)

**Interfaces:**
- Produces: `app.update_env(updates: dict[str, str]) -> None` — writes each
  `KEY=value` into `paths.env_file()` in place (preserving comments, blank
  lines, order, and unrelated keys), appends keys not already present, and
  mirrors every pair into `os.environ`. Empty value writes `KEY=` (cleared).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings.py`:

```python
import importlib
import json
import os
import sys
import threading
import unittest
import urllib.request

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)


def _fresh_home(name):
    """Point REVERIEBOT_HOME at an empty temp dir and reload modules that
    cache paths, so nothing touches the real .env."""
    home = os.path.join(os.environ.get("TEMP", "/tmp"), name)
    if os.path.isdir(home):
        for root, _d, files in os.walk(home, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
    os.makedirs(home, exist_ok=True)
    os.environ["REVERIEBOT_HOME"] = home
    import paths
    importlib.reload(paths)
    import gateway
    importlib.reload(gateway)
    import app
    importlib.reload(app)
    return home, app, gateway


class UpdateEnvTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REVERIEBOT_HOME", None)
        for k in ("OPENAI_API_KEY", "XAI_API_KEY", "OPENROUTER_MODEL"):
            os.environ.pop(k, None)

    def test_updates_existing_line_in_place(self):
        home, app, _ = _fresh_home("rvb_set1")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("# comment\nOPENAI_API_KEY=old\nXAI_API_KEY=keep\n")
        app.update_env({"OPENAI_API_KEY": "new"})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=new", text)
        self.assertNotIn("OPENAI_API_KEY=old", text)
        self.assertIn("XAI_API_KEY=keep", text)   # unrelated key untouched
        self.assertIn("# comment", text)           # comment preserved

    def test_appends_new_key(self):
        home, app, _ = _fresh_home("rvb_set2")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("XAI_API_KEY=keep\n")
        app.update_env({"OPENAI_API_KEY": "added"})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=added", text)
        self.assertIn("XAI_API_KEY=keep", text)

    def test_clears_on_empty(self):
        home, app, _ = _fresh_home("rvb_set3")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("OPENAI_API_KEY=old\n")
        app.update_env({"OPENAI_API_KEY": ""})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=", text)
        self.assertNotIn("OPENAI_API_KEY=old", text)

    def test_mirrors_into_os_environ(self):
        _fresh_home("rvb_set4")
        import app
        app.update_env({"OPENROUTER_MODEL": "some/model"})
        self.assertEqual(os.environ.get("OPENROUTER_MODEL"), "some/model")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_settings.UpdateEnvTest -v`
Expected: FAIL with `AttributeError: module 'app' has no attribute 'update_env'`

- [ ] **Step 3: Implement `update_env`**

In `server/app.py`, add directly after the `load_env()` function:

```python
def update_env(updates):
    """Set KEY=value pairs in the .env file (in place) and in os.environ.
    Empty string clears a key. Comments, blanks, order, and unrelated keys
    are preserved. New keys are appended."""
    path = paths.env_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read().splitlines()

    remaining = dict(updates)
    out = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")

    for key, value in updates.items():
        os.environ[key] = value
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_settings.UpdateEnvTest -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app.py tests/test_settings.py
git commit -m "feat: add update_env for in-place .env writes"
```

---

### Task 2: `gateway.key_hint()` + `gateway.settings_state()`

**Files:**
- Modify: `server/gateway.py` (add after `key_for`)
- Test: `tests/test_settings.py` (append a class)

**Interfaces:**
- Consumes: existing `gateway.PROVIDERS`, `key_for`, `model_for`.
- Produces:
  - `gateway.key_hint(provider: str) -> str | None` — last 4 chars of the key,
    or `None` when there is no key or it is shorter than 8 chars.
  - `gateway.settings_state() -> list[dict]` — one dict per provider with keys:
    `id, label, local, key_env, model_env, has_key, key_hint, model,
    default_model, model_overridden`. No full key value anywhere.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class SettingsStateTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REVERIEBOT_HOME", None)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_key_hint_masks_and_shortcircuits(self):
        _fresh_home("rvb_state1")
        import gateway
        os.environ["OPENAI_API_KEY"] = "sk-1234567890wxyz"
        self.assertEqual(gateway.key_hint("openai"), "wxyz")
        os.environ["OPENAI_API_KEY"] = "short"      # < 8 chars
        self.assertIsNone(gateway.key_hint("openai"))
        os.environ.pop("OPENAI_API_KEY")
        self.assertIsNone(gateway.key_hint("openai"))  # no key

    def test_settings_state_never_leaks_full_key(self):
        _fresh_home("rvb_state2")
        import gateway
        os.environ["OPENAI_API_KEY"] = "sk-secretvalue123"
        rows = {r["id"]: r for r in gateway.settings_state()}
        self.assertTrue(rows["openai"]["has_key"])
        self.assertEqual(rows["openai"]["key_hint"], "e123")
        self.assertNotIn("secret", json.dumps(rows))     # full key absent
        self.assertTrue(rows["ollama"]["local"])
        self.assertIsNone(rows["ollama"]["key_env"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_settings.SettingsStateTest -v`
Expected: FAIL with `AttributeError: module 'gateway' has no attribute 'key_hint'`

- [ ] **Step 3: Implement the helpers**

In `server/gateway.py`, add after `key_for()`:

```python
def key_hint(provider):
    """Last 4 chars of the key, or None if absent / too short to mask safely."""
    key = key_for(provider)
    if not key or len(key) < 8:
        return None
    return key[-4:]


def settings_state():
    """Per-provider config for the settings UI. Never includes full keys."""
    out = []
    for name, spec in PROVIDERS.items():
        out.append({
            "id": name,
            "label": spec["label"],
            "local": spec["key_env"] is None,
            "key_env": spec["key_env"],
            "model_env": spec["model_env"],
            "has_key": bool(key_for(name)),
            "key_hint": key_hint(name),
            "model": model_for(name),
            "default_model": spec["default_model"],
            "model_overridden": bool(
                os.environ.get(spec["model_env"], "").strip()
            ),
        })
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_settings.SettingsStateTest -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add server/gateway.py tests/test_settings.py
git commit -m "feat: gateway settings_state + masked key_hint"
```

---

### Task 3: `GET` and `POST /api/settings` routes

**Files:**
- Modify: `server/app.py` (route table in `do_GET`/`do_POST`, add `_get_settings`/`_save_settings`)
- Test: `tests/test_settings.py` (append a class)

**Interfaces:**
- Consumes: `app.update_env` (Task 1), `gateway.settings_state` (Task 2),
  `gateway.PROVIDERS`.
- Produces (HTTP):
  - `GET /api/settings` -> `200 {"providers": [...settings_state...],
    "finder_email": "<value or ''>"}`.
  - `POST /api/settings` with body
    `{"keys": {ENV: str}, "models": {ENV: str}, "finder_email": str}` (all
    optional) -> `200` fresh settings payload. Only whitelisted env names are
    written. `400` on non-string values; `500` on write failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings.py`:

```python
class SettingsRoutesTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REVERIEBOT_HOME", None)
        for k in ("OPENAI_API_KEY", "FINDER_CONTACT_EMAIL", "BOGUS_ENV"):
            os.environ.pop(k, None)

    def _serve(self, app):
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port

    def _post(self, port, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/settings",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_post_sets_key_live_and_persists(self):
        home, app, gateway = _fresh_home("rvb_routes1")
        srv, port = self._serve(app)
        try:
            self._post(port, {"keys": {"OPENAI_API_KEY": "sk-livevalue99"}})
            # live in this process
            self.assertEqual(gateway.key_for("openai"), "sk-livevalue99")
            # persisted to the file
            text = open(os.path.join(home, ".env"), encoding="utf-8").read()
            self.assertIn("OPENAI_API_KEY=sk-livevalue99", text)
        finally:
            srv.shutdown(); srv.server_close()

    def test_get_returns_masked_state(self):
        _fresh_home("rvb_routes2")
        import app, gateway
        os.environ["OPENAI_API_KEY"] = "sk-abcdefgh4444"
        srv, port = self._serve(app)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/settings", timeout=5
            ) as r:
                body = json.loads(r.read().decode("utf-8"))
            row = {p["id"]: p for p in body["providers"]}["openai"]
            self.assertTrue(row["has_key"])
            self.assertEqual(row["key_hint"], "4444")
            self.assertNotIn("abcdefgh", json.dumps(body))
            self.assertIn("finder_email", body)
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_ignores_non_whitelisted_env(self):
        home, app, _ = _fresh_home("rvb_routes3")
        srv, port = self._serve(app)
        try:
            self._post(port, {"keys": {"BOGUS_ENV": "x"}})
            self.assertIsNone(os.environ.get("BOGUS_ENV"))
            text = open(os.path.join(home, ".env"), encoding="utf-8").read()
            self.assertNotIn("BOGUS_ENV", text)
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_rejects_non_string(self):
        _fresh_home("rvb_routes4")
        import app
        srv, port = self._serve(app)
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(port, {"keys": {"OPENAI_API_KEY": 123}})
            self.assertEqual(ctx.exception.code, 400)
        finally:
            srv.shutdown(); srv.server_close()
```

Add `import urllib.error` to the test file's imports (top of `tests/test_settings.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `python -m unittest tests.test_settings.SettingsRoutesTest -v`
Expected: FAIL (404 from server -> JSON has no such endpoint, or HTTPError) because routes are not registered yet.

- [ ] **Step 3: Register routes and implement handlers**

In `server/app.py` `do_GET`, add before the final `return self._serve_static(route)`:

```python
        if route == "/api/settings":
            return self._get_settings()
```

In `server/app.py` `do_POST`, add before `return self._send(404, ...)`:

```python
        if route == "/api/settings":
            return self._save_settings(payload)
```

Add these handler methods to the `Handler` class (next to `_save`):

```python
    def _get_settings(self):
        return self._send(200, {
            "providers": gateway.settings_state(),
            "finder_email": os.environ.get("FINDER_CONTACT_EMAIL", ""),
        })

    def _save_settings(self, payload):
        key_envs = {s["key_env"] for s in gateway.PROVIDERS.values() if s["key_env"]}
        model_envs = {s["model_env"] for s in gateway.PROVIDERS.values()}

        updates = {}
        try:
            for env, val in (payload.get("keys") or {}).items():
                if env in key_envs:
                    if not isinstance(val, str):
                        raise ValueError("key values must be strings")
                    updates[env] = val.strip()
            for env, val in (payload.get("models") or {}).items():
                if env in model_envs:
                    if not isinstance(val, str):
                        raise ValueError("model values must be strings")
                    updates[env] = val.strip()
            if "finder_email" in payload:
                val = payload["finder_email"]
                if not isinstance(val, str):
                    raise ValueError("finder_email must be a string")
                updates["FINDER_CONTACT_EMAIL"] = val.strip()
        except ValueError as e:
            return self._send(400, {"error": str(e)})

        try:
            if updates:
                update_env(updates)
        except Exception as e:
            return self._send(500, {"error": f"could not write settings: {e}"})

        return self._get_settings()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m unittest tests.test_settings.SettingsRoutesTest -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: OK (all tests, 20+)

- [ ] **Step 6: Commit**

```bash
git add server/app.py tests/test_settings.py
git commit -m "feat: GET/POST /api/settings routes"
```

---

### Task 4: Settings modal UI (gear, modal, styles, wiring)

**Files:**
- Modify: `web/index.html` (gear button in `.rail-foot`; modal markup before `</div>` of `.app`)
- Modify: `web/styles.css` (append modal styles)
- Modify: `web/app.js` (factor `refreshConfig()`; add `openSettings`/`saveSettings`/`closeSettings`; wire events)

**Interfaces:**
- Consumes (HTTP): `GET /api/settings`, `POST /api/settings` (Task 3),
  `GET /api/config` (existing).
- Produces (JS): `openSettings()`, `saveSettings()`, `closeSettings()`,
  `refreshConfig()` — callable for verification.

- [ ] **Step 1: Add the gear button and modal markup**

In `web/index.html`, inside `.rail-foot`, add the gear button after the
`<div class="tools" ...>` line:

```html
      <button class="gear" id="settings-open" aria-label="Settings">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>
        <span>Settings</span>
      </button>
```

At the end of `web/index.html`, immediately before `<script src="/app.js"></script>`, add the modal:

```html
<div class="modal" id="settings" hidden>
  <div class="modal-card" role="dialog" aria-modal="true" aria-label="Settings">
    <header class="modal-head">
      <h2>Settings</h2>
      <button class="modal-x" id="settings-close" aria-label="Close">&times;</button>
    </header>
    <div class="modal-body" id="settings-body"></div>
    <footer class="modal-foot">
      <span class="modal-msg" id="settings-msg" aria-live="polite"></span>
      <button class="btn btn--ghost" id="settings-cancel">Cancel</button>
      <button class="btn btn--primary" id="settings-save">Save</button>
    </footer>
  </div>
</div>
```

- [ ] **Step 2: Add modal styles**

Append to `web/styles.css`:

```css
/* settings */
.gear { display:flex; align-items:center; gap:8px; width:100%; padding:8px 10px;
  background:transparent; border:0; color:var(--muted); cursor:pointer;
  border-radius:var(--radius); font:inherit; }
.gear:hover { background:var(--panel); color:var(--fg); }
.gear svg { width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.6; }

.modal { position:fixed; inset:0; z-index:100; display:flex;
  align-items:center; justify-content:center; background:rgba(0,0,0,.55); }
.modal[hidden] { display:none; }
.modal-card { width:min(560px, 92vw); max-height:88vh; overflow:auto;
  background:var(--bg); border:1px solid var(--line); border-radius:var(--radius);
  box-shadow:0 20px 60px rgba(0,0,0,.5); }
.modal-head { display:flex; align-items:center; justify-content:space-between;
  padding:16px 18px; border-bottom:1px solid var(--line); }
.modal-head h2 { font-size:15px; margin:0; }
.modal-x { background:transparent; border:0; color:var(--muted); font-size:22px;
  line-height:1; cursor:pointer; }
.modal-x:hover { color:var(--fg); }
.modal-body { padding:14px 18px; display:flex; flex-direction:column; gap:16px; }
.modal-foot { display:flex; align-items:center; gap:10px; justify-content:flex-end;
  padding:14px 18px; border-top:1px solid var(--line); }
.modal-msg { margin-right:auto; font-size:12px; color:var(--muted); }
.set-row { display:flex; flex-direction:column; gap:6px; }
.set-row .set-label { display:flex; align-items:center; gap:8px; font-size:13px; }
.set-dot { width:8px; height:8px; border-radius:50%; background:var(--line); }
.set-dot.on { background:var(--ok); }
.set-row input { width:100%; padding:8px 10px; background:var(--panel);
  border:1px solid var(--line); border-radius:var(--radius); color:var(--fg);
  font:inherit; }
.set-row input:focus { outline:1px solid var(--act); border-color:var(--act); }
.set-row .set-model { font-size:12px; }
.set-key { display:flex; gap:8px; align-items:center; }
.set-key input { flex:1; }
.set-clear { background:transparent; border:1px solid var(--line); color:var(--muted);
  border-radius:var(--radius); padding:6px 10px; font:inherit; font-size:12px; cursor:pointer; }
.set-clear:hover { color:var(--fg); border-color:var(--muted); }
.set-clear.armed { color:var(--fg); border-color:var(--act); }
.set-row input.cleared { opacity:.5; }
@media (prefers-reduced-motion: no-preference) {
  .modal-card { animation: popin .18s ease-out; }
  @keyframes popin { from { opacity:0; transform:translateY(6px) scale(.98); }
    to { opacity:1; transform:none; } }
}
```

Note: if any of `--muted`, `--panel`, `--line`, `--ok` are not defined in
`:root`, use the nearest existing token by reading the top of `web/styles.css`
first and substituting (e.g. a border token for `--line`). Do not invent new
palette values.

- [ ] **Step 3: Factor `refreshConfig()` out of `boot()`**

In `web/app.js`, replace the body of `boot()` (lines ~27-37) so config loading
is reusable:

```js
async function boot() {
  await refreshConfig();
  await loadFiles();
  wireNav();
  wireSettings();
}

async function refreshConfig() {
  try {
    const cfg = await fetch("/api/config").then((r) => r.json());
    renderProviders(cfg.providers);
    renderTools(cfg.tools);
  } catch {
    $("tools").innerHTML = '<span class="chip">server unreachable</span>';
  }
}
```

- [ ] **Step 4: Add the settings module**

In `web/app.js`, add near the other feature functions (e.g. after
`renderTools`):

```js
// ---------- settings ----------

let settingsInitial = null;  // { keyEnv/modelEnv -> "" , finder_email }

function wireSettings() {
  $("settings-open").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", closeSettings);
  $("settings-cancel").addEventListener("click", closeSettings);
  $("settings-save").addEventListener("click", saveSettings);
  $("settings").addEventListener("click", (e) => {
    if (e.target.id === "settings") closeSettings();   // scrim click
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("settings").hidden) closeSettings();
  });
}

async function openSettings() {
  const data = await fetch("/api/settings").then((r) => r.json());
  const rows = data.providers.map((p) => {
    const clearBtn = (!p.local && p.has_key)
      ? `<button type="button" class="set-clear" data-clear-for="${p.key_env}">Clear</button>` : "";
    const keyField = p.local ? "" : `
      <div class="set-key">
        <input type="password" autocomplete="off" data-key="${p.key_env}"
               placeholder="${p.has_key ? "set (····" + (p.key_hint || "") + ")" : "not set"}" />
        ${clearBtn}
      </div>`;
    return `
      <div class="set-row">
        <div class="set-label"><span class="set-dot ${p.has_key || p.local ? "on" : ""}"></span>${escapeHtml(p.label)}${p.local ? " (local, no key)" : ""}</div>
        ${keyField}
        <input class="set-model" type="text" data-model="${p.model_env}"
               placeholder="model: ${escapeHtml(p.model)}" />
      </div>`;
  }).join("");
  $("settings-body").innerHTML = rows + `
    <div class="set-row">
      <div class="set-label">Finder contact email</div>
      <input type="text" id="set-finder" placeholder="you@example.com"
             value="${escapeHtml(data.finder_email || "")}" />
    </div>`;
  settingsInitial = { finder: data.finder_email || "" };
  // wire per-key Clear buttons: arm/disarm clearing this key on save
  for (const btn of document.querySelectorAll("#settings-body .set-clear")) {
    btn.addEventListener("click", () => {
      const input = document.querySelector(`input[data-key="${btn.dataset.clearFor}"]`);
      const armed = input.dataset.clear === "1";
      input.dataset.clear = armed ? "" : "1";
      input.value = "";
      input.disabled = !armed;
      input.classList.toggle("cleared", !armed);
      btn.classList.toggle("armed", !armed);
      btn.textContent = armed ? "Clear" : "Undo";
    });
  }
  $("settings-msg").textContent = "";
  $("settings").hidden = false;
}

async function saveSettings() {
  const keys = {}, models = {};
  for (const el of document.querySelectorAll("#settings-body input[data-key]")) {
    if (el.dataset.clear === "1") keys[el.dataset.key] = "";      // armed Clear
    else if (el.value !== "") keys[el.dataset.key] = el.value;    // replace
  }
  for (const el of document.querySelectorAll("#settings-body input[data-model]")) {
    if (el.value !== "") models[el.dataset.model] = el.value;
  }
  const body = { keys, models };
  const finder = $("set-finder").value;
  if (finder !== settingsInitial.finder) body.finder_email = finder;

  $("settings-msg").textContent = "Saving...";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    if (res.error) { $("settings-msg").textContent = res.error; return; }
    await refreshConfig();   // provider readiness updates immediately
    closeSettings();
  } catch (e) {
    $("settings-msg").textContent = "Could not save: " + e.message;
  }
}

function closeSettings() {
  $("settings").hidden = true;
  $("settings-body").innerHTML = "";
}
```

Rationale for "changed fields only": a `password` input left blank means "no
change"; a filled one replaces. A model input left blank means "no change".
Clearing is explicit: each key with a value gets a **Clear** button that arms
"send empty string" for that key on save (toggles to Undo). This avoids the
footgun of "blank = wipe" while still letting the user remove a bad key from
the UI. Only touched fields are sent.

- [ ] **Step 5: Verify wiring without a build (handlers fire)**

Start the dev server and drive the handlers directly (the in-app browser's
coordinate clicks do not fire onclick; call the functions):

Run: `python server/app.py` (in one shell), then in the browser console / via
`javascript_tool` on `http://localhost:8765`:

```js
await openSettings();
document.querySelector('#settings').hidden === false   // expect: true
document.querySelectorAll('#settings-body input[data-key]').length >= 4  // expect: true
```

Expected: modal is visible, one row per provider, Ollama has no key input.

- [ ] **Step 6: Verify a real save round-trips (isolated home)**

With `REVERIEBOT_HOME` set to a temp dir so the real `.env` is untouched,
start the server, then:

```js
// set a fake key through the UI path
document.querySelector('[data-key="OPENAI_API_KEY"]').value = "sk-uitest12345";
await saveSettings();
// dropdown should now offer OpenAI as ready
(await fetch("/api/config").then(r=>r.json())).providers.find(p=>p.id==="openai").ready  // expect: true
```

Then confirm `%TEMP%\<home>\.env` contains `OPENAI_API_KEY=sk-uitest12345`.
Expected: provider ready flips to true; file written.

- [ ] **Step 7: Full suite green**

Run: `python -m unittest discover -s tests`
Expected: OK

- [ ] **Step 8: Commit**

```bash
git add web/index.html web/styles.css web/app.js
git commit -m "feat: in-app settings modal for keys, email, model overrides"
```

---

## Self-Review

**1. Spec coverage:**
- Security model (masked hint, no full key to browser): Task 2 `key_hint`/`settings_state`, Task 3 GET, tests assert full key absent. ✓
- `GET`/`POST /api/settings`: Task 3. ✓
- `update_env` in-place, preserve comments, clear-on-empty, mirror to os.environ: Task 1. ✓
- Whitelist env names: Task 3 `_save_settings` + `test_post_ignores_non_whitelisted_env`. ✓
- Keys + Finder email + model overrides: Tasks 2/3 (state + routes), Task 4 (UI rows). ✓
- Modal placement (gear in rail foot), styling from tokens, reduced-motion: Task 4. ✓
- Live readiness with no restart (refreshConfig after save): Task 4. ✓
- Tests set REVERIEBOT_HOME / stdlib unittest: all test steps. ✓
- Manual verify via javascript_tool (browser-click gotcha): Task 4 Steps 5-6. ✓

**2. Placeholder scan:** No TBD/TODO; all code steps carry full code. The one
conditional ("if `--muted` etc. not defined, substitute nearest token") is a
concrete instruction with a defined fallback, not a placeholder.

**3. Type consistency:** `update_env(updates: dict)` used identically in Tasks
1 and 3. `settings_state()` field names (`has_key`, `key_hint`, `key_env`,
`model_env`, `model`, `local`) match between Task 2 definition, Task 3 GET, and
Task 4 rendering (`p.key_env`, `p.has_key`, `p.key_hint`, `p.model_env`,
`p.model`, `p.local`). `refreshConfig()` defined in Task 4 Step 3, used in Step
4. Consistent.

## Out of scope (per spec)

- Keychain/DPAPI encryption; first-run wizard; editing `REVERIEBOT_PORT`.
