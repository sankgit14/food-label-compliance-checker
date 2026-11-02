"""Evaluate curated source pages for regulation-family-specific queries."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval import CorpusUnavailableError, RegulationSearch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASES_FILE = PROJECT_ROOT / "data" / "evaluation" / "retrieval_cases.jsonl"
INDEX_METADATA_FILE = PROJECT_ROOT / "data" / "processed" / "regulatory_index_metadata.json"


def load_cases() -> list[dict[str, Any]]:
    with CASES_FILE.open("r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--strategy",
        choices=("baseline", "global", "family-filtered"),
        default="family-filtered",
        help="Compare the original query, improved global query, and family-filtered query.",
    )
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        parser.error("--top-k must be between 1 and 100")

    search = RegulationSearch()
    try:
        cases = load_cases()
        per_case = []
        total_expected = 0
        total_hits = 0
        reciprocal_ranks = []
        evidence_reciprocal_ranks = []
        for case in cases:
            case_searches = []
            case_expected = 0
            case_hits = 0
            case_evidence_ranks = []
            if args.strategy == "baseline":
                expected_all = [
                    item
                    for spec in case["searches"]
                    for item in spec["expected_evidence"]
                ]
                query_specs = [
                    {
                        "category": None,
                        "query": case["baseline_query"],
                        "expected_evidence": expected_all,
                    }
                ]
            else:
                query_specs = case["searches"]
            for query_spec in query_specs:
                results = search.search(
                    query_spec["query"],
                    top_k=args.top_k,
                    category=(
                        query_spec["category"]
                        if args.strategy == "family-filtered"
                        else None
                    ),
                )
                ranked_pairs = [
                    (result.get("source_file"), result.get("page"))
                    for result in results
                ]
                expected = [
                    (item["source_file"], item["page"])
                    for item in query_spec["expected_evidence"]
                ]
                hits = [pair for pair in expected if pair in ranked_pairs]
                first_rank = next(
                    (rank for rank, pair in enumerate(ranked_pairs, start=1) if pair in expected),
                    None,
                )
                total_expected += len(expected)
                total_hits += len(hits)
                case_expected += len(expected)
                case_hits += len(hits)
                reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)
                for expected_pair in expected:
                    evidence_rank = next(
                        (
                            rank
                            for rank, pair in enumerate(ranked_pairs, start=1)
                            if pair == expected_pair
                        ),
                        None,
                    )
                    reciprocal_rank = 1 / evidence_rank if evidence_rank else 0.0
                    evidence_reciprocal_ranks.append(reciprocal_rank)
                    case_evidence_ranks.append(reciprocal_rank)
                case_searches.append(
                    {
                        "category": query_spec["category"],
                        "query": query_spec["query"],
                        "expected_count": len(expected),
                        "hit_count": len(hits),
                        "reciprocal_rank": round(1 / first_rank if first_rank else 0.0, 4),
                        "expected_evidence": [
                            {"source_file": path, "page": page}
                            for path, page in expected
                        ],
                        "returned_evidence": [
                            {"source_file": path, "page": page}
                            for path, page in ranked_pairs
                        ],
                    }
                )
            per_case.append(
                {
                    "case_id": case["case_id"],
                    "expected_outcome": case["expected_outcome"],
                    "curation_status": case["curation_status"],
                    "expected_count": case_expected,
                    "hit_count": case_hits,
                    "mean_evidence_reciprocal_rank": round(
                        sum(case_evidence_ranks) / len(case_evidence_ranks)
                        if case_evidence_ranks
                        else 0.0,
                        4,
                    ),
                    "searches": case_searches,
                }
            )
    except CorpusUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    summary = {
        "case_count": len(per_case),
        "search_count": len(reciprocal_ranks),
        "strategy": args.strategy,
        "top_k": args.top_k,
        "corpus": {
            "chunks_sha256": json.loads(
                INDEX_METADATA_FILE.read_text(encoding="utf-8")
            ).get("chunks_sha256"),
            "built_at_utc": json.loads(
                INDEX_METADATA_FILE.read_text(encoding="utf-8")
            ).get("built_at_utc"),
        },
        "evidence_recall_at_k": round(
            total_hits / total_expected if total_expected else 0.0, 4
        ),
        "mean_reciprocal_rank": round(
            sum(evidence_reciprocal_ranks) / len(evidence_reciprocal_ranks)
            if evidence_reciprocal_ranks
            else 0.0,
            4,
        ),
        "mrr_unit": "expected source/page evidence item",
        "cases": per_case,
        "interpretation": (
            "Retrieval metrics only. They do not verify legal applicability or answer correctness."
        ),
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
