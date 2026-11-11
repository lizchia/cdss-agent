"""Tool input/output contracts.

Input models double as the JSON Schemas advertised to the LLM for function calling,
so field descriptions are written for the model as much as for humans. All inputs
forbid unknown fields so hallucinated arguments are rejected rather than ignored.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictInput(BaseModel):
    """Base for every tool input: immutable, whitespace-stripped, no extra keys."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


# ---------------------------------------------------------------------------
# Patient database tool
# ---------------------------------------------------------------------------


class PatientQuery(StrEnum):
    """Allow-listed query templates. The LLM selects one; it never authors SQL."""

    DEMOGRAPHICS = "demographics"
    RECENT_VITALS = "recent_vitals"
    RECENT_LABS = "recent_labs"
    ACTIVE_MEDICATIONS = "active_medications"
    ACTIVE_DIAGNOSES = "active_diagnoses"


class PatientDataInput(StrictInput):
    query: PatientQuery = Field(
        description=(
            "Which patient record to fetch: demographics, recent_vitals, recent_labs, "
            "active_medications, or active_diagnoses."
        )
    )
    patient_id: UUID = Field(description="The patient's UUID exactly as provided by the user.")
    lookback_hours: int = Field(
        default=72,
        ge=1,
        le=720,
        description="Time window in hours. Only applies to recent_vitals and recent_labs.",
    )
    limit: int = Field(default=50, ge=1, le=200, description="Maximum number of rows to return.")


class PatientDataOutput(BaseModel):
    query: PatientQuery
    patient_id: UUID
    row_count: int = Field(ge=0)
    rows: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Clinical guideline RAG tool
# ---------------------------------------------------------------------------


class GuidelineSearchInput(StrictInput):
    query: str = Field(
        min_length=3,
        max_length=500,
        description="Natural-language clinical question to search the guideline corpus for.",
    )
    top_k: int = Field(default=4, ge=1, le=10, description="Number of passages to return.")
    specialty: str | None = Field(
        default=None,
        pattern=r"^[a-z_]{2,40}$",
        description="Optional lowercase specialty filter, e.g. 'cardiology' or 'critical_care'.",
    )


class GuidelineChunk(BaseModel):
    source: str = Field(description="Guideline document identifier or title.")
    section: str | None = None
    text: str
    score: float = Field(description="Similarity score; higher is more relevant.")


class GuidelineSearchOutput(BaseModel):
    query: str
    results: list[GuidelineChunk]


# ---------------------------------------------------------------------------
# ICU length-of-stay risk tool
# ---------------------------------------------------------------------------


class ICURiskInput(StrictInput):
    """Physiologic snapshot. Bounds reject physiologically implausible values."""

    age_years: int = Field(ge=18, le=120, description="Patient age in years (adults only).")
    heart_rate_bpm: float = Field(ge=20, le=250)
    systolic_bp_mmhg: float = Field(ge=40, le=300)
    diastolic_bp_mmhg: float = Field(ge=20, le=200)
    respiratory_rate_bpm: float = Field(ge=4, le=70)
    spo2_percent: float = Field(ge=50, le=100)
    temperature_c: float = Field(ge=30, le=45)
    gcs: int = Field(ge=3, le=15, description="Glasgow Coma Scale total score.")
    lactate_mmol_l: float = Field(ge=0, le=30)
    creatinine_mg_dl: float = Field(ge=0.1, le=25)
    wbc_k_per_ul: float = Field(ge=0, le=300, description="White blood cells, 10^3/uL.")
    on_vasopressors: bool
    mechanically_ventilated: bool

    @model_validator(mode="after")
    def _diastolic_below_systolic(self) -> ICURiskInput:
        if self.diastolic_bp_mmhg >= self.systolic_bp_mmhg:
            raise ValueError("diastolic_bp_mmhg must be lower than systolic_bp_mmhg")
        return self


class ICURiskOutput(BaseModel):
    predicted_icu_los_days: float = Field(ge=0)
    prolonged_stay_probability: float = Field(ge=0, le=1)
    prolonged_stay_threshold_days: float = Field(gt=0)
    model_version: str
    disclaimer: str = (
        "Model estimate for decision support only. It does not replace clinical judgement."
    )


# ---------------------------------------------------------------------------
# Uniform result envelope
# ---------------------------------------------------------------------------


class ToolErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    INTERNAL_ERROR = "internal_error"


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    retryable: bool = Field(
        description="True if the agent may retry, e.g. with corrected arguments or after a timeout."
    )


OutT = TypeVar("OutT", bound=BaseModel)


class ToolResult(BaseModel, Generic[OutT]):
    """Exactly one of ``data`` / ``error`` is set, consistent with ``ok``."""

    tool: str
    ok: bool
    data: OutT | None = None
    error: ToolError | None = None
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> ToolResult[OutT]:
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("successful result must have data and no error")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("failed result must have an error and no data")
        return self

    def to_llm_content(self) -> str:
        """Compact JSON for the tool-result message sent back to the model."""
        return self.model_dump_json(exclude={"duration_ms"}, exclude_none=True)
