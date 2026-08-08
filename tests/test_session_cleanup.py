import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import app  # noqa: E402
import sessions  # noqa: E402


class SessionJanitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _make_stopped(self, incognito=False, last_active_at="2020-01-01T00:00:00.000Z"):
        created = self.store.create(incognito=incognito)
        self.store.mark_stopped(created.session_id)
        connection = sqlite3.connect(
            os.path.join(self.temp.name, created.session_id, "ledger.sqlite3")
        )
        try:
            connection.execute(
                "UPDATE session SET last_active_at = ?",
                (last_active_at,),
            )
            connection.commit()
        finally:
            connection.close()
        return created.session_id

    def test_run_once_removes_expired_stopped_and_preserves_active_incognito(self):
        active = self.store.create()
        recent = self._make_stopped(
            last_active_at=datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")
        )
        expired = self._make_stopped()
        active_incognito = self.store.create(incognito=True)
        stopped_incognito = self._make_stopped(incognito=True)
        notebooks = os.path.join(self.temp.name, "notebooks")
        os.makedirs(notebooks)
        notebook = os.path.join(notebooks, "kept-notebook.json")
        with open(notebook, "w", encoding="utf-8") as handle:
            handle.write('{"title":"keep me"}')

        janitor = app.SessionJanitor(
            self.store,
            retention_provider=lambda: 3600,
            interval_seconds=0.01,
        )
        removed = janitor.run_once()

        self.assertEqual(set(removed), {expired, stopped_incognito})
        self.assertIsNotNone(self.store.get(active.session_id))
        self.assertIsNotNone(self.store.get(recent))
        self.assertIsNone(self.store.get(expired))
        self.assertIsNotNone(self.store.get(active_incognito.session_id))
        self.assertIsNone(self.store.get(stopped_incognito))
        self.assertFalse(any(self.store.audit_deleted(expired).values()))
        self.assertFalse(any(self.store.audit_deleted(stopped_incognito).values()))
        with open(notebook, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"title":"keep me"}')

    def test_startup_cleanup_removes_orphaned_active_incognito(self):
        active_incognito = self.store.create(incognito=True)

        janitor = app.SessionJanitor(
            self.store,
            retention_provider=lambda: 3600,
            interval_seconds=0.01,
        )
        removed = janitor.run_once(include_active_incognito=True)

        self.assertEqual(removed, [active_incognito.session_id])
        self.assertIsNone(self.store.get(active_incognito.session_id))

    def test_janitor_retries_a_marked_incomplete_deletion(self):
        expired = self._make_stopped()
        janitor = app.SessionJanitor(
            self.store,
            retention_provider=lambda: 3600,
            interval_seconds=0.01,
        )

        with mock.patch.object(
            sessions.shutil,
            "rmtree",
            side_effect=OSError("filesystem busy"),
        ):
            first_removed = janitor.run_once()

        self.assertEqual(first_removed, [])
        self.assertTrue(
            self.store.audit_deleted(expired)["deletion_failure_marker_exists"]
        )

        second_removed = janitor.run_once()

        self.assertEqual(second_removed, [expired])
        self.assertFalse(any(self.store.audit_deleted(expired).values()))


class ServerJanitorLifecycleTest(unittest.TestCase):
    def test_server_close_returns_while_cleanup_is_blocked(self):
        temp = tempfile.TemporaryDirectory()
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        failures = []

        class BlockingStore:
            def cleanup(self, _retention_seconds, include_active_incognito=False):
                entered.set()
                release.wait(5)
                return []

        srv = app.make_server(port=0, session_root=temp.name)
        original = srv.session_janitor
        original.stop()
        original.join()
        janitor = app.SessionJanitor(
            BlockingStore(),
            retention_provider=lambda: 3600,
            interval_seconds=0.01,
        )
        srv.session_janitor = janitor
        janitor.start()
        try:
            self.assertTrue(entered.wait(1))

            def close_server():
                try:
                    srv.server_close()
                except Exception as exc:  # pragma: no cover
                    failures.append(exc)
                finally:
                    finished.set()

            started_at = time.monotonic()
            worker = threading.Thread(target=close_server, daemon=True)
            worker.start()

            self.assertTrue(
                finished.wait(0.5),
                "server_close should not block on janitor cleanup",
            )
            self.assertLess(time.monotonic() - started_at, 1.0)
            self.assertEqual(failures, [])
        finally:
            release.set()
            finished.wait(2)
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
