# Reveriebot

A private web investigator: a browser, a chat, and a workspace in one window.

Open a page and it is fetched and rendered into a reading pane. Whatever is on
screen becomes context for the assistant beside it. Anything worth keeping is
saved as an artifact in the notebook. Inference runs through whichever model
you choose — including one running entirely on your own machine.

**It runs with zero dependencies.** Stdlib Python on the server, plain HTML and
JavaScript in the browser. No npm, no pip install, no build step, no Docker.

## Run it

```bash
python server/app.py
```

Then open <http://localhost:8765>.

That works immediately. To actually get answers you need one model backend —
either a key in `.env`, or Ollama running locally for a fully offline setup:

```bash
copy .env.example .env
```

## Model backends

Five, behind one gateway. Switch between them from the dropdown in the top
right; the app is deliberately not tied to any single vendor.

| Backend | Key | Notes |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Messages API |
| OpenAI | `OPENAI_API_KEY` | |
| OpenRouter | `OPENROUTER_API_KEY` | one key, many open-weight models |
| xAI (Grok) | `XAI_API_KEY` | |
| Ollama | none | local inference, fully offline |

Model IDs are configurable per backend in `.env` — the defaults are starting
points, not constraints.

## Research tools (optional)

Three open-source tools slot in as upgrades. The app detects each at startup
and shows it in the top strip; when one is missing everything still works, just
with less reach.

| Tool | Role | Status |
|---|---|---|
| [Obscura](https://github.com/h4ckf0r0day/obscura) | stealth headless browser — private fetch and render | wired: used for fetches when present |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | read/search across 15 platforms | detected; not yet wired |
| [last30days](https://github.com/mvanhorn/last30days-skill) | engagement-scored research brief | detected; not yet wired |

Install them into `vendor/` with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

The script asks before downloading anything and tells you the size first.

## Layout

```
server/
  app.py       stdlib HTTP server + JSON API
  gateway.py   the five-backend LLM router
  tools.py     optional-tool detection, page fetch + text extraction
web/           the three-pane UI (no build step)
workspace/     saved artifacts — gitignored, yours
vendor/        third-party binaries — gitignored
```

## Privacy

Keys live in `.env`, are read into the server process, and go only to the
provider you pick. Artifacts stay on disk in `workspace/`. Nothing is uploaded,
and with Ollama selected nothing leaves the machine at all.

Saved HTML artifacts render in a fully sandboxed iframe so a captured page
cannot script against the app.

## Status

Working: the three-pane UI, the five-backend gateway, URL fetch with Obscura
preferred, artifact save and reload, context-aware chat over whatever is open.

Next: wire Agent-Reach and last30days as real research actions, then package
the whole thing as a Tauri desktop app.
