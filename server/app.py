"""Celina - local server.

Stdlib only. Serves the web UI and a small JSON API:

  GET  /api/config           providers + tool availability
  POST /api/chat             talk to any provider through the gateway
  POST /api/fetch            fetch a page (via Obscura when present)
  GET  /api/workspace        list notebook artifacts
  GET  /api/workspace/file   read one artifact
  POST /api/workspace/save   write an artifact

Run:  python server/app.py     then open http://localhost:8765
"""

import json
import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finder  # noqa: E402
import gateway  # noqa: E402
import paths  # noqa: E402
import scanner  # noqa: E402
import tools  # noqa: E402

mimetypes.add_type("font/woff2", ".woff2")  # bundled local fonts

SYSTEM_PROMPT = (
    "You are Celina: a private research assistant. "
    "You help investigate topics using the notebook's collected sources. "
    "Cite what you were given; say plainly when you do not know something "
    "rather than guessing. Be concise and lead with the finding."
)


_ENV_TEMPLATE = """\
# Fill in whichever keys you have. This file stays on this machine - the app
# never sends keys anywhere except to the provider you select.
# You need ZERO keys to start if you run Ollama locally.

# --- Anthropic ---
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-4-8

# --- OpenAI ---
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o

# --- OpenRouter (one key, many open-weight models) ---
OPENROUTER_API_KEY=
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct

# --- xAI / Grok ---
XAI_API_KEY=
XAI_MODEL=grok-4

# --- Ollama (local, no key needed; requires Ollama running) ---
OLLAMA_MODEL=llama3.1:8b

# --- Finder ---
# Optional contact email. Unlocks Unpaywall and OpenAlex's faster polite pool.
FINDER_CONTACT_EMAIL=

# --- app ---
CELINA_PORT=8765
"""


