import os
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
