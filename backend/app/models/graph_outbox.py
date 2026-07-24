# prism/backend/app/models/graph_outbox.py
"""Scoped graph facts, generations, and transactional Outbox state.

Entity/Mention/Relation facts live in MySQL under ``tenant_id + kb_uid +
graph_generation``. Fact changes and immutable Outbox events commit in the same
transaction; Engine projectors (``neo4j``, ``milvus_graph``) independently claim
each event and record per-target receipts/cursors. Neo4j and Milvus are
disposable projections of this authoritative MySQL store.
"""
import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def new_uuid() -> str:
    return str(uuid.uuid4())


class KnowledgeGraphGeneration(Base):
    """One graph build/publication record per (tenant, kb, generation)."""

    __tablename__ = "knowledge_graph_generation"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kb_uid", "generation", name="uq_graph_generation_scope"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    generation = Column(CHAR(36), nullable=False)
    extractor_config_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="building")
    barrier_sequence = Column(BigInteger, nullable=True)
    failure_code = Column(String(64), nullable=False, default="")
    failure_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=local_now)
    activated_at = Column(DateTime)


class GraphExtractionRevision(Base):
    """Idempotent extraction identity for one Chunk content/config combination."""

    __tablename__ = "graph_extraction_revision"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "kb_uid",
            "chunk_uid",
            "content_hash",
            "extractor_config_hash",
            name="uq_graph_extraction_key",
        ),
    )

    revision_id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    file_uid = Column(CHAR(36), nullable=False, index=True)
    item_id = Column(CHAR(36), nullable=False, index=True)
    chunk_uid = Column(CHAR(36), nullable=False, index=True)
    graph_generation = Column(CHAR(36), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False)
    extractor_config_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    model_version = Column(String(255), nullable=False)
    prompt_version = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=local_now)


# BigInteger on MySQL (monotonic outbox sequence), Integer on SQLite for test
# compatibility (SQLite AUTOINCREMENT requires INTEGER PRIMARY KEY).
MYSQL_SEQUENCE = BigInteger().with_variant(Integer, "sqlite")


class GraphOutboxEvent(Base):
    """Immutable graph fact-change event, committed with the fact transaction."""

    __tablename__ = "graph_outbox_event"
    __table_args__ = (
        Index(
            "ix_graph_outbox_scope_sequence",
            "tenant_id",
            "kb_uid",
            "graph_generation",
            "sequence",
        ),
    )

    sequence = Column(MYSQL_SEQUENCE, primary_key=True, autoincrement=True)
    event_id = Column(CHAR(36), nullable=False, unique=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_uid = Column(CHAR(36), nullable=False, index=True)
    graph_generation = Column(CHAR(36), nullable=False, index=True)
    aggregate_type = Column(String(32), nullable=False)
    aggregate_id = Column(CHAR(36), nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=local_now)


class GraphProjectionReceipt(Base):
    """Per-event, per-projector durable retry/cursor state."""

    __tablename__ = "graph_projection_receipt"
    __table_args__ = (
        UniqueConstraint("event_id", "projector", name="uq_graph_projection_event_target"),
        Index("ix_graph_projection_due", "projector", "status", "next_attempt_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    event_id = Column(
        CHAR(36),
        ForeignKey("graph_outbox_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    projector = Column(String(32), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=8)
    next_attempt_at = Column(DateTime, nullable=False, default=local_now)
    lease_owner = Column(String(128), nullable=False, default="")
    lease_expires_at = Column(DateTime)
    last_error_code = Column(String(64), nullable=False, default="")
    last_error_message = Column(Text)
    applied_at = Column(DateTime)
    applied_sequence = Column(BigInteger)


class GraphProjectionCursor(Base):
    """Contiguous applied sequence per projector and graph scope."""

    __tablename__ = "graph_projection_cursor"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "kb_uid",
            "graph_generation",
            "projector",
            name="uq_graph_projection_cursor_scope",
        ),
    )

    id = Column(CHAR(36), primary_key=True, default=new_uuid)
    tenant_id = Column(String(64), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    graph_generation = Column(CHAR(36), nullable=False)
    projector = Column(String(32), nullable=False)
    applied_through_sequence = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=local_now, onupdate=local_now)
