"""Reveriebot - local server.

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
import tools  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
WORKSPACE = os.path.join(ROOT, "workspace")
PORT = int(os.environ.get("REVERIEBOT_PORT", "8765"))

SYSTEM_PROMPT = (
    "You are the Reveriebot workspace agent: a private research assistant. "
    "You help investigate topics using the notebook's collected sources. "
    "Cite what you were given; say plainly when you do not know something "
    "rather than guessing. Be concise and lead with the finding."
)


def load_env():
    """Minimal .env reader - avoids a python-dotenv dependency."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def safe_workspace_path(rel):
    """Resolve a workspace-relative path, refusing anything that escapes it."""
    target = os.path.realpath(os.path.join(WORKSPACE, rel))
    if target != os.path.realpath(WORKSPACE) and not target.startswith(
        os.path.realpath(WORKSPACE) + os.sep
    ):
        raise ValueError("path escapes the workspace")
    return target


class Handler(BaseHTTPRequestHandler):
    server_version = "Reveriebot"

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
            hits, notes = finder.search(query, limit=8)
        except Exception as e:
            return self._send(502, {"error": f"search failed: {e}"})

        resp = {"query": query, "results": hits, "notes": notes, "answer": None}

        # The grounded answer needs a model. No provider (or no key) -> results
        # only; the papers are useful on their own.
        if provider and hits:
            try:
                reply = gateway.chat(
                    provider,
                    messages=[{"role": "user", "content": query}],
                    system=finder.grounding_system(hits),
                )
                resp.update(answer=reply["text"], model=reply["model"],
                            provider=reply["provider"])
            except gateway.GatewayError as e:
                resp["answer_error"] = str(e)   # show papers, note the model issue
            except Exception as e:
                resp["answer_error"] = f"unexpected: {e}"
        return self._send(200, resp)

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

    def _list_workspace(self):
        out = []
        for dirpath, _dirs, names in os.walk(WORKSPACE):
            for name in sorted(names):
                if name.startswith("."):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, WORKSPACE).replace(os.sep, "/")
                out.append({
                    "path": rel,
                    "name": name,
                    "size": os.path.getsize(full),
                    "kind": "html" if name.endswith((".html", ".htm")) else "text",
                })
        return out

    def _serve_static(self, route):
        rel = "index.html" if route in ("/", "") else route.lstrip("/")
        target = os.path.realpath(os.path.join(WEB, rel))
        web_root = os.path.realpath(WEB)
        if not (target == web_root or target.startswith(web_root + os.sep)):
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(target):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as fh:
            return self._send(200, fh.read(), ctype)


def main():
    load_env()
    os.makedirs(WORKSPACE, exist_ok=True)

    ready = [p["id"] for p in gateway.available() if p["ready"]]
    present = [t["id"] for t in tools.status() if t["present"]]

    print("\n  Reveriebot")
    print(f"  http://localhost:{PORT}")
    print(f"  providers ready : {', '.join(ready) or 'none - add a key to .env'}")
    print(f"  tools detected  : {', '.join(present) or 'none (optional)'}\n")

    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  stopped\n")
