# Material 3 front-end redesign — design

**Date:** 2026-07-25
**Status:** Approved, executing via impeccable
**Milestone:** Replace the dark-slate visual world with a bright Material You
(Material 3) light theme. Same product, features, routes, and IA — new look.

## Design read

A redesign of a local research-and-content **workspace** (Operate mode) for a
solo creator, in a **Material 3 / Material You** language: light-first, bright,
friendly-Android. Implemented as **hand-written M3 CSS** (tonal color roles,
elevation, M3 shape scale, state layers, M3 motion) — NOT the official
`@material/web` library, which is an npm/build dependency and would break the
project's zero-dependency, no-build constraint.

Decisions locked in brainstorming:
- **Seed:** coral / sunset orange.
- **Themes:** light only this pass (a proper M3 dark scheme is a later
  follow-up).
- **"No dark patterns":** both go-light/bright AND nothing manipulative (the
  app already avoids engagement bait — see the house-cat product principle).

## Global constraints (carry into implementation)

- Zero dependencies: hand-written CSS, no library, no build step, no external
  font link (privacy). Font stays the system stack (Segoe UI on Windows reads
  clean-Android).
- One seed, one system: every accent derives from the coral seed's tonal
  palettes. No stray colors.
- No backend/logic change: the existing 20 tests still pass unchanged;
  the redesign is verified visually + an a11y pass.
- Accessibility bar (the "no dark patterns" floor): M3 contrast (>= 4.5:1 body),
  visible focus rings, >= 44px touch/click targets, `prefers-reduced-motion`
  honored, no color-only meaning.
- UI copy unchanged in meaning; no em-dashes, no hype words.

## Color — M3 light scheme (coral/sunset seed)

Semantic roles as CSS custom properties on `:root`. Approximate M3 tonal values
(refined during build against contrast):

```
--md-primary:            #B4310F;   --md-on-primary:            #FFFFFF;
--md-primary-container:  #FFDBD0;   --md-on-primary-container:  #3A0A00;
--md-secondary:          #77574C;   --md-on-secondary:          #FFFFFF;
--md-secondary-container:#FFDBD0;   --md-on-secondary-container:#2C160D;
--md-tertiary:           #6C5D2E;   --md-on-tertiary:           #FFFFFF;   /* Studio accent */
--md-tertiary-container: #F6E1A5;   --md-on-tertiary-container: #221B00;
--md-error:              #BA1A1A;   --md-on-error:              #FFFFFF;
--md-error-container:    #FFDAD6;   --md-on-error-container:    #410002;

--md-background:               #FFF8F6;   --md-on-background:      #241915;
--md-surface:                  #FFF8F6;   --md-on-surface:         #241915;
--md-surface-variant:          #F5DED5;   --md-on-surface-variant: #53433D;
--md-surface-container-lowest: #FFFFFF;
--md-surface-container-low:    #FFF1EC;
--md-surface-container:        #FCEBE5;
--md-surface-container-high:   #F7E5DF;
--md-surface-container-highest:#F1DFD9;

--md-outline:         #85736B;   --md-outline-variant: #D8C2B9;
--md-inverse-surface: #3A2D28;   --md-inverse-on-surface: #FFEDE7;
--md-inverse-primary: #FFB59B;   --md-scrim: #000000;
```

The existing app tokens (`--bg`, `--act`, `--create`, `--text`, `--surface*`,
`--border*`, `--ok`) are remapped onto these roles so component CSS that
references them keeps working, then components are migrated to the `--md-*`
roles directly.

## Shape scale (M3)

```
--md-corner-xs: 4px;  --md-corner-sm: 8px;  --md-corner-md: 12px;
--md-corner-lg: 16px; --md-corner-xl: 28px; --md-corner-full: 999px;
```
Buttons/chips = full (stadium). Cards/text-fields = md (12). FAB = lg (16).
Dialog = xl (28).

## Typography (M3 role scale)

System font stack. Roles used:
- headline: 28-32 / 36-40, weight 400.
- title-large 22/28, title-medium 16/24 (500).
- body-large 16/24, body-medium 14/20.
- label-large 14/20 (500) for buttons/nav.

## Elevation & state layers

- Elevation via surface-container tones + soft tinted shadows (levels 1-3);
  never harsh black shadows on light.
- **State layers:** hover 8%, focus 10%, pressed 12% overlay of the relevant
  on-color/primary — the M3 ripple/press feel via `::before` overlays.

## Component mapping (M3 patterns, existing structure)

- **Left rail -> M3 Navigation Rail:** each item icon+label with a rounded
  **active-indicator pill** behind the active icon; primary action ("Search")
  presented as a small **FAB** at the top of the rail.
- **Buttons:** filled (primary), tonal (secondary/tertiary container),
  outlined, text — with state layers. `.btn--primary` -> filled;
  `.btn--ghost` -> text/outlined.
- **Search field -> M3 search bar** (rounded-full, surface-container, leading
  icon). Text inputs -> M3 filled fields (surface-variant fill, focus indicator).
- **Cards:** results, library items, Studio format tiles, drafts -> M3
  filled/elevated cards (12px, container tone, state layer on interactive ones).
- **Chips:** tool strip -> M3 assist chips.
- **Settings modal -> M3 dialog:** 28px corner, surface-container-high, text +
  filled buttons; scrim uses `--md-scrim` at ~32% (lighter than the current
  dark scrim).
- **Assistant panel:** M3 surface-container side pane; message rows styled as
  M3 list/bubble.
- **Studio:** identity shifts from pink to the **tertiary** (gold/olive) role.
- **Editor placeholder:** M3 surfaces + tonal timeline mock.
- **Motion:** M3 emphasized easing `cubic-bezier(0.2, 0, 0, 1)` for surface
  swaps; the "settle" animation reworked to M3 timing; reduced-motion path keeps
  it static.

## Scope

- Full rewrite of `web/styles.css` (token system + all components).
- `web/index.html`: light markup additions (nav active-indicator spans, FAB,
  chip/card classes) — structure and copy otherwise intact.
- `web/app.js`: minor class toggles only (e.g. nav active-indicator, ripple
  origin if added). No logic change.

## Verification

- Visual, surface by surface, against the running app (dev server + the desktop
  window): Search/empty, results, reader, Library, Studio (formats + a draft),
  Editor, Settings modal, assistant.
- A11y pass: contrast on primary text and buttons, focus-visible rings, 44px
  targets, reduced-motion.
- Behavior regression: `python -m unittest discover -s tests` stays green (20).
- Rebuild `dist\Reveriebot.exe` at the end so the packaged app carries the new
  look.

## Out of scope (deferred)

- M3 dark scheme + theme toggle.
- Self-hosted Roboto Flex (stays system font for now).
- Any IA/feature change; the Project-folders model; the Editor build.
