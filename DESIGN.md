# Celina visual and interaction system

## Direction

Celina is a precise editorial research instrument with one living material.
The workspace is predominantly paper white and obsidian. A restrained
green-to-amber-to-oxblood liquid field identifies work that is currently in
motion. Completed work drains back to monochrome.

The interface is an Operate surface. Readability, state, and familiar controls
outrank expression. The fluid treatment is successful only when it makes live
execution easier to understand.

## Core composition

The desktop search workspace has four stable regions:

1. A narrow navigation rail.
2. A top query bar.
3. A wide evidence and answer canvas.
4. A narrower working-notes panel containing session state, token usage, the
   current action, and the observable trace.

The evidence canvas is the primary reading surface. The working-notes panel is
secondary but remains visible throughout a search. Dense operational text uses
light surfaces with dark text.

## Color

```css
:root {
  --color-obsidian: #000000;
  --color-paper: #ffffff;
  --color-inkstone: #181818;
  --color-felt-gray: #6d6d6d;
  --color-slate-pill: #636363;
  --color-ash-mist: #9a9a9a;
  --color-pewter: #808080;
  --color-iridescent-fade: #a52d25;
  --gradient-iridescent:
    linear-gradient(100deg, rgb(160, 224, 171),
    rgb(255, 172, 46) 48%, rgb(165, 45, 37));
}
```

Color roles:

- Paper owns reading surfaces.
- Obsidian owns primary text, selected navigation, and primary actions.
- Felt gray owns secondary text that passes WCAG AA at its rendered size.
- The iridescent gradient appears only in bounded live-state regions.
- Green indicates active collection, amber indicates review or comparison, and
  oxblood indicates a blocked path or action requiring attention. Every state
  also has a word or shape; color is never the only signal.
- The gradient must not represent model confidence.

## Typography

Fonts are self-hosted. No font CDN may be used.

- **Manrope:** all headings, answer text, evidence, navigation, controls, and
  Celina's conversational status language.
- **IBM Plex Mono:** token counts, timings, context usage, request IDs, session
  identifiers, byte counts, and other machine data only.

Raleway is not used in the application interface.

Weights are restrained:

- Manrope 400 for reading.
- Manrope 500 for labels and supporting emphasis.
- Manrope 600 for controls and compact headings.
- IBM Plex Mono 400 or 500 for aligned instrumentation.

Ordinary body text is at least 16 px. Reading measures remain between 45 and 75
characters. Display headings do not exceed 6 rem and tracking never goes below
-0.04 em.

## Shape and spacing

- Use a 4 px spacing base with 8, 12, 16, 20, 24, 32, 40, 48, and 64 px steps.
- Evidence and trace structures use sharp corners and hairline rules.
- Pills are reserved for compact controls such as Search, Stop, and active
  navigation.
- Basic content is separated by alignment, spacing, and rules rather than
  cards.
- Shadows are generally absent. Depth is introduced only when it clarifies a
  temporary overlay or spatial state.

## The living current

The iridescent field is a state instrument:

- A thin current begins at the active query.
- It gathers around the single sentence describing what Celina is doing now.
- It may connect an active trace event to evidence being added.
- When the event completes, the movement runs once into the resulting trace
  record and settles.
- Finished evidence and trace steps remain still and monochrome.
- Permission checks, failures, and user pauses stop the current at a labeled
  boundary.

Only one region may carry continuous motion. Supporting transitions run once.
Reduced-motion mode replaces flow with static gradient positions and discrete
state changes.

## Search conversation

The prominent live sentence is generated from an observable event:

- "I'm searching five focused queries."
- "I'm reading the three strongest sources I haven't checked yet."
- "One page blocked access. I left it out."
- "The newer evidence changed this conclusion."
- "I'm done. One question remains unresolved."

Celina may describe what it did, what happened, what it could not do, and what
it will do next. It may not expose or fabricate hidden chain-of-thought.

Every user-facing update must map to an event in the trace schema. Technical
inputs and outputs are available through progressive disclosure.

## Session controls

The working-notes panel contains:

- Session identifier and "local only" label.
- A plain explanation of deletion behavior.
- **End and delete**, visually distinct from **Stop**.
- Token Watchtower metrics.
- Current-action sentence.
- Search trace.
- **Open local traffic log** with an event count.

Meanings:

- **Stop:** halt new work while preserving the open session and evidence.
- **End and delete:** stop work and delete the temporary session ledger.
- **Keep this:** copy selected research into the durable workspace.

These controls must never be collapsed into one ambiguous action.

## Token Watchtower

The compact default view shows:

- Input tokens.
- Output tokens.
- Context used as tokens and percentage when the context limit is known.

Expanded details may show:

- Provider and model.
- Per-call usage.
- Elapsed time.
- Estimated usage when a provider omits counts, clearly labeled "estimated."
- Cost only when pricing data is locally configured and its date is visible.

The Watchtower is instrumentation, not a game. There are no goals, scores,
streaks, or celebratory states.

## Traffic Controller

The traffic view is a chronological local ledger. Each row shows:

- Time and correlation ID.
- Direction: outbound or inbound.
- Destination host or local process.
- Action type.
- Status and duration.
- Request and response sizes.
- Redaction state.

The default list is metadata-first. Expanding an event reveals the recorded
body when content recording was active for that session. Authorization headers,
API keys, cookies, and other configured secrets are never displayed or stored.

## Accessibility

- WCAG AA contrast for body and control text.
- Minimum 44 px interactive targets.
- Full keyboard operation and visible focus.
- Semantic landmarks and headings.
- Polite live announcements for meaningful state changes, batched to avoid
  screen-reader noise.
- No content concealed behind motion.
- Complete reduced-motion behavior.
- Status never depends on color alone.

## Approved reference

The approved design prototype is the session workspace developed on
2026-07-26. Its hierarchy, session model, fluid-state treatment, Manrope
reading system, and IBM Plex Mono instrumentation are authoritative. Prototype
values are illustrative until connected to real engine events.
