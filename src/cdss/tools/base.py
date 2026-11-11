"""Shared tool runtime: validation, timeout, error classification and the result envelope.

Concrete tools subclass :class:`CDSSTool` and implement only ``_run``. ``invoke`` never
raises for expected failures; it returns a :class:`ToolResult` whose ``error.retryable``
flag tells the agent graph whether a corrective retry is worthwhile.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from cdss.tools.schemas import ToolError, ToolErrorCode, ToolResult

logger = logging.getLogger(__name__)

InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT", bound=BaseModel)

# Bedrock / Anthropic tool-name constraint.
_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ToolExecutionError(Exception):
    """Expected, classified failure raised from inside a tool's ``_run``."""

    code: ToolErrorCode = ToolErrorCode.INTERNAL_ERROR
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidToolInputError(ToolExecutionError):
    """Arguments passed schema validation but are semantically invalid; the LLM can fix them."""

    code = ToolErrorCode.INVALID_INPUT
    retryable = True


class NotFoundError(ToolExecutionError):
    code = ToolErrorCode.NOT_FOUND
    retryable = False


class UpstreamUnavailableError(ToolExecutionError):
    """A dependency (DB, Bedrock, vector store) is temporarily unavailable."""

    code = ToolErrorCode.UPSTREAM_UNAVAILABLE
    retryable = True


def format_validation_error(exc: ValidationError) -> str:
    """Summarise validation errors for the LLM without echoing input values (may contain PHI)."""
    parts: list[str] = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


class CDSSTool(ABC, Generic[InT, OutT]):
    """Base class for agent tools with a strict input schema and a uniform result envelope."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_model: type[InT],
        timeout_seconds: float,
    ) -> None:
        if not _TOOL_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid tool name {name!r}; must match {_TOOL_NAME_RE.pattern}")
        if not description.strip():
            raise ValueError("tool description must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.name = name
        self.description = description
        self.input_model = input_model
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def _run(self, args: InT) -> OutT:
        """Execute the tool on validated arguments."""

    def tool_spec(self) -> dict[str, Any]:
        """Tool definition in Bedrock/Anthropic format for binding to the chat model."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }

    async def invoke(self, raw_args: Mapping[str, Any]) -> ToolResult[OutT]:
        """Validate, execute with a timeout, and wrap the outcome. Never raises for tool errors."""
        start = time.perf_counter()

        try:
            args = self.input_model.model_validate(dict(raw_args))
        except ValidationError as exc:
            return self._failure(
                ToolErrorCode.INVALID_INPUT, format_validation_error(exc), True, start
            )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                data = await self._run(args)
        except TimeoutError:
            return self._failure(
                ToolErrorCode.TIMEOUT,
                f"tool did not finish within {self.timeout_seconds:g}s",
                True,
                start,
            )
        except ToolExecutionError as exc:
            return self._failure(exc.code, exc.message, exc.retryable, start)
        except Exception:
            logger.exception("tool_unhandled_exception", extra={"tool": self.name})
            return self._failure(
                ToolErrorCode.INTERNAL_ERROR,
                "the tool failed due to an internal error",
                False,
                start,
            )

        duration_ms = _elapsed_ms(start)
        logger.info(
            "tool_call",
            extra={"tool": self.name, "outcome": "ok", "duration_ms": round(duration_ms, 1)},
        )
        return ToolResult[OutT](tool=self.name, ok=True, data=data, duration_ms=duration_ms)

    def _failure(
        self, code: ToolErrorCode, message: str, retryable: bool, start: float
    ) -> ToolResult[OutT]:
        duration_ms = _elapsed_ms(start)
        logger.warning(
            "tool_call",
            extra={
                "tool": self.name,
                "outcome": code.value,
                "retryable": retryable,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return ToolResult[OutT](
            tool=self.name,
            ok=False,
            error=ToolError(code=code, message=message, retryable=retryable),
            duration_ms=duration_ms,
        )


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
