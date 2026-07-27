"""Deterministic first-pass verification of structured cited claims."""

from dataclasses import dataclass
import re


_ABSOLUTES = {"all", "always", "never", "none", "guarantees", "prevents"}
_QUALIFIERS = {"can", "could", "may", "might", "some", "suggests", "associated"}
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "to", "was",
    "were", "with",
}


@dataclass(frozen=True)
class ClaimVerification:
    claim_id: str
    text: str
    citation_ids: tuple[str, ...]
    status: str
    supporting_passage: str | None
    reason: str | None


@dataclass(frozen=True)
class VerificationResult:
    claims: tuple[ClaimVerification, ...]
    rejected_citations: tuple[str, ...]
    corrected_answer: str
    unresolved_conflicts: tuple[str, ...]


class Verifier:
    def verify(self, answer, evidence):
        payload = answer if isinstance(answer, dict) else {"answer": str(answer)}
        base_answer = str(payload.get("answer") or "")
        evidence_by_id = {
            item.citation_id: item
            for item in evidence or ()
        }
        checked = []
        rejected = []
        correction_notes = []

        for index, claim in enumerate(payload.get("claims") or (), 1):
            claim_id = str(claim.get("claim_id") or f"claim-{index}")
            text = str(claim.get("text") or "").strip()
            citation_ids = tuple(
                str(item)
                for item in claim.get("citation_ids") or ()
                if str(item)
            )
            result = self._verify_claim(
                claim_id,
                text,
                citation_ids,
                evidence_by_id,
            )
            checked.append(result)
            if result.status != "supported":
                rejected.extend(citation_ids)
                correction_notes.append(
                    f"{text or claim_id}: {result.reason}."
                )

        conflicts = tuple(
            str(item).strip()
            for item in payload.get("conflicts") or ()
            if str(item).strip()
        )
        correction_notes.extend(
            f"Unresolved conflict: {item}"
            for item in conflicts
        )
        corrected = base_answer
        if correction_notes:
            corrected += "\n\n> Verification note: " + " ".join(correction_notes)
        return VerificationResult(
            claims=tuple(checked),
            rejected_citations=tuple(dict.fromkeys(rejected)),
            corrected_answer=corrected,
            unresolved_conflicts=conflicts,
        )

    def _verify_claim(
        self,
        claim_id,
        text,
        citation_ids,
        evidence_by_id,
    ):
        if not citation_ids:
            return ClaimVerification(
                claim_id,
                text,
                (),
                "rejected",
                None,
                "claim has no citation",
            )
        for citation_id in citation_ids:
            item = evidence_by_id.get(citation_id)
            if item is None:
                return ClaimVerification(
                    claim_id,
                    text,
                    citation_ids,
                    "rejected",
                    None,
                    f"citation {citation_id} does not exist",
                )
            if not item.was_read:
                return ClaimVerification(
                    claim_id,
                    text,
                    citation_ids,
                    "rejected",
                    None,
                    f"citation {citation_id} was not read",
                )

        passages = [
            passage
            for citation_id in citation_ids
            for passage in _passages(evidence_by_id[citation_id].text)
        ]
        best = max(
            passages,
            key=lambda passage: _coverage(text, passage),
            default=None,
        )
        coverage = _coverage(text, best) if best is not None else 0.0
        claim_words = _words(text)
        passage_words = _words(best)
        if (
            coverage >= 0.4
            and claim_words & _ABSOLUTES
            and passage_words & _QUALIFIERS
        ):
            return ClaimVerification(
                claim_id,
                text,
                citation_ids,
                "overstated",
                best,
                "claim overstates the qualified source passage",
            )
        if best is None or coverage < 0.6:
            return ClaimVerification(
                claim_id,
                text,
                citation_ids,
                "rejected",
                best,
                "no supporting passage was located",
            )
        return ClaimVerification(
            claim_id,
            text,
            citation_ids,
            "supported",
            best,
            None,
        )


def _passages(text):
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if item.strip()
    ]


def _words(text):
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if word not in _STOPWORDS
    }


def _coverage(claim, passage):
    claim_words = _words(claim)
    if not claim_words:
        return 0.0
    return len(claim_words & _words(passage)) / len(claim_words)
