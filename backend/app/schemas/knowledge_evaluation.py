from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


GoldChunkUid = Annotated[str, StringConstraints(min_length=1, max_length=128)]
MAX_EVALUATION_ITEMS = 10_000
MAX_JSONL_LINE_LENGTH = 100_000


class EvaluationItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    gold_chunk_uids: list[GoldChunkUid] = Field(default_factory=list, max_length=1000)
    gold_answer: str | None = Field(default=None, max_length=100000)


class EvaluationDatasetImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    jsonl: str = Field(min_length=1, max_length=5_000_000)


class EvaluationDatasetGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    items: list[EvaluationItemInput] = Field(min_length=1, max_length=MAX_EVALUATION_ITEMS)


class RetrievalEvaluationConfig(BaseModel):
    """The complete set of evaluation controls passed to Task 6 retrieval."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["fast", "deep"] = "fast"
    top_k: int = Field(default=10, ge=1, le=100)
    graph_hops: int | None = Field(default=None, ge=1, le=3)
    timeout_seconds: int = Field(default=120, ge=30, le=600)


class EvaluationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_uid: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    config: RetrievalEvaluationConfig = Field(default_factory=RetrievalEvaluationConfig)
