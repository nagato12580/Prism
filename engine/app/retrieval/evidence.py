from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChannelScore(_FrozenContract):
    raw_score: float
    raw_rank: int = Field(ge=1)


class ChannelProblem(_FrozenContract):
    code: str = Field(min_length=1)
    message: str = ""
    retryable: bool = False


class FrozenDict(dict):
    """JSON-compatible dict whose mutation operations are disabled."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("frozen mapping is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


def _deep_freeze(value):
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


class Evidence(_FrozenContract):
    evidence_id: Literal[None] = None
    tenant_id: str = Field(min_length=1)
    kb_uid: str = Field(min_length=1)
    file_uid: str = Field(min_length=1)
    item_id: str | None = None
    chunk_uid: str = Field(min_length=1)
    parent_chunk_uid: str | None = None
    display_title: str
    original_filename: str | None = None
    excerpt: str
    page_start: int | None = Field(default=None, ge=0)
    page_end: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    channel_scores: dict[str, ChannelScore] = Field(default_factory=dict)
    rrf_score: float
    rerank_score: float | None = None
    rerank_model: str | None = None
    retrieval_channels: tuple[Literal["dense", "bm25", "graph"], ...] = ()
    graph_path: tuple[dict[str, Any], ...] = ()
    graph_explanation: str | None = None
    evidence_type: Literal["chunk", "graph_path", "entity"] = "chunk"
    index_generation: str = Field(min_length=1)
    degradation_flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> Self:
        for start, end, label in (
            (self.page_start, self.page_end, "page"),
            (self.char_start, self.char_end, "char"),
        ):
            if start is not None and end is not None and end < start:
                raise ValueError(f"{label}_end must not precede {label}_start")
        object.__setattr__(self, "channel_scores", _deep_freeze(self.channel_scores))
        object.__setattr__(self, "graph_path", _deep_freeze(self.graph_path))
        return self


class RetrievalResponse(_FrozenContract):
    status: Literal["ok", "no_hits", "degraded", "unavailable", "invalid_request"]
    evidence: tuple[Evidence, ...] = ()
    warnings: tuple[ChannelProblem, ...] = ()
