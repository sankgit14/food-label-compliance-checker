
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def valid_payload():
    return {
        "product_name": "Jackfruit Chips",
        "product_category": "Packaged snack",
        "label_text": (
            "Jackfruit Chips. Ingredients: jackfruit, oil, salt. "
            "Source of protein."
        ),
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


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_input():
    response = client.post(
        "/api/v1/validate-input", json=valid_payload()
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["agent_run_started"] is False


def test_missing_product_name():
    payload = valid_payload()
    del payload["product_name"]

    response = client.post("/api/v1/validate-input", json=payload)
    assert response.status_code == 422


def test_negative_protein():
    payload = valid_payload()
    payload["nutrition"]["protein_g"] = -5

    response = client.post("/api/v1/validate-input", json=payload)
    assert response.status_code == 422


def test_missing_serving_size():
    payload = valid_payload()
    payload["nutrition"]["basis"] = "per_serving"

    response = client.post("/api/v1/validate-input", json=payload)
    assert response.status_code == 422


def test_unknown_field():
    payload = valid_payload()
    payload["unexpected_field"] = "not allowed"

    response = client.post("/api/v1/validate-input", json=payload)
    assert response.status_code == 422
