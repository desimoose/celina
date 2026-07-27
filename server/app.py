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

from dataclasses import replace
import json
import mimetypes
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import finder  # noqa: E402
import events  # noqa: E402
import gateway  # noqa: E402
import local_security  # noqa: E402
import paths  # noqa: E402
import scanner  # noqa: E402
import serialization  # noqa: E402
import sessions  # noqa: E402
import tokens  # noqa: E402
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
        # BaseHTTPRequestHandler normally logs full request targets, which can
        # leak a rejected query-string secret into a terminal or log collector.
        sys.stderr.write("  local request completed\n")

    # --- helpers -------------------------------------------------------
    def _send(
        self,
        code,
        body,
        ctype="application/json; charset=utf-8",
        headers=None,
    ):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if urllib.parse.urlparse(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _discard_request_body(self):
        try:
            remaining = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return
        while remaining:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                return
            remaining -= len(chunk)

    def _forbidden(self):
        return self._send(403, self.server.local_security.denial_body())

    def _not_found(self):
        return self._send(404, {"error": "not found"})

    def _has_launch_cookie(self):
        security = self.server.local_security
        return security.authorize_mutation(
            self.headers.get("Cookie"),
            security.csrf_token,
            security.expected_origin,
        )

    def _allows_session_mutation(self, query_string):
        security = self.server.local_security
        return security.authorize_mutation(
            self.headers.get("Cookie"),
            self.headers.get("X-Celina-CSRF"),
            self.headers.get("Origin"),
            query_string,
        )

    def _session(self, session_id):
        try:
            item = self.server.session_store.get(session_id)
        except (OSError, ValueError):
            return None
        if item is None:
            return None
        if item.session_id in self.server.recovery_required_session_ids:
            return replace(item, recovery_required=True)
        return item

    def _serialized_session(self, session):
        return serialization.serialize_session(session)

    @staticmethod
    def _traffic_record(record, include_bodies=False):
        value = {
            "traffic_event_id": record["traffic_event_id"],
            "session_id": record["session_id"],
            "run_id": record["run_id"],
            "correlation_id": record["correlation_id"],
            "direction": record["direction"],
            "transport": record["transport"],
            "destination": record["destination"],
            "method_or_action": record["method_or_action"],
            "started_at": record["started_at"],
            "completed_at": record["completed_at"],
            "status": record["status"],
            "duration_ms": record["duration_ms"],
            "request_bytes": record["request_bytes"],
            "response_bytes": record["response_bytes"],
            "request_headers": record["request_headers"],
            "response_headers": record["response_headers"],
            "redactions": record["redactions"],
            "error_class": record["error_class"],
            "error_summary": record["error_summary"],
        }
        if include_bodies:
            value["request_body"] = bytes(
                record["request_body"] or b""
            ).decode("utf-8", "replace")
            value["response_body"] = bytes(
                record["response_body"] or b""
            ).decode("utf-8", "replace")
        return value

    @staticmethod
    def _usage_summary(summary):
        return {
            "session_id": summary.session_id,
            "input_tokens": summary.input_tokens,
            "output_tokens": summary.output_tokens,
            "cached_input_tokens": summary.cached_input_tokens,
            "total_tokens": summary.total_tokens,
            "context_percentage": summary.context_percentage,
            "records": [{
                "usage_id": record.usage_id,
                "session_id": record.session_id,
                "correlation_id": record.correlation_id,
                "provider": record.provider,
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "cached_input_tokens": record.cached_input_tokens,
                "context_limit": record.context_limit,
                "context_percentage": record.context_percentage,
                "is_estimated": record.is_estimated,
                "recorded_at": record.recorded_at,
            } for record in summary.records],
        }

    # --- routes --------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path

        if route == "/api/sessions" or route.startswith("/api/sessions/"):
            return self._get_session_route(route)

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
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route == "/api/sessions" or route.startswith("/api/sessions/"):
            return self._post_session_route(parsed)
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

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        prefix = "/api/sessions/"
        if not route.startswith(prefix):
            return self._not_found()
        if not self._allows_session_mutation(parsed.query):
            self._discard_request_body()
            return self._forbidden()
        session_id = route[len(prefix):]
        if not session_id or "/" in session_id or self._session(session_id) is None:
            return self._not_found()
        try:
            result = self.server.session_store.delete(session_id)
        except (OSError, ValueError):
            return self._not_found()
        if not result.deleted:
            return self._send(500, {"error": "could not delete session"})
        self.server.recovery_required_session_ids.discard(session_id)
        return self._send(200, {"session_id": session_id, "deleted": True})

    def _get_session_route(self, route):
        if not self._has_launch_cookie():
            return self._forbidden()
        if route == "/api/sessions":
            return self._send(200, {"sessions": [
                self._serialized_session(
                    self._session(item.session_id) or item
                )
                for item in self.server.session_store.list()
            ]})

        prefix = "/api/sessions/"
        suffix = route[len(prefix):]
        if not suffix:
            return self._not_found()
        parts = suffix.split("/")
        session_id = parts[0]
        session = self._session(session_id)
        if session is None:
            return self._not_found()
        if len(parts) == 1:
            return self._send(200, self._serialized_session(session))
        if len(parts) == 2 and parts[1] == "traffic":
            try:
                records = self.server.session_store.list_traffic(session_id)
            except (OSError, ValueError):
                return self._not_found()
            return self._send(200, {
                "traffic": [self._traffic_record(record) for record in records]
            })
        if len(parts) == 3 and parts[1] == "traffic" and parts[2]:
            try:
                records = self.server.session_store.list_traffic(session_id)
            except (OSError, ValueError):
                return self._not_found()
            record = next(
                (
                    item for item in records
                    if item["traffic_event_id"] == parts[2]
                ),
                None,
            )
            if record is None:
                return self._not_found()
            return self._send(200, self._traffic_record(record, include_bodies=True))
        if len(parts) == 2 and parts[1] == "usage":
            summary = tokens.TokenAccountant(
                self.server.session_store, session_id
            ).summary(session_id)
            return self._send(200, self._usage_summary(summary))
        return self._not_found()

    def _post_session_route(self, parsed):
        if not self._allows_session_mutation(parsed.query):
            self._discard_request_body()
            return self._forbidden()
        route = parsed.path
        if route == "/api/sessions":
            try:
                payload = self._read_json()
            except Exception:
                return self._send(400, {"error": "invalid JSON body"})
            if not isinstance(payload, dict):
                return self._send(400, {"error": "invalid session request"})
            content_recording = payload.get("content_recording", True)
            if not isinstance(content_recording, bool):
                return self._send(400, {
                    "error": "content_recording must be a boolean"
                })
            session = self.server.session_store.create(content_recording)
            return self._send(201, self._serialized_session(session))

        prefix = "/api/sessions/"
        suffix = route[len(prefix):]
        if not suffix.endswith("/end"):
            return self._not_found()
        session_id = suffix[:-4]
        if not session_id or "/" in session_id or self._session(session_id) is None:
            return self._not_found()
        try:
            session = self.server.session_store.mark_stopped(session_id)
        except (OSError, ValueError, KeyError):
            return self._not_found()
        self.server.recovery_required_session_ids.discard(session_id)
        return self._send(200, self._serialized_session(session))

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
        if route in ("/", ""):
            with open(target, "r", encoding="utf-8") as fh:
                page = fh.read()
            csrf_meta = (
                '<meta name="celina-csrf" content="%s">'
                % self.server.local_security.csrf_token
            )
            if "</head>" in page:
                page = page.replace("</head>", csrf_meta + "</head>", 1)
            else:
                page = csrf_meta + page
            return self._send(
                200,
                page,
                ctype,
                headers={
                    "Set-Cookie": self.server.local_security.launch_cookie_header,
                    "Cache-Control": "no-store",
                },
            )
        with open(target, "rb") as fh:
            return self._send(200, fh.read(), ctype)


def _bound_origin(host, port):
    host = str(host)
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "http://%s:%s" % (host, port)


def make_server(port=None, host="127.0.0.1", session_root=None):
    """Build a bound (not-yet-serving) server. port=0 picks a free port;
    read it back from the returned server's .server_address[1]."""
    seed_env(paths.env_file())
    load_env()
    os.makedirs(paths.workspace_dir(), exist_ok=True)
    if port is None:
        port = int(os.environ.get("CELINA_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    bound_host, bound_port = server.server_address[:2]
    store = sessions.SessionStore(session_root)
    server.session_store = store
    server.event_bus = events.EventBus(store)
    server.local_security = local_security.LocalSecurity(
        _bound_origin(bound_host, bound_port)
    )
    server.recovery_required_session_ids = {
        item.session_id for item in store.list_recoverable()
    }
    return server


def main():
    srv = make_server()
    origin = srv.local_security.expected_origin

    ready = [p["id"] for p in gateway.available() if p["ready"]]
    present = [t["id"] for t in tools.status() if t["present"]]

    print("\n  Celina")
    print(f"  {origin}")
    print(f"  providers ready : {', '.join(ready) or 'none - add a key to .env'}")
    print(f"  tools detected  : {', '.join(present) or 'none (optional)'}\n")

    srv.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  stopped\n")
