# Celina

A quiet research tool. She looks things up without an account, so what comes
back is shaped by the topic instead of your history. Everything stays on your
machine.

**Goes and looks. Leaves nothing behind.**

## The house cat principle

Celina behaves like a good house cat. Not the mascot — the software. It goes
off and does its own thing, comes to you when it has a reason, and never needs
managing. No notifications designed to pull you back, no streaks, no badges, no
tuning. Boring reliability is the feature. An empty result is a finished
answer, not a failure. This is the opposite of engagement design, on purpose.

**Celina appears as a mascot, not in the interface.** She is on the icon and
the first-run line; she does not sit in the corner of the app watching you
work. The character carries the warmth; the interface stays out of the way.

The full product thinking lives in [.agents/](.agents/): the vision, copy,
visual system, architecture, and build plan.

## What it does today

One search box, and behind it a **zero-login Scanner** that fans out across
sources that need no key and no login, blended into one list:

- **Research** — open-access scholarly sources (OpenAlex, Europe PMC, Crossref)
- **Web** — a resilient search chain read privately through Obscura
- **Recent** — fresh news (Google News RSS)
- **Context** — Wikipedia

You get a grounded answer that cites across the blend, read any source
privately through the Obscura stealth browser, and keep what matters as clean
research notes in your Library. No account, no profile — the visit isn't tied
to you.

*Planned (per the vision docs): Sources (what social platforms are saying) and
Trails (topics Celina keeps watching). The social layer is an opt-in that needs
logins, deliberately kept out of the zero-setup core.*

## Run it

```bash
python server/app.py
```

Then open <http://localhost:8765>. To run it as a native window instead of a
browser tab:

```bash
python server/desktop.py
```

First run creates `Documents\Celina\` and seeds a `.env`. You need one model
backend — a key, or Ollama running locally for a fully offline setup. The
first-run screen walks you through connecting one.

## Desktop app (Windows)

Build the single-file exe:

```powershell
powershell -File build.ps1
```

This fetches the pinned Obscura release (verified against
`third_party/obscura/manifest.json` — exact version and SHA-256, never
"latest") and bundles it into the exe, so a fresh install is "add a key,
search" with no separate download. `dist\Celina.exe` keeps the rest of your
data in `Documents\Celina\`:

```
Documents\Celina\
  .env         your API keys (seeded on first run)
  workspace\   saved research notes
  projects\    local project folders and formatted outputs
```

Prerequisite on other machines: the Microsoft Edge WebView2 runtime (standard
on Windows 11). Obscura is bundled under its own Apache-2.0 license — see
`third_party/obscura/`.

## Model backends

Five, behind one gateway; the app is not tied to any single vendor. Switch in
Settings.

| Backend | Key | Notes |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Messages API |
| OpenAI | `OPENAI_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | one key, many open-weight models |
| xAI (Grok) | `XAI_API_KEY` | |
| Ollama | none | local inference, fully offline |

## Privacy

Keys live in `.env`, read into the server process, and go only to the provider
you pick. Notes stay on disk in `workspace/`, and Library projects keep their
Markdown, plain-text, HTML, or JSON outputs in `projects/`. With Ollama selected nothing
leaves the machine at all. Discovery and reading run through Obscura's stealth
fetch: a consistent fingerprint and a fresh, cookieless jar, so a visit isn't
tied to any login or history.

Search sessions automatically expire after 24 hours by default. Set
`CELINA_SESSION_RETENTION_SECONDS` in `.env` to change that retention window.
Enable Incognito before searching to create an ephemeral session: it is deleted
when ended, when the page closes, or when the server restarts.

## Notebook

Notebook is the source-grounded learning desk for adult and college-level
self-study. Create a notebook around a question, add the papers, books,
lectures, or excerpts you trust, keep evidence-linked notes, and generate a
survey, college, or graduate-depth path through the material. The tutor uses
the active notebook's bounded sources, notes, and path as its context rather
than answering from an unbounded conversation.

Notebook data is local JSON under `workspace/notebooks/`. It is intentionally
separate from Library projects: notebooks are living study spaces, while
Library outputs are finished artifacts you choose to keep.

## It runs with few dependencies

Stdlib Python on the server, plain HTML and JavaScript in the browser
(self-hosted fonts). `pypdf` improves PDF extraction but is optional; `pywebview`
is only needed for the desktop window. No build step for the web UI.

## Contributing

Issues and PRs welcome. `python -m unittest discover -s tests` runs the full
suite (stdlib `unittest`, no test framework dependency) before you push.

## License

[MIT](LICENSE)
