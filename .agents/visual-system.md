# Celina — Visual System (MVP)

*Last updated: 2026-07-22. Companion to `.agents/copy.md` and `.agents/product-marketing.md`.*

The look has one job: feel calm enough that a busy person trusts it in the room, warm enough that it has a character. Same split as the copy — **warmth carried by character, calm carried by the chrome.**

---

## Direction: Ghibli warmth × Hanna-Barbera flatness

Two references, and the fusion is the point.

- **From Ghibli:** soft natural light, warm and slightly desaturated colour, a hand-made feeling. Nothing neon, nothing clinical.
- **From Hanna-Barbera:** flat, confident shapes. Clean fills, no gradients-as-decoration, no fuss. Legible at a glance.

The fusion: **flat clean shapes filled with warm, naturalistic colour under soft light.** Editorial, not techy. A paper feeling, not a screen feeling. Celina — a black Persian cat — is the one dark, soft, high-detail object in an otherwise flat, light room. She's the focal point precisely because the interface around her is quiet.

**Anti-references** (name them so nobody drifts): no glassmorphism, no purple-on-black AI aesthetic, no neon gradients, no drop shadows for drama, no sharp shonen-anime styling, no dashboard-chrome density.

---

## Colour

Warm paper, soft ink, one accent. The base is deliberately *not* pure white and the text is *not* pure black — pure values read as a screen; softened values read as paper, and they let the black cat sit as the darkest thing on screen.

Values are a proposed starting point — tune against the real mascot art before locking.

### Light (day) — the default

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#F5F1E8` | Page background — warm cream |
| `--surface` | `#FBF8F1` | Cards, fields — a shade lighter than paper |
| `--ink` | `#2B2A26` | Primary text — soft near-black, never `#000` |
| `--ink-soft` | `#6B675E` | Secondary text, meta, timestamps |
| `--ink-faint` | `#9C978B` | Placeholders, hints |
| `--line` | `#E4DECF` | Hairline borders, dividers |
| `--marigold` | `#D98A3D` | The single action accent — buttons, focus, active |
| `--marigold-ink` | `#7A4A17` | Text on marigold fills |
| `--moss` | `#6E7B54` | Quiet "new / changed" marker on Trails |
| `--clay` | `#B4593F` | Errors and blocks — warm, never a hazard red |

### Dark (night)

Deep warm charcoal, not black — because the cat is black and needs to stay the darkest, softest shape in the room. She gets a faint warm rim light at night so she reads against the ground.

| Token | Hex | Use |
|---|---|---|
| `--paper` | `#22201C` | Page background — warm charcoal |
| `--surface` | `#2B2823` | Cards, fields |
| `--ink` | `#EDE7D9` | Primary text — warm off-white |
| `--ink-soft` | `#B0A996` | Secondary |
| `--ink-faint` | `#7C7565` | Placeholders |
| `--line` | `#3A362F` | Borders |
| `--marigold` | `#E0A05A` | Accent, lifted for contrast |
| `--marigold-ink` | `#2B2016` | Text on marigold |
| `--moss` | `#9BA97C` | New / changed |
| `--clay` | `#D07A5E` | Errors |

**Rules:** one accent visible per screen (marigold). Moss and clay are markers, not decoration — a single small dot or word, never a fill. Two ramps max in view at once. Every text/background pair clears WCAG AA (4.5:1 body, 3:1 large). Day is the default; follow the OS for the initial theme, offer a manual switch in Settings, and don't animate the swap.

---

## Type

The type system encodes the two-audience split directly: **a humanist serif is Celina's voice; a clean grotesque is the working chrome.** When you read a serif line, that's the cat talking. When you read sans, that's the tool.

| Role | Family (proposed) | Notes |
|---|---|---|
| **Voice** — Celina's lines, headings, empty states | Humanist serif — *Fraunces* or *Source Serif 4* | Warm, editorial, a little characterful. Never for dense data. |
| **Chrome** — UI, labels, buttons, results, meta | Humanist grotesque — *Inter Tight* or *IBM Plex Sans* | Neutral, legible, gets out of the way. |
| **Detail** — counts, timestamps, keys | Mono — *IBM Plex Mono* | Only where alignment helps (upvotes, dates, API keys). |

