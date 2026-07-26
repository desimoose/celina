# Architecture — the Windows app that ties the repos together

*Last updated: 2026-07-22. This is the core technical spec. The copy/visual/positioning decks dress it; this is the machine.*

## What the product actually is

A **local-first research app for Windows**. One window. Behind it, a small
orchestrator that drives four existing open-source tools, a model gateway, and
a local store. Nothing runs on a server we operate — at launch it's entirely
BYOK + local.

The realisation that makes this buildable: **we write one component — the
engine. The four repos are sidecars it spawns.** They already run on Windows.
The work is orchestration, not reinvention.

## The pieces (all verified to run on this machine)

| Component | What it is | How it runs on Windows | Role |
|---|---|---|---|
| **Window** | Tauri shell | `.exe`, WebView2 (built into Win11), Rust 1.96 present | The app the user launches |
| **Web UI** | plain HTML/CSS/JS | served by the engine on localhost | Search · Sources · Trails |
| **Engine** | Python, stdlib only | `python`/bundled runtime, no deps | The orchestrator — the only thing we write |
| **Obscura** | Rust stealth browser | prebuilt `obscura-x86_64-windows.zip` (43 MB) in `vendor/`, spawned | Unprofiled fetch + render |
| **Agent-Reach** | Python pkg, 15 platforms | pip-installs clean on Py 3.14; CLI/MCP | Sources — public social reads |
| **last30days** | stdlib Python engine (+Go MCP) | run the Python engine directly, no deps | Trails — engagement-scored digests |
| **Archify** | Node diagram renderer | `node bin/archify.mjs render …`, offline | A notebook output format |
| **Model gateway** | Python, stdlib urllib | in-engine | BYOK (Anthropic/OpenAI/OpenRouter/xAI) + local Ollama |
| **Mr.Holmes** | Python OSINT TUI | subprocess-wrapped | **Gated add-on, post-MVP** |

No Docker. No Go required (use last30days' Python engine, not its Go MCP). No
V8 compile (Obscura ships a binary). Everything is a local process the engine
starts and talks to.

## How they connect

The engine is the hub. Three connection styles, by what each tool offers:

- **Obscura** → spawn the binary, drive it over CDP (or its `obscura-mcp`). The
  engine asks it to load a page with a fresh, cookieless, not-logged-in
  context and hand back clean content. This is the *unprofiled* guarantee made
  real.
- **Agent-Reach / last30days** → invoke as Python (same interpreter or
  subprocess), pass a topic, get back structured results. Each is detected if
  present and degrades independently — a missing or broken one never takes the
  app down.
- **Archify** → shell out to `node` on demand when the user wants a result
  rendered as a diagram. Optional; absent Node just hides the feature.
- **Model gateway** → in-process; every synthesis/answer call routes through
  it, so BYOK vs local is one switch.

The three surfaces map onto these:

```
Search   = Obscura fetch  → gateway synthesis      → keep to workspace
Sources  = Agent-Reach    → group by platform      → (public only)
Trails   = last30days on a timer → snapshot + diff → report in-app
```

## Trails, precisely

A trail is a saved topic that last30days re-runs on a schedule.

1. User creates a trail (topic + Daily/Weekly).
2. A background thread in the engine re-runs the last30days engine on that
   cadence while the app is open, plus a "check now."
3. Each run's result is snapshotted to the local store (`sqlite3`, stdlib).
4. The new snapshot is diffed against the last one.
5. When the user opens the app, Trails shows **what changed** — and, when
   nothing did, says so explicitly ("Nothing new since Tuesday. I checked.").

No push, no daemon, no notifications — it reports when you come to it. That
"nothing changed" report is the load-bearing line; it's what makes the feature
feel dependable instead of broken-silent.

## Locked decisions

- **Launch inference: BYOK + local (Ollama) only.** No hosted tier at launch —
  near-zero cost to run, and we learn real per-run token numbers before
  building the managed tier.
- **Trails: in-app only.** No push, no email at launch.
- **Sequence: Search first.** Prove the Obscura→gateway loop end to end before
  adding Sources or Trails.
- **Shell: local web UI now, Tauri `.exe` wrapper once the slice works.** The
  UI code doesn't change when it gets wrapped; Tauri just points WebView2 at
  the local engine and bundles it as a sidecar. Rust is already installed.

## First milestone — the vertical slice

The smallest thing that proves the whole spine, so integration risk surfaces
on day one rather than month three:

> **Type a query → Obscura fetches the top results with no login/cookies →
> the BYOK-or-local model synthesises an answer → it renders in a window →
> "keep this" writes it to the local workspace.**

That single flow exercises: the engine, the Obscura sidecar, the gateway (both
BYOK and local paths), the UI, and the store. Everything after it — Sources,
Trails, Tauri packaging, real mascot art — is additive onto a proven spine.

## Integration risk, in the order it'll bite

1. **Spawning + driving Obscura from Python on Windows** (process handles, CDP
   handshake, clean-context flags). Highest-unknown, so it's milestone one.
2. **Bundling a Python runtime inside a Tauri `.exe`** so a non-technical user
   doesn't install Python. Solvable (embeddable Python / PyInstaller sidecar),
   but fiddly — defer until the slice works unwrapped.
3. **Agent-Reach's upstream auth for gated platforms** (some social sources
   need cookies/sessions). Keep to public-only reads; anything needing a login
   is out, by the same principle as the rest of the app.
4. **last30days scheduling that survives app restarts** without a always-on
   background service.

## Explicitly out of MVP

Windows desktop is the goal, but these wait: hosted/managed inference,
Mr.Holmes/OSINT, network-level anonymity (IP masking — we tell users to run a
VPN), accounts/cloud sync/teams, push notifications. Docker isn't used at all
in the desktop product — it was only ever for a cloud tier we're not building
yet.
