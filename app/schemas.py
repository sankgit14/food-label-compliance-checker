
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NutritionPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basis: Literal["per_100g", "per_100ml", "per_serving"]
    serving_size_g: float | None = Field(default=None, gt=0, le=10000)

    energy_kcal: float | None = Field(default=None, ge=0, le=10000)
    protein_g: float | None = Field(default=None, ge=0, le=1000)
    carbohydrates_g: float | None = Field(default=None, ge=0, le=1000)
    total_sugars_g: float | None = Field(default=None, ge=0, le=1000)
    added_sugars_g: float | None = Field(default=None, ge=0, le=1000)
    total_fat_g: float | None = Field(default=None, ge=0, le=1000)
    saturated_fat_g: float | None = Field(default=None, ge=0, le=1000)
    trans_fat_g: float | None = Field(default=None, ge=0, le=1000)
    sodium_mg: float | None = Field(default=None, ge=0, le=100000)


class PackageSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    net_quantity: float = Field(gt=0, le=100000)
    net_quantity_unit: Literal["g", "kg", "ml", "l"]
    package_surface_area_cm2: float | None = Field(
        default=None, gt=0, le=1000000
    )
    is_single_ingredient_food: bool = False


class LabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=2, max_length=200)
    product_category: str = Field(min_length=2, max_length=100)
    label_text: str = Field(min_length=10, max_length=20000)
    ingredients: list[str] = Field(min_length=1, max_length=100)
    declared_allergens: list[str] = Field(default_factory=list, max_length=50)
    nutrition: NutritionPanel
    package: PackageSpecification

    @model_validator(mode="after")
    def validate_cross_fields(self):
        if (
            self.nutrition.basis == "per_serving"
            and self.nutrition.serving_size_g is None
        ):
            raise ValueError(
                "serving_size_g is required for per_serving nutrition"
            )
        return self


class RegulationSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    category: Literal["labelling_display", "advertising_claims"] | None = None


class EvidenceCitation(BaseModel):
    document_id: str
    source_file: str
    page: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    category: Literal["labelling_display", "advertising_claims"]
    excerpt: str


class ReviewFinding(BaseModel):
    finding_id: str
    requirement: str
    status: Literal[
        "potential_issue",
        "no_issue_identified",
        "insufficient_evidence",
        "review_required",
    ]
    severity: Literal["low", "medium", "high", "unknown"] = "unknown"
    explanation: str
    uncertainty: str
    citations: list[EvidenceCitation] = Field(default_factory=list)


class ReviewReport(BaseModel):
    report_version: Literal["1.0"] = "1.0"
    analysis_status: Literal["evidence_retrieval_only"] = "evidence_retrieval_only"
    workflow_route: Literal[
        "clear-for-print", "revise-and-recheck", "regulatory-review"
    ] = "regulatory-review"
    human_review_required: bool = True
    detected_claims: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)
    notice: str = (
        "Candidate evidence only. A regulatory affairs professional must "
        "verify the applicable legal text and make the decision."
    )


class ReviewSubmissionResponse(BaseModel):
    run_id: str
    status: Literal["queued"]
    created_at: str
    poll_url: str


class ReviewRunResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    report: ReviewReport | None = None
    error: dict[str, str] | None = None
    attempts: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=36, max_length=36)
    rating: Literal["satisfactory", "unsatisfactory"]
    reason: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    feedback_id: str
    run_id: str
    rating: Literal["satisfactory", "unsatisfactory"]
    created_at: str
