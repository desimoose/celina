"""Normalized search candidates and content that Celina actually read."""

from dataclasses import dataclass, replace
import urllib.parse
import uuid


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    title: str
    url: str
    canonical_url: str
    source_kind: str
    published_at: str | None
    authors: tuple[str, ...]
    snippet: str | None
    open_access: bool | None
    retrieval_query_ids: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    citation_id: str
    candidate_id: str
    title: str
    url: str
    source_kind: str
    text: str
    content_type: str
    character_count: int
    was_read: bool

    @classmethod
    def from_read(cls, candidate, text, content_type, citation_id):
        cleaned = str(text or "").strip()
        if not cleaned:
            raise ValueError("read evidence requires usable body content")
        if (content_type or "").lower() == "search/snippet":
            raise ValueError("search-result snippets are not read evidence")
        if candidate.snippet and cleaned == candidate.snippet.strip():
            raise ValueError("search-result snippets are not read evidence")
        if not isinstance(citation_id, str) or not citation_id:
            raise ValueError("citation_id is required")
        return cls(
            citation_id=citation_id,
            candidate_id=candidate.candidate_id,
            title=candidate.title,
            url=candidate.url,
            source_kind=candidate.source_kind,
            text=cleaned,
            content_type=content_type or "text/plain",
            character_count=len(cleaned),
            was_read=True,
        )


def canonicalize_url(url):
    try:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    port = parsed.port
    if port and not (
        (scheme == "http" and port == 80)
        or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parsed.path or ""
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path.rstrip("/")
    query = []
    for key, value in urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ):
        lowered = key.lower()
        if lowered in _TRACKING_KEYS or lowered.startswith(_TRACKING_PREFIXES):
            continue
        query.append((key, value))
    return urllib.parse.urlunsplit((
        scheme,
        host,
        path,
        urllib.parse.urlencode(query),
        "",
    ))


def normalize_candidates(rows):
    found = {}
    order = []
    for row in rows or ():
        url = row.get("oa_url") or row.get("url")
        canonical = canonicalize_url(url)
        title = str(row.get("title") or "").strip()
        if not canonical or not title:
            continue
        query_id = str(row.get("query_id") or "").strip()
        source_kind = row.get("kind") or row.get("source_kind") or "web"
        candidate = Candidate(
            candidate_id=str(uuid.uuid5(uuid.NAMESPACE_URL, canonical)),
            title=title,
            url=url,
            canonical_url=canonical,
            source_kind=source_kind,
            published_at=row.get("published_at"),
            authors=tuple(row.get("authors") or ()),
            snippet=row.get("snippet") or row.get("abstract"),
            open_access=row.get("is_oa"),
            retrieval_query_ids=(query_id,) if query_id else (),
        )
        existing = found.get(canonical)
        if existing is None:
            found[canonical] = candidate
            order.append(canonical)
            continue
        query_ids = tuple(dict.fromkeys(
            existing.retrieval_query_ids + candidate.retrieval_query_ids
        ))
        preferred = _prefer(existing, candidate)
        found[canonical] = replace(
            preferred,
            retrieval_query_ids=query_ids,
        )
    return [found[key] for key in order]


def _prefer(left, right):
    ranks = {"research": 4, "news": 3, "context": 2, "web": 1}
    left_score = (
        ranks.get(left.source_kind, 0),
        bool(left.authors),
        bool(left.snippet),
    )
    right_score = (
        ranks.get(right.source_kind, 0),
        bool(right.authors),
        bool(right.snippet),
    )
    return right if right_score > left_score else left
