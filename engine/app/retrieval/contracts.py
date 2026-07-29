from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class SearchScope(BaseModel):
    tenant_id: str = Field(min_length=1)
    kb_uid: str = Field(min_length=1)
    index_generation: str = Field(min_length=1)
    graph_generation: str | None = None
    file_uids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()


class Candidate(BaseModel):
    chunk_uid: str
    item_id: str
    file_uid: str
    channel: Literal["dense", "bm25", "graph"]
    raw_score: float
    raw_rank: int
    metadata: dict = Field(default_factory=dict)


class ChannelProblem(BaseModel):
    code: str
    message: str = ""
    retryable: bool = False


class ChannelResult(BaseModel):
    channel: str
    health: Literal["ok", "degraded", "failed"]
    candidates: list[Candidate] = Field(default_factory=list)
    elapsed_ms: int = 0
    problem: ChannelProblem | None = None

    @model_validator(mode="after")
    def health_matches_problem(self) -> Self:
        if self.health == "ok" and self.problem is not None:
            raise ValueError("ok channel result cannot have a problem")
        if self.health in {"degraded", "failed"} and self.problem is None:
            raise ValueError(f"{self.health} channel result requires a problem")
        return self

    @classmethod
    def ok(cls, channel: str, candidates: list[Candidate]) -> Self:
        return cls(channel=channel, health="ok", candidates=candidates)

    @classmethod
    def failed(cls, channel: str, code: str, retryable: bool, message: str = "") -> Self:
        return cls(
            channel=channel,
            health="failed",
            problem=ChannelProblem(code=code, message=message, retryable=retryable),
        )
