# Slice A: onboarding + de-clutter — design

**Date:** 2026-07-25
**Status:** Approved, building
**Milestone:** Make the app usable by a non-technical person from second one:
a guided first-run that connects an AI in ~2 minutes, and a main UI with the
engine hidden. First slice of the workflow redesign (A of A/B/C).

## Principle

One useful thing, never lost, always oriented. The main surface shows the road
(a search box), never the engine (providers, tool detection, keys).

## Part 1 - De-clutter the rail

- Remove the provider `<select>` (`.model`) and the tool chips (`.tools`) from
  `.rail-foot`. The rail bottom keeps only the **Settings** gear.
- The active AI is chosen automatically: the first connected (keyed + ready)
  provider, else the first ready provider. This is the existing `firstReady`
  logic in `renderProviders`, minus the visible control.
- `renderProviders` no longer requires a DOM `<select>` in the rail; it sets
  `state.provider` directly and (if the Settings "Which AI" control is present)
  populates that instead.

## Part 2 - Settings absorbs the machinery

Add two sections to the existing Settings dialog (`#settings-body`), rendered by
`openSettings()` above the provider key rows:

- **Which AI** - a compact `<select>` (or radio list) of *ready* providers,
  bound to `state.provider`. Lets a power user switch; a newcomer ignores it.
- **Connected tools** - a read-only status list from `/api/config` `tools`:
  each tool as "Obscura - connected" / "Agent-Reach - not found". No action,
  just transparency, out of the newcomer's way.

`/api/config` is already fetched in `refreshConfig()`; cache its `tools` on a
module variable so `openSettings()` can render them without a second call.

## Part 3 - First-run welcome

A full-viewport overlay `#welcome` shown only when **no keyed provider is
connected**: `providers.some(p => !p.local && p.ready) === false`. Evaluated in
`boot()` after `refreshConfig()`.

Steps (one overlay, JS toggles `.wl-step` sections):

1. **Welcome** - one line: "Reveriebot finds real sources and turns them into
   content you can post." A single **Connect your AI** button. A quiet
   **Skip for now** text button (dismisses; app still opens, search will prompt
   to connect when used).
2. **Connect** - recommends OpenRouter: copy "Get a free key from OpenRouter,
   about two minutes," a **Get a free key** button (opens
   `https://openrouter.ai/keys` in the system browser), a single
   `type=password` paste field, and a **Connect** button. On Connect:
   `POST /api/settings {keys: {OPENROUTER_API_KEY: <value>}}`, then
   `refreshConfig()`, then check connected. If connected -> step 3; else show
   an inline message "That key did not connect. Check it and try again."
3. **Done** - "You are set." + **Start searching** button that closes the
   overlay and focuses the search input (`#url`).

No new persistence: the overlay's visibility is derived from whether a keyed
provider is connected. Once a key is saved it never shows again; Skip does not
set a flag (the user can connect later via Settings, and the search surface
will nudge them).

## Part 4 - Desktop external-link handling

External links (the "Get a free key" button) must open in the **system
browser**, not navigate the app's webview.

- `server/desktop.py`: define an `Api` class with
  `open_external(self, url)` that opens only `http(s)` URLs via
  `webbrowser.open(url)` (ignore anything else - do not shell out). Pass it to
  `webview.create_window(..., js_api=api)`.
- Frontend helper `openExternal(url)`: if `window.pywebview?.api?.open_external`
  exists, call it; else `window.open(url, "_blank", "noopener")` (dev/browser).

## Files

- `web/index.html` - add `#welcome` overlay markup; remove `.model`/`.tools`
  from `.rail-foot` (Settings gear stays).
- `web/app.js` - onboarding flow (`maybeWelcome`, `wlGoConnect`, `wlConnect`,
  `wlFinish`, `wlSkip`), `openExternal`, de-clutter `renderProviders`, cache
  tools + render "Which AI" and "Connected tools" in `openSettings`.
- `web/styles.css` - `#welcome` overlay + steps, Material 3 (surface, primary
  button, 28px card), reduced-motion aware.
- `server/desktop.py` - `Api.open_external` + `js_api=` on the window.
- `tests/test_desktop.py` - a unit test for `Api.open_external` (monkeypatch
  `webbrowser.open`; assert http(s) opens, non-http ignored).

## Verification

- Behavior suite stays green: `python -m unittest discover -s tests` (20 + 1).
- `Api.open_external` unit test (http opens, `file://`/`javascript:` ignored).
- Live (dev server + isolated `REVERIEBOT_HOME` so the real `.env` is
  untouched): with no key -> welcome shows; paste a key -> connects -> success
  -> search box focused; rail shows no provider/tools; Settings shows Which AI +
  Connected tools. With a key present -> welcome does not show.
- a11y: welcome card focusable, Escape does not trap, primary button contrast
  (already AA+ from the M3 pass), 44px targets.
- Rebuild `dist\Reveriebot.exe` at the end and confirm the external-link opens
  the system browser.

## Out of scope (later slices)

- Validating the pasted key with a live test call (Slice A treats key-present
  as connected; a wrong key surfaces on first search via existing error copy).
- The two-speed search->workspace flow (Slice B).
- Wiring Agent-Reach + last30days (Slice C).
