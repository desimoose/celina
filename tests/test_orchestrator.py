import os
import sys
import tempfile
import threading
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import events  # noqa: E402
import orchestrator  # noqa: E402
import sessions  # noqa: E402
import verification  # noqa: E402


class FakePlanner:
    def __call__(self, request):
        return {
            "queries": [
                request.query,
                f"{request.query} primary evidence",
                f"{request.query} recent",
                "extra one",
                "extra two",
                "must be trimmed",
            ],
            "angles": ["primary evidence", "recency"],
            "summary": "Separated primary evidence from recency.",
        }


def candidate(number, query_id="q1"):
    return {
        "title": f"Source {number}",
        "url": f"https://example.org/{number}",
        "kind": "web",
        "snippet": f"Snippet {number}",
        "query_id": query_id,
    }


class SearchRunStateTest(unittest.TestCase):
    def test_rejects_invalid_transition(self):
        run = orchestrator.SearchRun.create("session-1", "question")

        with self.assertRaises(orchestrator.InvalidTransition):
            run.transition("completed")


class SearchOrchestratorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.bus = events.EventBus(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def request(self):
        return orchestrator.SearchRequest(
            query="Does caffeine affect sleep?",
            provider="ollama",
            constraints={},
            session_id=self.session.session_id,
        )

    def make_orchestrator(
        self,
        retriever=None,
        reader=None,
        gap_checker=None,
        synthesizer=None,
        verifier=None,
    ):
        return orchestrator.SearchOrchestrator(
            event_bus=self.bus,
            planner=FakePlanner(),
            retriever=retriever or (
                lambda query, query_id, _request, _cancel: [
                    candidate(query_id, query_id)
                ]
            ),
            reader=reader or (
                lambda item, _request, _cancel: {
                    "text": (
                        f"Retrieved body for {item.title}; this is full page "
                        "content and not a search-result snippet."
                    ),
                    "content_type": "text/html",
                }
            ),
            gap_checker=gap_checker or (
                lambda _request, _evidence, _angles: {
                    "gaps": [],
                    "conflicts": [],
                    "follow_up_query": None,
                }
            ),
            synthesizer=synthesizer or (
                lambda _request, evidence_rows, _gaps: {
                    "answer": f"Grounded in {len(evidence_rows)} read sources.",
                    "citations": [row.citation_id for row in evidence_rows],
                }
            ),
            verifier=verifier,
            max_selected_sources=3,
        )

    def test_completes_bounded_run_and_uses_only_read_evidence(self):
        engine = self.make_orchestrator()

        started = engine.start(self.request())
        completed = engine.wait(started.run_id, timeout=2)

        self.assertEqual(completed.state, "completed")
        self.assertLessEqual(len(completed.query_plan.queries), 5)
        self.assertEqual(completed.query_plan.queries[0], self.request().query)
        self.assertTrue(completed.evidence)
        self.assertTrue(all(item.was_read for item in completed.evidence))
        self.assertNotIn("Snippet", completed.answer["answer"])

    def test_stop_prevents_late_response_from_starting_next_phase(self):
        entered = threading.Event()
        release = threading.Event()
        reader_calls = []

        def retriever(query, query_id, request, cancellation):
            entered.set()
            release.wait(1)
            return [candidate(1, query_id)]

        def reader(*args):
            reader_calls.append(args)
            return {"text": "should not run", "content_type": "text/plain"}

        engine = self.make_orchestrator(retriever=retriever, reader=reader)
        started = engine.start(self.request())
        self.assertTrue(entered.wait(1))

        engine.stop(started.run_id)
        release.set()
        stopped = engine.wait(started.run_id, timeout=2)

        self.assertEqual(stopped.state, "stopped")
        self.assertEqual(reader_calls, [])
        kinds = [
            item["kind"]
            for item in self.store.list_events(self.session.session_id)
        ]
        self.assertIn("search.stopped", kinds)
        self.assertNotIn("source.read.started", kinds)

    def test_one_source_failure_is_isolated(self):
        def retriever(query, query_id, request, cancellation):
            if query_id != "q1":
                return []
            return [candidate(1, query_id), candidate(2, query_id)]

        def reader(item, request, cancellation):
            if item.title == "Source 1":
                raise RuntimeError("blocked")
            return {
                "text": "A useful retrieved page body that supports synthesis.",
                "content_type": "text/html",
            }

        engine = self.make_orchestrator(retriever=retriever, reader=reader)
        completed = engine.wait(engine.start(self.request()).run_id, timeout=2)

        self.assertEqual(completed.state, "completed")
        self.assertEqual(len(completed.evidence), 1)
        kinds = [
            item["kind"]
            for item in self.store.list_events(self.session.session_id)
        ]
        self.assertIn("source.read.blocked", kinds)
        self.assertIn("synthesis.completed", kinds)

    def test_follow_up_never_exceeds_one_round(self):
        calls = []

        def retriever(query, query_id, request, cancellation):
            calls.append((query, query_id))
            return [candidate(len(calls), query_id)]

        def gap_checker(request, evidence_rows, angles):
            return {
                "gaps": ["missing long-term evidence"],
                "conflicts": [],
                "follow_up_query": "caffeine long-term sleep evidence",
            }

        engine = self.make_orchestrator(
            retriever=retriever,
            gap_checker=gap_checker,
        )
        completed = engine.wait(engine.start(self.request()).run_id, timeout=2)

        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.follow_up_count, 1)
        follow_ups = [
            item
            for item in self.store.list_events(self.session.session_id)
            if item["kind"] == "follow_up.started"
        ]
        self.assertEqual(len(follow_ups), 1)

    def test_event_summaries_come_from_public_templates(self):
        engine = self.make_orchestrator()
        completed = engine.wait(engine.start(self.request()).run_id, timeout=2)
        self.assertEqual(completed.state, "completed")

        stored = self.store.list_events(self.session.session_id)
        for item in stored:
            template = orchestrator.STATUS_TEMPLATES[item["kind"]]
            self.assertTrue(template.matches(item["summary"]))

    def test_verification_correction_remains_visible_in_trace(self):
        class RejectingVerifier:
            def verify(self, answer, evidence_rows):
                return verification.VerificationResult(
                    claims=(verification.ClaimVerification(
                        claim_id="claim-1",
                        text="Unsupported claim",
                        citation_ids=("C99",),
                        status="rejected",
                        supporting_passage=None,
                        reason="citation does not exist",
                    ),),
                    rejected_citations=("C99",),
                    corrected_answer="Grounded answer.\n\n> Verification note: removed.",
                    unresolved_conflicts=(),
                )

        engine = self.make_orchestrator(verifier=RejectingVerifier())
        completed = engine.wait(engine.start(self.request()).run_id, timeout=2)

        self.assertEqual(
            completed.answer["answer"],
            "Grounded answer.\n\n> Verification note: removed.",
        )
        kinds = [
            item["kind"]
            for item in self.store.list_events(self.session.session_id)
        ]
        self.assertIn("citation.rejected", kinds)
        self.assertIn("answer.corrected", kinds)


if __name__ == "__main__":
    unittest.main()
