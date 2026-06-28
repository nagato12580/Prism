from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep, ChatMessage


def bind_trace_message(
    db: Session,
    *,
    trace_id: str,
    session_id: str,
    assistant_message_id: str,
) -> AgentTrace:
    trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
    if trace is None:
        raise LookupError("trace not found")
    if trace.session_id and trace.session_id != session_id:
        raise ValueError("trace session mismatch")
    if trace.assistant_message_id and trace.assistant_message_id != assistant_message_id:
        raise ValueError("trace already bound to a different assistant message")

    message = db.query(ChatMessage).filter(ChatMessage.id == assistant_message_id).first()
    if message is None:
        raise ValueError("assistant message not found")
    if message.session_id != session_id:
        raise ValueError("assistant message session mismatch")
    if message.role != "assistant":
        raise ValueError("assistant message must have assistant role")

    trace.session_id = session_id
    trace.assistant_message_id = assistant_message_id
    db.commit()
    db.refresh(trace)
    return trace


def export_trace(db: Session, trace_id: str) -> dict[str, Any]:
    trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
    if trace is None:
        raise LookupError("trace not found")

    steps = (
        db.query(AgentTraceStep)
        .filter(AgentTraceStep.trace_id == trace.id)
        .order_by(AgentTraceStep.step_index.asc())
        .all()
    )
    return {
        "trace_id": trace.id,
        "session_id": trace.session_id,
        "user_message_id": trace.user_message_id,
        "assistant_message_id": trace.assistant_message_id,
        "user_query": trace.user_query,
        "status": trace.status,
        "model": trace.model,
        "started_at": trace.started_at.isoformat() if trace.started_at else None,
        "ended_at": trace.ended_at.isoformat() if trace.ended_at else None,
        "steps": [_serialize_step(step) for step in steps],
    }


def _serialize_step(step: AgentTraceStep) -> dict[str, Any]:
    return {
        "step_id": step.id,
        "step_index": step.step_index,
        "step_type": step.step_type,
        "status": step.status,
        "tool_name": step.tool_name,
        "tool_call_id": step.tool_call_id,
        "input": step.input_json,
        "output": step.output_json,
        "latency_ms": step.latency_ms,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "ended_at": step.ended_at.isoformat() if step.ended_at else None,
        "evidence_items": [_serialize_evidence(item) for item in step.evidence_items],
    }


def _serialize_evidence(item: AgentTraceEvidence) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "chunk_id": item.chunk_id,
        "parent_chunk_id": item.parent_chunk_id,
        "item_id": item.item_id,
        "display_title": item.display_title,
        "excerpt": item.excerpt,
        "hit_reason": item.hit_reason,
        "score": item.score,
        "retrieval_path": item.retrieval_path_json or [],
        "metadata": item.metadata_json or {},
    }
