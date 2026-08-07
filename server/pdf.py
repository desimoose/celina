"""PDF text extraction for open-access papers.

Zero-dependency by default. Born-digital PDFs (the arXiv / publisher kind)
store their text in content streams compressed with FlateDecode - and `zlib`
is stdlib, so we can inflate them and pull the text-showing operators without
any package. This will not read scanned/image PDFs (those need OCR) and can
garble PDFs built from CID fonts that ship no ToUnicode map.

If `pypdf` (or the older `PyPDF2`) is installed, we use it instead: a pure-
Python upgrade with far broader coverage. Detected at runtime, never required
- exactly the pattern the rest of Celina uses for heavy tools.
"""

import io
import re
import zlib


def looks_like_pdf(data):
    return data[:5] == b"%PDF-"


# --- optional upgrade: pypdf / PyPDF2 ------------------------------------

def _extract_pypdf(data, max_pages=None, max_chars_per_page=None):
    try:
        import pypdf as backend
    except ImportError:
        try:
            import PyPDF2 as backend
        except ImportError:
            return None
    try:
        reader = backend.PdfReader(io.BytesIO(data))
        pages = reader.pages if max_pages is None else reader.pages[:max_pages]
        parts = []
        for page in pages:
            text = page.extract_text() or ""
            if max_chars_per_page is not None:
                text = text[:max_chars_per_page]
            parts.append(text)
        return "\n\n".join(parts).strip()
    except Exception:
        return None  # fall through to the stdlib extractor


def extract_pages(data, max_pages=50, max_chars_per_page=2000):
    try:
        import pypdf as backend
    except ImportError:
        try:
            import PyPDF2 as backend
        except ImportError:
            return []
    try:
        reader = backend.PdfReader(io.BytesIO(data))
        pages = []
        for index, page in enumerate(reader.pages[:max_pages], start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            if len(text) > max_chars_per_page:
                text = text[:max_chars_per_page].rstrip()
            pages.append({"page": index, "text": text})
        return pages
    except Exception:
        return []


# --- stdlib fallback ------------------------------------------------------
#
# Speed matters: a real paper is a multi-MB binary with megabytes of
# decompressed content. Per-byte Python loops and DOTALL regexes over that are
# catastrophically slow (they hang). So this scans with bytes.find (no regex
# backtracking over the raw file), extracts strings with one compiled regex per
# decompressed stream, and hard-caps total work so it can never wedge the
# server. It is best-effort: born-digital PDFs read well; install pypdf for
# correct word spacing and CID-font coverage.

_MAX_INFLATED = 12_000_000   # stop decompressing past this many bytes
_MAX_CHARS = 600_000         # stop extracting past this much text

_ESCAPES = {0x6e: 0x0a, 0x72: 0x0d, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0c,
            0x28: 0x28, 0x29: 0x29, 0x5c: 0x5c}


def _decode_literal(body):
    """Decode a PDF literal string body (bytes between the parens)."""
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == 0x5C:  # backslash escape
            i += 1
            if i >= n:
                break
            e = body[i]
            if e in _ESCAPES:
                out.append(_ESCAPES[e]); i += 1
            elif 0x30 <= e <= 0x37:  # up to 3 octal digits
                j = 0
                while j < 3 and i + j < n and 0x30 <= body[i + j] <= 0x37:
                    j += 1
                out.append(int(body[i:i + j], 8) & 0xFF); i += j
            elif e in (0x0A, 0x0D):  # escaped line break -> nothing
                i += 1
            else:
                out.append(e); i += 1
        else:
            out.append(c); i += 1
    return out.decode("latin-1", "replace")


def _iter_flate_streams(data):
    """Yield decompressed bytes of each FlateDecode stream, bounded, via a
    linear bytes.find scan - no regex over the raw binary."""
    total, i = 0, 0
    while total < _MAX_INFLATED:
        s = data.find(b"stream", i)
        if s == -1:
            return
        j = s + 6
        if data[j:j + 2] == b"\r\n":
            j += 2
        elif data[j:j + 1] in (b"\n", b"\r"):
            j += 1
        e = data.find(b"endstream", j)
        if e == -1:
            return
        raw = data[j:e]
        i = e + 9
        try:
            dec = zlib.decompress(raw)
        except zlib.error:
            try:  # tolerate trailing bytes after the deflate data
                dec = zlib.decompressobj().decompress(raw)
            except zlib.error:
                continue
        total += len(dec)
        yield dec


# A single show operation, in document order: either a `[...]TJ` kerning array
# or a `(...)Tj` string. Reading them in order lets us recover word spacing.
_SHOW = re.compile(rb"\[([^\]]*)\]\s*TJ|\(((?:\\.|[^()\\])*)\)\s*(?:Tj|'|\")", re.S)
# Elements inside a TJ array: literal strings and kerning numbers.
_ELEM = re.compile(rb"\(((?:\\.|[^()\\])*)\)|(-?\d+(?:\.\d+)?)")

# A kerning adjustment more negative than this reads as a word space. Kerns
# between letters of a word are small (~ -10 to -60); a space is ~ -200+.
_SPACE_KERN = -120.0


def _text_from_stream(dec):
    parts = []
    for m in _SHOW.finditer(dec):
        arr, s = m.group(1), m.group(2)
        if s is not None:                      # (...)Tj  -> a run, then a gap
            parts.append(_decode_literal(s))
            parts.append(" ")
        elif arr is not None:                  # [...]TJ  -> kerned pieces
            for em in _ELEM.finditer(arr):
                estr, enum = em.group(1), em.group(2)
                if estr is not None:
                    parts.append(_decode_literal(estr))
                elif enum is not None:
                    try:
                        if float(enum) < _SPACE_KERN:
                            parts.append(" ")
                    except ValueError:
                        pass
            parts.append(" ")
    return "".join(parts)


def _extract_stdlib(data):
    out, count = [], 0
    for dec in _iter_flate_streams(data):
        if b"Tj" not in dec and b"TJ" not in dec:
            continue  # not a text-showing stream
        t = _text_from_stream(dec)
        if t.strip():
            out.append(t)
            count += len(t)
        if count > _MAX_CHARS:
            break
    text = "\n".join(out)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


# --- public ---------------------------------------------------------------

def extract_text(data, max_pages=None, max_chars_per_page=None):
    """Return (text, backend). backend is 'pypdf' or 'stdlib'. Raises if the
    PDF yields nothing readable (scanned image, or a font we can't map)."""
    via_pypdf = _extract_pypdf(data, max_pages, max_chars_per_page)
    if via_pypdf and len(via_pypdf) > 40:
        return via_pypdf, "pypdf"

    text = _extract_stdlib(data)
    if len(text) > 40:
        return text, "stdlib"

    raise RuntimeError(
        "couldn't read text from this PDF - it may be scanned images, or use "
        "fonts without a Unicode map. Installing pypdf (pip install pypdf) "
        "widens coverage."
    )
