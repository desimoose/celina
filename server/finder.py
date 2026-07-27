"""Finder - open-access scholarly search.

Queries open scientific sources with no API key and returns normalized
results an LLM can ground its answers in: real papers, real authors, real
open-access links - not hallucinated citations.

Stdlib only. Each source is isolated, so one being slow or down never takes
the search down with it. Add a source by writing one function and registering
it in SOURCES.

CLI:  python server/finder.py "your question"
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import traffic

TIMEOUT = 20

UA = "Celina-Finder/0.1 (open-access research tool)"


def contact_email():
    """Read the optional contact at call time, after app.load_env()."""
    return os.environ.get("FINDER_CONTACT_EMAIL", "").strip()


def _get(url, traffic_context=None, action_type="research.search"):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if traffic_context is not None:
        return traffic.http_request(
            traffic_context,
            req,
            timeout=TIMEOUT,
            action_type=action_type,
        ).body
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _get_json(url, traffic_context=None, action_type="research.search"):
    return json.loads(
        _get(url, traffic_context, action_type).decode("utf-8")
    )


def _reconstruct_abstract(inverted_index):
    """OpenAlex stores abstracts as a word -> [positions] inverted index.
    Rebuild the plain text from it."""
    if not inverted_index:
        return None
    positions = []
    for word, spots in inverted_index.items():
        for spot in spots:
            positions.append((spot, word))
    positions.sort()
    text = " ".join(word for _, word in positions)
    return text[:1200] + ("..." if len(text) > 1200 else "")


def _record(**kw):
    """A normalized result. Every source maps into this shape."""
    base = {
        "title": None, "authors": [], "year": None, "venue": None,
        "doi": None, "url": None, "oa_url": None, "is_oa": None,
        "cited_by": None, "abstract": None, "source": None,
    }
    base.update(kw)
    return base


# --- Sources -------------------------------------------------------------

def openalex(query, limit, traffic_context=None):
    """OpenAlex: 250M+ works, no key, includes open-access status + PDF link.
    The spine of the Finder."""
    params = {"search": query, "per_page": limit, "sort": "relevance_score:desc"}
    contact = contact_email()
    if contact:
        params["mailto"] = contact
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = (
        _get_json(url, traffic_context)
        if traffic_context is not None
        else _get_json(url)
    )
    out = []
    for w in data.get("results", []):
        oa = w.get("open_access") or {}
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in (w.get("authorships") or [])[:8]
        ]
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        out.append(_record(
            title=w.get("title") or w.get("display_name"),
            authors=[a for a in authors if a],
            year=w.get("publication_year"),
            venue=src.get("display_name"),
            doi=doi,
            url=w.get("doi") or loc.get("landing_page_url"),
            oa_url=oa.get("oa_url"),
            is_oa=oa.get("is_oa"),
            cited_by=w.get("cited_by_count"),
            abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
            source="OpenAlex",
        ))
    return out


def arxiv(query, limit, traffic_context=None):
    """arXiv: preprints, no key. Where research shows up before the paywall
    closes. Returns Atom XML."""
    params = {
        "search_query": "all:" + query,
        "max_results": limit,
        "sortBy": "relevance",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    raw = (
        _get(url, traffic_context)
        if traffic_context is not None
        else _get(url)
    )
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(raw)
    out = []
    for e in root.findall("a:entry", ns):
        def text(tag):
            node = e.find("a:" + tag, ns)
            return node.text.strip() if node is not None and node.text else None

        pdf = None
        for link in e.findall("a:link", ns):
            if link.get("title") == "pdf":
                pdf = link.get("href")
        published = text("published") or ""
        out.append(_record(
            title=text("title"),
            authors=[
                n.text.strip()
                for n in e.findall("a:author/a:name", ns) if n.text
            ][:8],
            year=int(published[:4]) if published[:4].isdigit() else None,
            venue="arXiv (preprint)",
            url=text("id"),
            oa_url=pdf,
            is_oa=True,  # arXiv is open by definition
            abstract=(text("summary") or "")[:1200] or None,
            source="arXiv",
        ))
    return out


def _strip_tags(text):
    """Crossref and Europe PMC abstracts arrive with XML/JATS tags. Strip them."""
    if not text:
        return None
    clean = re.sub(r"<[^>]+>", "", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    return (clean[:1200] + ("..." if len(clean) > 1200 else "")) or None


def europepmc(query, limit, traffic_context=None):
    """Europe PMC: life-sciences literature with full-text links, no key."""
    params = {"query": query, "format": "json",
              "resultType": "core", "pageSize": limit}
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
           + urllib.parse.urlencode(params))
    data = (
        _get_json(url, traffic_context)
        if traffic_context is not None
        else _get_json(url)
    )
    out = []
    for r in (data.get("resultList") or {}).get("result", []):
        oa_url = None
        for f in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
            if f.get("documentStyle") == "pdf" and \
                    f.get("availability") in ("Open access", "Free"):
                oa_url = f.get("url")
                break
        doi = r.get("doi")
        year = str(r.get("pubYear") or "")
        out.append(_record(
            title=r.get("title"),
            authors=[a.strip() for a in (r.get("authorString") or "").split(",")
                     if a.strip()][:8],
            year=int(year) if year.isdigit() else None,
            venue=r.get("journalTitle"),
            doi=doi,
            url=("https://doi.org/" + doi) if doi else None,
            oa_url=oa_url,
            is_oa=(r.get("isOpenAccess") == "Y"),
            cited_by=r.get("citedByCount"),
            abstract=_strip_tags(r.get("abstractText")),
            source="Europe PMC",
        ))
    return out


def crossref(query, limit, traffic_context=None):
    """Crossref: the registry of record for DOIs, no key. No OA link itself -
    Unpaywall enrichment fills that in."""
    params = {"query": query, "rows": limit,
              "select": ("title,author,issued,container-title,DOI,URL,"
                         "is-referenced-by-count,abstract")}
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    contact = contact_email()
    if contact:
        url += "&mailto=" + urllib.parse.quote(contact)
    data = (
        _get_json(url, traffic_context)
        if traffic_context is not None
        else _get_json(url)
    )
    out = []
    for it in (data.get("message") or {}).get("items", []):
        dp = ((it.get("issued") or {}).get("date-parts") or [[None]])
        year = dp[0][0] if dp and dp[0] else None
        authors = [" ".join(x for x in [a.get("given"), a.get("family")] if x)
                   for a in (it.get("author") or [])]
        out.append(_record(
            title=(it.get("title") or [None])[0],
            authors=[a for a in authors if a][:8],
            year=year,
            venue=(it.get("container-title") or [None])[0],
            doi=it.get("DOI"),
            url=it.get("URL"),
            cited_by=it.get("is-referenced-by-count"),
            abstract=_strip_tags(it.get("abstract")),
            source="Crossref",
        ))
    return out


def doaj(query, limit, traffic_context=None):
    """DOAJ: the Directory of Open Access Journals, no key. Every result is
    open access by definition."""
    url = ("https://doaj.org/api/search/articles/"
           + urllib.parse.quote(query) + "?pageSize=" + str(limit))
    data = (
        _get_json(url, traffic_context)
        if traffic_context is not None
        else _get_json(url)
    )
    out = []
    for r in data.get("results", []):
        b = r.get("bibjson") or {}
        fulltext = None
        for link in (b.get("link") or []):
            if link.get("type") == "fulltext":
                fulltext = link.get("url")
                break
        doi = None
        for idf in (b.get("identifier") or []):
            if idf.get("type") == "doi":
                doi = idf.get("id")
        year = str(b.get("year") or "")
        out.append(_record(
            title=b.get("title"),
            authors=[a.get("name") for a in (b.get("author") or [])
                     if a.get("name")][:8],
            year=int(year) if year.isdigit() else None,
            venue=(b.get("journal") or {}).get("title"),
            doi=doi,
            url=("https://doi.org/" + doi) if doi else fulltext,
            oa_url=fulltext,
            is_oa=True,
            abstract=(b.get("abstract") or "")[:1200] or None,
            source="DOAJ",
        ))
    return out


def unpaywall_resolve(doi, email=None, traffic_context=None):
    """Unpaywall: given a DOI, find the legal open-access copy. Not a search
    engine - a resolver. This is what turns a paywalled result into a readable
    one. Requires a contact email (free, no key): set FINDER_CONTACT_EMAIL."""
    email = email or contact_email()
    if not doi or not email:
        return None
    url = ("https://api.unpaywall.org/v2/"
           + urllib.parse.quote(doi) + "?email=" + urllib.parse.quote(email))
    data = (
        _get_json(url, traffic_context, "research.resolve")
        if traffic_context is not None
        else _get_json(url)
    )
    if not data.get("is_oa"):
        return None
    loc = data.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or loc.get("url")


# Register a source here and it joins every search. Keyless ones first;
# the commented rows are the obvious next additions, each one function away.
SOURCES = {
    "openalex": openalex,     # keyless - the spine
    "arxiv": arxiv,           # keyless - preprints
    "europepmc": europepmc,   # keyless - life-sciences full text
    "crossref": crossref,     # keyless - registered metadata
    # "doaj": doaj,           # keyless, but Cloudflare returns 403 to
                              # non-browser clients on many networks. Function
                              # is correct; enable if it's reachable from yours.
    # Unpaywall is a resolver, not a search source - it runs as an
    # enrichment pass inside search(), keyed on DOI. See unpaywall_resolve().
}


# --- Aggregation ---------------------------------------------------------

def _dedupe_key(rec):
    if rec.get("doi"):
        return rec["doi"].lower()
    title = (rec.get("title") or "").lower()
    return "".join(ch for ch in title if ch.isalnum())[:80]


def search(
    query,
    limit=8,
    sources=None,
    traffic_context=None,
    event_sink=None,
):
    """Search every registered source, merge, dedupe, and rank.

    Returns (results, notes) - notes records any source that failed, so the
    caller can say "that one didn't answer" instead of failing the whole run.
    """
    chosen = sources or list(SOURCES)
    seen = {}
    notes = []
    for name in chosen:
        fn = SOURCES.get(name)
        if not fn:
            continue
        try:
            records = (
                fn(query, limit, traffic_context)
                if traffic_context is not None
                else fn(query, limit)
            )
            for rec in records:
                if not rec.get("title"):
                    continue
                key = _dedupe_key(rec)
                # keep the record that knows the most (prefer one with an OA link)
                if key not in seen or (rec.get("oa_url") and not seen[key].get("oa_url")):
                    seen[key] = rec
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError,
                json.JSONDecodeError, TimeoutError) as e:
            notes.append(f"{name} didn't answer ({type(e).__name__})")
            if event_sink is not None:
                event_sink({
                    "kind": "source.failed",
                    "source": name,
                    "error_class": type(e).__name__,
                })

    results = list(seen.values())

    # Enrichment: for hits that have a DOI but no open-access link, ask
    # Unpaywall for the free copy. This is what makes paywalled results
    # readable. Capped so a big result set can't stall the search.
    if contact_email():
        for r in results[:15]:
            if r.get("doi") and not r.get("oa_url"):
                try:
                    oa = unpaywall_resolve(
                        r["doi"],
                        traffic_context=traffic_context,
                    )
                    if oa:
                        r["oa_url"] = oa
                        r["is_oa"] = True
                        r["oa_via"] = "Unpaywall"
                except (urllib.error.URLError, urllib.error.HTTPError,
                        json.JSONDecodeError, TimeoutError):
                    pass  # one DOI failing to resolve is not worth a note
    else:
        notes.append("Unpaywall skipped - set FINDER_CONTACT_EMAIL to unlock "
                     "free copies of paywalled hits")

    # rank: open-access first, then by citations, then recency
    results.sort(key=lambda r: (
        0 if r.get("oa_url") else 1,
        -(r.get("cited_by") or 0),
        -(r.get("year") or 0),
    ))
    return results[:limit], notes


def to_context(results):
    """Format results as a grounding block for an LLM. The model answers over
    THESE - real papers with real links - so citations point at something that
    exists. This is the difference between exploring knowledge and being told a
    confident story."""
    lines = []
    for i, r in enumerate(results, 1):
        who = ", ".join(r["authors"][:3]) + (" et al." if len(r["authors"]) > 3 else "")
        head = f"[{i}] {r['title']}"
        meta = " · ".join(x for x in [
            who or None,
            str(r["year"]) if r["year"] else None,
            r["venue"],
            f"cited by {r['cited_by']}" if r.get("cited_by") else None,
        ] if x)
        link = r.get("oa_url") or r.get("url") or ""
        block = f"{head}\n    {meta}"
        if link:
            block += f"\n    {'open access: ' if r.get('oa_url') else ''}{link}"
        if r.get("abstract"):
            block += f"\n    {r['abstract'][:400]}"
        lines.append(block)
    return "\n\n".join(lines)


def grounding_system(results):
    """The instruction that keeps the model honest: answer only from the
    retrieved papers, cite them by number, admit the gaps."""
    return (
        "You are a research companion. Answer using ONLY the numbered sources "
        "below. Cite them inline like [1], [3]. If the sources do not cover "
        "something, say so plainly instead of guessing. Lead with the finding. "
        "Never invent a citation.\n\nSources:\n" + to_context(results)
    )


def explore(query, provider, limit=8, traffic_context=None):
    """Search real papers, then have an LLM answer *grounded in them*.

    The model is told to use only the retrieved sources and to cite them by
    number. That is the whole point: it explores knowledge with you instead of
    telling you a confident story with invented references. Needs a provider
    from the gateway (a BYOK key, or local Ollama - no key).
    """
    import gateway

    hits, notes = search(
        query,
        limit=limit,
        traffic_context=traffic_context,
    )
    if not hits:
        return {"answer": None, "results": [], "notes": notes}

    system = grounding_system(hits)
    reply = gateway.chat(
        provider,
        messages=[{"role": "user", "content": query}],
        system=system,
        traffic_context=traffic_context,
    )
    return {"answer": reply["text"], "results": hits, "notes": notes,
            "model": reply["model"], "provider": reply["provider"]}


if __name__ == "__main__":
    # scholarly text is full of unicode; don't let a console codepage crash it
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print('usage: python server/finder.py "your question"')
        raise SystemExit(1)
    hits, notes = search(q, limit=8)
    print(f"\n{len(hits)} results for: {q}\n")
    for n in notes:
        print(f"  note: {n}")
    if notes:
        print()
    print(to_context(hits))
