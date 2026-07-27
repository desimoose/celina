"""Optional research tools, detected at runtime.

Nothing here is required to run Celina. Each tool is looked for on disk or
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
import time
import urllib.error
import urllib.parse
import urllib.request

import pdf
import paths
import traffic

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
    vend = paths.vendor_dir()
    bundled = paths.resource_path(os.path.join("vendor", "obscura", "obscura.exe"))
    return _first_existing(
        os.path.join(vend, "obscura", "obscura.exe"),
        os.path.join(vend, "obscura.exe"),
        os.path.join(VENDOR, "obscura", "obscura.exe"),
        os.path.join(VENDOR, "obscura.exe"),
        bundled,  # the copy PyInstaller froze in, when the exe was built with it
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


def _fetch_plain(url, traffic_context=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if traffic_context is not None:
        result = traffic.http_request(
            traffic_context,
            req,
            timeout=45,
            action_type="page.fetch",
        )
        content_type = next(
            (
                value
                for key, value in result.headers.items()
                if key.lower() == "content-type"
            ),
            "",
        )
        match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type)
        charset = match.group(1) if match else "utf-8"
        return result.body.decode(charset, "replace")
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


def obscura_dump(
    url,
    dump="html",
    stealth=True,
    timeout=30,
    traffic_context=None,
    action_type="page.fetch",
):
    """Raw Obscura dump for the Scanner: return stdout as text.

    dump="html"     -> stealth browser render, raw HTML (parse search results)
    dump="original" -> straight GET through Obscura's TLS (RSS/JSON feeds)
    Raises on non-zero exit or empty output.
    """
    binary = find_obscura()
    if not binary:
        raise RuntimeError("obscura not available")
    args = [binary]
    if stealth:
        args.append("--stealth")
    args += ["fetch", "--dump", dump, "--timeout", str(timeout), url]
    traffic_event_id = None
    request_redactions = ()
    started = time.monotonic()
    if traffic_context is not None:
        if (
            traffic_context.cancellation is not None
            and traffic_context.cancellation.is_set()
        ):
            raise traffic.TrafficCancelled(
                "request cancelled before opening process"
            )
        traffic_event_id, request_redactions = (
            traffic_context.recorder.start_process(
                traffic_context,
                url,
                action_type,
                {
                    "tool": "obscura",
                    "dump": dump,
                    "stealth": bool(stealth),
                    "timeout_seconds": timeout,
                },
            )
        )
    # Capture bytes and decode utf-8 ourselves: on Windows, text-mode capture can
    # mangle multibyte chars (curly quotes in RSS) via the console codepage.
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout + 60)
    except subprocess.TimeoutExpired as error:
        if traffic_context is not None:
            detail = error.stderr or b"obscura timed out"
            if isinstance(detail, str):
                detail = detail.encode("utf-8")
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                None,
                detail,
                request_redactions,
                "obscura timed out",
            )
        raise
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        if traffic_context is not None:
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                proc.returncode,
                proc.stderr or b"",
                request_redactions,
                err[:300] or "obscura exited non-zero",
            )
        raise RuntimeError(err[:300] or "obscura exited non-zero")
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if traffic_context is not None:
        traffic_context.recorder.complete_process(
            traffic_context,
            traffic_event_id,
            started,
            proc.returncode,
            proc.stdout or b"",
            request_redactions,
        )
    if not out:
        raise RuntimeError("empty dump")
    return out


def _looks_like_pdf_url(url):
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path


def _fetch_obscura_pdf(binary, url, timeout=40, traffic_context=None):
    """Fetch a PDF's raw bytes through Obscura and extract its text.

    Uses `--dump original` (a straight HTTP GET through Obscura's own TLS, which
    works where Python's cert store doesn't - e.g. arXiv) and deliberately does
    NOT pass `--stealth`: stealth forces the browser render path, which never
    fires a load event on a PDF and hangs. Bytes are captured raw (no text
    decode); the PDF module turns them into readable text.
    """
    if (
        traffic_context is not None
        and traffic_context.cancellation is not None
        and traffic_context.cancellation.is_set()
    ):
        raise traffic.TrafficCancelled("page read cancelled before it started")
    proc = subprocess.run(
        [binary, "fetch", "--dump", "original", "--timeout", str(timeout), url],
        capture_output=True, timeout=timeout + 40,
    )
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(msg or "obscura exited non-zero")
    data = proc.stdout
    if not pdf.looks_like_pdf(data):
        raise RuntimeError("not a PDF")
    return pdf.extract_text(data)  # (text, backend); raises if unreadable


def fetch(url, traffic_context=None):
    """Fetch a page, preferring Obscura when it is available.

    Returns the readable text plus which engine actually did the work, so the
    UI can be honest about how the request was made.
    """
    if (
        traffic_context is not None
        and traffic_context.cancellation is not None
        and traffic_context.cancellation.is_set()
    ):
        raise traffic.TrafficCancelled("page read cancelled before it started")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    binary = find_obscura()
    if binary:
        # A link that looks like a PDF goes straight to the byte path - no point
        # spinning the browser only to have it hang on a non-HTML resource.
        if _looks_like_pdf_url(url):
            try:
                text, backend = _fetch_obscura_pdf(
                    binary,
                    url,
                    traffic_context=traffic_context,
                )
                return {
                    "url": url,
                    "engine": "obscura-pdf",
                    "content_type": "application/pdf",
                    "note": f"pdf · {backend}",
                    "text": text,
                }
            except traffic.TrafficCancelled:
                raise
            except Exception:
                pass  # not really a PDF, or unreadable - try the normal path

        try:
            # Obscura's --dump text is already readable; no regex strip needed.
            return {
                "url": url,
                "engine": "obscura",
                "note": "stealth",
                "text": obscura_dump(
                    url,
                    dump="text",
                    stealth=True,
                    traffic_context=traffic_context,
                    action_type="page.fetch",
                ),
                "content_type": "text/plain",
            }
        except traffic.TrafficCancelled:
            raise
        except Exception as e:
            # An unmarked PDF (e.g. arXiv links carry no .pdf suffix) lands here
            # as empty text - try the byte path before giving up.
            try:
                text, backend = _fetch_obscura_pdf(
                    binary,
                    url,
                    traffic_context=traffic_context,
                )
                return {
                    "url": url,
                    "engine": "obscura-pdf",
                    "content_type": "application/pdf",
                    "note": f"pdf · {backend}",
                    "text": text,
                }
            except Exception:
                pass
            fallback_note = f"(obscura: {e}; used plain fetch)"
            try:
                return {
                    "url": url,
                    "engine": "plain",
                    "note": fallback_note,
                    "content_type": "text/plain",
                    "text": _readable(_fetch_plain(url, traffic_context)),
                }
            except Exception as inner:
                raise RuntimeError(f"{fallback_note} plain fetch also failed: {inner}")

    try:
        return {
            "url": url,
            "engine": "plain",
            "text": _readable(_fetch_plain(url, traffic_context)),
            "content_type": "text/plain",
        }
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        raise RuntimeError(f"could not fetch {url}: {e}")
