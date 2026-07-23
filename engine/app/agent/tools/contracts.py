"""Shared, model-visible contract for knowledge tool results."""
from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class ToolWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ToolProblem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False


class ToolEnvelope(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "no_hits", "degraded", "error"]
    data: T | None = None
    warnings: list[ToolWarning] = Field(default_factory=list)
    error: ToolProblem | None = None
    trace_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status_shape(self):
        if self.status == "error":
            if self.error is None or self.data is not None:
                raise ValueError("error envelopes require error and forbid data")
        elif self.error is not None:
            raise ValueError("non-error envelopes cannot contain error")
        return self

    @classmethod
    def ok(cls, data: T, trace_id: str):
        return cls(status="ok", data=data, trace_id=trace_id)

    @classmethod
    def no_hits(cls, data: T, trace_id: str):
        return cls(status="no_hits", data=data, trace_id=trace_id)

    @classmethod
    def degraded(
        cls,
        data: T,
        warnings: list[ToolWarning],
        trace_id: str,
    ):
        return cls(status="degraded", data=data, warnings=warnings, trace_id=trace_id)

    @classmethod
    def from_error(cls, problem: ToolProblem, trace_id: str):
        return cls(status="error", error=problem, trace_id=trace_id)
