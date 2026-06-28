import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import CHAR

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class KnowledgeJob(Base):
    __tablename__ = "knowledge_job"
    __table_args__ = (
        Index("ix_knowledge_job_status_available_priority_created", "status", "available_at", "priority", "created_at"),
        Index("ix_knowledge_job_resource_type_status", "resource_id", "job_type", "status"),
        Index("ix_knowledge_job_item_id", "item_id"),
        Index("ix_knowledge_job_topic_id", "topic_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    job_type = Column(String(32), nullable=False, comment="ingest / governance")
    resource_id = Column(CHAR(36), nullable=False)
    item_id = Column(CHAR(36), nullable=True)
    topic_id = Column(CHAR(36), nullable=True)
    status = Column(String(24), nullable=False, default="queued", comment="queued/processing/done/failed/canceled")
    priority = Column(Integer, nullable=False, default=100)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    stage = Column(String(64), nullable=False, default="")
    error_code = Column(String(64), nullable=False, default="")
    error_message = Column(Text, nullable=True)
    locked_by = Column(String(128), nullable=False, default="")
    locked_at = Column(DateTime, nullable=True)
    available_at = Column(DateTime, default=local_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
