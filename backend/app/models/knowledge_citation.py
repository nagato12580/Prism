# backend/app/models/knowledge_citation.py
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.mysql import CHAR

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import uuid4_str


class KnowledgeCitation(Base):
    __tablename__ = "knowledge_citation"

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    file_uid = Column(CHAR(36), nullable=True)
    chunk_uid = Column(CHAR(36), nullable=True)
    citation_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=local_now)
