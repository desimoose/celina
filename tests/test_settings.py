import importlib
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)


def _fresh_home(name):
    """Point CELINA_HOME at an empty temp dir and reload modules that
    cache paths, so nothing touches the real .env."""
    home = os.path.join(os.environ.get("TEMP", "/tmp"), name)
    if os.path.isdir(home):
        for root, _d, files in os.walk(home, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
    os.makedirs(home, exist_ok=True)
    os.environ["CELINA_HOME"] = home
    import paths
    importlib.reload(paths)
    import gateway
    importlib.reload(gateway)
    import app
    importlib.reload(app)
    return home, app, gateway


class UpdateEnvTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CELINA_HOME", None)
        for k in ("OPENAI_API_KEY", "XAI_API_KEY", "OPENROUTER_MODEL"):
            os.environ.pop(k, None)

    def test_updates_existing_line_in_place(self):
        home, app, _ = _fresh_home("rvb_set1")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("# comment\nOPENAI_API_KEY=old\nXAI_API_KEY=keep\n")
        app.update_env({"OPENAI_API_KEY": "new"})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=new", text)
        self.assertNotIn("OPENAI_API_KEY=old", text)
        self.assertIn("XAI_API_KEY=keep", text)   # unrelated key untouched
        self.assertIn("# comment", text)           # comment preserved

    def test_appends_new_key(self):
        home, app, _ = _fresh_home("rvb_set2")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("XAI_API_KEY=keep\n")
        app.update_env({"OPENAI_API_KEY": "added"})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=added", text)
        self.assertIn("XAI_API_KEY=keep", text)

    def test_clears_on_empty(self):
        home, app, _ = _fresh_home("rvb_set3")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("OPENAI_API_KEY=old\n")
        app.update_env({"OPENAI_API_KEY": ""})
        text = open(env, encoding="utf-8").read()
        self.assertIn("OPENAI_API_KEY=", text)
        self.assertNotIn("OPENAI_API_KEY=old", text)

    def test_mirrors_into_os_environ(self):
        _fresh_home("rvb_set4")
        import app
        app.update_env({"OPENROUTER_MODEL": "some/model"})
        self.assertEqual(os.environ.get("OPENROUTER_MODEL"), "some/model")


class SettingsStateTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CELINA_HOME", None)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_key_hint_masks_and_shortcircuits(self):
        _fresh_home("rvb_state1")
        import gateway
        os.environ["OPENAI_API_KEY"] = "sk-1234567890wxyz"
        self.assertEqual(gateway.key_hint("openai"), "wxyz")
        os.environ["OPENAI_API_KEY"] = "short"      # < 8 chars
        self.assertIsNone(gateway.key_hint("openai"))
        os.environ.pop("OPENAI_API_KEY")
        self.assertIsNone(gateway.key_hint("openai"))  # no key

    def test_settings_state_never_leaks_full_key(self):
        _fresh_home("rvb_state2")
        import gateway
        os.environ["OPENAI_API_KEY"] = "sk-secretvalue123"
        rows = {r["id"]: r for r in gateway.settings_state()}
        self.assertTrue(rows["openai"]["has_key"])
        self.assertEqual(rows["openai"]["key_hint"], "e123")
        self.assertNotIn("secret", json.dumps(rows))     # full key absent
        self.assertTrue(rows["ollama"]["local"])
        self.assertIsNone(rows["ollama"]["key_env"])


class SettingsRoutesTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CELINA_HOME", None)
        for k in ("OPENAI_API_KEY", "FINDER_CONTACT_EMAIL", "BOGUS_ENV"):
            os.environ.pop(k, None)

    def _serve(self, app):
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port

    def _post(self, port, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/settings",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_post_sets_key_live_and_persists(self):
        home, app, gateway = _fresh_home("rvb_routes1")
        srv, port = self._serve(app)
        try:
            self._post(port, {"keys": {"OPENAI_API_KEY": "sk-livevalue99"}})
            self.assertEqual(gateway.key_for("openai"), "sk-livevalue99")
            text = open(os.path.join(home, ".env"), encoding="utf-8").read()
            self.assertIn("OPENAI_API_KEY=sk-livevalue99", text)
        finally:
            srv.shutdown(); srv.server_close()

    def test_get_returns_masked_state(self):
        _fresh_home("rvb_routes2")
        import app
        os.environ["OPENAI_API_KEY"] = "sk-abcdefgh4444"
        srv, port = self._serve(app)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/settings", timeout=5
            ) as r:
                body = json.loads(r.read().decode("utf-8"))
            row = {p["id"]: p for p in body["providers"]}["openai"]
            self.assertTrue(row["has_key"])
            self.assertEqual(row["key_hint"], "4444")
            self.assertNotIn("abcdefgh", json.dumps(body))
            self.assertIn("finder_email", body)
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_ignores_non_whitelisted_env(self):
        home, app, _ = _fresh_home("rvb_routes3")
        srv, port = self._serve(app)
        try:
            self._post(port, {"keys": {"BOGUS_ENV": "x"}})
            self.assertIsNone(os.environ.get("BOGUS_ENV"))
            text = open(os.path.join(home, ".env"), encoding="utf-8").read()
            self.assertNotIn("BOGUS_ENV", text)
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_rejects_non_string(self):
        _fresh_home("rvb_routes4")
        import app
        srv, port = self._serve(app)
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(port, {"keys": {"OPENAI_API_KEY": 123}})
            self.assertEqual(ctx.exception.code, 400)
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
