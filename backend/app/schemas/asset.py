# prism/backend/app/schemas/asset.py
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AssetDraftCreate(BaseModel):
    raw_item_id: Optional[str] = None
    content: Optional[str] = None
    title: Optional[str] = None
    source_type: str = "manual"
    source_platform: Optional[str] = None
    source_url: Optional[str] = None


class PersonalAssetItemCreate(BaseModel):
    raw_text: str
    raw_title: Optional[str] = None
    raw_source_type: str = "manual"
    raw_source_platform: Optional[str] = None
    raw_source_url: Optional[str] = None
    raw_author: Optional[str] = None
    raw_tags: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class AssetDraftUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    asset_kind: Optional[str] = None
    source_type: Optional[str] = None
    source_platform: Optional[str] = None
    source_url: Optional[str] = None
    media_type: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    extracts: Optional[list[dict[str, Any]]] = None
    suggested_relations: Optional[list[dict[str, Any]]] = None
    suggested_extensions: Optional[list[dict[str, Any]]] = None
    confidence: Optional[dict[str, Any]] = None
    rationale: Optional[str] = None


class PersonalAssetItemUpdate(AssetDraftUpdate):
    raw_text: Optional[str] = None
    raw_title: Optional[str] = None
    raw_source_type: Optional[str] = None
    raw_source_platform: Optional[str] = None
    raw_source_url: Optional[str] = None
    raw_author: Optional[str] = None
    raw_tags: Optional[list[str]] = None
    raw_metadata: Optional[dict[str, Any]] = None
    raw_keywords: Optional[list[str]] = None
    keyword_index_text: Optional[str] = None
    body: Optional[str] = None


class PersonalAssetItemOut(BaseModel):
    id: str
    user_id: str
    raw_text: str
    raw_title: str
    raw_source_type: str
    raw_source_platform: str
    raw_source_url: str
    raw_author: str
    raw_captured_at: datetime
    raw_tags: list[str]
    raw_metadata: dict[str, Any]
    raw_keywords: list[str]
    keyword_index_text: Optional[str]
    raw_embedding_ref: str
    raw_embedding_model: str
    raw_embedding_status: str
    raw_embedding_updated_at: Optional[datetime]
    title: str
    body: Optional[str]
    summary: Optional[str]
    asset_kind: str
    source_type: str
    source_platform: str
    source_url: str
    media_type: str
    category: str
    tags: list[str]
    extracts: list[dict[str, Any]]
    suggested_relations: list[dict[str, Any]]
    suggested_extensions: list[dict[str, Any]]
    confidence: dict[str, Any]
    rationale: Optional[str]
    extra_meta: dict[str, Any]
    capabilities: list[str]
    source_raw_item_id: str
    source_draft_id: str
    source_ref_type: str
    source_ref_id: str
    importance: float
    status: str
    reviewed_at: Optional[datetime]
    confirmed_at: Optional[datetime]
    edited_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    raw_item_id: Optional[str] = None

    class Config:
        from_attributes = True


class AssetDraftOut(PersonalAssetItemOut):
    pass


class PersonalAssetOut(PersonalAssetItemOut):
    pass


class AssetConfirmRequest(BaseModel):
    confirm_relations: list[dict[str, Any]] = Field(default_factory=list)
    confirm_extensions: list[dict[str, Any]] = Field(default_factory=list)
    create_memory: bool = False


class AssetConfirmResponse(BaseModel):
    item: PersonalAssetItemOut
    draft: PersonalAssetItemOut
    asset: PersonalAssetOut
    relation_count: int = 0
    extension_count: int = 0
    pku_count: int = 0
    canonical_count: int = 0
    governance_link_count: int = 0


class AssetSearchResult(BaseModel):
    asset_id: str
    asset_kind: str
    title: str
    summary: Optional[str]
    source_type: str
    source_platform: str
    tags: list[str]
    category: str
    score: float


class AssetOverviewOut(BaseModel):
    summary: str
    categories: list[dict[str, Any]]
    tags: list[dict[str, Any]]
    representative_assets: list[AssetSearchResult]


class KnowledgeDraftCreate(BaseModel):
    asset_ids: list[str] = Field(..., min_length=1)
    title: Optional[str] = None
    instruction: Optional[str] = None


class KnowledgeDraftUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    outline: Optional[list[dict[str, Any]]] = None
    confidence: Optional[dict[str, Any]] = None
    rationale: Optional[str] = None


class KnowledgeDraftOut(BaseModel):
    id: str
    user_id: str
    title: str
    content: Optional[str]
    summary: Optional[str]
    category: str
    tags: list[str]
    source_asset_ids: list[str]
    outline: list[dict[str, Any]]
    confidence: dict[str, Any]
    rationale: Optional[str]
    status: str
    knowledge_item_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeDraftConfirmRequest(BaseModel):
    ingest: bool = False


class KnowledgeDraftConfirmResponse(BaseModel):
    draft: KnowledgeDraftOut
    knowledge_item_id: str
