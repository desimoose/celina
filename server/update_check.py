"""Local application version status.

Celina does not perform automatic or anonymous update checks. This module
intentionally reports only bundled local metadata and makes no network calls.
"""

import paths


def check():
    """Return local version status without contacting a remote service."""
    return {
        "current": paths.APP_VERSION,
        "status": "local-only",
        "remote_check": False,
    }
