
from fastapi import FastAPI
from app.schemas import LabelRequest

app = FastAPI(
    title="Food Label Compliance Check Service",
    version="0.1.0",
    description="Evidence-based food label compliance findings.",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "food-label-compliance",
    }


@app.post("/api/v1/validate-input")
def validate_input(request: LabelRequest):
    return {
        "accepted": True,
        "message": (
            "Input validation passed. "
            "No compliance determination has been made."
        ),
        "product_name": request.product_name,
        "product_category": request.product_category,
        "agent_run_started": False,
    }
