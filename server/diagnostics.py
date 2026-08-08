"""Safe, local-only health summaries.

This module deliberately reports configuration state rather than probing it.
Health checks never contact providers, fetch URLs, inspect prompts or source
content, or read traffic, event, or usage records.
"""

import ipaddress

import gateway
import paths
import search_runtime
import tools


_SAFE_LIMIT_KEYS = {
    "request_body_bytes",
    "workspace_content_bytes",
}


def _is_loopback_host(host):
    value = str(host or "").strip().strip("[]")
    if "%" in value:
        value = value.split("%", 1)[0]
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value.lower() == "localhost"


def is_loopback(server, client_address=None):
    """Return whether both the bound server and optional caller are loopback."""
    address = getattr(server, "server_address", ())
    if not address or not _is_loopback_host(address[0]):
        return False
    if client_address is None:
        return True
    return bool(client_address) and _is_loopback_host(client_address[0])


def _provider_summary():
    return [
        {
            "id": str(item.get("id") or "unknown")[:64],
            "status": "ready" if item.get("ready") else "not_configured",
            "local": bool(item.get("local")),
        }
        for item in gateway.available()
        if isinstance(item, dict)
    ]


def _tool_summary():
    return [
        {
            "id": str(item.get("id") or "unknown")[:64],
            "status": "available" if item.get("present") else "unavailable",
        }
        for item in tools.status()
        if isinstance(item, dict)
    ]


def _limits(server):
    value = {
        "provider_timeout_seconds": int(gateway.TIMEOUT),
        "search_selected_results": int(search_runtime.MAX_SELECTED_SOURCES),
        "search_context_chars_per_result": int(
            search_runtime._MAX_EVIDENCE_CHARS_PER_SOURCE
        ),
    }
    configured = getattr(server, "diagnostic_limits", {})
    if isinstance(configured, dict):
        for key in _SAFE_LIMIT_KEYS:
            item = configured.get(key)
            if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                value[key] = item
    return value


def health(server):
    """Return a bounded aggregate with no secret-bearing or activity data."""
    recovery_required = bool(
        getattr(server, "recovery_required_session_ids", ())
    )
    storage_status = "recovery_required" if recovery_required else "ready"
    providers = _provider_summary()
    tools_summary = _tool_summary()
    status = "degraded" if recovery_required else "ok"
    return {
        "status": status,
        "version": paths.APP_VERSION,
        "storage": {
            "status": storage_status,
            "recovery_required": recovery_required,
        },
        "providers": providers,
        "tools": tools_summary,
        "limits": _limits(server),
    }
