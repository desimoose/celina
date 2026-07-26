# Slice C: the zero-login Scanner — design

**Date:** 2026-07-25
**Status:** Approved, building on branch `scanner-sliceC`
**Milestone:** Broaden the one search box beyond scholarly to a blended,
keyless, no-login discovery layer, feeding Obscura for reading. Agent-Reach's
zero-login *channel ideas* are adopted natively; its login channels and heavy
stack (Node/mcporter/Exa/Jina) are NOT used.

## Principle

One search box -> a Scanner fans out across keyless sources -> ONE blended,
ranked candidate list -> Obscura reads whichever the user picks -> Studio.
Zero setup, no keys, no logins, private. Connections/auth (SSO/OAuth/stored
logins) are deliberately deferred (see the Slice-C brainstorm record).

## Sources (all keyless, no login)

1. **Research** — existing `finder.search` (OpenAlex / Europe PMC / Crossref).
2. **Web** — a resilient chain of search backends, each fetched through Obscura
   (its stealth fetch is built for this) and parsed for result links:
   DuckDuckGo HTML -> DuckDuckGo Lite -> Bing. First backend that yields
   results wins; on empty/error the scanner falls through to the next and notes
   which worked. This is the "restart and try another way" resilience.
3. **Recent** — Google News RSS search (`news.google.com/rss/search?q=...`),
   keyless XML, parsed with stdlib `xml.etree`. Covers the "what's fresh" need.
4. **Context** — Wikipedia keyless opensearch/summary API, one context result.

## Architecture

**`server/tools.py`** — add a raw-dump helper:
- `obscura_dump(url, dump="html", stealth=True, timeout=30) -> str` — runs
  `obscura [--stealth] fetch --dump <dump> --timeout <t> <url>` and returns raw
  stdout (UTF-8). `dump="html"` for search pages (stealth on); `dump="original"`
  for RSS/JSON (stealth off, straight GET through Obscura's TLS). Raises on
  non-zero / empty. Returns `None`-safe via caller try/except.

**`server/scanner.py`** (new, stdlib only) — pure, testable parsers + fan-out:
- `parse_ddg_html(html) -> list[dict]`, `parse_ddg_lite(html)`,
  `parse_bing(html)` — each extracts `{title, url, snippet}` from that engine's
  results markup (decoding DDG's `/l/?uddg=` redirect via
  `urllib.parse`). Pure functions, unit-tested against saved fixture HTML.
- `parse_news_rss(xml_text) -> list[dict]` — items -> `{title, url, snippet}`
  (snippet = source + date). Pure, unit-tested against a fixture.
- `parse_wikipedia(json_text) -> dict | None` — opensearch/summary ->
  `{title, url, snippet}`. Pure, unit-tested.
- `web_search(query, fetch_html, limit=6) -> (list, engine_used)` — tries the
  engine chain via the injected `fetch_html(url)`; returns first non-empty
  parsed list + which engine worked. Injected fetch = testable.
- `scan(query, gateway=None, provider=None, fetch_html=..., fetch_raw=...) ->
  dict` — runs research + web + recent + context (each in a try/except so one
  failing source is skipped, not fatal), blends into one list with a
  `kind` tag per item (`research|web|news|wikipedia`), returns
  `{query, results, notes, answer?}`. Optional grounded answer over the blended
  top items when a provider is given.
- Defaults wire `fetch_html`/`fetch_raw` to `tools.obscura_dump`; if Obscura is
  absent, web/news/context degrade to empty and research still works.

**`server/app.py`** — `/api/explore` (or a new `/api/scan`) routes to
`scanner.scan(...)` instead of finder-only. Response shape stays compatible
with the existing results renderer (adds `kind` per item).

**`web/app.js` + `web/styles.css`** — render the blended list with a small
per-item `kind` label (Research · Web · Recent · Wikipedia); a web/news/wiki
item's "Read" action goes through the existing Obscura `/api/fetch`; scholarly
items keep their open-access read. Minimal Coda-styled source tag.

## Build order (verifiable-first)

1. `tools.obscura_dump` + `web_search` (DDG chain) + parsers, unit-tested on
   fixtures, then live-verified (real Obscura fetch of a real query).
2. Blend web + research in `scan`; wire `/api/explore`; live-verify the list.
3. Add Google News RSS (recent) + Wikipedia (context); live-verify.
4. UI source tags + read routing.

## Verification

- Unit: parsers against saved fixture HTML/XML/JSON (deterministic, offline).
- Live (dev + isolated home): a real query returns a blended list with web +
  research items; clicking a web result reads it via Obscura; the engine
  fallback works (simulate first engine empty -> next used); graceful
  degradation with Obscura absent (research-only).
- Behavior suite stays green (21 + new scanner tests).
- impeccable detector clean; rebuild exe.

## Out of scope (deferred)

- Connections/auth layer (SSO/OAuth/stored logins) and any login-gated
  platform — parked per the brainstorm; core-first.
- Installing Agent-Reach itself (its ideas are adopted natively).
- YouTube transcripts / GitHub / niche channels (can be added as more scanner
  sources later, same pattern).
