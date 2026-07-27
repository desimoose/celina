import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import redaction  # noqa: E402
import finder  # noqa: E402
import gateway  # noqa: E402
import sessions  # noqa: E402
import traffic  # noqa: E402


CANARY = "canary-super-secret-9981"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"source": "fixture"}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        size = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(size)
        if self.path.startswith("/slow"):
            time.sleep(0.15)
        if self.path.startswith("/chat"):
            payload = json.dumps({
                "choices": [{"message": {"content": "grounded answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }).encode()
            self.send_response(200)
        elif self.path.startswith("/failure"):
            payload = json.dumps({"error": "denied", "echo": CANARY}).encode()
            self.send_response(403)
        elif self.path.startswith("/malformed"):
            payload = b"{not-json"
            self.send_response(200)
        else:
            payload = json.dumps({
                "ok": True,
                "received": json.loads(body.decode()),
            }).encode()
            self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("x-test-response", "visible")
        self.send_header("set-cookie", f"session={CANARY}")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        pass


class TrafficTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.recorder = traffic.TrafficRecorder(self.store)
        self.context = traffic.TrafficContext(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="correlation-1",
            recorder=self.recorder,
            redactor=redaction.Redactor([CANARY]),
        )

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, body=None):
        payload = json.dumps(body or {"question": "hello"}).encode()
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {CANARY}",
                "x-visible": "kept",
            },
            method="POST",
        )

    def test_success_records_redacted_inspectable_exchange(self):
        request = self.request(
            f"/success?api_key={CANARY}",
            {"question": "hello", "api_key": CANARY},
        )
        result = traffic.http_request(
            self.context,
            request,
            timeout=1,
            action_type="provider.chat",
        )

        self.assertEqual(result.status, 200)
        self.assertTrue(json.loads(result.body)["ok"])

        records = self.recorder.list(self.session.session_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.status, 200)
        self.assertEqual(record.direction, "outbound")
        self.assertEqual(record.transport, "http")
        self.assertEqual(record.method_or_action, "provider.chat")
        self.assertEqual(record.request_headers["authorization"], "[REDACTED]")
        self.assertEqual(record.request_headers["x-visible"], "kept")
        self.assertIn("[REDACTED]", record.request_body.decode())
        self.assertEqual(record.response_headers["set-cookie"], "[REDACTED]")
        self.assertGreaterEqual(record.duration_ms, 0)
        self.assertEqual(record.request_bytes, len(request.data))
        self.assertEqual(record.response_bytes, len(result.body))

    def test_http_error_is_recorded_and_still_raised(self):
        with self.assertRaises(urllib.error.HTTPError):
            traffic.http_request(
                self.context,
                self.request("/failure"),
                timeout=1,
                action_type="page.fetch",
            )

        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.status, 403)
        self.assertEqual(record.error_class, "HTTPError")
        self.assertNotIn(CANARY, record.error_summary)
        self.assertIn("[REDACTED]", record.response_body.decode())

    def test_provider_request_records_malformed_json(self):
        with self.assertRaises(traffic.MalformedResponseError):
            traffic.provider_request(
                self.context,
                "openai",
                self.request("/malformed"),
                timeout=1,
                action_type="provider.chat",
            )

        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.status, 200)
        self.assertEqual(record.error_class, "MalformedResponseError")
        self.assertEqual(record.response_body, b"{not-json")

    def test_timeout_is_recorded_without_secret_exception_text(self):
        with self.assertRaises((TimeoutError, urllib.error.URLError)):
            traffic.http_request(
                self.context,
                self.request(f"/slow?token={CANARY}"),
                timeout=0.01,
                action_type="page.fetch",
            )

        record = self.recorder.list(self.session.session_id)[0]
        self.assertIsNone(record.status)
        self.assertIn(record.error_class, {"TimeoutError", "URLError"})
        self.assertNotIn(CANARY, record.error_summary)

    def test_cancelled_context_does_not_open_or_record_request(self):
        cancellation = threading.Event()
        cancellation.set()
        context = traffic.TrafficContext(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="correlation-1",
            recorder=self.recorder,
            redactor=redaction.Redactor([CANARY]),
            cancellation=cancellation,
        )

        with self.assertRaises(traffic.TrafficCancelled):
            traffic.http_request(
                context,
                self.request("/success"),
                timeout=1,
                action_type="page.fetch",
            )

        self.assertEqual(self.recorder.list(self.session.session_id), [])

    def test_canary_never_reaches_sqlite_files(self):
        with self.assertRaises(urllib.error.HTTPError):
            traffic.http_request(
                self.context,
                self.request(
                    f"/failure?access_token={CANARY}",
                    {"secret": CANARY},
                ),
                timeout=1,
                action_type="provider.chat",
            )

        session_dir = os.path.join(self.temp.name, self.session.session_id)
        for name in os.listdir(session_dir):
            if name.startswith("ledger.sqlite3"):
                with open(os.path.join(session_dir, name), "rb") as handle:
                    self.assertNotIn(CANARY.encode(), handle.read())

    def test_gateway_routes_provider_calls_through_recorder(self):
        with (
            mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": CANARY},
                clear=False,
            ),
            mock.patch.dict(
                gateway.PROVIDERS["openai"],
                {"url": f"{self.base_url}/chat"},
                clear=False,
            ),
        ):
            result = gateway.chat(
                "openai",
                [{"role": "user", "content": "hello"}],
                traffic_context=self.context,
            )

        self.assertEqual(result["text"], "grounded answer")
        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.method_or_action, "provider.chat")
        self.assertEqual(record.request_headers["authorization"], "[REDACTED]")

    def test_finder_routes_research_calls_through_recorder(self):
        result = finder._get(
            f"{self.base_url}/research?q=hello",
            traffic_context=self.context,
        )

        self.assertEqual(json.loads(result), {"source": "fixture"})
        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.method_or_action, "research.search")


if __name__ == "__main__":
    unittest.main()
