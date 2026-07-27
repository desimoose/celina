import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import evidence  # noqa: E402


class CandidateTest(unittest.TestCase):
    def test_normalize_deduplicates_canonical_urls_and_merges_query_ids(self):
        rows = evidence.normalize_candidates([
            {
                "title": "First title",
                "url": "HTTPS://Example.com/article/?utm_source=x#section",
                "kind": "web",
                "snippet": "result snippet",
                "query_id": "q1",
            },
            {
                "title": "Better title",
                "url": "https://example.com/article",
                "kind": "research",
                "oa_url": "https://example.com/article",
                "authors": ["Ada"],
                "query_id": "q2",
            },
        ])

        self.assertEqual(len(rows), 1)
        candidate = rows[0]
        self.assertEqual(candidate.canonical_url, "https://example.com/article")
        self.assertEqual(candidate.retrieval_query_ids, ("q1", "q2"))
        self.assertEqual(candidate.source_kind, "research")
        self.assertEqual(candidate.authors, ("Ada",))

    def test_invalid_or_non_http_candidates_are_discarded(self):
        rows = evidence.normalize_candidates([
            {"title": "No URL"},
            {"title": "Local file", "url": "file:///private.txt"},
            {"title": "Valid", "url": "https://example.org"},
        ])

        self.assertEqual([row.title for row in rows], ["Valid"])


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.candidate = evidence.normalize_candidates([{
            "title": "Readable source",
            "url": "https://example.org/source",
            "kind": "web",
            "snippet": "A search-result snippet is not evidence.",
            "query_id": "q1",
        }])[0]

    def test_read_content_becomes_stable_citable_evidence(self):
        item = evidence.Evidence.from_read(
            self.candidate,
            text="A complete retrieved passage with enough useful content.",
            content_type="text/html",
            citation_id="C1",
        )

        self.assertEqual(item.citation_id, "C1")
        self.assertTrue(item.was_read)
        self.assertEqual(item.text.startswith("A complete"), True)
        self.assertEqual(item.candidate_id, self.candidate.candidate_id)

    def test_snippet_cannot_be_promoted_to_read_evidence(self):
        with self.assertRaises(ValueError):
            evidence.Evidence.from_read(
                self.candidate,
                text=self.candidate.snippet,
                content_type="search/snippet",
                citation_id="C1",
            )

    def test_empty_read_is_rejected(self):
        with self.assertRaises(ValueError):
            evidence.Evidence.from_read(
                self.candidate,
                text="   ",
                content_type="text/html",
                citation_id="C1",
            )


if __name__ == "__main__":
    unittest.main()
