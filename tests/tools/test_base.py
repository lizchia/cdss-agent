from __future__ import annotations

import asyncio
import logging

import pytest
from pydantic import BaseModel, ConfigDict, Field

from cdss.tools.base import (
    CDSSTool,
    InvalidToolInputError,
    NotFoundError,
    UpstreamUnavailableError,
)
from cdss.tools.schemas import ToolErrorCode


class EchoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    delay: float = 0.0
    fail_with: str | None = None


class EchoOut(BaseModel):
    text: str


class EchoTool(CDSSTool[EchoIn, EchoOut]):
    def __init__(self, timeout_seconds: float = 1.0) -> None:
        super().__init__(
            name="echo_tool",
            description="Echoes text back.",
            input_model=EchoIn,
            timeout_seconds=timeout_seconds,
        )

    async def _run(self, args: EchoIn) -> EchoOut:
        if args.delay:
            await asyncio.sleep(args.delay)
        match args.fail_with:
            case "not_found":
                raise NotFoundError("patient not found")
            case "upstream":
                raise UpstreamUnavailableError("database unavailable")
            case "semantic":
                raise InvalidToolInputError("lookback window exceeds admission")
            case "boom":
                raise RuntimeError("secret internal stack detail")
        return EchoOut(text=args.text)


async def test_success() -> None:
    result = await EchoTool().invoke({"text": "hi"})
    assert result.ok and result.data is not None
    assert result.data.text == "hi"
    assert result.tool == "echo_tool"
    assert result.duration_ms >= 0


async def test_schema_violation_is_retryable_and_hides_input_values() -> None:
    phi = "John Doe MRN 12345"
    result = await EchoTool().invoke({"text": "", "unexpected": phi})
    assert not result.ok and result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_INPUT
    assert result.error.retryable is True
    assert "text" in result.error.message and "unexpected" in result.error.message
    assert phi not in result.error.message


async def test_timeout_is_retryable() -> None:
    result = await EchoTool(timeout_seconds=0.05).invoke({"text": "x", "delay": 1.0})
    assert result.error is not None
    assert result.error.code is ToolErrorCode.TIMEOUT
    assert result.error.retryable is True


@pytest.mark.parametrize(
    "fail_with,code,retryable",
    [
        ("not_found", ToolErrorCode.NOT_FOUND, False),
        ("upstream", ToolErrorCode.UPSTREAM_UNAVAILABLE, True),
        ("semantic", ToolErrorCode.INVALID_INPUT, True),
    ],
)
async def test_classified_errors(fail_with: str, code: ToolErrorCode, retryable: bool) -> None:
    result = await EchoTool().invoke({"text": "x", "fail_with": fail_with})
    assert result.error is not None
    assert (result.error.code, result.error.retryable) == (code, retryable)


async def test_unexpected_exception_is_sanitised(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        result = await EchoTool().invoke({"text": "x", "fail_with": "boom"})
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INTERNAL_ERROR
    assert result.error.retryable is False
    assert "secret internal stack detail" not in result.error.message
    assert any(r.message == "tool_unhandled_exception" for r in caplog.records)


async def test_cancellation_propagates() -> None:
    task = asyncio.create_task(EchoTool(timeout_seconds=5).invoke({"text": "x", "delay": 5}))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_tool_spec_shape() -> None:
    spec = EchoTool().tool_spec()
    assert spec["name"] == "echo_tool"
    assert spec["input_schema"]["additionalProperties"] is False
    assert "text" in spec["input_schema"]["required"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "bad name!", "description": "d", "timeout_seconds": 1},
        {"name": "ok", "description": "  ", "timeout_seconds": 1},
        {"name": "ok", "description": "d", "timeout_seconds": 0},
    ],
)
def test_constructor_validation(kwargs: dict[str, object]) -> None:
    class _T(CDSSTool[EchoIn, EchoOut]):
        async def _run(self, args: EchoIn) -> EchoOut:
            return EchoOut(text=args.text)

    with pytest.raises(ValueError):
        _T(input_model=EchoIn, **kwargs)  # type: ignore[arg-type]
