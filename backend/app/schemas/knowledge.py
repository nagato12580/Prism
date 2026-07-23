# prism/backend/app/schemas/knowledge.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated, Literal, Optional


MAX_RETRIEVAL_FILTER_ITEMS = 100
MAX_RETRIEVAL_FILE_UID_LENGTH = 128
MAX_RETRIEVAL_SOURCE_TYPE_LENGTH = 64
RetrievalFileUid = Annotated[str, StringConstraints(min_length=1, max_length=MAX_RETRIEVAL_FILE_UID_LENGTH)]
RetrievalSourceType = Annotated[str, StringConstraints(min_length=1, max_length=MAX_RETRIEVAL_SOURCE_TYPE_LENGTH)]


class KnowledgeItemCreate(BaseModel):
    title: str = Field(..., max_length=255)
    content: Optional[str] = None
    source_type: str = "manual"
    source_ref: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None


class KnowledgeItemUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None
    status: Optional[str] = None


class KnowledgeItemOut(BaseModel):
    id: str
    title: str
    content: Optional[str]
    summary: Optional[str]
    source_type: str
    source_ref: Optional[str]
    tags: Optional[list[str]]
    category: Optional[str]
    status: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeItemListOut(BaseModel):
    """列表项（不含 content，避免响应过大）。"""
    id: str
    title: str
    summary: Optional[str]
    source_type: str
    tags: Optional[list[str]]
    category: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeTopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    resource_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeJobSummary(BaseModel):
    id: str
    job_type: str
    status: str
    stage: str
    attempts: int
    max_attempts: int
    progress_current: int
    progress_total: int
    error_code: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


class TopicIngestOut(BaseModel):
    queued: int
    skipped: int
    failed: int
    job_ids: list[str] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class KnowledgeResourceUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


class KnowledgeResourceOut(BaseModel):
    id: str
    user_id: str
    topic_id: Optional[str]
    item_id: Optional[str]
    title: str
    original_filename: str
    media_type: Literal["document", "image", "audio", "video"]
    mime_type: Optional[str]
    file_ext: str
    file_size: int
    md5: str
    storage_path: str
    processing_status: str
    description: Optional[str]
    tags: Optional[list[str]]
    source_type: str
    page_count: Optional[int]
    content_text: Optional[str]
    uploaded_at: datetime
    last_modified_at: datetime
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str]
    governance_status: str = "not_started"
    governance_progress_current: int = 0
    governance_progress_total: int = 0
    governance_error_message: Optional[str] = None
    governance_started_at: Optional[datetime] = None
    governance_finished_at: Optional[datetime] = None
    latest_job: Optional[KnowledgeJobSummary] = None

    class Config:
        from_attributes = True


class KnowledgeRetrievalFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_uids: tuple[RetrievalFileUid, ...] = Field(default=(), max_length=MAX_RETRIEVAL_FILTER_ITEMS)
    source_types: tuple[RetrievalSourceType, ...] = Field(default=(), max_length=MAX_RETRIEVAL_FILTER_ITEMS)


class KnowledgeRetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(default=10, ge=1, le=100)
    graph_hops: int | None = Field(default=None, ge=1, le=3)


class KnowledgeRetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["fast", "deep"] = "fast"
    filters: KnowledgeRetrievalFilters = Field(default_factory=KnowledgeRetrievalFilters)
    config: KnowledgeRetrievalConfig = Field(default_factory=KnowledgeRetrievalConfig)


class PublicChannelScore(BaseModel):
    raw_score: float
    raw_rank: int


class PublicChannelProblem(BaseModel):
    code: str
    message: str = ""
    retryable: bool = False


class PublicEvidence(BaseModel):
    evidence_id: None = None
    kb_uid: str
    file_uid: str
    item_id: str | None = None
    chunk_uid: str
    parent_chunk_uid: str | None = None
    display_title: str
    original_filename: str | None = None
    excerpt: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    channel_scores: dict[str, PublicChannelScore] = Field(default_factory=dict)
    rrf_score: float
    rerank_score: float | None = None
    rerank_model: str | None = None
    retrieval_channels: tuple[Literal["dense", "bm25", "graph"], ...] = ()
    graph_path: tuple[dict, ...] = ()
    graph_explanation: str | None = None
    evidence_type: Literal["chunk", "graph_path", "entity"]
    index_generation: str
    degradation_flags: tuple[str, ...] = ()


class KnowledgeRetrievalResponse(BaseModel):
    status: Literal["ok", "no_hits", "degraded"]
    evidence: list[PublicEvidence] = Field(default_factory=list)
    warnings: list[PublicChannelProblem] = Field(default_factory=list)


class EngineRetrievalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "no_hits", "degraded", "unavailable", "invalid_request"]
    evidence: list[PublicEvidence]
    warnings: list[PublicChannelProblem]
