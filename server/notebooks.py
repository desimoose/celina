"""File-backed research notebooks stored under the local data directory."""

from datetime import datetime, timezone
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
    clean_url = _clean_optional_text(url, "url", _URL_LIMIT) if url is not None else ""
    if clean_url:
        parsed_url = urllib.parse.urlparse(clean_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("url must be an http or https URL")
    kind = payload.get("kind")
    clean_kind = _clean_optional_text(kind, "kind", 64) if kind is not None else ""
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
