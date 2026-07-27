import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import events  # noqa: E402
import orchestrator  # noqa: E402
import redaction  # noqa: E402
import sessions  # noqa: E402
import traffic  # noqa: E402
import tools  # noqa: E402


class SearchRuntimePlannerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.bus = events.EventBus(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_planner_failure_falls_back_to_direct_query(self):
        import search_runtime

        def unavailable_provider(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        request = orchestrator.SearchRequest(
            query="Does caffeine affect sleep?",
            provider="ollama",
            constraints={},
            session_id=self.session.session_id,
        )
        runtime = search_runtime.SearchRuntime(
            self.bus,
            self.store,
            chat_fn=unavailable_provider,
            scan_fn=lambda *_args, **_kwargs: {"results": []},
        )
        started = runtime.start(request)
        completed = runtime.wait(started.run_id, timeout=2)

        self.assertIsNotNone(completed)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(
            completed.query_plan.queries,
            ("Does caffeine affect sleep?",),
        )


class PageReaderTrafficTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.context = traffic.TrafficContext(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="run-1",
            recorder=traffic.TrafficRecorder(self.store),
            redactor=redaction.Redactor(),
        )

    def tearDown(self):
        self.temp.cleanup()

    @mock.patch("tools.traffic.http_request")
    def test_plain_page_fetch_records_with_the_supplied_context(
        self,
        recorded_request,
    ):
        recorded_request.return_value = traffic.HttpResult(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=b"<p>Complete readable body.</p>",
            traffic_event_id="traffic-1",
        )

        text = tools._fetch_plain(
            "https://example.test/plain",
            traffic_context=self.context,
        )

        recorded_request.assert_called_once_with(
            self.context,
            mock.ANY,
            timeout=45,
            action_type="page.fetch",
        )
        self.assertEqual(text, "<p>Complete readable body.</p>")

    @mock.patch("tools.obscura_dump", return_value="should not be read")
    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    def test_cancelled_context_does_not_start_a_page_read(
        self,
        _find_obscura,
        dump,
    ):
        cancellation = threading.Event()
        cancellation.set()
        context = traffic.TrafficContext(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="run-1",
            recorder=traffic.TrafficRecorder(self.store),
            redactor=redaction.Redactor(),
            cancellation=cancellation,
        )

        with self.assertRaises(traffic.TrafficCancelled):
            tools.fetch("https://example.test/cancelled", context)

        dump.assert_not_called()

    @mock.patch("tools.obscura_dump", return_value="Complete extracted body.")
    @mock.patch("tools.find_obscura", return_value=r"C:\\vendor\\obscura.exe")
    def test_fetch_forwards_traffic_context_to_page_read(
        self,
        _find_obscura,
        dump,
    ):
        page = tools.fetch("https://example.test/source", self.context)

        dump.assert_called_once_with(
            "https://example.test/source",
            dump="text",
            stealth=True,
            traffic_context=self.context,
            action_type="page.fetch",
        )
        self.assertEqual(page["text"], "Complete extracted body.")
        self.assertEqual(page["content_type"], "text/plain")

    @mock.patch("tools._fetch_obscura_pdf", return_value=("PDF body.", "pypdf"))
    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    def test_pdf_page_fetch_forwards_traffic_context(
        self,
        _find_obscura,
        pdf_fetch,
    ):
        page = tools.fetch("https://example.test/source.pdf", self.context)

        pdf_fetch.assert_called_once_with(
            r"C:\vendor\obscura.exe",
            "https://example.test/source.pdf",
            traffic_context=self.context,
        )
        self.assertEqual(page["text"], "PDF body.")
        self.assertEqual(page.get("content_type"), "application/pdf")


class SearchRuntimeEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.bus = events.EventBus(self.store)
        self.provider_contexts = []
        self.scanner_contexts = []
        self.reader_contexts = []
        self.synthesis_inputs = []

    def tearDown(self):
        self.temp.cleanup()

    def test_deterministic_run_shares_context_and_records_provider_usage(self):
        reply_index = 0

        def fake_provider(provider, messages, *, system, traffic_context):
            nonlocal reply_index
            reply_index += 1
            self.provider_contexts.append(traffic_context)
            if reply_index == 1:
                payload = {
                    "direct_query": "Does caffeine affect sleep?",
                    "additional_queries": [],
                    "evidence_angles": ["sleep onset"],
                    "summary": "Check controlled evidence on sleep onset.",
                }
            elif reply_index == 2:
                payload = {
                    "covered_angles": ["sleep onset"],
                    "gaps": [],
                    "conflicts": [],
                    "follow_up_query": None,
                }
            else:
                self.synthesis_inputs.append(messages[0]["content"])
                payload = {
                    "answer": "Evening caffeine delayed sleep onset [C1].",
                    "claims": [{
                        "claim_id": "claim-1",
                        "text": "Evening caffeine delayed sleep onset",
                        "citation_ids": ["C1"],
                    }],
                    "citations": ["C1"],
                    "uncertainties": [],
                    "conflicts": [],
                    "gaps": [],
                }
            return {
                "text": json.dumps(payload),
                "provider": provider,
                "model": "deterministic-model",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cached_input_tokens": 0,
                },
            }

        def fake_scan(query, *, traffic_context):
            self.scanner_contexts.append(traffic_context)
            return {"results": [{
                "title": "Controlled trial",
                "url": "https://example.test/trial",
                "kind": "research",
                "snippet": "UNTRUSTED RESULT SNIPPET never cite this.",
            }]}

        def fake_fetch(url, *, traffic_context):
            self.reader_contexts.append(traffic_context)
            return {
                "url": url,
                "text": "A controlled trial found evening caffeine delayed sleep onset.",
                "content_type": "text/html",
            }

        import search_runtime

        runtime = search_runtime.SearchRuntime(
            self.bus,
            self.store,
            chat_fn=fake_provider,
            scan_fn=fake_scan,
            fetch_fn=fake_fetch,
        )
        request = orchestrator.SearchRequest(
            query="Does caffeine affect sleep?",
            provider="ollama",
            constraints={},
            session_id=self.session.session_id,
        )
        started = runtime.start(request)
        completed = runtime.wait(started.run_id, timeout=2)

        self.assertEqual(completed.state, "completed")
        context = runtime.traffic_context(started.run_id)
        self.assertEqual(context.session_id, self.session.session_id)
        self.assertEqual(context.run_id, started.run_id)
        self.assertEqual(context.correlation_id, started.run_id)
        self.assertTrue(all(item is context for item in self.provider_contexts))
        self.assertEqual(self.scanner_contexts, [context])
        self.assertEqual(self.reader_contexts, [context])
        summary = runtime.token_accountant(started.run_id).summary(
            self.session.session_id
        )
        self.assertEqual(len(summary.records), 3)
        self.assertEqual(summary.input_tokens, 30)
        self.assertEqual(summary.output_tokens, 15)
        self.assertNotIn("UNTRUSTED RESULT SNIPPET", self.synthesis_inputs[0])
        self.assertEqual(completed.evidence[0].citation_id, "C1")

    def test_malformed_structured_provider_outputs_degrade_safely(self):
        responses = iter([
            "not valid json",
            json.dumps({
                "covered_angles": [],
                "gaps": ["long-term outcomes"],
                "conflicts": [],
                "follow_up_query": "look for outcomes",
            }),
            "[]",
        ])

        def fake_provider(provider, _messages, *, system, traffic_context):
            return {
                "text": next(responses),
                "provider": provider,
                "model": "deterministic-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        def fake_scan(query, *, traffic_context):
            return {"results": [{
                "title": "Readable source",
                "url": "https://example.test/readable",
                "kind": "research",
            }]}

        def fake_fetch(url, *, traffic_context):
            return {
                "url": url,
                "text": "The full extracted body provides usable evidence.",
                "content_type": "text/html",
            }

        import search_runtime

        runtime = search_runtime.SearchRuntime(
            self.bus,
            self.store,
            chat_fn=fake_provider,
            scan_fn=fake_scan,
            fetch_fn=fake_fetch,
        )
        request = orchestrator.SearchRequest(
            query="What does the evidence show?",
            provider="ollama",
            constraints={},
            session_id=self.session.session_id,
        )
        completed = runtime.wait(runtime.start(request).run_id, timeout=2)

        self.assertEqual(completed.state, "completed")
        self.assertEqual(completed.query_plan.queries, (request.query,))
        self.assertEqual(completed.follow_up_count, 0)
        self.assertIn("could not produce a structured answer", completed.answer["answer"])

    def test_cancellation_prevents_later_adapters_from_starting(self):
        planning_started = threading.Event()
        release_provider = threading.Event()
        provider_calls = []
        scanner_calls = []
        reader_calls = []

        def delayed_provider(provider, _messages, *, system, traffic_context):
            provider_calls.append(system)
            planning_started.set()
            release_provider.wait(1)
            return {
                "text": json.dumps({
                    "direct_query": "Does caffeine affect sleep?",
                    "additional_queries": [],
                    "evidence_angles": [],
                    "summary": "A public plan.",
                }),
                "provider": provider,
                "model": "deterministic-model",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        def fake_scan(query, *, traffic_context):
            scanner_calls.append(query)
            return {"results": []}

        def fake_fetch(url, *, traffic_context):
            reader_calls.append(url)
            return {"text": "unreachable", "content_type": "text/plain"}

        import search_runtime

        runtime = search_runtime.SearchRuntime(
            self.bus,
            self.store,
            chat_fn=delayed_provider,
            scan_fn=fake_scan,
            fetch_fn=fake_fetch,
        )
        request = orchestrator.SearchRequest(
            query="Does caffeine affect sleep?",
            provider="ollama",
            constraints={},
            session_id=self.session.session_id,
        )
        started = runtime.start(request)
        self.assertTrue(planning_started.wait(1))

        runtime.stop(started.run_id)
        release_provider.set()
        completed = runtime.wait(started.run_id, timeout=2)

        self.assertEqual(completed.state, "stopped")
        self.assertEqual(len(provider_calls), 1)
        self.assertEqual(scanner_calls, [])
        self.assertEqual(reader_calls, [])


if __name__ == "__main__":
    unittest.main()
