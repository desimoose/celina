"""Small process-local primitives for safe file-backed state changes."""

from contextlib import contextmanager
import json
import os
import tempfile
import threading


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


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


def atomic_write_bytes(path, content):
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
        os.replace(temporary, path)
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