def seed_env(path):
    """Write a starter .env if none exists. Never overwrites user edits."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_ENV_TEMPLATE)


def load_env():
    """Minimal .env reader - avoids a python-dotenv dependency."""
    path = paths.env_file()
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def update_env(updates):
    """Set KEY=value pairs in the .env file (in place) and in os.environ.
    Empty string clears a key. Comments, blanks, order, and unrelated keys
    are preserved. New keys are appended."""
    path = paths.env_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read().splitlines()

    remaining = dict(updates)
    out = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")

    for key, value in updates.items():
        os.environ[key] = value


def safe_workspace_path(rel):
    """Resolve a workspace-relative path, refusing anything that escapes it."""
    ws = paths.workspace_dir()
    target = os.path.realpath(os.path.join(ws, rel))
    root = os.path.realpath(ws)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError("path escapes the workspace")
    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "Celina"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # --- helpers -------------------------------------------------------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # --- routes --------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route == "/api/config":
            return self._send(200, {
                "providers": gateway.available(),
                "tools": tools.status(),
            })

        if route == "/api/workspace":
            return self._send(200, {"files": self._list_workspace()})

        if route == "/api/workspace/file":
            qs = urllib.parse.parse_qs(parsed.query)
            rel = (qs.get("path") or [""])[0]
            try:
                target = safe_workspace_path(rel)
                with open(target, "r", encoding="utf-8", errors="replace") as fh:
                    return self._send(200, {"path": rel, "content": fh.read()})
            except Exception as e:
                return self._send(400, {"error": str(e)})

        if route == "/api/settings":
            return self._get_settings()

        return self._serve_static(route)

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path
        try:
            payload = self._read_json()
        except Exception:
            return self._send(400, {"error": "invalid JSON body"})

        if route == "/api/chat":
            return self._chat(payload)
        if route == "/api/explore":
            return self._explore(payload)
        if route == "/api/fetch":
            return self._fetch(payload)
        if route == "/api/workspace/save":
            return self._save(payload)
        if route == "/api/settings":
            return self._save_settings(payload)
        return self._send(404, {"error": "no such endpoint"})

    # --- handlers ------------------------------------------------------
    def _chat(self, payload):
        provider = payload.get("provider") or "anthropic"
        messages = payload.get("messages") or []
        context = (payload.get("context") or "").strip()
        if not messages:
            return self._send(400, {"error": "messages is required"})

        system = SYSTEM_PROMPT
        if context:
            system += (
                "\n\nThe user is currently viewing this artifact from the "
                "notebook. Ground your answer in it when relevant:\n\n"
                + context[:40000]
            )
        try:
            result = gateway.chat(provider, messages, system=system)
            return self._send(200, result)
        except gateway.GatewayError as e:
            return self._send(502, {"error": str(e)})
        except Exception as e:  # unexpected - still return JSON, not a stack page
            return self._send(500, {"error": f"unexpected: {e}"})

    def _explore(self, payload):
        query = (payload.get("query") or "").strip()
        provider = payload.get("provider")  # optional - results work keyless
        if not query:
            return self._send(400, {"error": "query is required"})
        try:
            resp = scanner.scan(query, gateway=gateway, provider=provider)
            return self._send(200, resp)
        except Exception as e:
            return self._send(502, {"error": f"search failed: {e}"})

    def _fetch(self, payload):
        url = (payload.get("url") or "").strip()
        if not url:
            return self._send(400, {"error": "url is required"})
        try:
            return self._send(200, tools.fetch(url))
        except Exception as e:
            return self._send(502, {"error": str(e)})

    def _save(self, payload):
        rel = (payload.get("path") or "").strip()
        content = payload.get("content") or ""
        if not rel:
            return self._send(400, {"error": "path is required"})
        try:
            target = safe_workspace_path(rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
            return self._send(200, {"saved": rel})
        except Exception as e:
            return self._send(400, {"error": str(e)})

    def _get_settings(self):
        return self._send(200, {
            "providers": gateway.settings_state(),
            "finder_email": os.environ.get("FINDER_CONTACT_EMAIL", ""),
        })

    def _save_settings(self, payload):
        key_envs = {s["key_env"] for s in gateway.PROVIDERS.values() if s["key_env"]}
        model_envs = {s["model_env"] for s in gateway.PROVIDERS.values()}

        updates = {}
        try:
            for env, val in (payload.get("keys") or {}).items():
                if env in key_envs:
                    if not isinstance(val, str):
                        raise ValueError("key values must be strings")
                    updates[env] = val.strip()
            for env, val in (payload.get("models") or {}).items():
                if env in model_envs:
                    if not isinstance(val, str):
                        raise ValueError("model values must be strings")
                    updates[env] = val.strip()
            if "finder_email" in payload:
                val = payload["finder_email"]
                if not isinstance(val, str):
                    raise ValueError("finder_email must be a string")
                updates["FINDER_CONTACT_EMAIL"] = val.strip()
        except ValueError as e:
            return self._send(400, {"error": str(e)})

        try:
            if updates:
                update_env(updates)
        except Exception as e:
            return self._send(500, {"error": f"could not write settings: {e}"})

        return self._get_settings()

    def _list_workspace(self):
        out = []
        ws = paths.workspace_dir()
        for dirpath, _dirs, names in os.walk(ws):
            for name in sorted(names):
                if name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, ws).replace(os.sep, "/")
                out.append({
                    "path": rel,
                    "name": name,
                    "size": os.path.getsize(full),
                    "kind": "html" if name.endswith((".html", ".htm")) else "text",
                })
        return out

    def _serve_static(self, route):
        rel = "index.html" if route in ("/", "") else route.lstrip("/")
        web_root = os.path.realpath(paths.web_dir())
        target = os.path.realpath(os.path.join(web_root, rel))
        if not (target == web_root or target.startswith(web_root + os.sep)):
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(target):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as fh:
            return self._send(200, fh.read(), ctype)


def make_server(port=None, host="127.0.0.1"):
    """Build a bound (not-yet-serving) server. port=0 picks a free port;
    read it back from the returned server's .server_address[1]."""
    seed_env(paths.env_file())
    load_env()
    os.makedirs(paths.workspace_dir(), exist_ok=True)
    if port is None:
        port = int(os.environ.get("CELINA_PORT", "8765"))
    return ThreadingHTTPServer((host, port), Handler)


def main():
    srv = make_server()
    port = srv.server_address[1]

    ready = [p["id"] for p in gateway.available() if p["ready"]]
    present = [t["id"] for t in tools.status() if t["present"]]

    print("\n  Celina")
    print(f"  http://localhost:{port}")
    print(f"  providers ready : {', '.join(ready) or 'none - add a key to .env'}")
    print(f"  tools detected  : {', '.join(present) or 'none (optional)'}\n")

    srv.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  stopped\n")
