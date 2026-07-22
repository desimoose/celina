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

ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT = 300


class GatewayError(Exception):
    pass


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


def _post(url, payload, headers):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:600]
        raise GatewayError(f"{e.code} from provider: {detail}") from e
    except urllib.error.URLError as e:
        raise GatewayError(f"could not reach provider: {e.reason}") from e


def _anthropic(spec, model, system, messages, max_tokens):
    key = os.environ.get(spec["key_env"], "").strip()
    if not key:
        raise GatewayError("ANTHROPIC_API_KEY is not set in .env")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system
    data = _post(spec["url"], payload, {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
    })
    # content is a list of blocks; keep only the text ones
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    usage = data.get("usage", {})
    return text, {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }


def _openai_compatible(spec, model, system, messages, max_tokens):
    headers = {"content-type": "application/json"}
    if spec["key_env"]:
        key = os.environ.get(spec["key_env"], "").strip()
        if not key:
            raise GatewayError(f"{spec['key_env']} is not set in .env")
        headers["authorization"] = f"Bearer {key}"

    full = ([{"role": "system", "content": system}] if system else []) + messages
    payload = {"model": model, "messages": full, "max_tokens": max_tokens}
    data = _post(spec["url"], payload, headers)

    choices = data.get("choices") or []
    if not choices:
        raise GatewayError(f"provider returned no choices: {json.dumps(data)[:400]}")
    text = choices[0].get("message", {}).get("content") or ""
    usage = data.get("usage", {})
    return text, {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }


def chat(provider, messages, system=None, model=None, max_tokens=4096):
    """Send a conversation to any backend and get back plain text."""
    if provider not in PROVIDERS:
        raise GatewayError(f"unknown provider '{provider}'")
    spec = PROVIDERS[provider]
    model = model or model_for(provider)

    if spec["shape"] == "anthropic":
        text, usage = _anthropic(spec, model, system, messages, max_tokens)
    else:
        text, usage = _openai_compatible(spec, model, system, messages, max_tokens)

    return {"text": text, "provider": provider, "model": model, "usage": usage}
