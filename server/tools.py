"""Optional research tools, detected at runtime.

Nothing here is required to run Reveriebot. Each tool is looked for on disk or
on PATH; if it is missing the app keeps working and the UI shows it as absent.
That is the whole point - the heavy tools are upgrades, not prerequisites.

  Obscura      stealth headless browser (Rust binary) - private fetch + render
  Agent-Reach  read/search across 15 platforms (Python CLI)
  last30days   engagement-scored research brief (Python engine)
"""

import html
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _first_existing(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


def find_obscura():
    return _first_existing(
        os.path.join(VENDOR, "obscura", "obscura.exe"),
        os.path.join(VENDOR, "obscura.exe"),
    ) or shutil.which("obscura")


def find_agent_reach():
    return shutil.which("agent-reach")


def find_last30days():
    return _first_existing(
        os.path.join(VENDOR, "last30days", "scripts", "last30days.py"),
    )


def status():
    """What is installed right now. Drives the UI's tool strip."""
    obscura, reach, last30 = find_obscura(), find_agent_reach(), find_last30days()
    return [
        {"id": "obscura", "label": "Obscura",
         "detail": "stealth browser", "path": obscura, "present": bool(obscura)},
        {"id": "agent-reach", "label": "Agent-Reach",
         "detail": "15 platforms", "path": reach, "present": bool(reach)},
        {"id": "last30days", "label": "last30days",
         "detail": "scored brief", "path": last30, "present": bool(last30)},
    ]


_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def _readable(raw_html):
    """Strip a page down to something a model can actually read."""
    text = _SCRIPT_STYLE.sub(" ", raw_html)
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"[ \t]{2,}", " ", text)
    return _BLANKS.sub("\n\n", text).strip()


def _fetch_plain(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, "replace")


def _fetch_obscura(binary, url, timeout=30):
    """Render through Obscura in stealth mode: a real browser load with a
    consistent fingerprint and a fresh, cookieless jar - so the fetch is not
    tied to any login or history. Obscura extracts readable text from the live
    DOM itself (`--dump text`), which beats regex-stripping raw HTML.

    Progress lines go to stderr; stdout is the page text. utf-8 is forced so
    scholarly unicode does not trip the Windows console codepage.
    """
    proc = subprocess.run(
        [binary, "--stealth", "fetch", "--dump", "text",
         "--timeout", str(timeout), url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout + 60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or "obscura exited non-zero")
    out = (proc.stdout or "").strip()
    if not out:
        # Empty almost always means a PDF or a JS/login wall the DOM text
        # dump cannot read - let the caller fall back to a plain fetch.
        raise RuntimeError("no readable text (likely a PDF or login wall)")
    return _BLANKS.sub("\n\n", out)


def fetch(url):
    """Fetch a page, preferring Obscura when it is available.

    Returns the readable text plus which engine actually did the work, so the
    UI can be honest about whether the request was stealth-rendered or plain.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    binary = find_obscura()
    if binary:
        try:
            # Obscura's --dump text is already readable; no regex strip needed.
            return {"url": url, "engine": "obscura", "note": "stealth",
                    "text": _fetch_obscura(binary, url)}
        except Exception as e:
            # Obscura present but unhappy - fall through rather than fail the request
            fallback_note = f"(obscura: {e}; used plain fetch)"
            try:
                return {"url": url, "engine": "plain", "note": fallback_note,
                        "text": _readable(_fetch_plain(url))}
            except Exception as inner:
                raise RuntimeError(f"{fallback_note} plain fetch also failed: {inner}")

    try:
        return {"url": url, "engine": "plain", "text": _readable(_fetch_plain(url))}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        raise RuntimeError(f"could not fetch {url}: {e}")
