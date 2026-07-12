import uuid

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def _uuid() -> str:
    return str(uuid.uuid4())


class GraphInsightSummary(Base):
    __tablename__ = "graph_insight_summary"
    __table_args__ = (UniqueConstraint("user_id", name="uq_graph_insight_summary_user"),)

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    suggested_questions = Column(JSON, default=list)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
