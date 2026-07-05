import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR

from ..database import Base
from ..utils.time import local_now


def _uuid() -> str:
    return str(uuid.uuid4())


class GraphCommunity(Base):
    __tablename__ = "graph_community"
    __table_args__ = (UniqueConstraint("user_id", "community_id", name="uq_graph_community_user_cid"),)

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    community_id = Column(Integer, nullable=False)
    label = Column(String(64), default="")
    cohesion = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
