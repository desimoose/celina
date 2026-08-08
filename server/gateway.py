"""Provider-agnostic LLM gateway.

Five backends behind one call. No SDKs, no dependencies - stdlib urllib only,
so the app runs with nothing installed. BYOK is the default: keys come from
.env and never leave this machine.

Anthropic uses the Messages API shape; OpenAI, OpenRouter, xAI and Ollama all
speak an OpenAI-compatible /chat/completions shape, so they share one adapter.
"""

import json
import os
import urllib.error
import urllib.request

import redaction
import traffic

ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT = 60
MAX_ERROR_SUMMARY_CHARS = 160


class GatewayError(Exception):
    def __init__(self, message, *, provider=None, status=None, kind=None):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.kind = kind


# Each provider: how to reach it, how to authenticate, which model to default to.
# Defaults are starting points - override any of them in .env.
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
        "model_env": "ANTHROPIC_MODEL",
        "default_model": "claude-opus-4-8",
        "shape": "anthropic",
    },
    "openai": {
        "label": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o",
        "shape": "openai",
    },
    "openrouter": {
        "label": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "shape": "openai",
    },
    "xai": {
        "label": "xAI Grok",
        "url": "https://api.x.ai/v1/chat/completions",
        "key_env": "XAI_API_KEY",
        "model_env": "XAI_MODEL",
        "default_model": "grok-4",
        "shape": "openai",
    },
    "ollama": {
        "label": "Ollama (local)",
        "url": "http://localhost:11434/v1/chat/completions",
        "key_env": None,  # local inference needs no key
        "model_env": "OLLAMA_MODEL",
        "default_model": "llama3.1:8b",
        "shape": "openai",
    },
}


def model_for(provider):
    spec = PROVIDERS[provider]
    return os.environ.get(spec["model_env"], "").strip() or spec["default_model"]


def key_for(provider):
    spec = PROVIDERS[provider]
    if not spec["key_env"]:
        return None
    return os.environ.get(spec["key_env"], "").strip() or None


def key_hint(provider):
    """Last 4 chars of the key, or None if absent / too short to mask safely."""
    key = key_for(provider)
    if not key or len(key) < 8:
        return None
    return key[-4:]


def settings_state():
    """Per-provider config for the settings UI. Never includes full keys."""
    out = []
    for name, spec in PROVIDERS.items():
        out.append({
            "id": name,
            "label": spec["label"],
            "local": spec["key_env"] is None,
            "key_env": spec["key_env"],
            "model_env": spec["model_env"],
            "has_key": bool(key_for(name)),
            "key_hint": key_hint(name),
            "model": model_for(name),
            "default_model": spec["default_model"],
            "model_overridden": bool(
                os.environ.get(spec["model_env"], "").strip()
            ),
        })
    return out


def available():
    """Which providers are usable right now. Ollama is local, so it is always
    offered - we cannot know if the daemon is up without paying for a probe."""
    out = []
    for name, spec in PROVIDERS.items():
        ready = spec["key_env"] is None or bool(key_for(name))
        out.append({
            "id": name,
            "label": spec["label"],
            "model": model_for(name),
            "ready": ready,
            "local": spec["key_env"] is None,
        })
    return out


def _provider_name(provider):
    return provider if provider in PROVIDERS else "provider"


def _bounded_summary(value):
    single_line = " ".join(str(value or "").split())
    return single_line[:MAX_ERROR_SUMMARY_CHARS] or "provider request failed"


def _configured_secrets():
    return tuple(
        key_for(name)
        for name in PROVIDERS
        if key_for(name)
    )


def safe_error_summary(error, provider=None):
    """Return a bounded public error without upstream response or URL text."""
    known_provider = _provider_name(
        provider or getattr(error, "provider", None)
    )
    status = getattr(error, "status", None)
    kind = getattr(error, "kind", None)
    if kind == "timeout" or isinstance(error, TimeoutError):
        summary = f"{known_provider} request timed out"
    elif isinstance(status, int):
        summary = f"{known_provider} returned HTTP {status}"
    elif kind == "not_configured":
        summary = f"{known_provider} is not configured"
    elif kind == "invalid_response":
        summary = f"{known_provider} returned an invalid response"
    elif kind == "unknown_provider":
        summary = "unknown provider"
    else:
        summary = f"{known_provider} request failed"
    safe = redaction.Redactor(_configured_secrets()).redact_text(summary)[0]
    return _bounded_summary(safe)


def _failure(provider, *, kind=None, status=None):
    error = GatewayError(
        "provider request failed",
        provider=provider,
        status=status,
        kind=kind,
    )
    error.args = (safe_error_summary(error, provider=provider),)
    return error


def _post(url, payload, headers, traffic_context=None, provider=None):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        if traffic_context is not None:
            return traffic.provider_request(
                traffic_context,
                provider or "provider",
                req,
                timeout=TIMEOUT,
                action_type="provider.chat",
            )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except traffic.TrafficCancelled:
        raise
    except urllib.error.HTTPError as e:
        e.close()
        raise _failure(provider, status=e.code) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise _failure(provider, kind="timeout") from e
        raise _failure(provider) from e
    except TimeoutError as e:
        raise _failure(provider, kind="timeout") from e
    except (UnicodeDecodeError, json.JSONDecodeError, traffic.MalformedResponseError) as e:
        raise _failure(provider, kind="invalid_response") from e


def _anthropic(
    spec,
    model,
    system,
    messages,
    max_tokens,
    traffic_context=None,
):
    key = os.environ.get(spec["key_env"], "").strip()
    if not key:
        raise _failure("anthropic", kind="not_configured")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    data = _post(
        spec["url"],
        payload,
        {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        traffic_context,
        "anthropic",
    )
    # content is a list of blocks; keep only the text ones
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    usage = data.get("usage", {})
    return text, {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": (
            (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            if (
                usage.get("cache_read_input_tokens") is not None
                or usage.get("cache_creation_input_tokens") is not None
            )
            else None
        ),
    }


def _openai_compatible(
    provider,
    spec,
    model,
    system,
    messages,
    max_tokens,
    traffic_context=None,
):
    headers = {"content-type": "application/json"}
    if spec["key_env"]:
        key = os.environ.get(spec["key_env"], "").strip()
        if not key:
            raise _failure(provider, kind="not_configured")
        headers["authorization"] = f"Bearer {key}"

    full = ([{"role": "system", "content": system}] if system else []) + messages
    payload = {"model": model, "messages": full, "max_tokens": max_tokens}
    data = _post(
        spec["url"],
        payload,
        headers,
        traffic_context,
        provider,
    )

    choices = data.get("choices") or []
    if not choices:
        raise _failure(provider, kind="invalid_response")
    text = choices[0].get("message", {}).get("content") or ""
    usage = data.get("usage", {})
    return text, {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "cached_input_tokens": (
            usage.get("prompt_tokens_details") or {}
        ).get("cached_tokens"),
    }


def chat(
    provider,
    messages,
    system=None,
    model=None,
    max_tokens=4096,
    traffic_context=None,
):
    """Send a conversation to any backend and get back plain text."""
    if provider not in PROVIDERS:
        raise _failure(provider, kind="unknown_provider")
    spec = PROVIDERS[provider]
    model = model or model_for(provider)

    if spec["shape"] == "anthropic":
        text, usage = _anthropic(
            spec,
            model,
            system,
            messages,
            max_tokens,
            traffic_context,
        )
    else:
        text, usage = _openai_compatible(
            provider,
            spec,
            model,
            system,
            messages,
            max_tokens,
            traffic_context,
        )

    return {"text": text, "provider": provider, "model": model, "usage": usage}
