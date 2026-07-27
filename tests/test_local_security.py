import os
import sys
import unittest
from types import SimpleNamespace

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import local_security  # noqa: E402
import serialization  # noqa: E402


class LocalSecurityTest(unittest.TestCase):
    def test_requires_a_loopback_origin(self):
        with self.assertRaises(ValueError):
            local_security.LocalSecurity("https://example.test")

    def test_issues_distinct_in_memory_launch_and_csrf_tokens(self):
        first = local_security.LocalSecurity("http://127.0.0.1:8765")
        second = local_security.LocalSecurity("http://127.0.0.1:8765")

        self.assertNotEqual(first.launch_token, second.launch_token)
        self.assertNotEqual(first.csrf_token, second.csrf_token)
        self.assertNotEqual(first.launch_token, first.csrf_token)
        self.assertIn("HttpOnly", first.launch_cookie_header)
        self.assertIn("SameSite=Strict", first.launch_cookie_header)

    def test_authorizes_a_mutation_with_matching_cookie_csrf_and_origin(self):
        security = local_security.LocalSecurity("http://127.0.0.1:8765")

        authorized = security.authorize_mutation(
            f"{security.cookie_name}={security.launch_token}",
            security.csrf_token,
            "http://127.0.0.1:8765",
        )

        self.assertTrue(authorized)

    def test_rejects_invalid_credentials_and_tokens_in_query_strings(self):
        security = local_security.LocalSecurity("http://127.0.0.1:8765")
        cookie = f"{security.cookie_name}={security.launch_token}"

        self.assertFalse(security.authorize_mutation(
            None, security.csrf_token, "http://127.0.0.1:8765"
        ))
        self.assertFalse(security.authorize_mutation(
            cookie, "wrong", "http://127.0.0.1:8765"
        ))
        self.assertFalse(security.authorize_mutation(
            cookie, "not-ascii-✓", "http://127.0.0.1:8765"
        ))
        self.assertFalse(security.authorize_mutation(
            cookie, security.csrf_token, "http://localhost:8765"
        ))
        self.assertFalse(security.authorize_mutation(
            cookie,
            security.csrf_token,
            "http://127.0.0.1:8765",
            query_string=f"csrf={security.csrf_token}",
        ))
        self.assertFalse(security.authorize_mutation(
            cookie,
            security.csrf_token,
            "http://127.0.0.1:8765",
            query_string=f"launch={security.launch_token}",
        ))

    def test_rejects_tokens_as_query_keys_or_bare_segments(self):
        security = local_security.LocalSecurity("http://127.0.0.1:8765")
        cookie = f"{security.cookie_name}={security.launch_token}"

        for case, query_string in (
            ("csrf-token-key", f"{security.csrf_token}=value"),
            ("bare-launch-token", security.launch_token),
        ):
            with self.subTest(case=case):
                self.assertFalse(security.authorize_mutation(
                    cookie,
                    security.csrf_token,
                    "http://127.0.0.1:8765",
                    query_string=query_string,
                ))

    def test_rejects_every_nonempty_mutation_query_string(self):
        security = local_security.LocalSecurity("http://127.0.0.1:8765")
        cookie = f"{security.cookie_name}={security.launch_token}"
        encoded_csrf = "".join(
            f"%{ord(character):02X}"
            for character in security.csrf_token
        )

        for case, query_string in (
            ("ordinary-query", "page=2"),
            ("embedded-csrf", f"q=prefix{security.csrf_token}"),
            ("percent-encoded-embedded-csrf", f"q=prefix{encoded_csrf}"),
            ("percent-encoded-csrf", f"q={encoded_csrf}"),
        ):
            with self.subTest(case=case):
                self.assertFalse(security.authorize_mutation(
                    cookie,
                    security.csrf_token,
                    "http://127.0.0.1:8765",
                    query_string=query_string,
                ))

    def test_denial_body_never_echoes_launch_or_csrf_tokens(self):
        security = local_security.LocalSecurity("http://127.0.0.1:8765")

        body = security.denial_body()

        self.assertNotIn(security.launch_token, body)
        self.assertNotIn(security.csrf_token, body)

    def test_serializes_only_session_product_state(self):
        session = SimpleNamespace(
            session_id="session-1",
            state="active",
            created_at="2026-07-26T00:00:00.000Z",
            last_active_at="2026-07-26T01:00:00.000Z",
            content_recording=True,
            recovery_required=False,
            provider_api_key="session-secret",
            lock=object(),
        )

        product_state = serialization.serialize_session(session)

        self.assertEqual(product_state, {
            "session_id": "session-1",
            "state": "active",
            "created_at": "2026-07-26T00:00:00.000Z",
            "last_active_at": "2026-07-26T01:00:00.000Z",
            "content_recording": True,
            "recovery_required": False,
        })

    def test_serializes_run_without_internal_or_secret_values(self):
        secret = "provider-secret"
        run = SimpleNamespace(
            run_id="run-1",
            session_id="session-1",
            state="reading",
            query="Does caffeine affect sleep?",
            query_plan=SimpleNamespace(
                queries=("caffeine sleep",),
                angles=("clinical evidence",),
                summary="Review clinical evidence.",
                provider_api_key=secret,
            ),
            candidates=[{
                "candidate_id": "candidate-1",
                "title": "Study",
                "url": "https://example.test/study",
                "canonical_url": "https://example.test/study",
                "source_kind": "research",
                "published_at": "2026-01-01",
                "authors": ("A. Researcher",),
                "snippet": "Summary",
                "open_access": True,
                "retrieval_query_ids": ("q1",),
                "traffic_secret": secret,
            }],
            evidence=[SimpleNamespace(
                citation_id="C1",
                candidate_id="candidate-1",
                title="Study",
                url="https://example.test/study",
                source_kind="research",
                text="Raw evidence body",
                content_type="text/html",
                character_count=17,
                was_read=True,
                provider_api_key=secret,
            )],
            answer={
                "answer": "Grounded answer.",
                "citations": ["C1"],
                "provider_api_key": secret,
            },
            gaps=["long-term evidence"],
            conflicts=[],
            follow_up_count=0,
            error_class="ProviderError",
            _thread=object(),
            _lock=object(),
            _cancellation=object(),
            raw_exception=RuntimeError(secret),
            traffic_secret=secret,
        )

        product_state = serialization.serialize_search_run(run)

        self.assertEqual(product_state, {
            "run_id": "run-1",
            "state": "reading",
            "query": "Does caffeine affect sleep?",
            "query_plan": {
                "queries": ["caffeine sleep"],
                "angles": ["clinical evidence"],
                "summary": "Review clinical evidence.",
            },
            "candidates": [{
                "candidate_id": "candidate-1",
                "title": "Study",
                "url": "https://example.test/study",
                "canonical_url": "https://example.test/study",
                "source_kind": "research",
                "published_at": "2026-01-01",
                "authors": ["A. Researcher"],
                "snippet": "Summary",
                "open_access": True,
                "retrieval_query_ids": ["q1"],
            }],
            "evidence": [{
                "citation_id": "C1",
                "candidate_id": "candidate-1",
                "title": "Study",
                "url": "https://example.test/study",
                "source_kind": "research",
                "content_type": "text/html",
                "character_count": 17,
                "was_read": True,
            }],
            "answer": {"answer": "Grounded answer.", "citations": ["C1"]},
            "gaps": ["long-term evidence"],
            "conflicts": [],
            "follow_up_count": 0,
            "error_class": "ProviderError",
        })
        rendered = repr(product_state)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("Raw evidence body", rendered)


if __name__ == "__main__":
    unittest.main()
