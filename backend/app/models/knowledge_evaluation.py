from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, and_
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import foreign, relationship

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import uuid4_str


class EvaluationDataset(Base):
    __tablename__ = "evaluation_dataset"
    __table_args__ = (
        UniqueConstraint("dataset_uid", name="uq_evaluation_dataset_uid"),
        UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_dataset_id_scope"),
        Index("ix_evaluation_dataset_scope_created", "tenant_id", "kb_uid", "created_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    dataset_uid = Column(CHAR(36), nullable=False, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), ForeignKey("knowledge_topic.kb_uid", name="fk_evaluation_dataset_topic", ondelete="RESTRICT"), nullable=False)
    name = Column(String(255), nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    source = Column(String(32), nullable=False, default="generated")
    extra_meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=local_now, nullable=False)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now, nullable=False)


class EvaluationDatasetItem(Base):
    __tablename__ = "evaluation_dataset_item"
    __table_args__ = (
        UniqueConstraint("dataset_id", "ordinal", name="uq_evaluation_dataset_item_ordinal"),
        UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_dataset_item_id_scope"),
        Index("ix_evaluation_dataset_item_scope", "tenant_id", "kb_uid", "dataset_id"),
        ForeignKeyConstraint(["dataset_id", "tenant_id", "kb_uid"], ["evaluation_dataset.id", "evaluation_dataset.tenant_id", "evaluation_dataset.kb_uid"], name="fk_evaluation_dataset_item_parent_scope", ondelete="CASCADE"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    dataset_id = Column(CHAR(36), nullable=False)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    ordinal = Column(Integer, nullable=False)
    query = Column(Text, nullable=False)
    gold_chunk_uids = Column(JSON, nullable=False, default=list)
    gold_answer = Column(Text, nullable=True)
    extra_meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=local_now, nullable=False)


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"
    __table_args__ = (
        UniqueConstraint("run_uid", name="uq_evaluation_run_uid"),
        UniqueConstraint("tenant_id", "kb_uid", "request_idempotency_key", name="uq_evaluation_run_request_key"),
        UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_run_id_scope"),
        Index("ix_evaluation_run_scope_created", "tenant_id", "kb_uid", "created_at"),
        Index("ix_evaluation_run_dataset", "dataset_id"),
        ForeignKeyConstraint(["dataset_id", "tenant_id", "kb_uid"], ["evaluation_dataset.id", "evaluation_dataset.tenant_id", "evaluation_dataset.kb_uid"], name="fk_evaluation_run_dataset_scope", ondelete="RESTRICT"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    run_uid = Column(CHAR(36), nullable=False, default=uuid4_str)
    dataset_id = Column(CHAR(36), nullable=False)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), ForeignKey("knowledge_topic.kb_uid", name="fk_evaluation_run_topic", ondelete="RESTRICT"), nullable=False)
    created_by = Column(CHAR(36), nullable=False)
    model = Column(String(255), nullable=True)
    request_idempotency_key = Column(String(128), nullable=False, default=uuid4_str)
    request_fingerprint = Column(CHAR(64), nullable=False, default=lambda: "0" * 64)
    config = Column(JSON, nullable=False, default=dict)
    retrieval_config = Column(JSON, nullable=False, default=dict)
    embedding_profile = Column(JSON, nullable=False, default=dict)
    graph_config = Column(JSON, nullable=False, default=dict)
    index_generation = Column(CHAR(36), nullable=True)
    graph_generation = Column(CHAR(36), nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    metrics = Column(JSON, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=local_now, nullable=False)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now, nullable=False)


class EvaluationRunItem(Base):
    __tablename__ = "evaluation_run_item"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_evaluation_run_item_ordinal"),
        Index("ix_evaluation_run_item_scope", "tenant_id", "kb_uid", "run_id"),
        Index("ix_evaluation_run_item_run_status", "run_id", "status"),
        ForeignKeyConstraint(["run_id", "tenant_id", "kb_uid"], ["evaluation_run.id", "evaluation_run.tenant_id", "evaluation_run.kb_uid"], name="fk_evaluation_run_item_parent_scope", ondelete="CASCADE"),
        ForeignKeyConstraint(["dataset_item_id", "tenant_id", "kb_uid"], ["evaluation_dataset_item.id", "evaluation_dataset_item.tenant_id", "evaluation_dataset_item.kb_uid"], name="fk_evaluation_run_item_dataset_item_scope", ondelete="RESTRICT"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    run_id = Column(CHAR(36), nullable=False)
    dataset_item_id = Column(CHAR(36), nullable=True)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    ordinal = Column(Integer, nullable=False)
    query = Column(Text, nullable=False)
    gold_chunk_uids = Column(JSON, nullable=False, default=list)
    gold_answer = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    evidence = Column(JSON, nullable=True)
    metrics = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=local_now, nullable=False)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now, nullable=False)


EvaluationDataset.items = relationship(
    EvaluationDatasetItem,
    primaryjoin=lambda: and_(
        EvaluationDataset.id == foreign(EvaluationDatasetItem.dataset_id),
        EvaluationDataset.tenant_id == foreign(EvaluationDatasetItem.tenant_id),
        EvaluationDataset.kb_uid == foreign(EvaluationDatasetItem.kb_uid),
    ),
    back_populates="dataset",
    cascade="all, delete-orphan",
)
EvaluationDatasetItem.dataset = relationship(
    EvaluationDataset,
    primaryjoin=lambda: and_(
        EvaluationDataset.id == foreign(EvaluationDatasetItem.dataset_id),
        EvaluationDataset.tenant_id == foreign(EvaluationDatasetItem.tenant_id),
        EvaluationDataset.kb_uid == foreign(EvaluationDatasetItem.kb_uid),
    ),
    back_populates="items",
)
EvaluationDataset.runs = relationship(
    EvaluationRun,
    primaryjoin=lambda: and_(
        EvaluationDataset.id == foreign(EvaluationRun.dataset_id),
        EvaluationDataset.tenant_id == foreign(EvaluationRun.tenant_id),
        EvaluationDataset.kb_uid == foreign(EvaluationRun.kb_uid),
    ),
    back_populates="dataset",
)
EvaluationRun.dataset = relationship(
    EvaluationDataset,
    primaryjoin=lambda: and_(
        EvaluationDataset.id == foreign(EvaluationRun.dataset_id),
        EvaluationDataset.tenant_id == foreign(EvaluationRun.tenant_id),
        EvaluationDataset.kb_uid == foreign(EvaluationRun.kb_uid),
    ),
    back_populates="runs",
)
EvaluationRun.items = relationship(
    EvaluationRunItem,
    primaryjoin=lambda: and_(
        EvaluationRun.id == foreign(EvaluationRunItem.run_id),
        EvaluationRun.tenant_id == foreign(EvaluationRunItem.tenant_id),
        EvaluationRun.kb_uid == foreign(EvaluationRunItem.kb_uid),
    ),
    back_populates="run",
    cascade="all, delete-orphan",
    overlaps="dataset_item,run_items",
)
EvaluationRunItem.run = relationship(
    EvaluationRun,
    primaryjoin=lambda: and_(
        EvaluationRun.id == foreign(EvaluationRunItem.run_id),
        EvaluationRun.tenant_id == foreign(EvaluationRunItem.tenant_id),
        EvaluationRun.kb_uid == foreign(EvaluationRunItem.kb_uid),
    ),
    back_populates="items",
    overlaps="dataset_item,run_items",
)
EvaluationDatasetItem.run_items = relationship(
    EvaluationRunItem,
    primaryjoin=lambda: and_(
        EvaluationDatasetItem.id == foreign(EvaluationRunItem.dataset_item_id),
        EvaluationDatasetItem.tenant_id == foreign(EvaluationRunItem.tenant_id),
        EvaluationDatasetItem.kb_uid == foreign(EvaluationRunItem.kb_uid),
    ),
    back_populates="dataset_item",
    overlaps="items,run",
)
EvaluationRunItem.dataset_item = relationship(
    EvaluationDatasetItem,
    primaryjoin=lambda: and_(
        EvaluationDatasetItem.id == foreign(EvaluationRunItem.dataset_item_id),
        EvaluationDatasetItem.tenant_id == foreign(EvaluationRunItem.tenant_id),
        EvaluationDatasetItem.kb_uid == foreign(EvaluationRunItem.kb_uid),
    ),
    back_populates="run_items",
    overlaps="items,run",
)
