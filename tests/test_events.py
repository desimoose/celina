import os
import sys
import tempfile
import threading
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import events  # noqa: E402
import sessions  # noqa: E402


class EventTest(unittest.TestCase):
    def test_create_validates_kind_phase_and_severity(self):
        event = events.Event.create(
            session_id="session-1",
            run_id="run-1",
            correlation_id="correlation-1",
            kind="search.started",
            phase="planning",
            summary="I started planning the search.",
        )
        self.assertEqual(event.kind, "search.started")
        self.assertEqual(event.severity, "info")
        self.assertTrue(event.event_id)
        self.assertTrue(event.occurred_at.endswith("Z"))

        for field, value in (
            ("kind", "model.private-thought"),
            ("phase", "daydreaming"),
            ("severity", "loud"),
        ):
            args = {
                "session_id": "session-1",
                "run_id": "run-1",
                "correlation_id": "correlation-1",
                "kind": "search.started",
                "phase": "planning",
                "severity": "info",
                "summary": "valid summary",
            }
            args[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    events.Event.create(**args)

    def test_details_must_be_json_serializable(self):
        with self.assertRaises(ValueError):
            events.Event.create(
                session_id="session-1",
                run_id="run-1",
                correlation_id="correlation-1",
                kind="search.started",
                phase="planning",
                summary="invalid details",
                details={"bad": object()},
            )


class EventBusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.bus = events.EventBus(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def make_event(self, summary):
        return events.Event.create(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="correlation-1",
            kind="search.started",
            phase="planning",
            summary=summary,
        )

    def test_publish_persists_before_delivering(self):
        subscription = self.bus.subscribe(self.session.session_id)
        published = self.bus.publish(self.make_event("first"))
        delivered = subscription.get(timeout=1)

        stored = self.store.list_events(self.session.session_id)
        self.assertEqual(stored[0]["event_id"], delivered.event_id)
        self.assertEqual(delivered.sequence, published.sequence)
        self.assertEqual(delivered.sequence, 1)
        subscription.close()

    def test_subscribe_resumes_after_sequence_without_duplicates(self):
        first = self.bus.publish(self.make_event("first"))
        second = self.bus.publish(self.make_event("second"))

        subscription = self.bus.subscribe(
            self.session.session_id,
            after_sequence=first.sequence,
        )

        self.assertEqual(subscription.get(timeout=1).event_id, second.event_id)
        self.assertIsNone(subscription.get(timeout=0.01))
        subscription.close()

    def test_concurrent_publish_preserves_transactional_order(self):
        published = []
        lock = threading.Lock()

        def publish(number):
            item = self.bus.publish(self.make_event(f"event {number}"))
            with lock:
                published.append(item)

        threads = [
            threading.Thread(target=publish, args=(number,))
            for number in range(30)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(
            sorted(item.sequence for item in published),
            list(range(1, 31)),
        )
        stored = self.store.list_events(self.session.session_id)
        self.assertEqual(
            [item["sequence"] for item in stored],
            list(range(1, 31)),
        )

    def test_closed_subscription_receives_no_more_events(self):
        subscription = self.bus.subscribe(self.session.session_id)
        subscription.close()
        self.bus.publish(self.make_event("after close"))
        self.assertIsNone(subscription.get(timeout=0.01))
        self.assertEqual(self.bus.subscriber_count(self.session.session_id), 0)


if __name__ == "__main__":
    unittest.main()
