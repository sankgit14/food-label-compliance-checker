"""End-to-end load workload: submit, queue, execute, and poll a review run."""

import json
import time

from locust import HttpUser, between, task
from locust import events


PAYLOAD = {
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


class ReviewUser(HttpUser):
    wait_time = between(0.1, 0.3)

    @task
    def submit_and_poll_review(self):
        started = time.perf_counter()
        report = None
        failure = None
        with self.client.post(
            "/api/v1/reviews",
            json=PAYLOAD,
            name="POST /api/v1/reviews (submit)",
            catch_response=True,
        ) as response:
            if response.status_code != 202:
                failure = RuntimeError(f"submission status {response.status_code}")
                response.failure(str(failure))
            else:
                poll_url = response.json()["poll_url"]

        if failure is None:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                with self.client.get(
                    poll_url,
                    name="GET /api/v1/reviews/{run_id} (poll)",
                    catch_response=True,
                ) as response:
                    if response.status_code != 200:
                        failure = RuntimeError(f"poll status {response.status_code}")
                        response.failure(str(failure))
                        break
                    body = response.json()
                    if body["status"] == "succeeded":
                        report = body["report"]
                        response.success()
                        break
                    if body["status"] == "failed":
                        failure = RuntimeError(body.get("error", {}).get("code", "run failed"))
                        response.failure(str(failure))
                        break
                time.sleep(0.25)
            else:
                failure = TimeoutError("review exceeded 180 second polling limit")

        if report is not None:
            citations = [
                citation
                for finding in report.get("findings", [])
                for citation in finding.get("citations", [])
            ]
            if report.get("workflow_route") != "regulatory-review" or not citations:
                failure = AssertionError("review was missing the expected evidence escalation")

        events.request.fire(
            request_type="WORKFLOW",
            name="review submit-to-result",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=len(json.dumps(report)) if report else 0,
            exception=failure,
            context={"route": "regulatory-review", "citations": len(citations) if report else 0},
        )
