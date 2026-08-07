"""Anonymous, best-effort check against GitHub Releases for a newer version.

No account, no telemetry - one unauthenticated GET to the public Releases
API, nothing that identifies this install. House-cat rule: a failed check
(offline, GitHub unreachable, rate-limited) must never look like a broken
app - it just quietly doesn't mention an update this launch.
"""

import json
import urllib.error
import urllib.request

import paths

_TIMEOUT = 4


def _parse_version(tag):
    if not isinstance(tag, str):
        return None
    tag = tag.strip()
    return tag[1:] if tag[:1] in ("v", "V") else tag or None


def _version_parts(value):
    parts = value.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        raise ValueError("not a dotted version")
    return [int(part) for part in parts]


def _is_newer(current, latest):
    try:
        return _version_parts(latest) > _version_parts(current)
    except ValueError:
        return latest != current  # best-effort fallback for non-dotted tags


def check():
    """Return {current, latest, update_available, url}. Never raises."""
    current = paths.APP_VERSION
    releases_url = f"https://github.com/{paths.GITHUB_REPO}/releases/latest"
    latest = None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{paths.GITHUB_REPO}/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{paths.APP_NAME}/{current}",
            },
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = _parse_version(data.get("tag_name"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        latest = None
    return {
        "current": current,
        "latest": latest,
        "update_available": bool(latest) and _is_newer(current, latest),
        "url": releases_url,
    }
