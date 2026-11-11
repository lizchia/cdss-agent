from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cdss.tools.schemas import (
    GuidelineSearchInput,
    ICURiskInput,
    PatientDataInput,
    PatientDataOutput,
    PatientQuery,
    ToolError,
    ToolErrorCode,
    ToolResult,
)


def _valid_risk_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "age_years": 67,
        "heart_rate_bpm": 112,
        "systolic_bp_mmhg": 94,
        "diastolic_bp_mmhg": 58,
        "respiratory_rate_bpm": 26,
        "spo2_percent": 91,
        "temperature_c": 38.6,
        "gcs": 14,
        "lactate_mmol_l": 3.1,
        "creatinine_mg_dl": 1.8,
        "wbc_k_per_ul": 16.2,
        "on_vasopressors": False,
        "mechanically_ventilated": False,
    }
    payload.update(overrides)
    return payload


class TestPatientDataInput:
    def test_defaults_applied(self) -> None:
        m = PatientDataInput.model_validate({"query": "recent_labs", "patient_id": str(uuid4())})
        assert m.query is PatientQuery.RECENT_LABS
        assert (m.lookback_hours, m.limit) == (72, 50)

    @pytest.mark.parametrize(
        "bad",
        [
            {"query": "drop_tables"},
            {"patient_id": "1; DROP TABLE patients;--"},
            {"lookback_hours": 0},
            {"limit": 10_000},
            {"sql": "SELECT * FROM patients"},  # extra keys forbidden
        ],
    )
    def test_rejects_invalid_or_injected_args(self, bad: dict[str, Any]) -> None:
        payload: dict[str, Any] = {"query": "demographics", "patient_id": str(uuid4()), **bad}
        with pytest.raises(ValidationError):
            PatientDataInput.model_validate(payload)

    def test_json_schema_exposes_enum_to_llm(self) -> None:
        schema = PatientDataInput.model_json_schema()
        assert schema["additionalProperties"] is False
        enum_def = schema["$defs"]["PatientQuery"]["enum"]
        assert set(enum_def) == {q.value for q in PatientQuery}


class TestGuidelineSearchInput:
    def test_strips_whitespace(self) -> None:
        m = GuidelineSearchInput(query="   sepsis fluid resuscitation  ")
        assert m.query == "sepsis fluid resuscitation"

    @pytest.mark.parametrize("specialty", ["Cardiology", "crit care", "x", "a" * 41])
    def test_specialty_pattern(self, specialty: str) -> None:
        with pytest.raises(ValidationError):
            GuidelineSearchInput(query="anticoagulation", specialty=specialty)

    def test_query_too_short(self) -> None:
        with pytest.raises(ValidationError):
            GuidelineSearchInput(query="ab")


class TestICURiskInput:
    def test_valid(self) -> None:
        assert ICURiskInput.model_validate(_valid_risk_payload()).gcs == 14

    @pytest.mark.parametrize(
        "field,value",
        [("age_years", 12), ("spo2_percent", 120), ("gcs", 2), ("temperature_c", 50)],
    )
    def test_out_of_physiologic_range(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError):
            ICURiskInput.model_validate(_valid_risk_payload(**{field: value}))

    def test_diastolic_must_be_below_systolic(self) -> None:
        with pytest.raises(ValidationError, match="diastolic"):
            ICURiskInput.model_validate(
                _valid_risk_payload(systolic_bp_mmhg=90, diastolic_bp_mmhg=95)
            )


class TestToolResult:
    def _data(self) -> PatientDataOutput:
        return PatientDataOutput(
            query=PatientQuery.DEMOGRAPHICS, patient_id=uuid4(), row_count=0, rows=[]
        )

    def test_success_requires_data(self) -> None:
        with pytest.raises(ValidationError):
            ToolResult[PatientDataOutput](tool="t", ok=True, duration_ms=1.0)

    def test_failure_requires_error_and_no_data(self) -> None:
        err = ToolError(code=ToolErrorCode.TIMEOUT, message="slow", retryable=True)
        with pytest.raises(ValidationError):
            ToolResult[PatientDataOutput](tool="t", ok=False, duration_ms=1.0)
        with pytest.raises(ValidationError):
            ToolResult[PatientDataOutput](
                tool="t", ok=False, data=self._data(), error=err, duration_ms=1.0
            )

    def test_llm_content_is_compact_json(self) -> None:
        r = ToolResult[PatientDataOutput](tool="t", ok=True, data=self._data(), duration_ms=3.2)
        content = json.loads(r.to_llm_content())
        assert content["ok"] is True
        assert "duration_ms" not in content
        assert "error" not in content
