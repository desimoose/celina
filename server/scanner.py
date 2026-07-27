"""The Scanner - zero-login discovery across keyless sources.

One query fans out across sources that need no key and no login, and returns
one blended candidate list. Obscura does the fetching for web/news/context (so
discovery uses the same private engine that reads); the scholarly finder brings
credible research. Anything that errors is skipped, not fatal.

Parsers are pure functions (unit-tested against saved fixtures). Network fetches
are injected (`fetch_html`, `fetch_raw`) so the logic is testable offline and so
the whole thing degrades gracefully when Obscura is absent.
"""

import base64
import html as _html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET

import finder

_TAG = re.compile(r"<[^>]+>")


def _clean(s):
    return _html.unescape(_TAG.sub("", s or "")).strip()


# ---------- web search parsers ----------

_DDG_A = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIP = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _ddg_real_url(href):
    href = _html.unescape(href)
    if "uddg=" in href:
        query = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href).query
        vals = urllib.parse.parse_qs(query).get("uddg")
        if vals:
            return vals[0]
    return href if href.startswith("http") else ""


def parse_ddg_html(html_text, limit=8):
    links = _DDG_A.findall(html_text)
    snips = _DDG_SNIP.findall(html_text)
    out = []
    for i, (href, title) in enumerate(links):
        url = _ddg_real_url(href)
        if not url.startswith("http"):
            continue
        out.append({
            "title": _clean(title),
            "url": url,
            "snippet": _clean(snips[i]) if i < len(snips) else "",
        })
        if len(out) >= limit:
            break
    return out


_DDG_LITE_A = re.compile(
    r'<a[^>]*rel=["\']nofollow["\'][^>]*href=["\']([^"\']+)["\'][^>]*>'
    r'(.*?)</a>',
    re.S | re.I,
)
_DDG_LITE_SNIP = re.compile(
    r'<td[^>]*class=["\'][^"\']*result-snippet[^"\']*["\'][^>]*>'
    r'(.*?)</td>',
    re.S | re.I,
)


def parse_ddg_lite(html_text, limit=8):
    """Parse DuckDuckGo's low-script Lite results page."""
    links = _DDG_LITE_A.findall(html_text)
    snips = _DDG_LITE_SNIP.findall(html_text)
    out = []
    for i, (href, title) in enumerate(links):
        url = _ddg_real_url(href)
        if not url.startswith("http"):
            continue
        out.append({
            "title": _clean(title),
            "url": url,
            "snippet": _clean(snips[i]) if i < len(snips) else "",
        })
        if len(out) >= limit:
            break
    return out


_BING_H2 = re.compile(r"<h2[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)


def _bing_real_url(href):
    href = _html.unescape(href)
    if "/ck/a" in href:
        u = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("u", [""])[0]
        if u.startswith("a1"):
            raw = u[2:] + "=" * (-len(u[2:]) % 4)
            try:
                return base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
            except Exception:
                return ""
    return href if href.startswith("http") else ""


def parse_bing(html_text, limit=8):
    out = []
    for href, title in _BING_H2.findall(html_text):
        url = _bing_real_url(href)
        if url.startswith("http") and "bing.com" not in url:
            out.append({"title": _clean(title), "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


# Ordered fallback chain: first backend that yields results wins.
_ENGINES = [
    ("duckduckgo",
     lambda q: "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q),
     parse_ddg_html),
    ("duckduckgo-lite",
     lambda q: "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(q),
     parse_ddg_lite),
    ("bing",
     lambda q: "https://www.bing.com/search?q=" + urllib.parse.quote(q),
     parse_bing),
]


def web_search(query, fetch_html, limit=6):
    """Try each search backend in turn; return (results, engine_used).
    On empty/error, fall through to the next - the resilience mechanism."""
    tried = []
    for name, build_url, parse in _ENGINES:
        try:
            results = parse(fetch_html(build_url(query)), limit)
            if results:
                return results[:limit], name
            tried.append(f"{name}: 0")
        except Exception as e:
            tried.append(f"{name}: {str(e)[:50]}")
    return [], "none (" + "; ".join(tried) + ")"


# ---------- recent (Google News RSS) ----------

def parse_news_rss(xml_text, limit=5):
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iterfind(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        src = item.findtext("source") or ""
        date = item.findtext("pubDate") or ""
        if not link:
            continue
        out.append({
            "title": _clean(title),
            "url": link.strip(),
            "snippet": _clean(" · ".join([p for p in (src, date[:16]) if p])),
        })
        if len(out) >= limit:
            break
    return out


# ---------- context (Wikipedia opensearch) ----------

def parse_wikipedia(json_text):
    try:
        hits = json.loads(json_text)["query"]["search"]
        if hits:
            title = hits[0]["title"]
            return {
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": _clean(hits[0].get("snippet", "")) or "Wikipedia article",
            }
    except Exception:
        pass
    return None


def _news_url(query):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-US"


def _wiki_url(query):
    return ("https://en.wikipedia.org/w/api.php?action=query&list=search&srlimit=1&format=json&srsearch="
            + urllib.parse.quote(query))


# ---------- blend ----------

def _grounding_system(items):
    lines = ["You answer the user's question using ONLY these sources. Cite by "
             "number like [1]. If they do not cover it, say so plainly.\n"]
    for i, it in enumerate(items, 1):
        lines.append(f"[{i}] {it.get('title','')} — {it.get('snippet') or it.get('abstract') or ''} ({it.get('url') or it.get('oa_url') or ''})")
    return "\n".join(lines)


def scan(query, gateway=None, provider=None, fetch_html=None, fetch_raw=None):
    """Fan out across keyless sources, blend into one candidate list.
    fetch_html/fetch_raw are injected (default: Obscura via tools)."""
    if fetch_html is None or fetch_raw is None:
        import tools
        if fetch_html is None:
            fetch_html = lambda u: tools.obscura_dump(u, dump="html", stealth=True)
        if fetch_raw is None:
            fetch_raw = lambda u: tools.obscura_dump(u, dump="original", stealth=False)

    results, notes = [], []

    # research (scholarly)
    try:
        hits, fnotes = finder.search(query, limit=6)
        for h in hits:
            h["kind"] = "research"
        results.extend(hits)
        notes.extend(fnotes or [])
    except Exception as e:
        notes.append(f"research: {str(e)[:60]}")

    # context (Wikipedia) - one item, placed first
    try:
        wiki = parse_wikipedia(fetch_raw(_wiki_url(query)))
        if wiki:
            wiki["kind"] = "wikipedia"
            results.insert(0, wiki)
    except Exception as e:
        notes.append(f"wikipedia: {str(e)[:60]}")

    # web
    try:
        web, engine = web_search(query, fetch_html, limit=6)
        for w in web:
            w["kind"] = "web"
        results.extend(web)
        if not web:
            notes.append(f"web: {engine}")
    except Exception as e:
        notes.append(f"web: {str(e)[:60]}")

    # recent (news)
    try:
        news = parse_news_rss(fetch_raw(_news_url(query)))
        for n in news:
            n["kind"] = "news"
        results.extend(news)
    except Exception as e:
        notes.append(f"news: {str(e)[:60]}")

    out = {"query": query, "results": results, "notes": notes, "answer": None}

    if provider and gateway and results:
        try:
            reply = gateway.chat(
                provider,
                messages=[{"role": "user", "content": query}],
                system=_grounding_system(results[:10]),
            )
            out.update(answer=reply["text"], model=reply["model"], provider=reply["provider"])
        except Exception as e:
            out["answer_error"] = str(e)
    return out
