# Coda visual world + Slice B — design

**Date:** 2026-07-25
**Status:** Approved (user said build it), on branch `coda-redesign`
**Milestone:** Replace the Material 3 coral theme with the "Coda" editorial
visual world, and build Slice B (two-speed search->workspace + orientation +
plain copy) inside it.

## Visual world: Coda (editorial cream-paper workspace)

Adopt the user-supplied Coda design system as the committed visual world. It
supersedes the M3 coral tokens. Character: nearly monochrome, warm cream paper
canvas, carved black display type, ONE ember-orange accent, hard offset
shadows, 8px radius, black primary buttons.

### Tokens (from the Coda reference)

- **Color:** ink `#212121`, white `#ffffff`, carbon `#000000`, cream
  `#fff6ec`, ash-border `#e0e0e0`, graphite `#666666`, smoke `#8e8e8e`,
  slate `#444444`, ember-orange `#ee5a29`. Surfaces: white main content, cream
  for warm bands (welcome, empty state, rail or footer).
- **Type:** **Manrope only** (self-hosted woff2, weights 400/500/700/800; no
  Inter - user's call, and Inter is a discouraged default). 800 tight-tracked
  for display/headlines (carved-ink look), 400/500 body/UI, 700 labels.
  Tracking -0.025em to -0.045em on display; near-0 on body.
- **Shape:** 8px default radius (cards, buttons, inputs, images), 12px large
  buttons, 4px base spacing grid.
- **Shadows:** the signature moves - hard offset `#000 8px 8px 0 0` (zero blur)
  for editorial blocks; two-layer soft `rgba(0,0,0,.06)` for product/reader
  frames; 1.5px inset borders for buttons (`#212121`) and inputs (`#e0e0e0`,
  focus -> `#212121`).

### Fonts (self-hosted, offline)

`web/fonts/manrope-{400,500,700,800}.woff2` (OFL, license in
`web/fonts/LICENSE.txt`). `@font-face` with `font-display: swap`, loaded from
`/fonts/...` on the local server. `app.py` registers `font/woff2`. PyInstaller
bundles `web/` so fonts ship in the exe. Never requests a remote font.

### Accessibility (respect Coda's own rule)

Ember orange is ~3.4:1 on white - **large text / eyebrows / icons only, never
small body text**. Body = ink `#212121` (16.1:1) or graphite `#666666`
(5.7:1). Placeholder = smoke `#8e8e8e` (3.5:1, placeholders only). Primary
actions = white on carbon black (max contrast). Focus-visible = 2px ink ring.
44px min targets. Keeps the non-technical-audience a11y bar.

### App adaptation (Operate mode, not a landing page)

Coda's reference is a marketing site; we apply its tokens/components to the
workspace shell (rail / stage / assistant), not its hero/footer layout.
Editorial display type is used for empty-state and welcome headlines; working
UI stays calm at body sizes. Cream is an accent band (welcome, empty state),
white is the working canvas. Hard offset shadow used sparingly (one signature
moment, e.g. the "Keep this" workspace card or the reader frame), not on every
card - impeccable craft-floor: one authored move, not scattered.

## Slice B behavior (built in the Coda look)

The two-speed spine + orientation + plain copy approved earlier:

1. **Quick answer is the default.** A question in the one search box returns a
   grounded answer + its sources. Answer leads.
2. **"Keep this" -> a kept item.** A primary (black) button on results saves
   question + answer + sources as one named Library item (title = question).
   Replaces the subtle "Save".
3. **Every kept item opens with one next action: "Make something"** -> Studio
   with that item as source. No new persistence type; "workspace" = a kept
   item you can Make from. Arc: search -> keep -> make.
4. **One next step per screen:** empty search shows a friendly prompt + an
   example question chip; after an answer -> Keep this; reading a source ->
   Make something; Library item -> Make something; Studio draft -> Save.
5. **Plain copy** (non-technical): search placeholder "Ask anything, or paste a
   link to read"; empty state drops "stealth browser"/"open-access papers";
   "Open URL" -> "Read a link"; engine line -> "read privately".
6. **Two-input clarity:** relabel the assistant panel "Ask about this" (helper
   for what's open), so the big search box vs the side panel roles are obvious.

## Files

- `web/fonts/*.woff2` + `LICENSE.txt` (added).
- `web/styles.css` - full rewrite to Coda tokens/components (replaces M3).
- `web/index.html` - `@font-face`? no (in CSS); button-label + copy changes;
  assistant relabel; empty-state nudge markup; Keep this / Make something.
- `web/app.js` - Keep this (save bundle), Make something (open item -> Studio),
  orientation next-steps, copy, assistant relabel.
- `server/app.py` - `mimetypes.add_type("font/woff2", ".woff2")` (done).

## Verification

- Behavior suite green: `python -m unittest discover -s tests` (21).
- Live (dev + isolated home): fonts load from /fonts (network tab shows no
  remote font); Coda look on every surface (search/empty, results, reader,
  Library, Studio, Editor, Settings, welcome, assistant); Keep this -> Library
  item -> Make something -> Studio; plain copy present; a11y (orange not on
  body, focus rings, contrast).
- impeccable detector clean on changed files.
- Rebuild `dist\Reveriebot.exe`; confirm fonts render in the frozen window.

## Out of scope

- Source Serif / Tiempos editorial subhead (Manrope-only for now).
- Slice C (wire Agent-Reach + last30days).
- M3 dark scheme (moot - Coda is light).
