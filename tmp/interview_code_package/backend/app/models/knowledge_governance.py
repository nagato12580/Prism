# prism/backend/app/models/knowledge_governance.py
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class PersonalKnowledgeUnit(Base):
    __tablename__ = "personal_knowledge_unit"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_kind",
            "source_id",
            "unit_type",
            "normalized_statement_hash",
            name="uq_pku_source_normalized",
        ),
        Index("ix_pku_source", "source_kind", "source_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    source_kind = Column(String(64), nullable=False, index=True, comment="document_chunk/personal_asset_item")
    source_id = Column(CHAR(36), nullable=False, index=True)

    unit_type = Column(String(64), default="claim", index=True)
    statement = Column(Text, nullable=False)
    normalized_statement = Column(Text, nullable=False)
    normalized_statement_hash = Column(String(64), nullable=False, index=True)

    subject = Column(String(255), default="")
    predicate = Column(String(255), default="")
    object = Column(Text)

    polarity = Column(String(32), default="unknown", index=True)
    modality = Column(String(64), default="unknown", index=True)

    domains = Column(JSON, default=list)
    entities = Column(JSON, default=list)
    concepts = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    scope = Column(JSON, default=dict)
    conditions = Column(JSON, default=dict)

    evidence_span = Column(Text)
    confidence = Column(Float, default=0.5)
    llm_model = Column(String(128), default="")
    embedding_ref = Column(String(255), default="")
    embedding_model = Column(String(128), default="")
    embedding_status = Column(String(32), default="pending", index=True)

    status = Column(String(32), default="active", index=True, comment="active/merged/deprecated/rejected")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    canonical_links = relationship("PKUCanonicalLink", back_populates="pku", cascade="all, delete-orphan")
    outgoing_relations = relationship(
        "PKURelation",
        foreign_keys="PKURelation.source_pku_id",
        back_populates="source_pku",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "PKURelation",
        foreign_keys="PKURelation.target_pku_id",
        back_populates="target_pku",
        cascade="all, delete-orphan",
    )


class CanonicalKnowledgePoint(Base):
    __tablename__ = "canonical_knowledge_point"
    __table_args__ = (
        Index("ix_ckp_title", "title"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    canonical_type = Column(String(64), default="claim", index=True)
    title = Column(String(255), nullable=False)
    canonical_statement = Column(Text, nullable=False)
    summary = Column(Text)

    aliases = Column(JSON, default=list)
    domains = Column(JSON, default=list)
    entities = Column(JSON, default=list)
    concepts = Column(JSON, default=list)
    keywords = Column(JSON, default=list)
    scope = Column(JSON, default=dict)
    conditions = Column(JSON, default=dict)

    status = Column(String(32), default="draft", index=True, comment="draft/stable/disputed/deprecated")
    confidence = Column(Float, default=0.5)
    embedding_ref = Column(String(255), default="")
    embedding_model = Column(String(128), default="")
    embedding_status = Column(String(32), default="pending", index=True)
    extra_meta = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    pku_links = relationship("PKUCanonicalLink", back_populates="canonical", cascade="all, delete-orphan")
    outgoing_relations = relationship(
        "CanonicalRelation",
        foreign_keys="CanonicalRelation.source_canonical_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "CanonicalRelation",
        foreign_keys="CanonicalRelation.target_canonical_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )


class PKUCanonicalLink(Base):
    __tablename__ = "pku_canonical_link"
    __table_args__ = (
        UniqueConstraint("pku_id", "canonical_id", "relation_type", name="uq_pku_ckp_relation"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    pku_id = Column(CHAR(36), ForeignKey("personal_knowledge_unit.id", ondelete="CASCADE"), nullable=False, index=True)
    canonical_id = Column(CHAR(36), ForeignKey("canonical_knowledge_point.id", ondelete="CASCADE"), nullable=False, index=True)

    relation_type = Column(String(64), default="same_as", index=True)
    role = Column(String(64), default="origin", index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)

    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    pku = relationship("PersonalKnowledgeUnit", back_populates="canonical_links")
    canonical = relationship("CanonicalKnowledgePoint", back_populates="pku_links")


class PKURelation(Base):
    __tablename__ = "pku_relation"
    __table_args__ = (
        UniqueConstraint(
            "source_pku_id",
            "target_pku_id",
            "relation_type",
            name="uq_pku_relation",
        ),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    source_pku_id = Column(
        CHAR(36),
        ForeignKey("personal_knowledge_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_pku_id = Column(
        CHAR(36),
        ForeignKey("personal_knowledge_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relation_type = Column(String(64), default="related_to", index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    source_kind = Column(String(64), default="", index=True)
    source_id = Column(CHAR(36), default="", index=True)
    llm_model = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source_pku = relationship(
        "PersonalKnowledgeUnit",
        foreign_keys=[source_pku_id],
        back_populates="outgoing_relations",
    )
    target_pku = relationship(
        "PersonalKnowledgeUnit",
        foreign_keys=[target_pku_id],
        back_populates="incoming_relations",
    )


class CanonicalRelation(Base):
    __tablename__ = "canonical_relation"
    __table_args__ = (
        UniqueConstraint(
            "source_canonical_id",
            "target_canonical_id",
            "relation_type",
            name="uq_ckp_relation",
        ),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    source_canonical_id = Column(
        CHAR(36),
        ForeignKey("canonical_knowledge_point.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_canonical_id = Column(
        CHAR(36),
        ForeignKey("canonical_knowledge_point.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relation_type = Column(String(64), default="related_to", index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    extra_meta = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source = relationship(
        "CanonicalKnowledgePoint",
        foreign_keys=[source_canonical_id],
        back_populates="outgoing_relations",
    )
    target = relationship(
        "CanonicalKnowledgePoint",
        foreign_keys=[target_canonical_id],
        back_populates="incoming_relations",
    )
