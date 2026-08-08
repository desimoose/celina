from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SecurityDocumentationTest(unittest.TestCase):
    def test_security_documents_cover_required_threats_and_invariants(self):
        text = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("docs/SECURITY_MODEL.md", "docs/OPERATIONS.md", "SECURITY.md")
        ).lower()
        for value in (
            "url_public_only",
            "untrusted_source_data",
            "bounded_mutation",
            "atomic_local_state",
            "durable_idempotency",
            "ephemeral_incognito",
            "no_secret_output",
            "no_telemetry",
            "malicious webpage",
            "hostile pdf",
            "compromised provider",
            "same-machine user",
            "release supply chain",
            "adult-learning",
            "local-first",
        ):
            self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
