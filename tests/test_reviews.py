import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import review_queue
from app import quarantine
from app import worker
from app.agents import run_agent_review
from app.main import app
from app.retrieval import RegulationSearch


def sample_request():
    return {
        "product_name": "Jackfruit Chips",
        "product_category": "Packaged snack",
        "label_text": "Jackfruit chips. Ingredients: jackfruit, oil, salt. Source of protein.",
        "ingredients": ["jackfruit", "oil", "salt"],
        "declared_allergens": [],
        "nutrition": {
            "basis": "per_100g",
            "energy_kcal": 450,
            "protein_g": 5,
            "carbohydrates_g": 50,
            "total_fat_g": 25,
            "sodium_mg": 400,
        },
        "package": {
            "net_quantity": 100,
            "net_quantity_unit": "g",
            "package_surface_area_cm2": 250,
            "is_single_ingredient_food": False,
        },
    }


def write_test_corpus(path: Path):
    chunks = [
        {
            "document_id": "ads-gazette-test",
            "source_file": "advertising_claims/test/claims-gazette.pdf",
            "page": 28,
            "chunk_index": 0,
            "category": "advertising_claims",
            "text": (
                "Schedule I source of protein claim conditions: 10 percent of RDA "
                "per 100 g for solids. This is a retrieved historical passage."
            ),
        },
        {
            "document_id": "label-gazette-test",
            "source_file": "labelling_display/test/labelling-gazette.pdf",
            "page": 32,
            "chunk_index": 0,
            "category": "labelling_display",
            "text": (
                "Nutrition information declaration: energy value, protein, "
                "carbohydrates and total sugars shall be stated on the label."
            ),
        },
    ]
    path.write_text(
        "".join(json.dumps(chunk) + "\n" for chunk in chunks), encoding="utf-8"
    )


def test_queued_protein_review_returns_verified_cross_regulation_citations(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "state" / "review.sqlite3"
    chunks_path = tmp_path / "regulatory_chunks.jsonl"
    write_test_corpus(chunks_path)
    monkeypatch.setattr(review_queue, "DB_PATH", db_path)

    async def run_with_test_corpus(run_id, request, **kwargs):
        return await run_agent_review(
            run_id,
            request,
            model=kwargs.get("model"),
            search=RegulationSearch(chunks_path),
        )

    monkeypatch.setattr(worker, "run_agent_review", run_with_test_corpus)
    with TestClient(app) as client:
        submission = client.post("/api/v1/reviews", json=sample_request())
        assert submission.status_code == 202
        run_id = submission.json()["run_id"]
        assert worker.process_once() is True
        result = client.get(submission.json()["poll_url"])
        feedback_response = client.post(
            "/api/v1/feedback",
            json={
                "run_id": run_id,
                "rating": "satisfactory",
                "reason": "Both regulation families were retrieved.",
            },
        )
        web_response = client.get("/")
        metrics_response = client.get("/metrics")

    assert result.status_code == 200
    body = result.json()
    report = body["report"]
    assert body["status"] == "succeeded"
    assert report["workflow_route"] == "regulatory-review"
    assert report["human_review_required"] is True
    assert report["execution_metadata"]["workflow_failure"] is None
    finding = report["findings"][0]
    assert finding["status"] == "review_required"
    assert {citation["category"] for citation in finding["citations"]} == {
        "labelling_display",
        "advertising_claims",
    }
    verified = {
        (
            item["result"]["document_id"],
            item["result"]["source_file"],
            item["result"]["page"],
            item["result"]["chunk_index"],
        )
        for item in report["execution_metadata"]["tool_trace"]
        if item["tool"] == "citation_verify" and item["result"].get("verified")
    }
    assert all(
        (
            item["document_id"],
            item["source_file"],
            item["page"],
            item["chunk_index"],
        )
        in verified
        for item in finding["citations"]
    )
    assert report["execution_metadata"]["run_id"] == run_id
    assert feedback_response.status_code == 201
    assert web_response.status_code == 200
    assert "Start evidence review" in web_response.text
    assert metrics_response.status_code == 200
    assert "food_label_review_end_to_end_latency_seconds" in metrics_response.text
    assert 'food_label_feedback_total{rating="satisfactory"} 1' in metrics_response.text


def test_invalid_review_is_quarantined_before_queueing(tmp_path, monkeypatch):
    db_path = tmp_path / "state" / "review.sqlite3"
    quarantine_file = tmp_path / "quarantine" / "rejected.jsonl"
    monkeypatch.setattr(review_queue, "DB_PATH", db_path)
    monkeypatch.setattr(quarantine, "QUARANTINE_FILE", quarantine_file)
    payload = sample_request()
    payload["nutrition"]["protein_g"] = -1

    with TestClient(app) as client:
        response = client.post("/api/v1/reviews", json=payload)

    assert response.status_code == 422
    assert response.json()["agent_run_started"] is False
    assert review_queue.queue_counts() == {
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
    }
    record = json.loads(quarantine_file.read_text(encoding="utf-8"))
    assert record["agent_run_started"] is False
    assert record["field_errors"]


def test_fiber_us_spelling_is_detected():
    from app.review_workflow import detect_claim_phrases

    assert detect_claim_phrases("Snack. Source of fiber.") == ["Source of fiber"]
    assert detect_claim_phrases("Snack. High in fibre.") == ["High in fibre"]


def test_review_without_claims_produces_mandatory_declarations_finding(tmp_path):
    chunks_path = tmp_path / "regulatory_chunks.jsonl"
    write_test_corpus(chunks_path)
    search = RegulationSearch(chunks_path)
    payload = sample_request()
    payload["label_text"] = "Jackfruit chips. Ingredients: jackfruit, oil, salt."

    report, diagnostics = asyncio.run(
        run_agent_review("test-no-claims", payload, search=search)
    )

    assert len(report["findings"]) >= 1
    finding = report["findings"][0]
    assert finding["finding_id"] == "mandatory-declarations"
    assert finding["status"] in {"review_required", "insufficient_evidence"}


def test_citation_verify_tool_handles_none_gracefully():
    from app.agents import _resolve_tool

    chunks_path = Path("data/processed/regulatory_chunks.jsonl")
    search = RegulationSearch(chunks_path)
    # Should not raise TypeError when page or chunk_index is None
    result = _resolve_tool(
        "citation_verify",
        {
            "document_id": "test",
            "source_file": "test.pdf",
            "page": None,
            "chunk_index": None,
            "quote": "any",
        },
        request={},
        search=search,
    )
    assert result["verified"] is False

