import json
import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import redaction  # noqa: E402


class RedactorTest(unittest.TestCase):
    def setUp(self):
        self.secret = "canary-secret-value-123"
        self.redactor = redaction.Redactor([self.secret])

    def assertSecretAbsent(self, value):
        self.assertNotIn(self.secret, repr(value))

    def test_redacts_sensitive_headers_case_insensitively(self):
        headers = self.redactor.redact_headers({
            "Authorization": "Bearer " + self.secret,
            "x-api-key": self.secret,
            "Cookie": "session=" + self.secret,
            "Content-Type": "application/json",
        })
        self.assertEqual(headers["Authorization"], "[REDACTED]")
        self.assertEqual(headers["x-api-key"], "[REDACTED]")
        self.assertEqual(headers["Cookie"], "[REDACTED]")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertSecretAbsent(headers)

    def test_redacts_secret_query_parameters_and_values(self):
        url = (
            "https://example.com/search?q=sleep"
            "&api_key=" + self.secret + "&note=" + self.secret
        )
        result = self.redactor.redact_url(url)
        self.assertIn("q=sleep", result)
        self.assertNotIn(self.secret, result)
        self.assertGreaterEqual(result.count("%5BREDACTED%5D"), 2)

    def test_redacts_nested_json_keys_and_configured_secrets(self):
        body = json.dumps({
            "prompt": "use " + self.secret,
            "authorization": "Bearer hidden",
            "nested": {"api_key": "hidden", "safe": "keep"},
        }).encode()
        result = self.redactor.redact_body("application/json", body)
        parsed = json.loads(result.body.decode())
        self.assertEqual(parsed["authorization"], "[REDACTED]")
        self.assertEqual(parsed["nested"]["api_key"], "[REDACTED]")
        self.assertEqual(parsed["nested"]["safe"], "keep")
        self.assertNotIn(self.secret, parsed["prompt"])
        self.assertTrue(result.redactions)
        self.assertSecretAbsent(result)

    def test_redacts_form_and_plain_text_bodies(self):
        form = self.redactor.redact_body(
            "application/x-www-form-urlencoded",
            ("query=sleep&token=" + self.secret + "&note=" + self.secret).encode(),
        )
        self.assertNotIn(self.secret.encode(), form.body)
        self.assertIn(b"query=sleep", form.body)

        plain = self.redactor.redact_body(
            "text/plain", ("before " + self.secret + " after").encode()
        )
        self.assertEqual(plain.body, b"before [REDACTED] after")

    def test_redact_text_returns_safe_metadata(self):
        text, records = self.redactor.redact_text(
            "provider rejected " + self.secret
        )
        self.assertEqual(text, "provider rejected [REDACTED]")
        self.assertTrue(records)
        self.assertSecretAbsent(records)


if __name__ == "__main__":
    unittest.main()
