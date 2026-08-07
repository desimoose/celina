import json
import os
import sys
import threading
import unittest
import urllib.request
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402


class MakeServerTest(unittest.TestCase):
    def test_ephemeral_port_is_bound(self):
        srv = app.make_server(port=0)
        try:
            port = srv.server_address[1]
            self.assertGreater(port, 0)
            self.assertEqual(srv.server_address[0], "127.0.0.1")
        finally:
            srv.server_close()

    def test_serves_config_endpoint(self):
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/config", timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertIn("providers", body)
                self.assertIn("tools", body)
        finally:
            srv.shutdown()
            srv.server_close()

    @mock.patch.object(app.update_check, "check")
    def test_serves_update_check_endpoint(self, check):
        check.return_value = {
            "current": "0.1.0", "latest": "0.2.0",
            "update_available": True, "url": "https://example.test/releases",
        }
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/update-check", timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(json.loads(resp.read()), check.return_value)
        finally:
            srv.shutdown()
            srv.server_close()


class SeedEnvTest(unittest.TestCase):
    def test_seeds_when_absent_and_never_overwrites(self):
        tmp = os.path.join(
            os.environ.get("TEMP", "/tmp"), "celina_seed_test.env"
        )
        if os.path.exists(tmp):
            os.remove(tmp)
        app.seed_env(tmp)
        self.assertTrue(os.path.isfile(tmp))
        with open(tmp, "r", encoding="utf-8") as fh:
            first = fh.read()
        self.assertIn("OPENROUTER_API_KEY", first)
        # Second call must not clobber user edits.
        with open(tmp, "a", encoding="utf-8") as fh:
            fh.write("\nUSER_EDIT=1\n")
        app.seed_env(tmp)
        with open(tmp, "r", encoding="utf-8") as fh:
            second = fh.read()
        self.assertIn("USER_EDIT=1", second)
        os.remove(tmp)


if __name__ == "__main__":
    unittest.main()
