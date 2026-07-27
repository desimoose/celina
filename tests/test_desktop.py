import json
import os
import sys
import unittest
import urllib.request
from types import SimpleNamespace
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import desktop  # noqa: E402
import app  # noqa: E402


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

    def test_start_server_origin_matches_the_bound_security_origin(self):
        srv, port = desktop.start_server()
        try:
            self.assertEqual(
                srv.local_security.expected_origin,
                f"http://127.0.0.1:{port}",
            )
        finally:
            srv.shutdown()
            srv.server_close()


class LaunchOriginTest(unittest.TestCase):
    def test_desktop_uses_server_expected_origin_for_its_window(self):
        expected_origin = "http://[::1]:45678"
        server = SimpleNamespace(
            local_security=SimpleNamespace(expected_origin=expected_origin)
        )
        webview = SimpleNamespace(
            create_window=mock.Mock(),
            start=mock.Mock(),
        )

        with (
            mock.patch.object(desktop, "start_server", return_value=(server, 45678)),
            mock.patch.dict(sys.modules, {"webview": webview}),
        ):
            desktop.run()

        self.assertEqual(webview.create_window.call_args.args[1], expected_origin)

    def test_command_line_advertises_server_expected_origin(self):
        expected_origin = "http://127.0.0.1:45678"
        server = SimpleNamespace(
            server_address=("127.0.0.1", 45678),
            local_security=SimpleNamespace(expected_origin=expected_origin),
            serve_forever=mock.Mock(),
        )

        with (
            mock.patch.object(app, "make_server", return_value=server),
            mock.patch.object(app.gateway, "available", return_value=[]),
            mock.patch.object(app.tools, "status", return_value=[]),
            mock.patch("builtins.print") as printed,
        ):
            app.main()

        rendered = "\n".join(
            str(call.args[0]) for call in printed.call_args_list
        )
        self.assertIn(expected_origin, rendered)
        server.serve_forever.assert_called_once_with()


class ApiTest(unittest.TestCase):
    def test_open_external_only_http(self):
        import webbrowser

        import desktop
        calls = []
        orig = webbrowser.open
        webbrowser.open = lambda u: calls.append(u)
        try:
            api = desktop.Api()
            self.assertTrue(api.open_external("https://openrouter.ai/keys"))
            self.assertTrue(api.open_external("http://example.com"))
            self.assertFalse(api.open_external("file:///etc/passwd"))
            self.assertFalse(api.open_external("javascript:alert(1)"))
            self.assertFalse(api.open_external(123))
            self.assertEqual(
                calls, ["https://openrouter.ai/keys", "http://example.com"]
            )
        finally:
            webbrowser.open = orig


if __name__ == "__main__":
    unittest.main()
