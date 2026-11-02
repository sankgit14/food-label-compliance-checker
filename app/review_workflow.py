"""Phrase-based fallback report workflow for retrieval-only review runs.

The main workflow uses separate discovery and verification roles. This module
also supplies the bounded lexical fallback and never decides compliance.
"""

import re
from typing import Any

from app.retrieval import CorpusUnavailableError, RegulationSearch
from app.schemas import ReviewFinding, ReviewReport

CLAIM_PATTERNS = (
    re.compile(r"\bsource of protein\b", re.IGNORECASE),
    re.compile(r"\b(?:high|rich) in protein\b", re.IGNORECASE),
    re.compile(r"\b(?:source of|high in|rich in) fib(?:re|er)\b", re.IGNORECASE),
    re.compile(r"\b(?:low|free|no added) (?:sugar|salt|sodium|fat)\b", re.IGNORECASE),
    re.compile(r"\b(?:sugar[- ]free|fat[- ]free|gluten[- ]free)\b", re.IGNORECASE),
    re.compile(r"\b(?:boosts?|supports?) (?:immunity|energy|health|digestion)\b", re.IGNORECASE),
)


def detect_claim_phrases(label_text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(label_text):
            phrase = match.group(0).strip()
            key = phrase.casefold()
            if key not in seen:
                seen.add(key)
                found.append((match.start(), phrase))
    return [phrase for _, phrase in sorted(found)]


def _search_queries(claim: str) -> dict[str, str]:
    normalized = claim.casefold()
    if "protein" in normalized:
        return {
            "advertising_claims": (
                "protein source high rich claim RDA per 100g per 100ml per serving"
            ),
            "labelling_display": (
                "nutrition information protein declaration RDA serving size"
            ),
        }
    return {
        "advertising_claims": f"{claim} conditions nutrition health claim",
        "labelling_display": f"{claim} nutrition information label declaration",
    }


def _citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": result.get("document_id") or "unknown",
            "source_file": result.get("source_file") or "unknown",
            "page": result.get("page") or 1,
            "chunk_index": result.get("chunk_index") or 0,
            "category": result.get("category"),
            "excerpt": result.get("text", "")[:1800],
        }
        for result in results
    ]


def build_retrieval_report(
    label: dict[str, Any], search: RegulationSearch | None = None
) -> dict[str, Any]:
    """Collect candidate evidence and route the run to human review."""
    search = search or RegulationSearch()
    claims = detect_claim_phrases(label.get("label_text", ""))
    findings: list[ReviewFinding] = []
    unresolved = [
        "No automated rule-based assessment of mandatory label declarations has been performed.",
        "Regulation version and effective-date applicability have not been verified for this product and assessment date.",
        "Claim detection is phrase-based and may miss claims or detect phrases used in another context.",
        "Retrieved passages have not been independently checked against Gazette text or verified for legal applicability.",
    ]

    if not claims:
        results: list[dict[str, Any]] = []
        try:
            results.extend(
                search.search(
                    "nutritional information energy value amounts protein carbohydrate declaration label",
                    top_k=3,
                    category="labelling_display",
                )
            )
        except (CorpusUnavailableError, ValueError) as exc:
            findings.append(
                ReviewFinding(
                    finding_id="mandatory-declarations",
                    requirement="Review mandatory food label declarations (ingredients, nutrition, allergens)",
                    status="insufficient_evidence",
                    explanation="The regulation corpus could not provide searchable candidate evidence.",
                    uncertainty=str(exc),
                )
            )
        else:
            citations = _citations(results)
            findings.append(
                ReviewFinding(
                    finding_id="mandatory-declarations",
                    requirement="Review mandatory food label declarations (ingredients, nutrition, allergens)",
                    status="review_required" if citations else "insufficient_evidence",
                    explanation=(
                        "Candidate provisions were retrieved for mandatory food label declarations. "
                        "They are candidate evidence and not a verified interpretation of compliance."
                        if citations
                        else "No positive lexical match was found for mandatory food label declarations."
                    ),
                    uncertainty=(
                        "A regulatory affairs professional must verify mandatory declarations, format, font size, and effective amendments."
                    ),
                    citations=citations,
                )
            )

    for index, claim in enumerate(claims, start=1):
        results: list[dict[str, Any]] = []
        try:
            for category, query in _search_queries(claim).items():
                results.extend(
                    search.search(query, top_k=3, category=category)
                )
        except (CorpusUnavailableError, ValueError) as exc:
            findings.append(
                ReviewFinding(
                    finding_id=f"claim-{index}",
                    requirement=f"Review the detected label claim: {claim}",
                    status="insufficient_evidence",
                    explanation="The regulation corpus could not provide searchable candidate evidence.",
                    uncertainty=str(exc),
                )
            )
            continue

        citations = _citations(results)
        findings.append(
            ReviewFinding(
                finding_id=f"claim-{index}",
                requirement=f"Review the detected label claim: {claim}",
                status="review_required" if citations else "insufficient_evidence",
                explanation=(
                    "Candidate passages were retrieved from the relevant regulation families. "
                    "They are not a verified interpretation of the claim."
                    if citations
                    else "No positive lexical match was found. This does not establish that no applicable rule exists."
                ),
                uncertainty=(
                    "A professional must verify exact clauses, product category, applicable RDA basis, amendments, and effective dates."
                ),
                citations=citations,
            )
        )

    report = ReviewReport(
        detected_claims=claims,
        findings=findings,
        unresolved_questions=unresolved,
    )
    return report.model_dump(mode="json")
