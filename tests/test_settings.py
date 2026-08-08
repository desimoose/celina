import importlib
import json
import os
import sqlite3
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
        with open(env, encoding="utf-8") as fh:
            text = fh.read()
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
        with open(env, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("OPENAI_API_KEY=added", text)
        self.assertIn("XAI_API_KEY=keep", text)

    def test_clears_on_empty(self):
        home, app, _ = _fresh_home("rvb_set3")
        env = os.path.join(home, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("OPENAI_API_KEY=old\n")
        app.update_env({"OPENAI_API_KEY": ""})
        with open(env, encoding="utf-8") as fh:
            text = fh.read()
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


class SettingsUiSourceTest(unittest.TestCase):
    def test_empty_model_field_is_sent_to_clear_override(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web", "app.js"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn('if (el.value !== "") models[', source)
        self.assertIn('models[el.dataset.model] = el.value;', source)
        self.assertIn(
            'value="${p.model_overridden ? escapeHtml(p.model) : ""}"',
            source,
        )

    def test_privacy_ui_exposes_provider_disclosure_and_session_actions(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        with open(os.path.join(root, "web", "index.html"), encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn('session_retention_seconds', js)
        self.assertIn('provider_privacy', js)
        self.assertIn('Ollama — stays on this machine', js)
        self.assertIn('question/context sent to provider', js)
        self.assertIn('Incognito — deletes on end', js)
        self.assertIn('Auto-delete after 24 hours', js)
        self.assertIn('Delete current session', js)
        self.assertIn('/api/notebooks/export', js)
        self.assertIn('method: "DELETE"', js)
        self.assertIn('fetch("/api/notebooks"', js)
        self.assertIn('history: state.history.slice(0, -1)', js)
        self.assertIn('/study-set', js)
        self.assertIn('/study-set/review', js)
        self.assertIn('Again', html)
        self.assertIn('Got it', html)
        self.assertIn('study-mode', html)
        self.assertIn('session-badge', html)
        self.assertIn('learning-home', html)
        self.assertIn('/api/learning-home', js)

    def test_guided_study_session_uses_due_cards_tutor_and_notes(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        with open(os.path.join(root, "web", "index.html"), encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("guidedSession", js)
        self.assertIn("startGuidedSession", js)
        self.assertIn("/study-set/review", js)
        self.assertIn("/tutor", js)
        self.assertIn("/notes", js)
        self.assertIn("runGuidedQuiz", js)
        self.assertIn("data-guided-followup-rating", html)
        self.assertIn("guided-session", html)
        self.assertIn("guided-session-start", html)
        self.assertIn("guided-session-reveal", html)
        self.assertIn("guided-session-save-note", html)
        self.assertIn("Start guided session", html)

    def test_research_first_navigation_keeps_learning_as_secondary_depth(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "web", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-tooltip="Search and read"', html)
        self.assertIn('aria-label="Research workspace"', html)
        self.assertIn(">Workspace<", html)
        self.assertIn("Optional learning", html)
        self.assertIn("Save useful research", html)
        self.assertIn("Save and query sources", html)
        with open(os.path.join(root, "web", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('head.textContent = "Ask about your research"', js)
        self.assertIn('input").placeholder = "Ask a research question or paste a link"', js)


class SettingsRoutesTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CELINA_HOME", None)
        for k in (
            "OPENAI_API_KEY",
            "FINDER_CONTACT_EMAIL",
            "BOGUS_ENV",
            "CELINA_SESSION_RETENTION_SECONDS",
        ):
            os.environ.pop(k, None)

    def _serve(self, app):
        srv = app.make_server(port=0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port

    def _mutation_headers(self, srv):
        return {
            "Content-Type": "application/json",
            "Cookie": srv.local_security.launch_cookie_header.split(";", 1)[0],
            "X-Celina-CSRF": srv.local_security.csrf_token,
            "Origin": srv.local_security.expected_origin,
        }

    def _post(self, srv, port, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/settings",
            data=json.dumps(body).encode("utf-8"),
            headers=self._mutation_headers(srv),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_post_sets_key_live_and_persists(self):
        home, app, gateway = _fresh_home("rvb_routes1")
        srv, port = self._serve(app)
        try:
            self._post(srv, port, {"keys": {"OPENAI_API_KEY": "sk-livevalue99"}})
            self.assertEqual(gateway.key_for("openai"), "sk-livevalue99")
            with open(os.path.join(home, ".env"), encoding="utf-8") as fh:
                text = fh.read()
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
            self._post(srv, port, {"keys": {"BOGUS_ENV": "x"}})
            self.assertIsNone(os.environ.get("BOGUS_ENV"))
            with open(os.path.join(home, ".env"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("BOGUS_ENV", text)
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_rejects_non_string(self):
        _fresh_home("rvb_routes4")
        import app
        srv, port = self._serve(app)
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._post(srv, port, {"keys": {"OPENAI_API_KEY": 123}})
            self.assertEqual(ctx.exception.code, 400)
            ctx.exception.close()
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_rejects_missing_mutation_credentials(self):
        _fresh_home("rvb_routes4b")
        import app
        srv, port = self._serve(app)
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/settings",
                data=json.dumps({"finder_email": "hello@example.com"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 403)
            ctx.exception.close()
        finally:
            srv.shutdown(); srv.server_close()

    def test_get_exposes_session_retention_and_provider_privacy(self):
        _fresh_home("rvb_routes5")
        import app
        srv, port = self._serve(app)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/settings", timeout=5
            ) as r:
                body = json.loads(r.read().decode("utf-8"))

            self.assertEqual(body["session_retention_seconds"], 86400)
            self.assertEqual(
                body["provider_privacy"]["ollama"],
                "Ollama — stays on this machine",
            )
            self.assertIn("question/context sent to provider", body["provider_privacy"]["openai"])
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_persists_allowed_session_retention_seconds(self):
        home, app, _ = _fresh_home("rvb_routes6")
        srv, port = self._serve(app)
        try:
            for value in (0, 3600, 86400, 604800):
                with self.subTest(value=value):
                    response = self._post(
                        srv, port, {"session_retention_seconds": value}
                    )
                    self.assertEqual(response["session_retention_seconds"], value)
                    with open(os.path.join(home, ".env"), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertIn(
                        f"CELINA_SESSION_RETENTION_SECONDS={value}", text
                    )

            srv.shutdown()
            srv.server_close()

            os.environ.pop("CELINA_SESSION_RETENTION_SECONDS", None)
            importlib.reload(app)
            srv2, port2 = self._serve(app)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port2}/api/settings", timeout=5
                ) as r:
                    body = json.loads(r.read().decode("utf-8"))
                self.assertEqual(body["session_retention_seconds"], 604800)
            finally:
                srv2.shutdown(); srv2.server_close()
        finally:
            pass

    def test_post_rejects_invalid_session_retention_seconds(self):
        _fresh_home("rvb_routes7")
        import app
        srv, port = self._serve(app)
        try:
            for value in (-1, 1, 42, "86400"):
                with self.subTest(value=value):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/settings",
                        data=json.dumps(
                            {"session_retention_seconds": value}
                        ).encode("utf-8"),
                        headers=self._mutation_headers(srv),
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(ctx.exception.code, 400)
                    ctx.exception.close()
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_immediate_retention_triggers_cleanup(self):
        _fresh_home("rvb_routes8")
        import app
        srv, port = self._serve(app)
        try:
            stopped = srv.session_store.create()
            srv.session_store.mark_stopped(stopped.session_id)
            connection = sqlite3.connect(
                os.path.join(
                    srv.session_store.root,
                    stopped.session_id,
                    "ledger.sqlite3",
                )
            )
            try:
                connection.execute(
                    "UPDATE session SET last_active_at = ?",
                    ("2020-01-01T00:00:00.000Z",),
                )
                connection.commit()
            finally:
                connection.close()

            response = self._post(
                srv,
                port,
                {"session_retention_seconds": 0},
            )

            self.assertEqual(response["session_retention_seconds"], 0)
            self.assertIsNone(srv.session_store.get(stopped.session_id))
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
