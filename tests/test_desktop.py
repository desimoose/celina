import json
import os
import sys
import unittest
import urllib.request

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import desktop  # noqa: E402


class StartServerTest(unittest.TestCase):
    def test_start_server_returns_live_loopback_server(self):
        srv, port = desktop.start_server()
        try:
            self.assertGreater(port, 0)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/config", timeout=5
            ) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("providers", json.loads(resp.read().decode("utf-8")))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
