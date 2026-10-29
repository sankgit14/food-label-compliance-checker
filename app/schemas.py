
from typing import Literal

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
