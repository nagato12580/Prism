# prism/backend/app/models/entity.py
import hashlib
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint, event
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entity"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "normalized_key", name="uq_entity_user_type_key"),
        Index("ix_entity_lookup", "user_id", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    canonical_name = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    aliases = Column(JSON, default=list)
    description = Column(Text)
    confidence = Column(Float, default=0.5)
    status = Column(String(32), default="active", index=True)
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    entity_aliases = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")
    mentions = relationship("EntityMention", back_populates="entity", cascade="all, delete-orphan")
    outgoing_relations = relationship(
        "EntityRelation",
        foreign_keys="EntityRelation.subject_entity_id",
        back_populates="subject_entity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    incoming_relations = relationship(
        "EntityRelation",
        foreign_keys="EntityRelation.object_entity_id",
        back_populates="object_entity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_key", name="uq_entity_alias_key"),
        Index("ix_entity_alias_lookup", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    created_at = Column(DateTime, default=local_now)

    entity = relationship("KnowledgeEntity", back_populates="entity_aliases")


class EntityMention(Base):
    __tablename__ = "entity_mention"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "source_kind",
            "source_id",
            "surface_text",
            name="uq_entity_mention_source_surface",
        ),
        Index("ix_entity_mention_source", "source_kind", "source_id"),
        Index("ix_entity_mention_key", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    source_kind = Column(String(64), nullable=False, index=True)
    source_id = Column(CHAR(36), nullable=False, index=True)
    item_id = Column(CHAR(36), default="", index=True)
    chunk_id = Column(CHAR(36), default="", index=True)
    surface_text = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    evidence_span = Column(Text)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)

    entity = relationship("KnowledgeEntity", back_populates="mentions")


class EntityRelation(Base):
    __tablename__ = "entity_relation"
    __table_args__ = (
        UniqueConstraint("relation_key", name="uq_entity_relation_evidence"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    subject_entity_id = Column(
        CHAR(36),
        ForeignKey("knowledge_entity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predicate = Column(String(128), nullable=False, index=True)
    object_entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=True, index=True)
    object_literal = Column(Text)
    relation_key = Column(String(64), nullable=False, index=True)
    source_kind = Column(String(64), nullable=False, index=True)
    source_id = Column(CHAR(36), nullable=False, index=True)
    evidence_span = Column(Text)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)

    subject_entity = relationship(
        "KnowledgeEntity",
        foreign_keys=[subject_entity_id],
        back_populates="outgoing_relations",
    )
    object_entity = relationship(
        "KnowledgeEntity",
        foreign_keys=[object_entity_id],
        back_populates="incoming_relations",
    )


def compute_relation_key(
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str | None,
    object_literal: str | None,
    source_kind: str,
    source_id: str,
) -> str:
    parts = [
        subject_entity_id or "",
        predicate or "",
        object_entity_id or "",
        object_literal or "",
        source_kind or "",
        source_id or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _set_relation_key(mapper, connection, target):
    target.relation_key = compute_relation_key(
        target.subject_entity_id,
        target.predicate,
        target.object_entity_id,
        target.object_literal,
        target.source_kind,
        target.source_id,
    )


event.listen(EntityRelation, "before_insert", _set_relation_key)
event.listen(EntityRelation, "before_update", _set_relation_key)
