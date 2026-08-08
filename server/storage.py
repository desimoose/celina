"""Small process-local primitives for safe file-backed state changes."""

from contextlib import contextmanager
import json
import os
import tempfile
import threading


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def safe_child(root, relative_or_name):
    """Resolve a child path without crossing the supplied filesystem boundary."""
    root_path = os.fsdecode(os.fspath(root))
    relative = os.fsdecode(os.fspath(relative_or_name))
    drive, _tail = os.path.splitdrive(relative)
    if not relative or drive or os.path.isabs(relative):
        raise ValueError("unsafe child path")

    component_path = relative
    if os.path.altsep:
        component_path = component_path.replace(os.path.altsep, os.path.sep)
    components = component_path.split(os.path.sep)
    if any(component == os.pardir for component in components):
        raise ValueError("unsafe child path")

    root_real = os.path.realpath(root_path)
    candidate = os.path.join(root_path, relative)
    candidate_real = os.path.realpath(candidate)
    try:
        contained = os.path.commonpath((root_real, candidate_real)) == root_real
    except ValueError:
        contained = False
    if not contained or candidate_real == root_real:
        raise ValueError("unsafe child path")

    current = os.path.abspath(root_path)
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    for component in components:
        if component in ("", os.curdir):
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and (
            os.path.islink(current) or is_junction(current)
        ):
            raise ValueError("unsafe child path")
    return candidate_real


def _lock_for(path):
    key = os.path.realpath(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def locked(path):
    """Serialize read-modify-write operations for one local path."""
    lock = _lock_for(path)
    with lock:
        yield


def atomic_write_bytes(path, content, replace_func=os.replace):
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    directory = os.path.dirname(os.path.realpath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".celina-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        replace_func(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass


def atomic_write_text(path, content, encoding="utf-8"):
    if not isinstance(content, str):
        raise TypeError("content must be text")
    atomic_write_bytes(path, content.encode(encoding))


def atomic_write_json(path, value):
    atomic_write_text(
        path,
        json.dumps(value, indent=2) + "\n",
    )
