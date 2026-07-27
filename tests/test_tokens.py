import os
import sys
import tempfile
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import sessions  # noqa: E402
import tokens  # noqa: E402


class NormalizeUsageTest(unittest.TestCase):
    def test_normalizes_openai_compatible_usage(self):
        normalized = tokens.normalize_usage(
            "openai",
            {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        )

        self.assertEqual(normalized.input_tokens, 120)
        self.assertEqual(normalized.output_tokens, 30)
        self.assertEqual(normalized.cached_input_tokens, 40)
        self.assertFalse(normalized.is_estimated)

    def test_normalizes_anthropic_cache_usage(self):
        normalized = tokens.normalize_usage(
            "anthropic",
            {
                "input_tokens": 80,
                "output_tokens": 20,
                "cache_read_input_tokens": 45,
                "cache_creation_input_tokens": 10,
            },
        )

        self.assertEqual(normalized.input_tokens, 80)
        self.assertEqual(normalized.output_tokens, 20)
        self.assertEqual(normalized.cached_input_tokens, 55)
        self.assertFalse(normalized.is_estimated)

    def test_preserves_unknown_usage_instead_of_converting_to_zero(self):
        normalized = tokens.normalize_usage("ollama", {})

        self.assertIsNone(normalized.input_tokens)
        self.assertIsNone(normalized.output_tokens)
        self.assertIsNone(normalized.cached_input_tokens)
        self.assertFalse(normalized.is_estimated)


class TokenAccountantTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.accountant = tokens.TokenAccountant(
            self.store,
            self.session.session_id,
            context_limits={("openai", "model-a"): 1_000},
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_records_and_sums_usage_across_calls_and_models(self):
        first = self.accountant.record(
            "openai",
            "model-a",
            {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 25},
            "correlation-1",
        )
        second = self.accountant.record(
            "anthropic",
            "model-b",
            {
                "input_tokens": 50,
                "output_tokens": 10,
                "cached_input_tokens": 0,
            },
            "correlation-2",
        )

        self.assertFalse(first.is_estimated)
        self.assertEqual(first.context_percentage, 10.0)
        self.assertIsNone(second.context_percentage)

        summary = self.accountant.summary(self.session.session_id)
        self.assertEqual(summary.input_tokens, 150)
        self.assertEqual(summary.output_tokens, 30)
        self.assertEqual(summary.cached_input_tokens, 25)
        self.assertEqual(summary.total_tokens, 180)
        self.assertEqual(len(summary.records), 2)

    def test_summary_preserves_unknown_totals(self):
        self.accountant.record(
            "ollama",
            "local-model",
            {"input_tokens": None, "output_tokens": None},
            "correlation-1",
        )

        summary = self.accountant.summary(self.session.session_id)
        self.assertIsNone(summary.input_tokens)
        self.assertIsNone(summary.output_tokens)
        self.assertIsNone(summary.total_tokens)
        self.assertIsNone(summary.context_percentage)

    def test_known_and_unknown_counts_do_not_create_false_totals(self):
        self.accountant.record(
            "openai",
            "model-a",
            {"input_tokens": 100, "output_tokens": 20},
            "correlation-1",
        )
        self.accountant.record(
            "ollama",
            "local-model",
            {"input_tokens": None, "output_tokens": None},
            "correlation-2",
        )

        summary = self.accountant.summary(self.session.session_id)
        self.assertIsNone(summary.input_tokens)
        self.assertIsNone(summary.output_tokens)
        self.assertIsNone(summary.total_tokens)


if __name__ == "__main__":
    unittest.main()
