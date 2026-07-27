import os
import sys
import unittest
from dataclasses import replace

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import evidence  # noqa: E402
import verification  # noqa: E402


def read_evidence(citation_id, text):
    candidate = evidence.normalize_candidates([{
        "title": f"Source {citation_id}",
        "url": f"https://example.org/{citation_id}",
        "kind": "research",
        "query_id": "q1",
    }])[0]
    return evidence.Evidence.from_read(
        candidate,
        text=text,
        content_type="text/html",
        citation_id=citation_id,
    )


def answer_for(claim, citation_ids, conflicts=None):
    return {
        "answer": f"{claim} {' '.join(f'[{item}]' for item in citation_ids)}",
        "claims": [{
            "claim_id": "claim-1",
            "text": claim,
            "citation_ids": citation_ids,
        }],
        "conflicts": conflicts or [],
    }


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.verifier = verification.Verifier()
        self.source = read_evidence(
            "C1",
            (
                "A controlled trial found that evening caffeine delayed "
                "sleep onset in healthy adults."
            ),
        )

    def test_locates_supporting_passage_for_valid_claim(self):
        result = self.verifier.verify(
            answer_for("Evening caffeine delayed sleep onset", ["C1"]),
            [self.source],
        )

        claim = result.claims[0]
        self.assertEqual(claim.status, "supported")
        self.assertIn("delayed sleep onset", claim.supporting_passage)
        self.assertEqual(result.rejected_citations, ())

    def test_rejects_nonexistent_citation_id(self):
        result = self.verifier.verify(
            answer_for("Evening caffeine delayed sleep onset", ["C99"]),
            [self.source],
        )

        self.assertEqual(result.claims[0].status, "rejected")
        self.assertEqual(result.rejected_citations, ("C99",))
        self.assertIn("Verification note", result.corrected_answer)

    def test_rejects_citation_whose_page_was_not_read(self):
        unread = replace(self.source, was_read=False)

        result = self.verifier.verify(
            answer_for("Evening caffeine delayed sleep onset", ["C1"]),
            [unread],
        )

        self.assertEqual(result.claims[0].status, "rejected")
        self.assertIn("not read", result.claims[0].reason)

    def test_flags_absolute_claim_when_passage_is_qualified(self):
        qualified = read_evidence(
            "C1",
            "Caffeine may delay sleep onset in some adults.",
        )

        result = self.verifier.verify(
            answer_for("Caffeine always prevents sleep", ["C1"]),
            [qualified],
        )

        self.assertEqual(result.claims[0].status, "overstated")
        self.assertIn("overstates", result.claims[0].reason)
        self.assertIn("Verification note", result.corrected_answer)

    def test_preserves_explicit_conflicts_as_unresolved(self):
        conflict = "Trials disagree about effects in habitual users."
        result = self.verifier.verify(
            answer_for(
                "Evening caffeine delayed sleep onset",
                ["C1"],
                conflicts=[conflict],
            ),
            [self.source],
        )

        self.assertEqual(result.unresolved_conflicts, (conflict,))
        self.assertIn(conflict, result.corrected_answer)


if __name__ == "__main__":
    unittest.main()
