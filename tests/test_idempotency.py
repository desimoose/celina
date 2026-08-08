from contextlib import closing
import os
import sqlite3
import sys
import tempfile
import threading
import unittest


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import idempotency  # noqa: E402


class IdempotencyStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "idempotency.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_completed_response_replays_from_second_store(self):
        first = idempotency.IdempotencyStore(self.path)
        outcome, token, cached = first.begin("retry-1", "fingerprint-a")
        self.assertEqual((outcome, cached), ("new", None))
        first.complete(token, 201, b'{"created":true}', {"Content-Type": "application/json"})

        second = idempotency.IdempotencyStore(self.path)
        outcome, token, cached = second.begin("retry-1", "fingerprint-a")

        self.assertEqual(outcome, "replay")
        self.assertIsNone(token)
        self.assertEqual(cached, {
            "status": 201,
            "body": b'{"created":true}',
            "headers": {"Content-Type": "application/json"},
        })

    def test_different_fingerprint_conflicts_from_second_store(self):
        first = idempotency.IdempotencyStore(self.path)
        outcome, token, _cached = first.begin("retry-1", "fingerprint-a")
        self.assertEqual(outcome, "new")
        first.complete(token, 204, b"", {})

        second = idempotency.IdempotencyStore(self.path)
        self.assertEqual(
            second.begin("retry-1", "fingerprint-b"),
            ("conflict", None, None),
        )

    def test_expired_records_are_purged_during_begin(self):
        store = idempotency.IdempotencyStore(self.path, ttl_seconds=60)
        outcome, token, _cached = store.begin("expired", "fingerprint-a")
        self.assertEqual(outcome, "new")
        store.complete(token, 200, b"old", {})
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE idempotency_records SET updated_at = 0 WHERE key = ?",
                ("expired",),
            )
            connection.commit()

        store.begin("fresh", "fingerprint-b")

        with closing(sqlite3.connect(self.path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM idempotency_records WHERE key = ?",
                ("expired",),
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_two_stores_claiming_same_key_get_new_and_in_progress(self):
        stores = [
            idempotency.IdempotencyStore(self.path),
            idempotency.IdempotencyStore(self.path),
        ]
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def claim(store):
            try:
                barrier.wait(timeout=5)
                outcomes.append(store.begin("shared-key", "same-fingerprint")[0])
            except Exception as exc:  # surfaced by the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=claim, args=(store,)) for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), ["in_progress", "new"])

    def test_oldest_records_are_capped(self):
        store = idempotency.IdempotencyStore(self.path, max_records=2)
        for index in range(3):
            outcome, token, _cached = store.begin(
                "key-%s" % index,
                "fingerprint-%s" % index,
            )
            self.assertEqual(outcome, "new")
            store.complete(token, 200, str(index).encode("ascii"), {})

        with closing(sqlite3.connect(self.path)) as connection:
            keys = {
                row[0]
                for row in connection.execute(
                    "SELECT key FROM idempotency_records"
                ).fetchall()
            }
        self.assertEqual(keys, {"key-1", "key-2"})

    def test_oversized_response_is_not_cached(self):
        store = idempotency.IdempotencyStore(self.path)
        outcome, token, _cached = store.begin("retry-1", "fingerprint-a")
        self.assertEqual(outcome, "new")

        with self.assertRaisesRegex(ValueError, "cached response body too large"):
            store.complete(
                token,
                200,
                b"x" * (idempotency.MAX_CACHED_RESPONSE_BYTES + 1),
                {},
            )

    def test_request_payload_is_not_stored_beyond_fingerprint(self):
        secret = "do-not-store-this-request-secret"
        store = idempotency.IdempotencyStore(self.path)
        request_fingerprint = idempotency.fingerprint(
            "POST",
            "/api/example",
            '{"secret":"%s"}' % secret,
        )

        store.begin("retry-1", request_fingerprint)

        with open(self.path, "rb") as database:
            self.assertNotIn(secret.encode("utf-8"), database.read())


if __name__ == "__main__":
    unittest.main()
