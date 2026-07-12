import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class AgentTrace(Base):
    __tablename__ = "agent_trace"
    __table_args__ = (
        Index("ix_agent_trace_session_started", "session_id", "started_at"),
        Index("ix_agent_trace_assistant_message", "assistant_message_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    session_id = Column(CHAR(36), nullable=True, index=True)
    user_message_id = Column(CHAR(36), nullable=True, index=True)
    assistant_message_id = Column(CHAR(36), nullable=True, index=True)
    user_query = Column(Text, default="")
    status = Column(String(32), default="running", index=True)
    model = Column(String(128), default="")
    started_at = Column(DateTime, default=local_now)
    ended_at = Column(DateTime, nullable=True)
    trace_json = Column(JSON, nullable=True, default=None)

    steps = relationship(
        "AgentTraceStep",
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="AgentTraceStep.step_index",
    )


class AgentTraceStep(Base):
    __tablename__ = "agent_trace_step"
    __table_args__ = (
        Index("ix_agent_trace_step_trace_index", "trace_id", "step_index"),
        Index("ix_agent_trace_step_tool_call", "tool_call_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    trace_id = Column(CHAR(36), ForeignKey("agent_trace.id", ondelete="CASCADE"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False, default=0)
    step_type = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(128), nullable=True, default=None)
    tool_call_id = Column(String(128), nullable=True, default=None)
    input_json = Column(JSON, nullable=True, default=None)
    output_json = Column(JSON, nullable=True, default=None)
    status = Column(String(32), default="success", index=True)
    latency_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=local_now)
    ended_at = Column(DateTime, nullable=True)

    trace = relationship("AgentTrace", back_populates="steps")
    evidence_items = relationship(
        "AgentTraceEvidence",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="AgentTraceEvidence.id",
    )


class AgentTraceEvidence(Base):
    __tablename__ = "agent_trace_evidence"
    __table_args__ = (
        Index("ix_agent_trace_evidence_chunk", "chunk_id"),
        Index("ix_agent_trace_evidence_source", "source_kind", "source_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    trace_step_id = Column(CHAR(36), ForeignKey("agent_trace_step.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(String(255), nullable=False, index=True)
    source_kind = Column(String(64), default="", index=True)
    source_id = Column(String(128), default="", index=True)
    chunk_id = Column(String(128), default="", index=True)
    parent_chunk_id = Column(String(128), default="")
    item_id = Column(String(128), default="", index=True)
    display_title = Column(String(512), default="")
    excerpt = Column(Text, default="")
    hit_reason = Column(Text, default="")
    score = Column(Float, nullable=True)
    retrieval_path_json = Column(JSON, nullable=True, default=None)
    metadata_json = Column(JSON, nullable=True, default=None)

    step = relationship("AgentTraceStep", back_populates="evidence_items")
