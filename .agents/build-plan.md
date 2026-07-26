# Celina — Build Plan (MVP)

*Last updated: 2026-07-22. Companion to the copy, visual, and positioning decks.*

## Ground rules

1. **Skeleton first, then port.** The Reveriebot repo is the reference implementation. Its working parts get **rewritten line by line under the Celina name** — read, understand, retype — not copied wholesale. Christopher's call, to avoid inheriting problems. Not started yet.
2. **Zero dependencies for MVP.** Stdlib Python server, plain HTML/CSS/JS, no build step, no npm. It runs with nothing installed. Optional backends (Obscura, social readers) are *detected if present*, never required.
3. **BYOK by default.** Keys live in a local `.env`, never transit a server we run. Local (Ollama) needs no key.
4. **Every feature passes the house-cat test:** would a good house cat do this? If it demands attention, needs managing, or performs for approval, it doesn't ship.
5. **The anonymity claim is exact.** Unprofiled — no login, no cookies, no history shaping results. IP is *not* hidden, and we say so. Nothing in the build may quietly overclaim.

## What we're porting (reference surface)

The Reveriebot server already exposes, stdlib-only:

| Endpoint | Does | Reuse for Celina |
|---|---|---|
| `GET /api/config` | providers + tool availability | Search + Settings — provider list |
| `POST /api/chat` | any provider via the gateway | Search — synthesis, and later the assistant |
| `POST /api/fetch` | fetch a page (Obscura when present) | Search + Sources — the unprofiled fetch |
| `GET/POST /api/workspace*` | list / read / save artifacts | "Keep this" — saved results |

Provider gateway (five backends: Anthropic, OpenAI, OpenRouter, xAI, Ollama) ports almost as-is — it's already provider-agnostic and keyless-for-local. **Trails has no equivalent in the reference and is net-new** — it's the real engineering, and the retention engine, so it gets its own phase.

---

## Phases

Each phase ships something usable on its own. Order is dependency-honest: the substrate, then the three surfaces cheapest-proof-first, then polish.

### Phase 0 — Foundations
*Repo scaffold only. No product logic.*

- Directory skeleton (`server/`, `web/`, `workspace/`, `vendor/`, `scripts/`), `.env.example`, `.gitignore`, run script.
- Design tokens as a single CSS `:root` from the visual system (both themes). Fonts self-hosted.
- The static shell: warm paper, single 720px column, header nook, Celina's resting corner (art can be a placeholder box). First-run line renders.
- **Done when:** `python server/app.py` serves a themed, empty, accessible shell at localhost, day/night both correct, keyboard-navigable. No features yet.

### Phase 1 — Search
*The core loop, proven end to end.*

- Port `config`, `chat`, `fetch`, `workspace-save` under the Celina name, line by line.
- One field → unprofiled fetch of top results → model synthesis → clean result list. Privacy pill visible. "Keep this" saves to `workspace/`.
- Fresh context per fetch: no cookies, no login, no carried state. Via Obscura if the binary is in `vendor/`; plain stdlib fetch as fallback.
- All Search copy + errors from the copy deck, verbatim. Line-bank status while she works (text, not spinner).
- **Done when:** a real query returns synthesized, kept-able results with no account anywhere in the path; blocked/empty/slow states all render their real copy; works on Anthropic key and on local Ollama.
- **House-cat check:** she reports and stops. No follow-up prompts, no "search again?" nudge.

### Phase 2 — Sources
*Read the social layer — public only.*

- A topic → what Reddit / X / YouTube / Hacker News are saying, scored by real engagement, grouped by platform.
- Backends detected if present (e.g. Agent-Reach / last30days-style readers in `vendor/`); each source degrades independently — one being down never breaks the page ("That one didn't answer. I'll leave it and carry on.").
- Public-only, always-visible caveat. No login to any platform, ever — that's the same principle as Search.
- **Done when:** a topic returns grouped, engagement-ranked public results with the scope caveat shown; missing backends fail quietly per-source, not globally.
- **House-cat check:** silence is a valid answer — "Quiet everywhere I looked." renders cleanly and isn't treated as an error.

### Phase 3 — Trails  ← the retention engine
*Net-new. The hardest and most valuable phase.*

- A trail = a topic Celina keeps watching. Create (name + Daily/Weekly), list, pause, delete.
- **Persistence:** trail definitions + last-seen snapshots in a local JSON/SQLite store under `workspace/` (stdlib `sqlite3`, no dependency).
- **Scheduling, house-cat style:** a plain interval check on a background thread while the app runs, plus a "check now." No always-on daemon for MVP, no push notifications — a cat doesn't tap you on the shoulder. She reports *in the app* when you open it.
- **Diffing:** compare this check to last-seen; surface only what changed.
- **The load-bearing line:** when nothing changed, she says so — "Nothing new on X. I checked Tuesday and again today." Never suppress it; that report is what makes her feel dependable and is the whole habit loop.
- **Done when:** a trail persists across restarts, reports real changes since last check, and reports *no* changes explicitly; pause/delete honour their copy.
- **House-cat check:** no notifications, no badges, no streaks. She surfaces when there's a reason, and once to say there wasn't.

### Phase 4 — Polish & package
- Real mascot art (resting) dropped into the corner; full visual pass against the system doc.
- Settings finished: five providers + local, the keys-stay-local note, theme switch.
- Accessibility sweep (AA, keyboard, reduced-motion, aria-live) as an explicit gate, not a hope.
- Simple packaging so a non-technical user can launch it (a one-click run script; the Tauri desktop wrapper is later, not MVP).
- **Done when:** a first-time user goes install → first-run → first kept result without reading docs.

---

## Explicitly out of MVP

Named so they don't sneak in:

- Windows desktop app (Tauri) — planned, post-MVP. The local web UI is the same code, wraps later with no rewrite.
- Network-level anonymity (proxy/Tor/IP masking) — we don't promise it; we tell users to run a VPN.
- Managed/hosted inference tier — BYOK + local only at launch; add hosted open-models once real per-run token costs are known.
- Push notifications, accounts, cloud sync, teams/sharing, the workspace *assistant* chat (Reveriebot has the plumbing; Celina earns it later).
- OSINT / people-search — not this product.

## Open decisions (need Christopher)

1. **Trails delivery:** in-app-only on open (my lean, most house-cat), or also a quiet daily email digest? Email is the one non-nagging way to "come to you," but it's infrastructure.
2. **Sources backends:** wire real social readers into `vendor/` now, or ship Search-only first and add Sources once a reader is chosen?
3. **Launch providers:** BYOK + local only at launch (near-zero cost, my lean), or stand up a hosted tier day one?

## Sequencing at a glance

```
Phase 0  Foundations ......... shell, tokens, resting corner (placeholder)
Phase 1  Search .............. the core loop, proven end to end
Phase 2  Sources ............. public social read, per-source graceful
Phase 3  Trails .............. persistence + quiet scheduling  ← retention
Phase 4  Polish & package .... real art, a11y gate, one-click run
                              (Tauri, hosted inference = later)
```
