import contextlib
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402
import redaction  # noqa: E402
import search_runtime  # noqa: E402
import tokens  # noqa: E402
import traffic  # noqa: E402


def _scripted_chat(payloads):
    """A chat_fn returning each payload (already-encoded JSON strings) in order."""
    remaining = list(payloads)

    def chat(provider, _messages, *, system, traffic_context):
        text = remaining.pop(0) if remaining else "{}"
        return {
            "text": text,
            "provider": provider,
            "model": "deterministic-model",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    return chat


def _one_candidate_scan(query, *, traffic_context):
    return {"results": [{
        "title": "Controlled trial",
        "url": "https://example.test/trial",
        "kind": "research",
    }]}


def _readable_fetch(url, *, traffic_context):
    return {
        "url": url,
        "text": "A controlled trial found evening caffeine delayed sleep onset.",
        "content_type": "text/html",
    }


_DETERMINISTIC_PAYLOADS = [
    json.dumps({
        "direct_query": "Does caffeine affect sleep?",
        "additional_queries": [],
        "evidence_angles": ["sleep onset"],
        "summary": "Check controlled evidence on sleep onset.",
    }),
    json.dumps({
        "covered_angles": ["sleep onset"],
        "gaps": [],
        "conflicts": [],
        "follow_up_query": None,
    }),
    json.dumps({
        "answer": "Evening caffeine delayed sleep onset [C1].",
        "claims": [{
            "claim_id": "claim-1",
            "text": "Evening caffeine delayed sleep onset",
            "citation_ids": ["C1"],
        }],
        "citations": ["C1"],
        "uncertainties": [],
        "conflicts": [],
        "gaps": [],
    }),
]


class SearchApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session_root = os.path.join(self.temp.name, "sessions")
        self.workspace_root = os.path.join(self.temp.name, "workspace")
        self.env_path = os.path.join(self.temp.name, ".env")
        self._patches = [
            mock.patch.object(app.paths, "env_file", return_value=self.env_path),
            mock.patch.object(
                app.paths,
                "workspace_dir",
                return_value=self.workspace_root,
            ),
            mock.patch.object(
                app.scanner,
                "scan",
                return_value={"items": [{"title": "offline fixture"}]},
            ),
        ]
        for patch in self._patches:
            patch.start()
        self._start_server()

    def tearDown(self):
        self._stop_server()
        for patch in reversed(self._patches):
            patch.stop()
        self.temp.cleanup()

    def _start_server(self):
        self.server = app.make_server(port=0, session_root=self.session_root)
        self.base_url = "http://127.0.0.1:%s" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def _stop_server(self):
        if not hasattr(self, "server"):
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        del self.server

    def _request(self, method, path, body=None, headers=None):
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                response_headers = response.headers
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = error.headers
            response_body = error.read().decode("utf-8")
            error.close()
        if path.startswith("/api/"):
            self.assertEqual(response_headers.get("Cache-Control"), "no-store")
            self.assertIsNone(response_headers.get("Access-Control-Allow-Origin"))
        return status, response_headers, response_body

    def _launch(self):
        status, headers, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie").split(";", 1)[0]
        csrf = re.search(
            r'<meta name="celina-csrf" content="([^"]+)">', body
        ).group(1)
        return cookie, csrf

    def _mutation_headers(self, cookie, csrf, origin=None):
        return {
            "Content-Type": "application/json",
            "Cookie": cookie,
            "X-Celina-CSRF": csrf,
            "Origin": origin or self.base_url,
        }

    def _create_session(self, content_recording=None, incognito=None):
        cookie, csrf = self._launch()
        payload = {}
        if content_recording is not None:
            payload["content_recording"] = content_recording
        if incognito is not None:
            payload["incognito"] = incognito
        status, _headers, body = self._request(
            "POST",
            "/api/sessions",
            payload,
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 201)
        return json.loads(body), cookie, csrf

    def _record_traffic(self, session_id, event_id, request_body, response_body):
        self.server.session_store.start_traffic({
            "traffic_event_id": event_id,
            "session_id": session_id,
            "run_id": "run-1",
            "correlation_id": "correlation-1",
            "direction": "outbound",
            "transport": "https",
            "destination": "https://example.test/resource",
            "method_or_action": "page.fetch",
            "started_at": "2026-07-27T00:00:00.000Z",
            "request_bytes": len(request_body),
            "request_headers": {"authorization": "[REDACTED]"},
            "request_body": request_body,
            "redactions": ["sensitive-header"],
        })
        self.server.session_store.complete_traffic(session_id, event_id, {
            "completed_at": "2026-07-27T00:00:01.000Z",
            "status": 200,
            "duration_ms": 10,
            "response_bytes": len(response_body),
            "response_headers": {"content-type": "text/plain"},
            "response_body": response_body,
            "redactions": ["sensitive-header"],
            "error_class": None,
            "error_summary": None,
        })

    def _install_deterministic_runtime(self, chat_fn=None):
        self.server.search_runtime = search_runtime.SearchRuntime(
            self.server.event_bus,
            self.server.session_store,
            chat_fn=chat_fn or _scripted_chat(_DETERMINISTIC_PAYLOADS),
            scan_fn=_one_candidate_scan,
            fetch_fn=_readable_fetch,
        )

    def _start_run(self, session_id, cookie, csrf, query="Does caffeine affect sleep?"):
        status, _headers, body = self._request(
            "POST",
            "/api/search-runs",
            {"session_id": session_id, "query": query, "provider": "ollama"},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 202)
        return json.loads(body)

    def _sse_socket(self, path, cookie, last_event_id=None):
        host, port = self.server.server_address[0], self.server.server_address[1]
        sock = socket.create_connection((host, port), timeout=5)
        lines = [
            "GET %s HTTP/1.1" % path,
            "Host: %s:%s" % (host, port),
            "Cookie: %s" % cookie,
            "Accept: text/event-stream",
        ]
        if last_event_id is not None:
            lines.append("Last-Event-ID: %s" % last_event_id)
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
        return sock

    @staticmethod
    def _read_sse_headers(sock):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        header_part, _, rest = buf.partition(b"\r\n\r\n")
        return header_part.decode("utf-8", "replace"), rest

    @staticmethod
    def _read_sse_frames(sock, leftover=b"", count=1):
        buf = leftover
        frames = []
        while len(frames) < count:
            while b"\n\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return frames, buf
                buf += chunk
            frame, _, buf = buf.partition(b"\n\n")
            frames.append(frame.decode("utf-8"))
        return frames, buf

    def test_root_sets_memory_cookie_and_injects_csrf_without_changing_source(self):
        index_path = os.path.join(app.paths.web_dir(), "index.html")
        with open(index_path, "rb") as handle:
            source_before = handle.read()

        status, headers, body = self._request("GET", "/")

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("HttpOnly", headers.get("Set-Cookie"))
        self.assertIn("SameSite=Strict", headers.get("Set-Cookie"))
        self.assertIn("Path=/", headers.get("Set-Cookie"))
        csrf = re.search(
            r'<meta name="celina-csrf" content="([^"]+)">', body
        ).group(1)
        self.assertEqual(csrf, self.server.local_security.csrf_token)
        with open(index_path, "rb") as handle:
            self.assertEqual(handle.read(), source_before)

    def test_protected_session_reads_reject_missing_or_wrong_launch_cookie(self):
        denied, _headers, body = self._request("GET", "/api/sessions")
        self.assertEqual(denied, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

        denied, _headers, body = self._request(
            "GET", "/api/sessions", headers={"Cookie": "celina_launch=wrong"}
        )
        self.assertEqual(denied, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

        cookie, _csrf = self._launch()
        allowed, _headers, body = self._request(
            "GET", "/api/sessions", headers={"Cookie": cookie}
        )
        self.assertEqual(allowed, 200)
        self.assertEqual(json.loads(body), {"sessions": []})

    def test_session_mutations_require_launch_cookie_csrf_and_expected_origin(self):
        cookie, csrf = self._launch()
        attempts = (
            {},
            {"Cookie": cookie, "Origin": self.base_url},
            {
                "Cookie": cookie,
                "X-Celina-CSRF": "wrong",
                "Origin": self.base_url,
            },
            {
                "Cookie": cookie,
                "X-Celina-CSRF": csrf,
                "Origin": "http://localhost:%s" % self.server.server_address[1],
            },
        )
        for headers in attempts:
            with self.subTest(headers=headers):
                status, _response_headers, body = self._request(
                    "POST", "/api/sessions", {"content_recording": True}, headers
                )
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body), {"error": "forbidden"})

    def test_session_mutation_query_strings_are_rejected(self):
        cookie, csrf = self._launch()

        status, _headers, body = self._request(
            "POST",
            "/api/sessions?trace=not-allowed",
            {"content_recording": True},
            self._mutation_headers(cookie, csrf),
        )

        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

    def test_session_secrets_are_absent_from_responses_logs_and_ledger_files(self):
        canary = "phase-c-canary-secret"
        created, cookie, csrf = self._create_session()
        recorder = traffic.TrafficRecorder(self.server.session_store)
        context = traffic.TrafficContext(
            session_id=created["session_id"],
            run_id="run-1",
            correlation_id="correlation-1",
            recorder=recorder,
            redactor=redaction.Redactor([canary]),
        )
        traffic_id, _redactions = recorder.start(
            context,
            urllib.request.Request(
                "https://example.test/resource?token=" + canary,
                data=json.dumps({"token": canary}).encode("utf-8"),
                headers={"Authorization": "Bearer " + canary},
                method="POST",
            ),
            "provider.chat",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            status, _headers, body = self._request(
                "POST",
                "/api/sessions?token=" + canary,
                {"content_recording": True},
                self._mutation_headers(cookie, csrf),
            )
        self.assertEqual(status, 403)
        self.assertNotIn(canary, body)
        self.assertNotIn(canary, stderr.getvalue())
        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/traffic" % created["session_id"],
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertNotIn(canary, body)
        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/traffic/%s" % (
                created["session_id"], traffic_id
            ),
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertNotIn(canary, body)
        for directory, _names, files in os.walk(self.session_root):
            for name in files:
                if name.startswith("ledger.sqlite3"):
                    with open(os.path.join(directory, name), "rb") as handle:
                        self.assertNotIn(canary.encode("utf-8"), handle.read())

    def test_create_get_and_list_sessions_with_explicit_session_serializer(self):
        created, cookie, _csrf = self._create_session()
        expected_keys = {
            "session_id",
            "state",
            "created_at",
            "last_active_at",
            "content_recording",
            "incognito",
            "recovery_required",
        }
        self.assertEqual(set(created), expected_keys)
        self.assertEqual(created["state"], "active")
        self.assertTrue(created["content_recording"])
        self.assertFalse(created["incognito"])
        self.assertFalse(created["recovery_required"])

        status, _headers, body = self._request(
            "GET",
            "/api/sessions/" + created["session_id"],
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), created)

        status, _headers, body = self._request(
            "GET", "/api/sessions", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"sessions": [created]})

        _cookie, csrf = self._launch()
        status, _headers, _body = self._request(
            "POST",
            "/api/sessions",
            {"content_recording": 1},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 400)

        status, _headers, body = self._request(
            "POST",
            "/api/sessions",
            {"content_recording": False},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 201)
        self.assertFalse(json.loads(body)["content_recording"])

    def test_incognito_session_is_deleted_when_ended(self):
        created, cookie, csrf = self._create_session(incognito=True)
        self.assertTrue(created["incognito"])
        session_dir = os.path.join(self.session_root, created["session_id"])
        self.assertTrue(os.path.isdir(session_dir))

        status, _headers, body = self._request(
            "POST",
            "/api/sessions/%s/end" % created["session_id"],
            {},
            self._mutation_headers(cookie, csrf),
        )

        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["deleted"])
        self.assertFalse(os.path.exists(session_dir))

    def test_expired_stopped_sessions_are_deleted_on_server_start(self):
        created, cookie, csrf = self._create_session()
        status, _headers, _body = self._request(
            "POST",
            "/api/sessions/%s/end" % created["session_id"],
            {},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 200)

        self._stop_server()
        with mock.patch.dict(os.environ, {"CELINA_SESSION_RETENTION_SECONDS": "0"}):
            self._start_server()
            cookie, _csrf = self._launch()
            status, _headers, body = self._request(
                "GET", "/api/sessions", headers={"Cookie": cookie}
            )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["sessions"], [])

    def test_recovery_required_session_is_visible_after_restart(self):
        created, _cookie, _csrf = self._create_session()

        self._stop_server()
        self._start_server()
        cookie, _csrf = self._launch()
        status, _headers, body = self._request(
            "GET", "/api/sessions", headers={"Cookie": cookie}
        )

        self.assertEqual(status, 200)
        sessions = json.loads(body)["sessions"]
        self.assertEqual([item["session_id"] for item in sessions], [
            created["session_id"]
        ])
        self.assertTrue(sessions[0]["recovery_required"])

    def test_traffic_list_is_metadata_only(self):
        created, cookie, _csrf = self._create_session()
        self._record_traffic(
            created["session_id"],
            "traffic-1",
            b"request=[REDACTED]",
            b"response=[REDACTED]",
        )

        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/traffic" % created["session_id"],
            headers={"Cookie": cookie},
        )

        self.assertEqual(status, 200)
        record = json.loads(body)["traffic"][0]
        self.assertNotIn("request_body", record)
        self.assertNotIn("response_body", record)
        self.assertNotIn("request=", json.dumps(record))
        self.assertNotIn("response=", json.dumps(record))

    def test_traffic_detail_returns_one_redacted_record_with_bodies(self):
        created, cookie, _csrf = self._create_session()
        self._record_traffic(
            created["session_id"],
            "traffic-1",
            b"request=[REDACTED]",
            b"response=[REDACTED]",
        )
        self._record_traffic(
            created["session_id"],
            "traffic-2",
            b"second request",
            b"second response",
        )

        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/traffic/traffic-1" % created["session_id"],
            headers={"Cookie": cookie},
        )

        self.assertEqual(status, 200)
        record = json.loads(body)
        self.assertEqual(record["traffic_event_id"], "traffic-1")
        self.assertEqual(record["request_body"], "request=[REDACTED]")
        self.assertEqual(record["response_body"], "response=[REDACTED]")
        self.assertNotIn("traffic-2", body)

    def test_usage_preserves_unknown_token_values(self):
        created, cookie, _csrf = self._create_session()
        tokens.TokenAccountant(
            self.server.session_store, created["session_id"]
        ).record("ollama", "local", {}, "correlation-1")

        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/usage" % created["session_id"],
            headers={"Cookie": cookie},
        )

        self.assertEqual(status, 200)
        usage = json.loads(body)
        self.assertIsNone(usage["input_tokens"])
        self.assertIsNone(usage["output_tokens"])
        self.assertIsNone(usage["total_tokens"])
        self.assertIsNone(usage["records"][0]["input_tokens"])
        self.assertIsNone(usage["records"][0]["output_tokens"])

    def test_end_and_delete_wait_for_session_filesystem_removal(self):
        created, cookie, csrf = self._create_session()
        session_dir = os.path.join(self.session_root, created["session_id"])
        os.makedirs(os.path.join(session_dir, "extracted"))
        with open(
            os.path.join(session_dir, "extracted", "page.txt"), "w", encoding="utf-8"
        ) as handle:
            handle.write("temporary evidence")
        for suffix in ("-wal", "-shm"):
            with open(
                os.path.join(session_dir, "ledger.sqlite3" + suffix), "wb"
            ) as handle:
                handle.write(b"temporary")

        status, _headers, body = self._request(
            "POST",
            "/api/sessions/%s/end" % created["session_id"],
            {},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "stopped")

        status, _headers, body = self._request(
            "DELETE",
            "/api/sessions/" + created["session_id"],
            headers=self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "session_id": created["session_id"], "deleted": True
        })
        self.assertFalse(os.path.exists(session_dir))

    def test_deleting_session_preserves_workspace_siblings(self):
        os.makedirs(self.workspace_root, exist_ok=True)
        kept = os.path.join(self.workspace_root, "kept.md")
        with open(kept, "w", encoding="utf-8") as handle:
            handle.write("keep me")
        created, cookie, csrf = self._create_session()

        status, _headers, _body = self._request(
            "DELETE",
            "/api/sessions/" + created["session_id"],
            headers=self._mutation_headers(cookie, csrf),
        )

        self.assertEqual(status, 200)
        self.assertTrue(os.path.isfile(kept))

    def test_unknown_or_unsafe_session_and_traffic_ids_return_not_found(self):
        cookie, _csrf = self._launch()
        for path in (
            "/api/sessions/not-a-real-session",
            "/api/sessions/%2e%2e",
            "/api/sessions/not-a-real-session/traffic/not-a-real-record",
        ):
            with self.subTest(path=path):
                status, _headers, body = self._request(
                    "GET", path, headers={"Cookie": cookie}
                )
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": "not found"})
                self.assertNotIn(self.session_root, body)

        created, cookie, _csrf = self._create_session()
        status, _headers, body = self._request(
            "GET",
            "/api/sessions/%s/traffic/not-a-real-record" % created["session_id"],
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})

    def test_legacy_config_workspace_settings_and_explore_routes_remain_operational(self):
        os.makedirs(self.workspace_root, exist_ok=True)
        with open(
            os.path.join(self.workspace_root, "note.md"), "w", encoding="utf-8"
        ) as handle:
            handle.write("local note")

        status, _headers, body = self._request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertIn("providers", json.loads(body))

        status, _headers, body = self._request("GET", "/api/workspace")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["files"][0]["path"], "note.md")

        status, _headers, body = self._request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertIn("providers", json.loads(body))

        status, _headers, body = self._request(
            "POST", "/api/explore", {"query": "offline"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["title"], "offline fixture")

    # --- search-run routes (Phase D) ------------------------------------

    def test_search_run_starts_and_completes_with_expected_shape(self):
        created, cookie, csrf = self._create_session()
        self._install_deterministic_runtime()

        started = self._start_run(created["session_id"], cookie, csrf)
        self.assertEqual(started["session_id"], created["session_id"])
        self.assertEqual(started["state"], "created")
        self.assertEqual(
            started["events_url"],
            "/api/search-runs/%s/events" % started["run_id"],
        )

        self.server.search_runtime.wait(started["run_id"], timeout=2)

        status, _headers, body = self._request(
            "GET",
            "/api/search-runs/" + started["run_id"],
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        run = json.loads(body)
        self.assertEqual(run["state"], "completed")
        self.assertEqual(run["query"], "Does caffeine affect sleep?")
        self.assertEqual(run["evidence"][0]["citation_id"], "C1")
        self.assertIn(
            "Evening caffeine delayed sleep onset", run["answer"]["answer"]
        )

    def test_search_run_start_validates_body_and_unknown_session(self):
        cookie, csrf = self._launch()
        status, _headers, _body = self._request(
            "POST",
            "/api/search-runs",
            {"query": "x"},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 400)

        status, _headers, body = self._request(
            "POST",
            "/api/search-runs",
            {"session_id": "not-a-real-session", "query": "x"},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "unknown session"})

    def test_search_run_start_requires_mutation_auth(self):
        created, cookie, _csrf = self._create_session()
        status, _headers, body = self._request(
            "POST",
            "/api/search-runs",
            {"session_id": created["session_id"], "query": "x"},
            {"Cookie": cookie, "Origin": self.base_url},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

    def test_search_run_mutation_query_strings_are_rejected(self):
        created, cookie, csrf = self._create_session()
        status, _headers, body = self._request(
            "POST",
            "/api/search-runs?trace=nope",
            {"session_id": created["session_id"], "query": "x"},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

    def test_search_run_second_active_run_on_same_session_returns_409(self):
        created, cookie, csrf = self._create_session()
        release = threading.Event()
        self._install_deterministic_runtime(chat_fn=_blocking_chat(release))
        started = self._start_run(created["session_id"], cookie, csrf)

        status, _headers, body = self._request(
            "POST",
            "/api/search-runs",
            {"session_id": created["session_id"], "query": "another question"},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {
            "error": "session already has an active search run"
        })

        release.set()
        self.server.search_runtime.wait(started["run_id"], timeout=2)

    def test_search_run_get_requires_cookie_and_unknown_returns_404(self):
        status, _headers, body = self._request(
            "GET", "/api/search-runs/does-not-exist"
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

        cookie, _csrf = self._launch()
        status, _headers, body = self._request(
            "GET", "/api/search-runs/does-not-exist", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})

    def test_search_run_stop_transitions_to_stopped_and_requires_mutation_auth(self):
        created, cookie, csrf = self._create_session()
        planning_started = threading.Event()
        release = threading.Event()
        self._install_deterministic_runtime(
            chat_fn=_blocking_chat(release, started_signal=planning_started)
        )
        started = self._start_run(created["session_id"], cookie, csrf)
        self.assertTrue(planning_started.wait(2))

        status, _headers, body = self._request(
            "POST",
            "/api/search-runs/%s/stop" % started["run_id"],
            {},
            {"Cookie": cookie, "Origin": self.base_url},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

        status, _headers, body = self._request(
            "POST",
            "/api/search-runs/%s/stop" % started["run_id"],
            {},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "stopped")

        release.set()
        self.server.search_runtime.wait(started["run_id"], timeout=2)

    def test_search_run_stop_unknown_run_returns_404(self):
        cookie, csrf = self._launch()
        status, _headers, body = self._request(
            "POST",
            "/api/search-runs/does-not-exist/stop",
            {},
            self._mutation_headers(cookie, csrf),
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not found"})

    # --- resumable SSE trace (Phase E) ----------------------------------

    def test_sse_stream_backfills_all_events_and_delivers_terminal_close(self):
        created, cookie, csrf = self._create_session()
        self._install_deterministic_runtime()
        started = self._start_run(created["session_id"], cookie, csrf)
        self.server.search_runtime.wait(started["run_id"], timeout=2)

        sock = self._sse_socket(
            "/api/search-runs/%s/events" % started["run_id"], cookie
        )
        try:
            headers, rest = self._read_sse_headers(sock)
            self.assertIn("200", headers.splitlines()[0])
            self.assertIn("text/event-stream", headers)
            self.assertIn("Cache-Control: no-store", headers)
            kinds = self._collect_sse_kinds(sock, rest)
        finally:
            sock.close()

        self.assertEqual(kinds[0], "search.started")
        self.assertEqual(kinds[-1], "search.completed")
        self.assertIn("plan.completed", kinds)
        self.assertIn("synthesis.completed", kinds)
        self.assertIn("citation.verified", kinds)

    def test_sse_last_event_id_resumes_without_duplicate_events(self):
        created, cookie, csrf = self._create_session()
        self._install_deterministic_runtime()
        started = self._start_run(created["session_id"], cookie, csrf)
        self.server.search_runtime.wait(started["run_id"], timeout=2)

        sock = self._sse_socket(
            "/api/search-runs/%s/events" % started["run_id"], cookie
        )
        try:
            _headers, rest = self._read_sse_headers(sock)
            all_events = self._collect_sse_events(sock, rest)
        finally:
            sock.close()

        third_sequence = all_events[2]["sequence"]
        sock2 = self._sse_socket(
            "/api/search-runs/%s/events" % started["run_id"],
            cookie,
            last_event_id=third_sequence,
        )
        try:
            _headers, rest = self._read_sse_headers(sock2)
            resumed = self._collect_sse_events(sock2, rest)
        finally:
            sock2.close()

        self.assertEqual(
            [item["kind"] for item in resumed],
            [item["kind"] for item in all_events[3:]],
        )
        self.assertTrue(all(item["sequence"] > third_sequence for item in resumed))

    def test_sse_heartbeat_keeps_an_idle_stream_alive(self):
        created, cookie, csrf = self._create_session()
        self._install_deterministic_runtime()
        started = self._start_run(created["session_id"], cookie, csrf)
        completed = self.server.search_runtime.wait(started["run_id"], timeout=2)
        self.assertEqual(completed.state, "completed")
        final_sequence = self.server.session_store.list_events(
            created["session_id"]
        )[-1]["sequence"]

        with mock.patch.object(app.sse, "HEARTBEAT_INTERVAL", 0.05):
            sock = self._sse_socket(
                "/api/search-runs/%s/events" % started["run_id"],
                cookie,
                last_event_id=final_sequence,
            )
            try:
                _headers, rest = self._read_sse_headers(sock)
                frames, _rest = self._read_sse_frames(sock, rest, count=2)
            finally:
                sock.close()

        self.assertEqual(len(frames), 2)
        for frame in frames:
            self.assertTrue(frame.startswith(": heartbeat"))

    def test_sse_disconnect_removes_the_subscriber(self):
        created, cookie, csrf = self._create_session()
        release = threading.Event()
        self._install_deterministic_runtime(chat_fn=_blocking_chat(release))
        started = self._start_run(created["session_id"], cookie, csrf)

        with mock.patch.object(app.sse, "HEARTBEAT_INTERVAL", 0.05):
            sock = self._sse_socket(
                "/api/search-runs/%s/events" % started["run_id"], cookie
            )
            try:
                self._read_sse_headers(sock)
                self._wait_for_subscriber_count(created["session_id"], 1)
            finally:
                sock.close()

            self._wait_for_subscriber_count(created["session_id"], 0)

        self.assertEqual(
            self.server.event_bus.subscriber_count(created["session_id"]), 0
        )
        release.set()
        self.server.search_runtime.wait(started["run_id"], timeout=2)

    def _wait_for_subscriber_count(self, session_id, expected, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.event_bus.subscriber_count(session_id) == expected:
                return
            time.sleep(0.01)

    def _collect_sse_events(self, sock, leftover):
        events = []
        while True:
            frames, leftover = self._read_sse_frames(sock, leftover, count=1)
            if not frames:
                return events
            data_line = next(
                line for line in frames[0].splitlines()
                if line.startswith("data: ")
            )
            payload = json.loads(data_line[len("data: "):])
            events.append(payload)
            if payload["kind"] == "search.completed":
                return events

    def _collect_sse_kinds(self, sock, leftover):
        return [item["kind"] for item in self._collect_sse_events(sock, leftover)]


def _blocking_chat(release, started_signal=None):
    def chat(provider, _messages, *, system, traffic_context):
        if started_signal is not None:
            started_signal.set()
        release.wait(2)
        return {
            "text": _DETERMINISTIC_PAYLOADS[0],
            "provider": provider,
            "model": "deterministic-model",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    return chat


if __name__ == "__main__":
    unittest.main()
