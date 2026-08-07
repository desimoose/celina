"""Resumable server-sent event framing for Celina's local search trace."""

import json


HEARTBEAT_INTERVAL = 15

_TERMINAL_KINDS = {"search.completed", "search.stopped", "search.failed"}


def format_event(event):
    """Encode one persisted Event as an SSE frame; sequence becomes the SSE id."""
    data = json.dumps(event.to_dict(), separators=(",", ":"))
    return ("id: %s\nevent: trace\ndata: %s\n\n" % (event.sequence, data)).encode(
        "utf-8"
    )


def format_heartbeat():
    return b": heartbeat\n\n"


def is_terminal(event):
    return event.kind in _TERMINAL_KINDS


def last_event_id(headers):
    """Parse Last-Event-ID for resume; missing/invalid means start from zero."""
    raw = headers.get("Last-Event-ID")
    if raw is None:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value >= 0 else 0
