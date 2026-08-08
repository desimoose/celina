"""Small, file-backed project store for durable local outputs."""

from datetime import datetime, timezone
import json
import os
import re
import uuid

import paths
import storage


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_FORMATS = {
    "markdown": {"extension": "md", "label": "Markdown"},
    "text": {"extension": "txt", "label": "Plain text"},
    "html": {"extension": "html", "label": "HTML"},
    "json": {"extension": "json", "label": "JSON"},
}


def formats():
    return [
        {"id": key, "label": value["label"], "extension": value["extension"]}
        for key, value in _FORMATS.items()
    ]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _slugify(value):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-").lower()
    return slug[:60] or "project"


def _project_dir(project_id):
    if not isinstance(project_id, str) or not _SAFE_ID.fullmatch(project_id):
        raise ValueError("invalid project id")
    root = paths.projects_dir()
    try:
        return storage.safe_child(root, project_id)
    except ValueError:
        raise ValueError("project path escapes projects root") from None


def _read_meta(directory):
    path = os.path.join(directory, "project.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None
    return data


def list_projects():
    root = paths.projects_dir()
    result = []
    for name in sorted(os.listdir(root)):
        if not _SAFE_ID.fullmatch(name):
            continue
        directory = _project_dir(name)
        if not os.path.isdir(directory):
            continue
        meta = _read_meta(directory)
        if not meta:
            continue
        outputs_dir = os.path.join(directory, "outputs")
        outputs = []
        if os.path.isdir(outputs_dir):
            for filename in sorted(os.listdir(outputs_dir), reverse=True):
                full = os.path.join(outputs_dir, filename)
                if not os.path.isfile(full) or filename.startswith("."):
                    continue
                extension = os.path.splitext(filename)[1].lstrip(".")
                format_id = next(
                    (key for key, value in _FORMATS.items() if value["extension"] == extension),
                    "text",
                )
                outputs.append({
                    "name": filename,
                    "path": filename,
                    "format": format_id,
                    "format_label": _FORMATS[format_id]["label"],
                    "size": os.path.getsize(full),
                })
        result.append({**meta, "outputs": outputs})
    return result


def create_project(name):
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("project name is required")
    if len(clean_name) > 120:
        raise ValueError("project name is too long")
    root = os.path.realpath(paths.projects_dir())
    with storage.locked(root):
        base = _slugify(clean_name)
        project_id = base
        while os.path.exists(_project_dir(project_id)):
            project_id = f"{base}-{uuid.uuid4().hex[:6]}"
        directory = _project_dir(project_id)
        os.makedirs(os.path.join(directory, "outputs"), exist_ok=False)
        meta = {"id": project_id, "name": clean_name, "created_at": _now()}
        storage.atomic_write_json(os.path.join(directory, "project.json"), meta)
        return {**meta, "outputs": []}


def save_output(project_id, title, format_id, content):
    if format_id not in _FORMATS:
        raise ValueError("unsupported output format")
    if not isinstance(content, str):
        raise ValueError("output content must be text")
    if len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("output content is too large")
    directory = _project_dir(project_id)
    meta = _read_meta(directory)
    if not meta:
        raise ValueError("unknown project")
    try:
        outputs_dir = storage.safe_child(directory, "outputs")
    except ValueError:
        raise ValueError("output path escapes project") from None
    with storage.locked(outputs_dir):
        os.makedirs(outputs_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{stamp}-{_slugify(title)}.{_FORMATS[format_id]['extension']}"
        target = os.path.realpath(os.path.join(outputs_dir, filename))
        if not target.startswith(os.path.realpath(outputs_dir) + os.sep):
            raise ValueError("output path escapes project")
        suffix = 2
        while os.path.exists(target):
            filename = f"{stamp}-{_slugify(title)}-{suffix}.{_FORMATS[format_id]['extension']}"
            target = os.path.join(outputs_dir, filename)
            suffix += 1
        storage.atomic_write_text(target, content)
        return {"project_id": project_id, "name": filename, "format": format_id, "size": len(content.encode("utf-8"))}


def read_output(project_id, filename):
    directory = _project_dir(project_id)
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        raise ValueError("invalid output name")
    target = os.path.realpath(os.path.join(directory, "outputs", filename))
    outputs_root = os.path.realpath(os.path.join(directory, "outputs"))
    if not target.startswith(outputs_root + os.sep) or not os.path.isfile(target):
        raise ValueError("output not found")
    with open(target, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()
