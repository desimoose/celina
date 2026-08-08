"""Optional research tools, detected at runtime.

Nothing here is required to run Celina. Each tool is looked for on disk or
on PATH; if it is missing the app keeps working and the UI shows it as absent.
That is the whole point - the heavy tools are upgrades, not prerequisites.

  Obscura      stealth headless browser (Rust binary) - private fetch + render
  Agent-Reach  read/search across 15 platforms (Python CLI)
  last30days   engagement-scored research brief (Python engine)
"""

import html
from dataclasses import dataclass
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
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


@dataclass(frozen=True)
class _PageResponse:
    body: bytes
    content_type: str


@dataclass(frozen=True)
class _PublicHttpResponse:
    status: int
    headers: dict
    body: bytes


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

# Matches pdf.py's own cap. A rendered page's extracted text is normally a
# few thousand to a few tens of thousands of characters; a PDF-viewer page
# that puts every page's text in the DOM (missed by _looks_like_pdf_url, or
# any other DOM oddity) can otherwise return megabytes uncapped.
_MAX_FETCHED_TEXT_CHARS = 600_000
_MAX_FETCHED_BYTES = 8_000_000
_MAX_PUBLIC_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_PUBLIC_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _bounded_bytes(body):
    if len(body) > _MAX_FETCHED_BYTES:
        raise RuntimeError("fetched document is too large")
    return body


def _run_bounded_process(args, timeout):
    """Run a byte-producing helper without buffering an unbounded stdout."""
    child = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout = bytearray()
    stderr = bytearray()

    def drain(stream, target, limit):
        while len(target) <= limit:
            chunk = stream.read(min(64 * 1024, limit + 1 - len(target)))
            if not chunk:
                break
            target.extend(chunk)

    out_thread = threading.Thread(
        target=drain, args=(child.stdout, stdout, _MAX_FETCHED_BYTES), daemon=True
    )
    err_thread = threading.Thread(
        target=drain, args=(child.stderr, stderr, 64 * 1024), daemon=True
    )
    out_thread.start()
    err_thread.start()
    deadline = time.monotonic() + timeout
    while out_thread.is_alive() or err_thread.is_alive():
        if len(stdout) > _MAX_FETCHED_BYTES:
            child.kill()
            break
        if time.monotonic() >= deadline:
            child.kill()
            out_thread.join(1)
            err_thread.join(1)
            child.wait()
            raise subprocess.TimeoutExpired(args, timeout, output=bytes(stdout), stderr=bytes(stderr))
        time.sleep(0.01)
    child.wait()
    out_thread.join(1)
    err_thread.join(1)
    if len(stdout) > _MAX_FETCHED_BYTES:
        raise RuntimeError("fetched document is too large")
    return SimpleNamespace(
        returncode=child.returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
    )


def _cap_fetched_text(text):
    if len(text) <= _MAX_FETCHED_TEXT_CHARS:
        return text
    return text[:_MAX_FETCHED_TEXT_CHARS] + "\n\n[truncated for length]"


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
        return _PageResponse(_bounded_bytes(result.body), _content_type(result.headers))
    with urllib.request.urlopen(req, timeout=45) as resp:
        body = resp.read(_MAX_FETCHED_BYTES + 1)
        return _PageResponse(_bounded_bytes(body), _content_type(resp.headers))


def _content_type(headers):
    for key, value in headers.items():
        if key.lower() == "content-type":
            return str(value)
    return "text/html"


def _media_type(content_type):
    return content_type.split(";", 1)[0].strip().lower()


def _legacy_ipv4_address(hostname):
    """Parse inet_aton-style IPv4 forms without asking the OS resolver."""
    if not hostname or not hostname[0].isdigit():
        return None
    parts = hostname.lower().split(".")
    if len(parts) > 4:
        return None

    values = []
    try:
        for part in parts:
            if not part:
                return None
            if part.startswith("0x"):
                values.append(int(part[2:], 16))
            elif len(part) > 1 and part.startswith("0"):
                values.append(int(part, 8))
            else:
                values.append(int(part, 10))
    except ValueError:
        return None

    widths = {
        1: (32,),
        2: (8, 24),
        3: (8, 8, 16),
        4: (8, 8, 8, 8),
    }[len(values)]
    if any(value < 0 or value >= (1 << width) for value, width in zip(values, widths)):
        return None
    packed = 0
    for value, width in zip(values, widths):
        packed = (packed << width) | value
    return ipaddress.IPv4Address(packed)


