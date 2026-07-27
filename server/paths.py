"""Where things live - the one module that knows.

Splits read-only bundled assets (the web UI) from writable user data
(workspace, .env, vendor). Frozen-aware so the same code works whether we run
from source in dev or from a PyInstaller onefile exe.

In dev the writable base is the repo root, so `python server/app.py` behaves
exactly as before. Only the frozen exe writes to Documents\\Celina.
Set CELINA_HOME to override the writable base (used by tests and power
users).
"""

import os
import re
import sys

APP_NAME = "Celina"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def _repo_root():
    # server/paths.py -> server -> repo root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel=""):
    """Read-only bundled asset base. The web/ tree lives under here."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = _repo_root()
    return os.path.join(base, rel) if rel else base


def data_dir():
    """Writable user-data base. Created on demand."""
    override = os.environ.get("CELINA_HOME")
    if override:
        base = override
    elif is_frozen():
        base = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME)
    else:
        base = _repo_root()
    os.makedirs(base, exist_ok=True)
    return base


def web_dir():
    return resource_path("web")


def workspace_dir():
    d = os.path.join(data_dir(), "workspace")
    os.makedirs(d, exist_ok=True)
    return d


def sessions_dir():
    d = os.path.join(data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return d


_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def session_dir(session_id):
    """Return one writable session directory without allowing traversal."""
    if not isinstance(session_id, str) or not _SAFE_COMPONENT.fullmatch(
        session_id
    ):
        raise ValueError("invalid session id")
    d = os.path.join(sessions_dir(), session_id)
    os.makedirs(d, exist_ok=True)
    return d


def vendor_dir():
    return os.path.join(data_dir(), "vendor")


def env_file():
    return os.path.join(data_dir(), ".env")
