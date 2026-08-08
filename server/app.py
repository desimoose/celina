"""Celina - local server.

Stdlib only. Serves the web UI and a small JSON API:

  GET  /api/config                    providers + tool availability
  POST /api/chat                      talk to any provider through the gateway
  POST /api/fetch                     fetch a page (via Obscura when present)
  GET  /api/workspace                 list notebook artifacts
  GET  /api/workspace/file            read one artifact
  POST /api/workspace/save            write an artifact
  GET  /api/projects                   list local projects and outputs
  POST /api/projects                   create a local project folder
  POST /api/projects/{id}/outputs      save a formatted project output
  GET  /api/projects/{id}/outputs/{n}  read one project output
  POST /api/search-runs               start a bounded, observable search run
  GET  /api/search-runs/{id}          read run state
  POST /api/search-runs/{id}/stop     cooperatively stop a run
  GET  /api/search-runs/{id}/events   resumable live trace (SSE)
  GET  /api/update-check              anonymous check against GitHub Releases

Run:  python server/app.py     then open the exact loopback URL it prints
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
import notebooks  # noqa: E402
import orchestrator  # noqa: E402
import paths  # noqa: E402
import projects  # noqa: E402
import scanner  # noqa: E402
import search_runtime  # noqa: E402
import serialization  # noqa: E402
import sessions  # noqa: E402
import session_cleanup  # noqa: E402
import sse  # noqa: E402
import tokens  # noqa: E402
import tools  # noqa: E402
import update_check  # noqa: E402

mimetypes.add_type("font/woff2", ".woff2")  # bundled local fonts

SYSTEM_PROMPT = (
    "You are Celina: a private research assistant. "
    "You help investigate topics using the notebook's collected sources. "
    "Cite what you were given; say plainly when you do not know something "
    "rather than guessing. Be concise and lead with the finding."
)

_DEFAULT_SESSION_RETENTION_SECONDS = 24 * 60 * 60
_SESSION_RETENTION_CHOICES = {0, 3600, 86400, 604800}
_CHAT_SYSTEM_LIMIT = 40000
SessionJanitor = session_cleanup.SessionJanitor


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
# Completed sessions are automatically removed after this many seconds.
CELINA_SESSION_RETENTION_SECONDS=86400
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


def session_retention_seconds():
    raw = os.environ.get(
        "CELINA_SESSION_RETENTION_SECONDS",
        str(_DEFAULT_SESSION_RETENTION_SECONDS),
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_SESSION_RETENTION_SECONDS


def provider_privacy_state():
    out = {}
    for name, spec in gateway.PROVIDERS.items():
        if spec["key_env"] is None:
            out[name] = "Ollama — stays on this machine"
        else:
            out[name] = "%s — question/context sent to provider" % spec["label"]
    return out


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
    def _require_object(payload, error):
        if not isinstance(payload, dict):
            raise ValueError(error)
        return payload

    @staticmethod
    def _notebook_request_value(payload, field, *, limit, required=True):
        value = payload.get(field)
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        text = value.strip()
        if required and not text:
            raise ValueError(f"{field} is required")
        if len(text) > limit:
            raise ValueError(f"{field} is too long")
        return text

    def _safe_notebook_id(self, notebook_id):
        if not isinstance(notebook_id, str) or not notebooks._SAFE_ID.fullmatch(
            notebook_id
        ):
            raise ValueError("invalid notebook id")
        return notebook_id

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

        if route.startswith("/api/search-runs/"):
            return self._get_search_run_route(route)

        if route == "/api/config":
            return self._send(200, {
                "providers": gateway.available(),
                "tools": tools.status(),
            })

        if route == "/api/update-check":
            return self._send(200, update_check.check())

        if route == "/api/notebooks/export":
            if not self._has_launch_cookie():
                return self._forbidden()
            return self._send(
                200,
                notebooks.export_notebooks(),
                headers={"Content-Disposition": "attachment; filename=celina-notebooks.json"},
            )

        if route == "/api/notebooks" or route.startswith("/api/notebooks/"):
            return self._get_notebook_route(route)

        if route == "/api/workspace":
            return self._send(200, {"files": self._list_workspace()})

        if route == "/api/projects":
            try:
                items = projects.list_projects()
                if not items:
                    items = [projects.create_project("Inbox")]
                return self._send(200, {
                    "projects": items,
                    "formats": projects.formats(),
                })
            except Exception as e:
                return self._send(500, {"error": str(e)})

        if route.startswith("/api/projects/"):
            parts = route.split("/")
            if len(parts) == 6 and parts[4] == "outputs":
                try:
                    content = projects.read_output(parts[3], parts[5])
                    return self._send(200, {
                        "project_id": parts[3],
                        "name": parts[5],
                        "content": content,
                    })
                except (OSError, ValueError):
                    return self._not_found()
            return self._not_found()

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
        if route == "/api/search-runs" or route.startswith("/api/search-runs/"):
            return self._post_search_run_route(parsed)
        if route == "/api/notebooks" or route.startswith("/api/notebooks/"):
            if not self._allows_session_mutation(parsed.query):
                self._discard_request_body()
                return self._forbidden()
            try:
                payload = self._read_json()
            except Exception:
                return self._send(400, {"error": "invalid JSON body"})
            return self._post_notebook_route(parsed, payload)
        if route == "/api/settings":
            if not self._allows_session_mutation(parsed.query):
                self._discard_request_body()
                return self._forbidden()
            try:
                payload = self._read_json()
            except Exception:
                return self._send(400, {"error": "invalid JSON body"})
            return self._save_settings(payload)
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
        if route == "/api/notebooks" or route.startswith("/api/notebooks/"):
            return self._post_notebook_route(parsed, payload)
        if route == "/api/workspace/save":
            return self._save(payload)
        if route == "/api/projects":
            return self._create_project(payload, parsed.query)
        if route.startswith("/api/projects/"):
            return self._save_project_output(parsed, payload)
        return self._send(404, {"error": "no such endpoint"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route == "/api/notebooks":
            if not self._allows_session_mutation(parsed.query):
                self._discard_request_body()
                return self._forbidden()
            try:
                deleted = notebooks.delete_all_notebooks()
            except OSError as exc:
                return self._send(500, {"error": str(exc)})
            return self._send(200, {"deleted": deleted})
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
            incognito = payload.get("incognito", False)
            if not isinstance(incognito, bool):
                return self._send(400, {"error": "incognito must be a boolean"})
            session = self.server.session_store.create(
                content_recording, incognito=incognito
            )
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
        if session.incognito:
            result = self.server.session_store.delete(session_id)
            if not result.deleted:
                return self._send(500, {"error": "could not delete incognito session"})
            return self._send(200, {
                **self._serialized_session(session),
                "deleted": True,
            })
        return self._send(200, self._serialized_session(session))

    def _get_search_run_route(self, route):
        if not self._has_launch_cookie():
            return self._forbidden()
        prefix = "/api/search-runs/"
        suffix = route[len(prefix):]
        if not suffix:
            return self._not_found()
        parts = suffix.split("/")
        run_id = parts[0]
        if len(parts) == 1:
            try:
                run = self.server.search_runtime.get(run_id)
            except KeyError:
                return self._not_found()
            return self._send(200, serialization.serialize_search_run(run))
        if len(parts) == 2 and parts[1] == "events":
            return self._stream_search_run_events(run_id)
        return self._not_found()

    def _get_notebook_route(self, route):
        if not self._has_launch_cookie():
            return self._forbidden()
        if route == "/api/notebooks":
            items = notebooks.list_notebooks()
            summaries = []
            for notebook in items:
                summaries.append({
                    "id": notebook["id"],
                    "title": notebook["title"],
                    "goal": notebook["goal"],
                    "created_at": notebook["created_at"],
                    "updated_at": notebook["updated_at"],
                    "source_count": len(notebook["sources"]),
                    "note_count": len(notebook["notes"]),
                    "learning_path_depth": notebook.get("learning_path", {}).get("depth", "college"),
                })
            return self._send(200, {"notebooks": summaries})

        prefix = "/api/notebooks/"
        notebook_id = route[len(prefix):]
        if not notebook_id or "/" in notebook_id:
            return self._not_found()
        try:
            notebook_id = self._safe_notebook_id(notebook_id)
            notebook = notebooks.read_notebook(notebook_id)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except OSError:
            return self._not_found()
        return self._send(200, {"notebook": notebook})

    def _post_search_run_route(self, parsed):
        route = parsed.path
        if route == "/api/search-runs":
            if not self._allows_session_mutation(parsed.query):
                self._discard_request_body()
                return self._forbidden()
            try:
                payload = self._read_json()
            except Exception:
                return self._send(400, {"error": "invalid JSON body"})
            return self._start_search_run(payload)

        prefix = "/api/search-runs/"
        suffix = route[len(prefix):]
        if not suffix.endswith("/stop"):
            self._discard_request_body()
            return self._not_found()
        run_id = suffix[:-len("/stop")]
        if not self._allows_session_mutation(parsed.query):
            self._discard_request_body()
            return self._forbidden()
        self._discard_request_body()
        if not run_id or "/" in run_id:
            return self._not_found()
        try:
            run = self.server.search_runtime.stop(run_id)
        except KeyError:
            return self._not_found()
        return self._send(200, serialization.serialize_search_run(run))

    def _post_notebook_route(self, parsed, payload):
        route = parsed.path
        if not self._allows_session_mutation(parsed.query):
            return self._forbidden()
        if route == "/api/notebooks":
            try:
                payload = self._require_object(payload, "invalid notebook request")
                title = self._notebook_request_value(
                    payload, "title", limit=notebooks._TITLE_LIMIT
                )
                goal = self._notebook_request_value(
                    payload,
                    "goal",
                    limit=notebooks._NOTE_BODY_LIMIT,
                    required=False,
                )
                notebook = notebooks.create_notebook(title, goal)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except OSError as e:
                return self._send(500, {"error": str(e)})
            except Exception:
                return self._send(500, {"error": "could not create notebook"})
            return self._send(201, {"notebook": notebook})

        prefix = "/api/notebooks/"
        suffix = route[len(prefix):]
        if not suffix:
            return self._not_found()
        parts = suffix.split("/")
        if len(parts) not in {2, 3} or not parts[1]:
            return self._not_found()
        try:
            notebook_id = self._safe_notebook_id(parts[0])
            payload = self._require_object(payload, "invalid notebook request")
            if parts[1] == "sources" and len(parts) == 2:
                source = self._create_notebook_source(notebook_id, payload)
                return self._send(201, {"source": source})
            if parts[1] == "sources" and len(parts) == 3 and parts[2] == "import":
                source = self._import_notebook_source(notebook_id, payload)
                return self._send(201, {"source": source})
            if parts[1] == "notes" and len(parts) == 2:
                note = self._create_notebook_note(notebook_id, payload)
                return self._send(201, {"note": note})
            if parts[1] == "learning-path" and len(parts) == 2:
                learning_path = self._generate_learning_path(notebook_id, payload)
                return self._send(200, {"learning_path": learning_path})
            if parts[1] == "tutor" and len(parts) == 2:
                result = self._notebook_tutor(notebook_id, payload)
                return self._send(200, result)
            if parts[1] == "study-set" and len(parts) == 2:
                result = self._notebook_study_set(notebook_id, payload)
                return self._send(200, result)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": str(e)})
        except Exception:
            if suffix.endswith("/sources/import"):
                return self._send(502, {"error": "could not import source"})
            return self._send(500, {"error": "could not update notebook"})
        return self._not_found()

    def _create_notebook_source(self, notebook_id, payload):
        request = {
            "title": self._notebook_request_value(
                payload, "title", limit=notebooks._SOURCE_TITLE_LIMIT
            ),
            "url": self._notebook_request_value(
                payload, "url", limit=notebooks._URL_LIMIT, required=False
            ),
            "kind": self._notebook_request_value(
                payload, "kind", limit=64, required=False
            ),
            "excerpt": self._notebook_request_value(
                payload, "excerpt", limit=notebooks._EXCERPT_LIMIT
            ),
        }
        if "origin" in payload:
            request["origin"] = self._notebook_request_value(
                payload, "origin", limit=notebooks._ORIGIN_LIMIT, required=False
            )
        if "source_result" in payload:
            source_result = payload.get("source_result")
            if not isinstance(source_result, dict):
                raise ValueError("source_result must be an object")
            request["source_result"] = {
                "title": self._notebook_request_value(
                    source_result,
                    "title",
                    limit=notebooks._SOURCE_TITLE_LIMIT,
                    required=False,
                ),
                "url": self._notebook_request_value(
                    source_result,
                    "url",
                    limit=notebooks._URL_LIMIT,
                    required=False,
                ),
                "kind": self._notebook_request_value(
                    source_result, "kind", limit=64, required=False
                ),
            }
        return notebooks.add_source(notebook_id, request)

    def _create_notebook_note(self, notebook_id, payload):
        source_ids = payload.get("source_ids")
        if source_ids is None:
            source_ids = []
        if not isinstance(source_ids, list):
            raise ValueError("source_ids must be a list")
        request = {
            "title": self._notebook_request_value(
                payload, "title", limit=notebooks._NOTE_TITLE_LIMIT
            ),
            "body": self._notebook_request_value(
                payload, "body", limit=notebooks._NOTE_BODY_LIMIT
            ),
            "source_ids": source_ids,
        }
        return notebooks.add_note(notebook_id, request)

    def _import_notebook_source(self, notebook_id, payload):
        notebooks.read_notebook(notebook_id)
        request = {
            "url": notebooks._clean_http_url(
                self._notebook_request_value(
                    payload, "url", limit=notebooks._URL_LIMIT
                ),
                required=True,
            ),
            "title": self._notebook_request_value(
                payload, "title", limit=notebooks._SOURCE_TITLE_LIMIT, required=False
            ),
            "kind": self._notebook_request_value(
                payload, "kind", limit=64, required=False
            ),
        }
        tools.validate_public_http_url(request["url"])
        fetched = tools.fetch(request["url"])
        return notebooks.import_source(notebook_id, request, fetched)

    def _generate_learning_path(self, notebook_id, payload):
        depth = payload.get("depth")
        if not isinstance(depth, str) or depth not in {"survey", "college", "graduate"}:
            raise ValueError("depth must be one of: survey, college, graduate")
        request = {
            "goal": self._notebook_request_value(
                payload, "goal", limit=notebooks._NOTE_BODY_LIMIT, required=False
            ),
            "depth": depth,
        }
        return notebooks.generate_learning_path(notebook_id, request)

    def _notebook_tutor(self, notebook_id, payload):
        provider = payload.get("provider") or "anthropic"
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a string")
        question = self._notebook_request_value(
            payload, "question", limit=2000
        )
        history = payload.get("history") or []
        if not isinstance(history, list):
            raise ValueError("history must be a list")
        messages = []
        for item in history[-12:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                raise ValueError("history contains an invalid message")
            messages.append({
                "role": item["role"],
                "content": self._notebook_request_value(item, "content", limit=2000),
            })
        messages.append({"role": "user", "content": question})
        notebook = notebooks.read_notebook(notebook_id)
        context = notebooks.build_tutor_context(notebook)
        system = (
            SYSTEM_PROMPT
            + "\n\nYou are the Celina Notebook tutor. Teach at the notebook's requested "
            "level, distinguish evidence from inference, and cite claims using only "
            "the exact citation IDs in the notebook context, such as [source-1-p2]. "
            "Never invent a citation ID. If the sources do not support an answer, say so."
            + "\n\nNotebook context:\n"
            + context
        )
        result = gateway.chat(
            provider,
            messages,
            system=system[:_CHAT_SYSTEM_LIMIT],
        )
        result = dict(result)
        result["citations"] = notebooks.tutor_citations(notebook)
        return result

    def _notebook_study_set(self, notebook_id, payload):
        provider = payload.get("provider") or "anthropic"
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be a string")
        mode = payload.get("mode") or "flashcards"
        if mode not in {"flashcards", "quiz"}:
            raise ValueError("mode must be flashcards or quiz")
        count = payload.get("count", 5)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= notebooks._STUDY_ITEM_LIMIT
        ):
            raise ValueError("count must be between 1 and 12")
        notebook = notebooks.read_notebook(notebook_id)
        system = (
            SYSTEM_PROMPT
            + "\n\nYou are Celina's study-set generator. Create exactly valid JSON with no "
            "markdown fences. Use only the notebook context. Return an object shaped "
            f'{{"mode":"{mode}","items":[...]}}. For flashcards each item has '
            '"front", "back", and "citation_ids". For quiz each item has "question", '
            '"answer", and "citation_ids". Citation IDs must be copied exactly from '
            "the context; never invent them.\n\nNotebook context:\n"
            + notebooks.build_tutor_context(notebook)
        )
        result = gateway.chat(
            provider,
            [{"role": "user", "content": f"Create {count} {mode} items."}],
            system=system[:_CHAT_SYSTEM_LIMIT],
        )
        result = dict(result)
        result["study_set"] = notebooks.normalize_study_set(
            result.get("text", ""), mode, count, notebook
        )
        return result

    def _start_search_run(self, payload):
        if not isinstance(payload, dict):
            return self._send(400, {"error": "invalid search-run request"})
        session_id = payload.get("session_id")
        query = payload.get("query")
        provider = payload.get("provider") or "anthropic"
        constraints = payload.get("constraints")
        if constraints is None:
            constraints = {}
        if not isinstance(session_id, str) or not session_id:
            return self._send(400, {"error": "session_id is required"})
        if not isinstance(query, str) or not query.strip():
            return self._send(400, {"error": "query is required"})
        if not isinstance(provider, str):
            return self._send(400, {"error": "provider must be a string"})
        if not isinstance(constraints, dict):
            return self._send(400, {"error": "constraints must be an object"})
        try:
            request = orchestrator.SearchRequest(
                query=query,
                provider=provider,
                constraints=constraints,
                session_id=session_id,
            )
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        try:
            run = self.server.search_runtime.start(request)
        except KeyError:
            return self._send(404, {"error": "unknown session"})
        except RuntimeError:
            return self._send(409, {
                "error": "session already has an active search run"
            })
        return self._send(202, {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "state": run.state,
            "events_url": "/api/search-runs/%s/events" % run.run_id,
        })

    def _stream_search_run_events(self, run_id):
        try:
            run = self.server.search_runtime.get(run_id)
        except KeyError:
            return self._not_found()
        after_sequence = sse.last_event_id(self.headers)
        subscription = self.server.event_bus.subscribe(
            run.session_id, after_sequence
        )
        try:
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream; charset=utf-8"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            while True:
                event = subscription.get(timeout=sse.HEARTBEAT_INTERVAL)
                if event is None:
                    self.wfile.write(sse.format_heartbeat())
                    self.wfile.flush()
                    continue
                if event.run_id != run_id:
                    continue
                self.wfile.write(sse.format_event(event))
                self.wfile.flush()
                if sse.is_terminal(event):
                    return
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return
        finally:
            subscription.close()

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

    def _create_project(self, payload, query_string):
        if not self._allows_session_mutation(query_string):
            return self._forbidden()
        try:
            result = projects.create_project(payload.get("name"))
            return self._send(201, result)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": f"could not create project: {e}"})

    def _save_project_output(self, parsed, payload):
        if not self._allows_session_mutation(parsed.query):
            return self._forbidden()
        parts = parsed.path.split("/")
        if len(parts) != 5 or parts[4] != "outputs":
            return self._not_found()
        try:
            result = projects.save_output(
                parts[3],
                payload.get("title"),
                payload.get("format"),
                payload.get("content"),
            )
            return self._send(201, result)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": f"could not save output: {e}"})

    def _get_settings(self):
        return self._send(200, {
            "providers": gateway.settings_state(),
            "finder_email": os.environ.get("FINDER_CONTACT_EMAIL", ""),
            "session_retention_seconds": session_retention_seconds(),
            "provider_privacy": provider_privacy_state(),
        })

    def _save_settings(self, payload):
        key_envs = {s["key_env"] for s in gateway.PROVIDERS.values() if s["key_env"]}
        model_envs = {s["model_env"] for s in gateway.PROVIDERS.values()}

        updates = {}
        retention_changed = False
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
            if "session_retention_seconds" in payload:
                retention = payload["session_retention_seconds"]
                if not (
                    isinstance(retention, int)
                    and not isinstance(retention, bool)
                    and retention in _SESSION_RETENTION_CHOICES
                ):
                    raise ValueError(
                        "session_retention_seconds must be one of: 0, 3600, 86400, 604800"
                    )
                updates["CELINA_SESSION_RETENTION_SECONDS"] = str(retention)
                retention_changed = True
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
            if retention_changed:
                janitor = getattr(self.server, "session_janitor", None)
                if janitor is not None:
                    janitor.run_once()
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


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A client closing an SSE stream (tab close, navigation, reconnect)
        # aborts its connection routinely - keep the same terse line
        # log_message uses instead of a stack trace on every disconnect.
        sys.stderr.write("  local request completed\n")

    def server_close(self):
        janitor = getattr(self, "session_janitor", None)
        if janitor is not None:
            janitor.stop()
            janitor.join(timeout=0.25)
        return super().server_close()


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
    server = Server((host, port), Handler)
    bound_host, bound_port = server.server_address[:2]
    store = sessions.SessionStore(session_root)
    server.session_janitor = session_cleanup.SessionJanitor(
        store,
        session_retention_seconds,
    )
    server.session_janitor.run_once(include_active_incognito=True)
    server.session_janitor.start()
    server.session_store = store
    server.event_bus = events.EventBus(store)
    server.search_runtime = search_runtime.SearchRuntime(
        server.event_bus, store
    )
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
