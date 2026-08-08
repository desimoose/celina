import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import sessions  # noqa: E402


def _event(session_id, number):
    return {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "run_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": f"2026-07-26T22:00:{number % 60:02d}.000Z",
        "kind": "search.started",
        "phase": "planning",
        "severity": "info",
        "summary": f"event {number}",
        "details": {"number": number},
        "traffic_event_ids": [],
    }


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_and_reopen_session(self):
        created = self.store.create(content_recording=True)
        self.assertEqual(created.state, "active")
        self.assertTrue(created.content_recording)
        self.assertTrue(os.path.isfile(
            os.path.join(self.temp.name, created.session_id, "ledger.sqlite3")
        ))

        reopened = sessions.SessionStore(self.temp.name).get(created.session_id)
        self.assertEqual(reopened.session_id, created.session_id)
        self.assertEqual(reopened.created_at, created.created_at)
        self.assertEqual(reopened.state, "active")

    def test_incognito_session_is_marked_and_reopened(self):
        created = self.store.create(incognito=True)
        self.assertTrue(created.incognito)
        self.assertTrue(os.path.isfile(
            os.path.join(self.temp.name, created.session_id, ".incognito")
        ))
        reopened = sessions.SessionStore(self.temp.name).get(created.session_id)
        self.assertTrue(reopened.incognito)

    def test_cleanup_deletes_expired_and_stopped_incognito_sessions(self):
        old = self.store.create()
        self.store.mark_stopped(old.session_id)
        connection = sqlite3.connect(os.path.join(self.temp.name, old.session_id, "ledger.sqlite3"))
        try:
            connection.execute(
                "UPDATE session SET last_active_at = ?",
                ("2020-01-01T00:00:00.000Z",),
            )
            connection.commit()
        finally:
            connection.close()
        recent = self.store.create()
        self.store.mark_stopped(recent.session_id)
        incognito = self.store.create(incognito=True)
        stopped_incognito = self.store.create(incognito=True)
        self.store.mark_stopped(stopped_incognito.session_id)

        removed = self.store.cleanup(retention_seconds=3600)

        self.assertEqual(set(removed), {old.session_id, stopped_incognito.session_id})
        self.assertIsNone(self.store.get(old.session_id))
        self.assertIsNotNone(self.store.get(recent.session_id))
        self.assertIsNotNone(self.store.get(incognito.session_id))
        self.assertIsNone(self.store.get(stopped_incognito.session_id))

    def test_cleanup_can_remove_orphaned_active_incognito_on_startup(self):
        incognito = self.store.create(incognito=True)

        removed = self.store.cleanup(
            retention_seconds=3600,
            include_active_incognito=True,
        )

        self.assertEqual(removed, [incognito.session_id])
        self.assertIsNone(self.store.get(incognito.session_id))

    def test_active_session_is_recoverable_after_restart(self):
        created = self.store.create()
        recovered = sessions.SessionStore(
            self.temp.name
        ).list_recoverable()
        self.assertEqual([item.session_id for item in recovered], [
            created.session_id
        ])
        self.assertTrue(recovered[0].recovery_required)

    def test_state_changes_persist(self):
        created = self.store.create()
        stopped = self.store.mark_stopped(created.session_id)
        self.assertEqual(stopped.state, "stopped")
        self.assertEqual(
            sessions.SessionStore(self.temp.name).get(
                created.session_id
            ).state,
            "stopped",
        )

    def test_event_sequences_are_unique_and_monotonic_across_threads(self):
        created = self.store.create()
        sequences = []
        lock = threading.Lock()

        def write_batch(offset):
            local = []
            for number in range(offset, offset + 10):
                local.append(self.store.append_event(
                    _event(created.session_id, number)
                ))
            with lock:
                sequences.extend(local)

        threads = [
            threading.Thread(target=write_batch, args=(index * 10,))
            for index in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(sequences), list(range(1, 81)))
        stored = self.store.list_events(created.session_id)
        self.assertEqual(
            [event["sequence"] for event in stored],
            list(range(1, 81)),
        )

    def test_audit_deleted_reports_only_safe_residue_metadata(self):
        created = self.store.create()
        directory = os.path.join(self.temp.name, created.session_id)
        extracted = os.path.join(directory, "extracted")
        os.makedirs(extracted)
        with open(os.path.join(extracted, "page.txt"), "w", encoding="utf-8") as fh:
            fh.write("temporary evidence")
        with open(os.path.join(directory, "search.tmp"), "w", encoding="utf-8") as fh:
            fh.write("temporary query")
        self.store.append_event(_event(created.session_id, 1))
        for suffix in ("-wal", "-shm"):
            with open(
                os.path.join(directory, "ledger.sqlite3" + suffix),
                "wb",
            ) as fh:
                fh.write(b"temporary")

        before = self.store.audit_deleted(created.session_id)

        self.assertEqual(before, {
            "directory_exists": True,
            "ledger_exists": True,
            "sidecar_count": 2,
            "sqlite_row_exists": True,
            "deletion_failure_marker_exists": False,
        })
        self.assertTrue(all(
            isinstance(value, (bool, int)) for value in before.values()
        ))

        result = self.store.delete(created.session_id)

        self.assertTrue(result.deleted)
        self.assertEqual(result.errors, ())
        self.assertEqual(self.store.audit_deleted(created.session_id), {
            "directory_exists": False,
            "ledger_exists": False,
            "sidecar_count": 0,
            "sqlite_row_exists": False,
            "deletion_failure_marker_exists": False,
        })

    def test_delete_does_not_touch_notebook_files(self):
        notebooks = os.path.join(self.temp.name, "notebooks")
        os.makedirs(notebooks)
        kept = os.path.join(notebooks, "kept-notebook.json")
        with open(kept, "w", encoding="utf-8") as fh:
            fh.write('{"title":"keep me"}')
        created = self.store.create()

        self.store.delete(created.session_id)

        self.assertTrue(os.path.isfile(kept))
        with open(kept, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), '{"title":"keep me"}')

    def test_incomplete_delete_is_not_success_and_keeps_safe_marker(self):
        created = self.store.create()
        directory = os.path.join(self.temp.name, created.session_id)
        with open(os.path.join(directory, "private.tmp"), "w", encoding="utf-8") as fh:
            fh.write("private session evidence")

        with mock.patch.object(
            sessions.shutil,
            "rmtree",
            side_effect=OSError("private session evidence at a secret path"),
        ):
            result = self.store.delete(created.session_id)

        self.assertFalse(result.deleted)
        self.assertEqual(result.errors, ("local session residue remains",))
        audit = self.store.audit_deleted(created.session_id)
        self.assertTrue(audit["directory_exists"])
        self.assertTrue(audit["deletion_failure_marker_exists"])
        markers = [
            name for name in os.listdir(self.temp.name)
            if name.startswith(".delete-failed-")
        ]
        self.assertEqual(len(markers), 1)
        with open(os.path.join(self.temp.name, markers[0]), encoding="utf-8") as fh:
            marker_text = fh.read()
        self.assertNotIn("private session evidence", marker_text)
        self.assertNotIn(directory, marker_text)

    def test_delete_does_not_start_without_a_safe_failure_marker(self):
        created = self.store.create()

        with mock.patch.object(
            sessions.storage,
            "atomic_write_json",
            side_effect=OSError("marker unavailable"),
        ):
            result = self.store.delete(created.session_id)

        self.assertFalse(result.deleted)
        self.assertEqual(result.errors, ("local deletion could not start",))
        audit = self.store.audit_deleted(created.session_id)
        self.assertTrue(audit["directory_exists"])
        self.assertTrue(audit["ledger_exists"])
        self.assertTrue(audit["sqlite_row_exists"])
        self.assertFalse(audit["deletion_failure_marker_exists"])


if __name__ == "__main__":
    unittest.main()