> Pick from system-available or self-hosted fonts at build time; do not pull the AI-slop defaults called out in the copy deck (Inter-default-everything, Roboto, Arial). Self-host for the local-first promise — no font CDN phoning home.

**Scale** (1.25 ratio, 16px base):

| Step | Size / line-height | Use |
|---|---|---|
| Display | 33 / 40 | First-run "Hello. I'm Celina." |
| Title | 26 / 32 | Screen headers |
| Heading | 21 / 28 | Section headers (Reddit, X…) |
| Body | 16 / 26 | Everything readable |
| Small | 14 / 20 | Meta, captions |
| Micro | 12.5 / 16 | Legal-ish caveats, the IP note |

Two weights only: 400 regular, 500 medium. Sentence case everywhere — never Title Case, never ALL CAPS, matching the copy rules.

---

## Space & shape

- **Grid:** 8px base. Spacing steps 4 / 8 / 12 / 16 / 24 / 32 / 48.
- **Column:** single readable column, `max-width: 720px`, centered. This is a reading tool; do not sprawl to full width.
- **Radius:** 10px on cards and fields, 8px on buttons, 999px only on the small privacy pill. Consistent, soft, never sharp.
- **Borders:** 1px `--line` hairlines do the separating. **No drop shadows** except one barely-there lift on the mascot's resting spot so she sits *in* the room rather than pasted on. Elevation is a paper metaphor, not a glow.
- **Density:** generous. Whitespace is the calm. When in doubt, remove a rule and add space.

---

## The mascot — resting

**One state for MVP: resting.** (Settled at Christopher's call — "it is resting, leave it as it is.") No away/working/celebrating variants get built now; note them only as future.

- **Where:** her own corner — a fixed, small resting spot (a windowsill / cushion motif), bottom-left of the main column or in the header nook. She has a *place*; she doesn't float or follow.
- **Pose:** curled loaf or side-rest, eyes closed or half-closed. Calm. A black Persian — soft silhouette, flat Hanna-Barbera fill, one or two Ghibli soft-light highlights on the fur, big-but-closed calm eyes.
- **Behaviour:** she does **nothing** in response to you. No perk-up on click, no cursor tracking, no reaction to results. A cat shares the room without running it.
- **Motion:** at most a very slow breathing rise-fall (~4s loop, 2–3px), and only if `prefers-reduced-motion` is not set. Off by default is acceptable. She never animates *over* content.
- **Size:** small — roughly 88–120px in her corner. Present, ignorable. She is never a loading spinner and never blocks a task.

The icon / marketing Celina can be more rendered and expressive; the in-app Celina is this quiet resting form.

---

## Motion

Near-zero, on purpose — restraint is the calm.

- Allowed: state cross-fades at 150ms ease; the mascot's optional slow breathe.
- **Not** allowed: entrance animations over content, skeleton shimmer, spinners as personality, anything that reacts to a click, parallax, bounce.
- While Celina works, show a rotating one-line status from the copy deck's line bank (text changing, not motion) plus a single static, calm indicator. No spinner theatre.
- Honour `prefers-reduced-motion`: kill the breathe and the cross-fades, keep everything usable.

---

## Iconography

- Line icons, ~1.75px stroke, rounded caps — flat and friendly, matching HB linework. One set, consistent weight.
- Sparingly. Labels beat icons where there's room; Celina's a reading tool, not a toolbar.
- The privacy pill (`no account · no cookies`) is text, not an icon — the claim is worth the words.

---

## Accessibility (non-negotiable, ships in MVP)

- AA contrast on every pair, both themes.
- Full keyboard path: search, open a result, keep it, start a trail — all reachable and operable without a mouse. Visible marigold focus ring on everything focusable.
- Targets ≥ 44px. Body never below 12.5px.
- `prefers-reduced-motion` respected everywhere.
- Real semantics — the mascot is decorative (`aria-hidden`); status lines are announced politely (`aria-live="polite"`) so a screen reader hears "Found 14. Three are new." without being spammed.

---

## The one-paragraph brief for whoever draws it

A warm paper-coloured room, flatly and cleanly drawn, lit softly. Almost nothing in it — a single reading column, quiet type, one marigold button. In the corner, on a cushion by a window, a black Persian cat is asleep. She's the only soft, dark, detailed thing in the picture, and she isn't doing anything. That's the product: you came to get something done, she's just there, and the room lets you work.
