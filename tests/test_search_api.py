import contextlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402
import redaction  # noqa: E402
import tokens  # noqa: E402
import traffic  # noqa: E402


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

    def _create_session(self, content_recording=None):
        cookie, csrf = self._launch()
        payload = {}
        if content_recording is not None:
            payload["content_recording"] = content_recording
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

    def test_root_sets_memory_cookie_and_injects_csrf_without_changing_source(self):
        index_path = os.path.join(app.paths.web_dir(), "index.html")
        with open(index_path, "rb") as handle:
            source_before = handle.read()

        status, headers, body = self._request("GET", "/")

        self.assertEqual(status, 200)
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
            "recovery_required",
        }
        self.assertEqual(set(created), expected_keys)
        self.assertEqual(created["state"], "active")
        self.assertTrue(created["content_recording"])
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


if __name__ == "__main__":
    unittest.main()
