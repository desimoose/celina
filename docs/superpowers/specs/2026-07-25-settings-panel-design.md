# In-app Settings panel for keys — design

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Milestone:** A settings modal to manage API keys, the Finder email, and
per-provider model overrides from inside the app — no hand-editing `.env`.

## Goal

Today, BYOK means the user edits `Documents\Reveriebot\.env` by hand. This
milestone adds an in-app Settings panel (a modal) that reads and writes those
same values, so a newly-added key flips a provider to "ready" immediately with
no restart. Scope, confirmed:

- The provider API keys (Anthropic, OpenAI, OpenRouter, xAI; Ollama is local
  and has no key).
- `FINDER_CONTACT_EMAIL` (unlocks Unpaywall + OpenAlex's faster polite pool).
- Per-provider model-ID overrides (e.g. change the OpenRouter model).

Placement: a gear button in the rail foot opening a centered modal. Not a fifth
rail surface — settings is a "step aside and adjust" action, and a modal keeps
the Search / Library / Studio / Editor IA clean.

## Security model (drives everything)

Even though this is a local app, full secrets never round-trip to the browser:

- `GET /api/settings` returns, per provider, `has_key` (bool) and `key_hint`
  (the last 4 characters, or `null` when the key is shorter than 8). Never the
  full value.
- Key inputs are `type="password"`, `autocomplete="off"`.
- Writes are one-directional: the browser sends a new value to set, or an empty
  string to clear. It can never read back what is stored.
- Nothing key-related is logged. `FINDER_CONTACT_EMAIL` is not a secret and is
  returned/edited in plain text.

## How keys are read today (context)

`server/gateway.py` reads keys from `os.environ` at call time
(`key_for()` -> `os.environ.get(spec["key_env"])`) and reports readiness via
`available()`. So if a save updates BOTH `os.environ` (live) AND the `.env`
file (persisted), readiness reflects instantly and survives restart. The
`PROVIDERS` dict already carries `label`, `key_env`, `model_env`,
`default_model`, and the local flag.

## Components

### 1. `server/gateway.py` (add read helpers)

- `key_hint(provider)` -> `str | None`. Returns the last 4 chars of the key
  when its length is >= 8, else `None` (avoids leaking short/whole keys).
- `settings_state()` -> `list[dict]`, one per provider:
  ```python
  {
      "id": name,
      "label": spec["label"],
      "local": spec["key_env"] is None,
      "key_env": spec["key_env"],          # None for ollama
      "model_env": spec["model_env"],
      "has_key": bool(key_for(name)),
      "key_hint": key_hint(name),          # None for local or short keys
      "model": model_for(name),            # effective model
      "default_model": spec["default_model"],
      "model_overridden": bool(os.environ.get(spec["model_env"], "").strip()),
  }
  ```
  No full key value appears anywhere in the return.

### 2. `server/app.py` (two routes + one file helper)

- `update_env(updates: dict)` — the one piece with real edge cases.
  - Reads `paths.env_file()` line by line (creating the file's dir if needed).
  - For each `KEY` in `updates`: if a non-comment line matches
    `^\s*KEY\s*=` it is rewritten in place as `KEY=value`; otherwise the pair
    is appended at the end. Comments, blank lines, ordering, and unrelated keys
    are preserved.
  - An empty-string value writes `KEY=` (the effective "cleared" state, since
    `key_for`/`model_for` treat empty as unset).
  - Mirrors every update into `os.environ` (so readiness changes are live).
  - Writes the whole file back once (read-modify-write; single-user local app,
    no concurrent-writer concern).
- `GET /api/settings` -> `_get_settings()`:
  `{"providers": gateway.settings_state(),
    "finder_email": os.environ.get("FINDER_CONTACT_EMAIL", "")}`.
- `POST /api/settings` -> `_save_settings(payload)`:
  - Accepts `{"keys": {ENV: val}, "models": {ENV: val}, "finder_email": val}`.
    All three sections optional; only fields **present** are touched.
  - Validates all values are strings; whitelists `keys`/`models` env names
    against the ones in `PROVIDERS` (ignore anything else — never let the
    browser set arbitrary env vars). `finder_email`, when present, maps to
    `FINDER_CONTACT_EMAIL`.
  - Builds one `updates` dict, calls `update_env(updates)`, returns the fresh
    `_get_settings()` payload (200). Bad body -> 400 JSON; write failure -> 500
    JSON. Consistent with the existing handlers' JSON-error style.

### 3. `web/index.html`

- A gear button in `.rail-foot` (next to the model `<select>`), `id="settings-open"`,
  `aria-label="Settings"`, inline SVG gear icon matching the existing icon style.
- A modal, hidden by default:
  ```
  <div class="modal" id="settings" hidden>            (scrim)
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Settings">
      <header> Settings  [x close] </header>
      <div id="settings-body"> ...rows rendered by JS... </div>
      <footer> <span id="settings-msg"></span> [Cancel] [Save] </footer>
    </div>
  </div>
  ```
- Rows are rendered by JS (not hardcoded) so they track `PROVIDERS`.

### 4. `web/styles.css`

- `.modal` fixed full-viewport scrim (`background: rgba(0,0,0,.55)`),
  centered `.modal-card` on the `--surface`/off-black token, one `--radius`,
  blue `--act` for the primary Save button, ghost Cancel. Key/model inputs
  reuse the app's input styling. `prefers-reduced-motion: no-preference` gets a
  short fade/scale-in; reduced-motion gets none.

### 5. `web/app.js`

- `openSettings()` -> `GET /api/settings` -> render one row per provider:
  label, a ready dot (green when `has_key` or `local`), a `type=password` key
  input whose placeholder is `set (····<hint>)` when `has_key` else `not set`
  (no key input for `local` providers), and a model-override input whose
  placeholder is the effective `model`. Plus a Finder-email text input.
- `saveSettings()` collects **only fields the user changed** (track initial
  values; diff on save) into `{keys, models, finder_email}`, `POST`s them,
  then on success reuses the existing config loader (the function that
  populates the provider `<select>` and tool strip from `/api/config`) so a
  new key flips the provider to ready, then closes the modal. On error, shows
  the message inline in `#settings-msg` and keeps the modal open.
- `closeSettings()` hides the modal and clears inputs. Close on the [x],
  Cancel, scrim click, and Escape.

## Data flow

```
gear click
  -> GET /api/settings           (masked state)
  -> render rows
user edits key / model / email
Save
  -> POST /api/settings {changed fields only}
  -> update_env(): rewrite .env in place + mirror to os.environ
  -> 200 fresh state
  -> reload /api/config (provider dropdown + tools refresh; provider now ready)
  -> close modal
```

## Error handling

- Malformed JSON body -> 400 `{error}`. Non-string value -> 400 `{error}`.
- Unknown env names in `keys`/`models` are silently ignored (whitelist).
- File write failure -> 500 `{error}`; frontend keeps modal open and shows it.
- Frontend never assumes success: it re-reads state from the POST response.

## Testing (stdlib `unittest`, matching the repo)

`tests/test_settings.py`:

- `update_env` updates an existing `KEY=` line in place.
- `update_env` appends a brand-new key.
- `update_env` clears a key on empty string (`KEY=`).
- `update_env` preserves comments, blank lines, and unrelated keys.
- `update_env` mirrors updates into `os.environ`.
- `GET /api/settings` returns `key_hint` (masked), never the full key, and
  `has_key` tracks the environment.
- `POST /api/settings` setting a key makes `gateway.key_for()` see it live and
  persists it to the file; posting an empty value clears it.
- Whitelist: a POST with a bogus env name does not write it.

Tests set `REVERIEBOT_HOME` to a temp dir so they never touch the real
`.env` (same pattern as the existing suite).

Manual: the settings modal is verified via `javascript_tool` handler calls
(`openSettings()`, `saveSettings()`) plus a live desktop-window smoke, because
the in-app browser's coordinate clicks do not fire DOM `onclick` handlers
(known gotcha). Real users click fine.

## What does NOT change

Gateway `chat()` and all other routes, the Finder, Studio, the reader, and the
packaging all stay as-is. This adds two read/write routes, one gateway read
helper, and a modal.

## Out of scope (named, deferred)

- OS keychain / DPAPI encryption of `.env` (it stays a plain file on the local
  drive, gitignored — consistent with the current model).
- A first-run onboarding wizard (the empty state can point at Settings later).
- Editing non-key `.env` settings like `REVERIEBOT_PORT` from the UI.
