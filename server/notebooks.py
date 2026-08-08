"""File-backed research notebooks stored under the local data directory."""

from datetime import datetime, timedelta, timezone
import json
import os
import re
import tempfile
import urllib.parse

import paths


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_TITLE_LIMIT = 120
_URL_LIMIT = 2048
_EXCERPT_LIMIT = 5000
_NOTE_BODY_LIMIT = 10000
_SOURCE_TITLE_LIMIT = 160
_NOTE_TITLE_LIMIT = 160
_IMPORT_PAGE_LIMIT = 50
_IMPORT_CITATION_TEXT_LIMIT = 2000
_ORIGIN_LIMIT = 32
_TUTOR_CONTEXT_LIMIT = 40000
_TUTOR_CONTEXT_CITATIONS_PER_SOURCE = 6
_STUDY_ITEM_LIMIT = 12
_STUDY_TEXT_LIMIT = 1200
_STUDY_CITATION_LIMIT = 6
_STUDY_REVIEW_RATINGS = {"again", "hard", "got_it"}
_STUDY_INTERVAL_CAP_DAYS = 30.0
_PATH_DEPTHS = {"survey", "college", "graduate"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _slugify(value, fallback="notebook"):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-").lower()
    return slug[:80] or fallback


def _workspace_root():
    root = os.path.realpath(os.path.join(paths.data_dir(), "workspace", "notebooks"))
    os.makedirs(root, exist_ok=True)
    return root


def _notebook_path(notebook_id):
    if not isinstance(notebook_id, str) or not _SAFE_ID.fullmatch(notebook_id):
        raise ValueError("invalid notebook id")
    root = _workspace_root()
    target = os.path.realpath(os.path.join(root, f"{notebook_id}.json"))
    if target != root and not target.startswith(root + os.sep):
        raise ValueError("notebook path escapes workspace")
    return target


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("invalid notebook")
    return data


def _read_notebook_file(notebook_id):
    path = _notebook_path(notebook_id)
    if not os.path.isfile(path):
        raise ValueError("unknown notebook")
    data = _read_json(path)
    if data.get("id") != notebook_id:
        raise ValueError("invalid notebook")
    for key in ("title", "goal", "created_at", "updated_at", "sources", "notes", "learning_path"):
        if key not in data:
            raise ValueError("invalid notebook")
    if not isinstance(data["sources"], list) or not isinstance(data["notes"], list):
        raise ValueError("invalid notebook")
    if "study_sets" not in data:
        data["study_sets"] = []
    if not isinstance(data["study_sets"], list):
        raise ValueError("invalid notebook")
    return data


def _write_notebook(data):
    path = _notebook_path(data["id"])
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".notebook-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _clean_text(value, field, limit, required=True):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > limit:
        raise ValueError(f"{field} is too long")
    return text


def _clean_optional_text(value, field, limit):
    if value is None:
        return ""
    return _clean_text(value, field, limit, required=False)


def _clean_http_url(value, field="url", required=False):
    if required:
        text = _clean_text(value, field, _URL_LIMIT)
    else:
        text = _clean_optional_text(value, field, _URL_LIMIT)
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an http or https URL")
    return text


def _truncate(text, limit):
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _derived_title(url):
    parsed = urllib.parse.urlparse(url)
    leaf = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if leaf:
        leaf = urllib.parse.unquote(leaf)
        return _truncate(leaf, _SOURCE_TITLE_LIMIT)
    return _truncate(parsed.netloc or "Imported source", _SOURCE_TITLE_LIMIT)


def _source_id(notebook):
    return f"source-{len(notebook['sources']) + 1}"


def _note_id(notebook):
    return f"note-{len(notebook['notes']) + 1}"


def _normalize_source_ids(source_ids, notebook):
    if source_ids is None:
        return []
    if not isinstance(source_ids, list):
        raise ValueError("source_ids must be a list")
    valid_ids = {source["id"] for source in notebook["sources"] if isinstance(source, dict)}
    result = []
    for source_id in source_ids:
        if not isinstance(source_id, str) or not _SAFE_ID.fullmatch(source_id):
            raise ValueError("invalid source id")
        if source_id not in valid_ids:
            raise ValueError("unknown source id")
        if source_id not in result:
            result.append(source_id)
    return result


def _default_learning_path(goal, sources, depth="college"):
    if depth not in _PATH_DEPTHS:
        raise ValueError("depth must be one of: survey, college, graduate")
    source_titles = [source["title"] for source in sources if isinstance(source, dict)]
    source_ids = [source["id"] for source in sources if isinstance(source, dict)]
    return {
        "goal": goal,
        "depth": depth,
        "sections": [
            {
                "id": "foundations",
                "title": "Foundations",
                "items": [
                    {
                        "text": goal or "Define the learning target before reading deeply.",
                        "references": [],
                    },
                    {
                        "text": "Identify the core concepts and terms you need to understand first.",
                        "references": [],
                    },
                ],
            },
            {
                "id": "source-synthesis",
                "title": "Source synthesis",
                "items": [
                    {
                        "text": (
                            "Compare the notebook sources: " + ", ".join(source_titles)
                            if source_titles
                            else "Add at least one source and compare the claims across them."
                        ),
                        "references": source_ids,
                    }
                ],
            },
            {
                "id": "application-review",
                "title": "Application / review",
                "items": [
                    {
                        "text": (
                            f"Apply the notebook goal in a small exercise: {goal}."
                            if goal
                            else "Apply the current ideas in a small exercise, then review what remains unclear."
                        ),
                        "references": source_ids,
                    },
                    {
                        "text": "Review what changed in your understanding and note the next question.",
                        "references": [],
                    },
                ],
            },
        ],
        "generated_at": _now(),
    }


def list_notebooks():
    root = _workspace_root()
    result = []
    for filename in sorted(os.listdir(root)):
        if not filename.endswith(".json"):
            continue
        notebook_id = filename[:-5]
        if not _SAFE_ID.fullmatch(notebook_id):
            continue
        try:
            result.append(_read_notebook_file(notebook_id))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    result.sort(key=lambda item: (item.get("updated_at", ""), item.get("id", "")), reverse=True)
    return result


def export_notebooks():
    """Return the local learning data without provider or session secrets."""
    return {
        "version": 1,
        "exported_at": _now(),
        "notebooks": list_notebooks(),
    }


def delete_all_notebooks():
    """Delete notebook JSON files and return the number removed."""
    root = _workspace_root()
    deleted = 0
    for filename in os.listdir(root):
        if not filename.endswith(".json") or not _SAFE_ID.fullmatch(filename[:-5]):
            continue
        path = os.path.join(root, filename)
        if not os.path.isfile(path):
            continue
        os.remove(path)
        deleted += 1
    return deleted


def create_notebook(title, goal=""):
    clean_title = _clean_text(title, "title", _TITLE_LIMIT)
    clean_goal = _clean_optional_text(goal, "goal", _NOTE_BODY_LIMIT)
    notebook_id = _slugify(clean_title)
    path = _notebook_path(notebook_id)
    if os.path.isfile(path):
        return _read_notebook_file(notebook_id)
    now = _now()
    notebook = {
        "id": notebook_id,
        "title": clean_title,
        "goal": clean_goal,
        "created_at": now,
        "updated_at": now,
        "sources": [],
        "notes": [],
        "study_sets": [],
        "learning_path": _default_learning_path(clean_goal, [], "college"),
    }
    _write_notebook(notebook)
    return notebook


def read_notebook(notebook_id):
    return _read_notebook_file(notebook_id)


def add_source(notebook_id, payload):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid source payload")
    title = _clean_text(payload.get("title"), "title", _SOURCE_TITLE_LIMIT)
    excerpt = _clean_text(payload.get("excerpt"), "excerpt", _EXCERPT_LIMIT)
    url = payload.get("url")
    clean_url = _clean_http_url(url, required=False) if url is not None else ""
    kind = payload.get("kind")
    clean_kind = _clean_optional_text(kind, "kind", 64) if kind is not None else ""
    origin = payload.get("origin")
    clean_origin = (
        _clean_optional_text(origin, "origin", _ORIGIN_LIMIT)
        if origin is not None
        else ""
    )
    source_result = payload.get("source_result")
    source = {
        "id": _source_id(notebook),
        "title": title,
        "excerpt": excerpt,
        "created_at": _now(),
    }
    if clean_url:
        source["url"] = clean_url
    if clean_kind:
        source["kind"] = clean_kind
    if clean_origin:
        source["origin"] = clean_origin
    if source_result is not None:
        if not isinstance(source_result, dict):
            raise ValueError("source_result must be an object")
        result = {
            "title": _clean_optional_text(
                source_result.get("title"), "title", _SOURCE_TITLE_LIMIT
            ),
            "url": _clean_http_url(source_result.get("url"), required=False),
            "kind": _clean_optional_text(source_result.get("kind"), "kind", 64),
        }
        source["source_result"] = {
            key: value for key, value in result.items() if value
        }
    notebook["sources"].append(source)
    notebook["updated_at"] = _now()
    _write_notebook(notebook)
    return source


def _normalized_page_citations(source_id, pages):
    citations = []
    for raw in pages[:_IMPORT_PAGE_LIMIT]:
        if not isinstance(raw, dict):
            continue
        page = raw.get("page")
        text = raw.get("text")
        if not isinstance(page, int) or page < 1 or not isinstance(text, str):
            continue
        clipped = _truncate(text, _IMPORT_CITATION_TEXT_LIMIT)
        if not clipped:
            continue
        citations.append(
            {
                "id": f"{source_id}-p{page}",
                "label": f"p. {page}",
                "page": page,
                "text": clipped,
            }
        )
    return citations


def _document_citation(source_id, text):
    clipped = _truncate(text, _IMPORT_CITATION_TEXT_LIMIT)
    if not clipped:
        raise ValueError("imported source did not include readable text")
    return {
        "id": f"{source_id}-doc",
        "label": "document",
        "text": clipped,
    }


def _import_excerpt(citations, fallback_text):
    parts = []
    for citation in citations[:3]:
        label = citation.get("label")
        text = citation.get("text")
        if not text:
            continue
        prefix = f"{label}: " if label and label != "document" else ""
        parts.append(prefix + text)
    if not parts:
        parts.append(_truncate(fallback_text, _EXCERPT_LIMIT))
    return _truncate("\n\n".join(part for part in parts if part), _EXCERPT_LIMIT)


def import_source(notebook_id, payload, fetched):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid source payload")
    if not isinstance(fetched, dict):
        raise ValueError("invalid imported source")
    url = _clean_http_url(payload.get("url"), required=True)
    title = _clean_optional_text(payload.get("title"), "title", _SOURCE_TITLE_LIMIT)
    kind = _clean_optional_text(payload.get("kind"), "kind", 64)
    content_type = _clean_optional_text(
        fetched.get("content_type"),
        "content_type",
        160,
    )
    engine = _clean_optional_text(fetched.get("engine"), "engine", 64)
    fetched_url = _clean_http_url(fetched.get("url") or url, required=True)
    text = fetched.get("text")
    if not isinstance(text, str):
        raise ValueError("imported source did not include readable text")

    source_id = _source_id(notebook)
    pages = fetched.get("pages")
    citations = []
    if isinstance(pages, list):
        citations = _normalized_page_citations(source_id, pages)
    if not citations:
        citations = [_document_citation(source_id, text)]

    source = {
        "id": source_id,
        "title": title or _derived_title(fetched_url),
        "url": fetched_url,
        "kind": kind or ("paper" if content_type.startswith("application/pdf") else "import"),
        "excerpt": _import_excerpt(citations, text),
        "origin": "import",
        "content_type": content_type or "text/plain",
        "engine": engine or "import",
        "citations": citations,
        "created_at": _now(),
    }
    notebook["sources"].append(source)
    notebook["updated_at"] = _now()
    _write_notebook(notebook)
    return source


def add_note(notebook_id, payload):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid note payload")
    title = _clean_text(payload.get("title"), "title", _NOTE_TITLE_LIMIT)
    body = _clean_text(payload.get("body"), "body", _NOTE_BODY_LIMIT)
    source_ids = _normalize_source_ids(payload.get("source_ids"), notebook)
    note = {
        "id": _note_id(notebook),
        "title": title,
        "body": body,
        "source_ids": source_ids,
        "created_at": _now(),
    }
    notebook["notes"].insert(0, note)
    notebook["updated_at"] = _now()
    _write_notebook(notebook)
    return note


def generate_learning_path(notebook_id, payload):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid learning path payload")
    goal = payload.get("goal")
    if goal is None:
        clean_goal = notebook.get("goal", "")
    else:
        clean_goal = _clean_text(goal, "goal", _NOTE_BODY_LIMIT, required=False)
        if not clean_goal:
            clean_goal = notebook.get("goal", "")
    depth = payload.get("depth")
    if depth is None:
        depth = notebook.get("learning_path", {}).get("depth", "college")
    if depth not in _PATH_DEPTHS:
        raise ValueError("depth must be one of: survey, college, graduate")
    notebook["learning_path"] = _default_learning_path(clean_goal, notebook["sources"], depth)
    notebook["updated_at"] = _now()
    _write_notebook(notebook)
    return notebook["learning_path"]


def build_tutor_context(notebook_or_id):
    notebook = (
        _read_notebook_file(notebook_or_id)
        if isinstance(notebook_or_id, str)
        else notebook_or_id
    )
    if not isinstance(notebook, dict):
        raise ValueError("invalid notebook")
    chunks = [
        f"Notebook: {notebook.get('title', '')}",
        f"Learning goal: {notebook.get('goal') or 'not specified'}",
    ]
    for index, source in enumerate(notebook.get("sources") or (), start=1):
        if not isinstance(source, dict):
            continue
        parts = [f"Source {index}: {source.get('title', 'Untitled source')}"]
        if source.get("kind"):
            parts.append(f"Kind: {source['kind']}")
        if source.get("url"):
            parts.append(f"URL: {source['url']}")
        excerpt = _truncate(source.get("excerpt"), _EXCERPT_LIMIT)
        if excerpt:
            parts.append(f"Excerpt:\n{excerpt}")
        citation_lines = []
        source_citations = source.get("citations") or [{
            "id": f"{source.get('id', 'source')}-doc",
            "label": "document",
            "text": excerpt or "Source-level evidence.",
        }]
        for citation in source_citations[:_TUTOR_CONTEXT_CITATIONS_PER_SOURCE]:
            if not isinstance(citation, dict):
                continue
            label = _truncate(citation.get("label"), 40) or "document"
            citation_id = _truncate(citation.get("id"), 100) or "source"
            text = _truncate(citation.get("text"), 600)
            if text:
                citation_lines.append(f"{label} [{citation_id}]: {text}")
        if citation_lines:
            parts.append("Citations:\n" + "\n".join(citation_lines))
        chunks.append("\n".join(parts))
    for index, note in enumerate(notebook.get("notes") or (), start=1):
        if not isinstance(note, dict):
            continue
        title = _truncate(note.get("title"), _NOTE_TITLE_LIMIT)
        body = _truncate(note.get("body"), 1200)
        if title or body:
            chunks.append(f"Note {index}: {title}\n{body}".strip())
    return "\n\n".join(chunks)[:_TUTOR_CONTEXT_LIMIT]


def tutor_citations(notebook_or_id):
    """Return bounded citation metadata for the Notebook tutor UI."""
    notebook = (
        _read_notebook_file(notebook_or_id)
        if isinstance(notebook_or_id, str)
        else notebook_or_id
    )
    if not isinstance(notebook, dict):
        raise ValueError("invalid notebook")
    citations = []
    for source in notebook.get("sources") or ():
        if not isinstance(source, dict):
            continue
        source_id = _truncate(source.get("id"), 80)
        title = _truncate(source.get("title"), _SOURCE_TITLE_LIMIT) or "Untitled source"
        url = _truncate(source.get("url"), _URL_LIMIT)
        source_citations = source.get("citations") or [{
            "id": f"{source_id}-doc",
            "label": "document",
        }]
        for citation in source_citations[:_TUTOR_CONTEXT_CITATIONS_PER_SOURCE]:
            if not isinstance(citation, dict):
                continue
            item = {
                "source_id": source_id,
                "citation_id": _truncate(citation.get("id"), 100),
                "label": _truncate(citation.get("label"), 40) or "document",
                "title": title,
            }
            if url:
                item["url"] = url
            if isinstance(citation.get("page"), int):
                item["page"] = citation["page"]
            citations.append(item)
            if len(citations) >= 40:
                return citations
    return citations


def normalize_study_set(value, mode, count, notebook_or_id):
    """Validate and bound provider-generated flashcards or quiz items."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("provider returned invalid study set JSON") from exc
    if not isinstance(value, dict) or value.get("mode") != mode:
        raise ValueError("provider returned an invalid study set")
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("study set items must be a list")
    valid_citations = {
        item["citation_id"] for item in tutor_citations(notebook_or_id)
        if item.get("citation_id")
    }
    normalized = []
    for raw in items[: min(count, _STUDY_ITEM_LIMIT)]:
        if not isinstance(raw, dict):
            continue
        if mode == "flashcards":
            front = _truncate(raw.get("front"), _STUDY_TEXT_LIMIT)
            back = _truncate(raw.get("back"), _STUDY_TEXT_LIMIT)
            if not front or not back:
                continue
            item = {"front": front, "back": back}
        else:
            question = _truncate(raw.get("question"), _STUDY_TEXT_LIMIT)
            answer = _truncate(raw.get("answer"), _STUDY_TEXT_LIMIT)
            if not question or not answer:
                continue
            item = {"question": question, "answer": answer}
        citation_ids = raw.get("citation_ids") or []
        if not isinstance(citation_ids, list):
            citation_ids = []
        item["citation_ids"] = [
            citation_id for citation_id in citation_ids[:_STUDY_CITATION_LIMIT]
            if isinstance(citation_id, str) and citation_id in valid_citations
        ]
        normalized.append(item)
    if not normalized:
        raise ValueError("provider returned no usable study items")
    return {"mode": mode, "items": normalized}


def _study_set_id(notebook):
    return f"study-set-{len(notebook.get('study_sets', [])) + 1}"


def _parse_study_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _study_item_is_due(item, now=None):
    due_at = _parse_study_time(item.get("due_at"))
    if due_at is None:
        return True
    current = now or datetime.now(timezone.utc)
    return due_at <= current


def save_study_set(notebook_id, normalized):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(normalized, dict) or normalized.get("mode") not in {"flashcards", "quiz"}:
        raise ValueError("invalid study set")
    items = normalized.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("study set items must be a list")
    now = _now()
    study_set = {
        "id": _study_set_id(notebook),
        "mode": normalized["mode"],
        "created_at": now,
        "updated_at": now,
        "items": [],
    }
    for index, raw in enumerate(items[:_STUDY_ITEM_LIMIT], start=1):
        item = {
            "id": f"card-{index}",
            "citation_ids": list(raw.get("citation_ids") or [])[:_STUDY_CITATION_LIMIT],
            "status": "learning",
            "repetitions": 0,
            "interval_days": 0,
            "due_at": now,
            "last_reviewed_at": None,
        }
        if study_set["mode"] == "flashcards":
            item["front"] = _truncate(raw.get("front"), _STUDY_TEXT_LIMIT)
            item["back"] = _truncate(raw.get("back"), _STUDY_TEXT_LIMIT)
        else:
            item["question"] = _truncate(raw.get("question"), _STUDY_TEXT_LIMIT)
            item["answer"] = _truncate(raw.get("answer"), _STUDY_TEXT_LIMIT)
        study_set["items"].append(item)
    if not study_set["items"]:
        raise ValueError("study set items must be a list")
    notebook.setdefault("study_sets", []).append(study_set)
    notebook["updated_at"] = now
    _write_notebook(notebook)
    return study_set


def review_due_count(notebook_or_id, now=None):
    notebook = (
        _read_notebook_file(notebook_or_id)
        if isinstance(notebook_or_id, str)
        else notebook_or_id
    )
    if not isinstance(notebook, dict):
        raise ValueError("invalid notebook")
    current = now or datetime.now(timezone.utc)
    return sum(
        1
        for study_set in notebook.get("study_sets", [])
        if isinstance(study_set, dict)
        for item in study_set.get("items", [])
        if isinstance(item, dict) and _study_item_is_due(item, current)
    )


def review_study_item(notebook_id, payload):
    notebook = _read_notebook_file(notebook_id)
    if not isinstance(payload, dict):
        raise ValueError("invalid review payload")
    study_set_id = _clean_text(payload.get("study_set_id"), "study_set_id", 128)
    item_id = _clean_text(payload.get("item_id"), "item_id", 128)
    rating = _clean_text(payload.get("rating"), "rating", 16)
    if rating not in _STUDY_REVIEW_RATINGS:
        raise ValueError("rating must be one of: again, hard, got_it")
    study_set = next(
        (item for item in notebook.get("study_sets", [])
         if isinstance(item, dict) and item.get("id") == study_set_id),
        None,
    )
    if study_set is None:
        raise ValueError("unknown study set")
    item = next(
        (candidate for candidate in study_set.get("items", [])
         if isinstance(candidate, dict) and candidate.get("id") == item_id),
        None,
    )
    if item is None:
        raise ValueError("unknown study item")
    previous_interval = float(item.get("interval_days") or 0)
    repetitions = int(item.get("repetitions") or 0)
    if rating == "again":
        interval_days = 1.0 / 24.0
        item["status"] = "learning"
        item["repetitions"] = 0
    elif rating == "hard":
        interval_days = min(
            _STUDY_INTERVAL_CAP_DAYS,
            max(1.0, previous_interval * 1.5 if previous_interval else 1.0),
        )
        item["status"] = "review"
        item["repetitions"] = repetitions
    else:
        interval_days = min(
            _STUDY_INTERVAL_CAP_DAYS,
            max(1.0, previous_interval * 2.5 if previous_interval else 1.0),
        )
        item["status"] = "review"
        item["repetitions"] = repetitions + 1
    reviewed_at = datetime.now(timezone.utc)
    item["interval_days"] = interval_days
    item["last_reviewed_at"] = reviewed_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    item["due_at"] = (reviewed_at + timedelta(days=interval_days)).isoformat(timespec="seconds").replace("+00:00", "Z")
    study_set["updated_at"] = item["last_reviewed_at"]
    notebook["updated_at"] = item["last_reviewed_at"]
    _write_notebook(notebook)
    return {
        "study_set": study_set,
        "review_due_count": review_due_count(notebook, reviewed_at),
    }
