"""What a data health scan reads and how it weighs the seven dimensions.

Defaults are common B2B fields. Change them on the
Data Doctor's "Full data health scan" template (or a task's params).
"""

from typing import Any

from pydantic import BaseModel, Field, model_validator

DIMENSIONS = ("uniqueness", "completeness", "normalization", "accuracy", "contactability",
              "recency", "engagement")

# Activity types read from the history (Marketo standard IDs).
VISIT, FORM, CLICK_LINK, DELIVERED, HARD_BOUNCE, UNSUBSCRIBE, OPEN, CLICK, SOFT_BOUNCE = (
    1, 2, 3, 7, 8, 9, 10, 11, 27)
ACTIVITY_TYPES = [VISIT, FORM, CLICK_LINK, OPEN, CLICK, HARD_BOUNCE, SOFT_BOUNCE, UNSUBSCRIBE]


class ScanConfig(BaseModel):
    # Completeness: each entry is one field, or alternatives that count as one ("a|b").
    relevant_fields: list[str] = Field(default_factory=lambda: [
        "firstName", "lastName", "email", "company", "title", "industry",
        "numberOfEmployees|annualRevenue", "country", "phone|mobilePhone"])
    weights: dict[str, float] = Field(default_factory=lambda: {
        "uniqueness": 15, "completeness": 15, "normalization": 10, "accuracy": 20,
        "contactability": 20, "recency": 10, "engagement": 10})
    engagement_months: int = Field(default=18, ge=1, le=36)  # activity history read
    batch_size: int = Field(default=300, ge=10, le=300)  # lead IDs per REST call
    pace_s: float = Field(default=0.5, ge=0, le=60)  # pause between batches / windows
    corporate_email_required: bool = True  # free-mail-only leads score lower
    use_llm: bool = True  # map unknown values and confirm suspect names with the model
    max_lead_id: int | None = None  # stop here (tests / partial scans); None = whole database
    # After the scan, hand the best reachable leads to this agent (id or name) to qualify.
    handoff_to: str | None = None
    handoff_max: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _weights(self) -> "ScanConfig":
        unknown = set(self.weights) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown dimension(s) in weights: {', '.join(sorted(unknown))}")
        if sum(self.weights.get(d, 0) for d in DIMENSIONS) <= 0:
            raise ValueError("weights must add up to more than 0")
        return self


def load(template: dict[str, Any], task: dict[str, Any]) -> ScanConfig:
    keys = set(ScanConfig.model_fields)
    merged = {k: v for k, v in {**template, **task}.items() if k in keys}
    return ScanConfig.model_validate(merged)
