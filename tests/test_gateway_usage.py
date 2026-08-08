import io
import os
import sys
import unittest
import urllib.error
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import gateway  # noqa: E402


class GatewayUsageTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False)
    @mock.patch("gateway._post")
    def test_anthropic_normalizes_cache_usage(self, post):
        post.return_value = {
            "content": [{"type": "text", "text": "answer"}],
            "usage": {
                "input_tokens": 80,
                "output_tokens": 20,
                "cache_read_input_tokens": 45,
                "cache_creation_input_tokens": 10,
            },
        }

        result = gateway.chat("anthropic", [{"role": "user", "content": "hi"}])

        self.assertEqual(result["usage"]["input_tokens"], 80)
        self.assertEqual(result["usage"]["output_tokens"], 20)
        self.assertEqual(result["usage"]["cached_input_tokens"], 55)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    @mock.patch("gateway._post")
    def test_openai_normalizes_prompt_token_details(self, post):
        post.return_value = {
            "choices": [{"message": {"content": "answer"}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
        }

        result = gateway.chat("openai", [{"role": "user", "content": "hi"}])

        self.assertEqual(result["usage"]["input_tokens"], 120)
        self.assertEqual(result["usage"]["output_tokens"], 30)
        self.assertEqual(result["usage"]["cached_input_tokens"], 40)


class GatewayFailureTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    @mock.patch("gateway.urllib.request.urlopen")
    def test_provider_timeout_has_a_bounded_safe_summary(self, urlopen):
        secret = "sk-timeout-secret-value"
        urlopen.side_effect = TimeoutError(secret + ("x" * 2000))

        with self.assertRaises(gateway.GatewayError) as raised:
            gateway.chat("openai", [{"role": "user", "content": "hi"}])

        summary = str(raised.exception)
        self.assertEqual(summary, "openai request timed out")
        self.assertLessEqual(len(summary), gateway.MAX_ERROR_SUMMARY_CHARS)
        self.assertNotIn(secret, summary)
        urlopen.assert_called_once_with(mock.ANY, timeout=gateway.TIMEOUT)

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    @mock.patch("gateway.urllib.request.urlopen")
    def test_provider_http_error_does_not_expose_response_body(self, urlopen):
        secret = "sk-http-error-secret"
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.example.test/chat",
            401,
            "unauthorized",
            {},
            io.BytesIO((secret + " raw provider response").encode("utf-8")),
        )

        with self.assertRaises(gateway.GatewayError) as raised:
            gateway.chat("openai", [{"role": "user", "content": "hi"}])

        self.assertEqual(str(raised.exception), "openai returned HTTP 401")
        self.assertNotIn(secret, str(raised.exception))

    @mock.patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "sk-configured-secret-value"},
        clear=False,
    )
    def test_public_error_summary_redacts_configured_keys(self):
        error = gateway.GatewayError(
            "upstream failed with sk-configured-secret-value" + ("y" * 1000)
        )

        summary = gateway.safe_error_summary(error, provider="openai")

        self.assertNotIn("sk-configured-secret-value", summary)
        self.assertLessEqual(len(summary), gateway.MAX_ERROR_SUMMARY_CHARS)


if __name__ == "__main__":
    unittest.main()
