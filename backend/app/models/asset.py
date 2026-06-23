# prism/backend/app/models/asset.py
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class PersonalAsset(Base):
    __tablename__ = "personal_asset"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    asset_kind = Column(String(64), default="idea", index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    summary = Column(Text)
    category = Column(String(128), default="", index=True)
    tags = Column(JSON, default=list)
    source_type = Column(String(64), default="manual", index=True)
    source_platform = Column(String(128), default="")
    source_url = Column(String(1000), default="")
    media_type = Column(String(64), default="text", index=True)
    extra_meta = Column(JSON, default=dict)
    capabilities = Column(JSON, default=list)
    source_raw_item_id = Column(CHAR(36), default="")
    source_draft_id = Column(CHAR(36), default="")
    source_ref_type = Column(String(64), default="")
    source_ref_id = Column(CHAR(36), default="")
    importance = Column(Float, default=0.5)
    status = Column(String(32), default="active", index=True, comment="active/archived")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class PersonalAssetItem(Base):
    __tablename__ = "personal_asset_item"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    raw_text = Column(Text, nullable=False)
    raw_title = Column(String(255), default="")
    raw_source_type = Column(String(64), default="manual", index=True)
    raw_source_platform = Column(String(128), default="")
    raw_source_url = Column(String(1000), default="")
    raw_author = Column(String(255), default="")
    raw_captured_at = Column(DateTime, default=local_now)
    raw_tags = Column(JSON, default=list)
    raw_metadata = Column(JSON, default=dict)
    

    raw_keywords = Column(JSON, default=list)
    keyword_index_text = Column(Text)
    raw_embedding_ref = Column(String(255), default="")
    raw_embedding_model = Column(String(128), default="")
    raw_embedding_status = Column(String(32), default="pending", index=True)
    raw_embedding_updated_at = Column(DateTime)

    asset_kind = Column(String(64), default="idea", index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    rewritten_content = Column(Text)
    summary = Column(Text)
    category = Column(String(128), default="", index=True)
    tags = Column(JSON, default=list)
    extracts = Column(JSON, default=list)
    suggested_relations = Column(JSON, default=list)
    suggested_extensions = Column(JSON, default=list)
    confidence = Column(JSON, default=dict)
    rationale = Column(Text)

    source_type = Column(String(64), default="manual", index=True)
    source_platform = Column(String(128), default="")
    source_url = Column(String(1000), default="")
    media_type = Column(String(64), default="text", index=True)
    extra_meta = Column(JSON, default=dict)
    capabilities = Column(JSON, default=list)
    source_ref_type = Column(String(64), default="fragment")
    source_ref_id = Column(CHAR(36), default="")
    importance = Column(Float, default=0.5)

    status = Column(String(32), default="pending_review", index=True, comment="pending_review/confirmed/rejected/archived")
    reviewed_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    edited_at = Column(DateTime)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    @property
    def raw_item_id(self):
        if isinstance(self.raw_metadata, dict):
            return self.raw_metadata.get("legacy_raw_item_id") or self.raw_metadata.get("source_item_id") or None
        return None

    @property
    def source_raw_item_id(self):
        return self.raw_item_id or self.id

    @property
    def source_draft_id(self):
        return self.id


class AssetRelation(Base):
    __tablename__ = "asset_relation"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    from_asset_id = Column(CHAR(36), ForeignKey("personal_asset_item.id", ondelete="CASCADE"), nullable=False)
    to_asset_id = Column(CHAR(36), ForeignKey("personal_asset_item.id", ondelete="CASCADE"), nullable=False)
    relation_type = Column(String(64), default="related", index=True)
    reason = Column(Text)
    confidence = Column(Float, default=0.5)
    source_draft_id = Column(CHAR(36), default="")
    status = Column(String(32), default="confirmed", index=True)
    created_at = Column(DateTime, default=local_now)


class ExtensionPoint(Base):
    __tablename__ = "extension_point"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    asset_id = Column(CHAR(36), ForeignKey("personal_asset_item.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    reason = Column(Text)
    suggested_kind = Column(String(64), default="knowledge")
    confidence = Column(Float, default=0.5)
    status = Column(String(32), default="confirmed", index=True)
    created_at = Column(DateTime, default=local_now)


class AssetUsageEvent(Base):
    __tablename__ = "asset_usage_event"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    session_id = Column(CHAR(36), default="", index=True)
    message_id = Column(CHAR(36), default="", index=True)
    asset_id = Column(CHAR(36), ForeignKey("personal_asset_item.id", ondelete="CASCADE"), nullable=False)
    usage_type = Column(String(64), default="cited", index=True)
    created_at = Column(DateTime, default=local_now)


class PersonalAssetUnit(Base):
    __tablename__ = "personal_asset_unit"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text)
    summary = Column(Text)
    category = Column(String(128), default="", index=True)
    tags = Column(JSON, default=list)
    source_asset_ids = Column(JSON, default=list)
    outline = Column(JSON, default=list)
    confidence = Column(JSON, default=dict)
    rationale = Column(Text)
    status = Column(String(32), default="pending_review", index=True, comment="pending_review/confirmed/rejected")
    confirmed_at = Column(DateTime)
    edited_at = Column(DateTime)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