def validate_public_http_url(url):
    """Parse an HTTP(S) URL and require every resolved address to be public."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url is required")
    candidate = url.strip()
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only HTTP(S) URLs are allowed")
    if parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("URL must not contain credentials and must include a host")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("URL has an invalid port")
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    if port < 1:
        raise ValueError("URL has an invalid port")
    hostname = parsed.hostname.rstrip(".").lower()
    if not hostname:
        raise ValueError("URL must include a host")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("local hostnames are not allowed")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        if _legacy_ipv4_address(hostname) is not None:
            raise ValueError("alternate IP address forms are not allowed")
        try:
            addresses = [
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(
                    hostname, port, type=socket.SOCK_STREAM
                )
            ]
        except (socket.gaierror, ValueError):
            raise ValueError("URL host could not be resolved")
    if not addresses:
        raise ValueError("URL host could not be resolved")
    for address in addresses:
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            raise ValueError("IPv4-mapped IPv6 addresses are not allowed")
        if not address.is_global:
            raise ValueError("URL must resolve to a public address")
    return parsed


def _header_value(headers, name):
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return None


def _response_status(response):
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()
    return int(status)


def _open_url(url, *, traffic_context=None):
    """Open one URL without following redirects and return a bounded response."""
    if (
        traffic_context is not None
        and traffic_context.cancellation is not None
        and traffic_context.cancellation.is_set()
    ):
        raise traffic.TrafficCancelled("request cancelled before opening connection")

    request = urllib.request.Request(url, headers={"User-Agent": UA})
    event_id = None
    request_redactions = ()
    started = time.monotonic()
    if traffic_context is not None:
        event_id, request_redactions = traffic_context.recorder.start(
            traffic_context,
            request,
            "page.fetch",
        )

    response = None
    try:
        try:
            response = _PUBLIC_OPENER.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            if error.code not in _REDIRECT_STATUSES:
                raise
            response = error
        status = _response_status(response)
        headers = dict(response.headers.items())
        body = b"" if status in _REDIRECT_STATUSES else response.read(
            _MAX_FETCHED_BYTES + 1
        )
        body = _bounded_bytes(body)
    except Exception as error:
        if traffic_context is not None:
            traffic_context.recorder.complete(
                traffic_context,
                event_id,
                started,
                redactions=request_redactions,
                error=error,
            )
        raise
    finally:
        if response is not None:
            response.close()

    if traffic_context is not None:
        traffic_context.recorder.complete(
            traffic_context,
            event_id,
            started,
            status=status,
            headers=headers,
            body=body,
            redactions=request_redactions,
        )
    return _PublicHttpResponse(status, headers, body)


def _coerce_public_response(response):
    if isinstance(response, _PublicHttpResponse):
        return response
    try:
        status = _response_status(response)
        headers = dict(response.headers.items())
        body = b"" if status in _REDIRECT_STATUSES else response.read(
            _MAX_FETCHED_BYTES + 1
        )
        return _PublicHttpResponse(status, headers, _bounded_bytes(body))
    finally:
        response.close()


def _decode_page_body(body, content_type):
    match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type)
    charset = match.group(1) if match else "utf-8"
    return body.decode(charset, "replace")


def _pdf_payload_from_bytes(data):
    data = _bounded_bytes(data)
    text, backend = pdf.extract_text(
        data, max_pages=50, max_chars_per_page=2000
    )
    payload = {"text": text, "backend": backend}
    pages = pdf.extract_pages(data)
    if pages:
        payload["pages"] = pages
    return payload


def _page_from_response(url, response, note=None):
    media_type = _media_type(response.content_type)
    if media_type == "application/pdf":
        if not pdf.looks_like_pdf(response.body):
            raise RuntimeError("response declared PDF but did not contain a PDF")
        pages = pdf.extract_pages(response.body)
        text, backend = pdf.extract_text(
            response.body, max_pages=50, max_chars_per_page=2000
        )
        result = {
            "url": url,
            "engine": "plain-pdf",
            "note": f"pdf Â· {backend}",
            "text": _cap_fetched_text(text),
            "content_type": "application/pdf",
        }
        if pages:
            result["pages"] = pages
    else:
        textual_types = {
            "application/json",
            "application/xml",
            "application/xhtml+xml",
        }
        if not (media_type.startswith("text/") or media_type in textual_types):
            raise RuntimeError(
                f"unsupported non-text page content type: {media_type or 'unknown'}"
            )
        result = {
            "url": url,
            "engine": "plain",
            "text": _cap_fetched_text(_readable(_decode_page_body(
                response.body,
                response.content_type,
            ))),
            "content_type": response.content_type,
        }
    if note:
        result["note"] = note
    return result


def _plain_page(url, traffic_context=None, note=None):
    return _page_from_response(url, _fetch_plain(url, traffic_context), note)


def fetch_public(url, *, traffic_context=None):
    """Fetch bounded public content after validating every redirect hop."""
    current = url.strip() if isinstance(url, str) else url
    for redirect_count in range(_MAX_PUBLIC_REDIRECTS + 1):
        validate_public_http_url(current)
        response = _coerce_public_response(
            _open_url(current, traffic_context=traffic_context)
        )
        if response.status in _REDIRECT_STATUSES:
            location = _header_value(response.headers, "Location")
            if not location:
                raise RuntimeError("redirect response did not include a Location header")
            if redirect_count >= _MAX_PUBLIC_REDIRECTS:
                raise RuntimeError("too many redirects")
            target = urllib.parse.urljoin(current, location.strip())
            validate_public_http_url(target)
            current = target
            continue
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status} fetching {current}")
        return _page_from_response(
            current,
            _PageResponse(response.body, _content_type(response.headers)),
        )
    raise RuntimeError("too many redirects")


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
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf") or "/pdf/" in path:
        return True
    # Some publishers (e.g. EuropePMC's ?pdf=render) signal a PDF-viewer page
    # only through a "pdf" query key, never the path - without this a viewer
    # page gets browser-rendered instead of routed to the byte/pdf.py path,
    # and a viewer that puts every page's text in the DOM for accessibility
    # can dump megabytes of text through the stealth text-dump.
    query_keys = {key.lower() for key in urllib.parse.parse_qs(parsed.query)}
    return "pdf" in query_keys


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
    traffic_event_id = None
    request_redactions = ()
    started = time.monotonic()
    if traffic_context is not None:
        traffic_event_id, request_redactions = (
            traffic_context.recorder.start_process(
                traffic_context,
                url,
                "page.fetch",
                {
                    "tool": "obscura",
                    "dump": "original",
                    "stealth": False,
                    "timeout_seconds": timeout,
                },
            )
        )
    try:
        proc = subprocess.run(
            [binary, "fetch", "--dump", "original", "--timeout", str(timeout), url],
            capture_output=True,
            timeout=timeout + 40,
        )
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
    except OSError:
        if traffic_context is not None:
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                None,
                b"",
                request_redactions,
                "obscura process failed",
            )
        raise
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[:300]
        if traffic_context is not None:
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                proc.returncode,
                proc.stderr or b"",
                request_redactions,
                msg or "obscura exited non-zero",
            )
        raise RuntimeError(msg or "obscura exited non-zero")
    data = proc.stdout
    if traffic_context is not None:
        traffic_context.recorder.complete_process(
            traffic_context,
            traffic_event_id,
            started,
            proc.returncode,
            data,
            request_redactions,
        )
    if not pdf.looks_like_pdf(data):
        raise RuntimeError("not a PDF")
    return pdf.extract_text(data)  # (text, backend); raises if unreadable


def _fetch_obscura_pdf_payload(binary, url, timeout=40, traffic_context=None):
    if (
        traffic_context is not None
        and traffic_context.cancellation is not None
        and traffic_context.cancellation.is_set()
    ):
        raise traffic.TrafficCancelled("page read cancelled before it started")
    traffic_event_id = None
    request_redactions = ()
    started = time.monotonic()
    if traffic_context is not None:
        traffic_event_id, request_redactions = (
            traffic_context.recorder.start_process(
                traffic_context,
                url,
                "page.fetch",
                {
                    "tool": "obscura",
                    "dump": "original",
                    "stealth": False,
                    "timeout_seconds": timeout,
                },
            )
        )
    try:
        proc = _run_bounded_process(
            [binary, "fetch", "--dump", "original", "--timeout", str(timeout), url],
            timeout + 40,
        )
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
    except OSError:
        if traffic_context is not None:
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                None,
                b"",
                request_redactions,
                "obscura process failed",
            )
        raise
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()[:300]
        if traffic_context is not None:
            traffic_context.recorder.complete_process(
                traffic_context,
                traffic_event_id,
                started,
                proc.returncode,
                proc.stderr or b"",
                request_redactions,
                msg or "obscura exited non-zero",
            )
        raise RuntimeError(msg or "obscura exited non-zero")
    data = _bounded_bytes(proc.stdout)
    if traffic_context is not None:
        traffic_context.recorder.complete_process(
            traffic_context,
            traffic_event_id,
            started,
            proc.returncode,
            data,
            request_redactions,
        )
    if not pdf.looks_like_pdf(data):
        raise RuntimeError("not a PDF")
    return _pdf_payload_from_bytes(data)


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
                pdf_payload = _fetch_obscura_pdf_payload(
                    binary,
                    url,
                    traffic_context=traffic_context,
                )
                return {
                    "url": url,
                    "engine": "obscura-pdf",
                    "content_type": "application/pdf",
                    "note": f"pdf · {pdf_payload['backend']}",
                    "text": pdf_payload["text"],
                    "pages": pdf_payload.get("pages") or [],
                }
            except traffic.TrafficCancelled:
                raise
            except Exception:
                pass  # not really a PDF, or unreadable - try the normal path

        try:
            # Obscura's --dump text is already readable; no regex strip needed.
            dumped = _cap_fetched_text(obscura_dump(
                url,
                dump="text",
                stealth=True,
                traffic_context=traffic_context,
                action_type="page.fetch",
            ))
            # Some browser/pdf combinations hand --dump the binary document
            # decoded as text. Never persist that as evidence; retry through
            # the bounded byte/PDF path instead.
            if dumped.lstrip().startswith("%PDF-"):
                return _plain_page(url, traffic_context, "(obscura returned PDF bytes)")
            return {
                "url": url,
                "engine": "obscura",
                "note": "stealth",
                "text": dumped,
                "content_type": "text/plain",
            }
        except traffic.TrafficCancelled:
            raise
        except Exception as e:
            # An unmarked PDF (e.g. arXiv links carry no .pdf suffix) lands here
            # as empty text - try the byte path before giving up.
            try:
                pdf_payload = _fetch_obscura_pdf_payload(
                    binary,
                    url,
                    traffic_context=traffic_context,
                )
                return {
                    "url": url,
                    "engine": "obscura-pdf",
                    "content_type": "application/pdf",
                    "note": f"pdf · {pdf_payload['backend']}",
                    "text": pdf_payload["text"],
                    "pages": pdf_payload.get("pages") or [],
                }
            except Exception:
                pass
            fallback_note = f"(obscura: {e}; used plain fetch)"
            try:
                return _plain_page(url, traffic_context, fallback_note)
            except Exception as inner:
                raise RuntimeError(f"{fallback_note} plain fetch also failed: {inner}")

    try:
        return _plain_page(url, traffic_context)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        raise RuntimeError(f"could not fetch {url}: {e}")
