from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.chat import ChatSession
from ..models.agent_trace import AgentTrace
from ..security.actor import ActorContext, get_actor_context
from ..services.agent_trace import bind_trace_message, export_session_traces, export_trace


router = APIRouter(prefix="/traces", tags=["traces"])


class TraceBindRequest(BaseModel):
    session_id: str
    assistant_message_id: str


def _require_session_owner(session_id: str, db: Session, actor: ActorContext) -> None:
    """The trace tables carry no user column; ownership is derived from the
    linked chat session. Reject (404) when the session is missing or belongs
    to another user."""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == actor.actor_id,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")


@router.post("/{trace_id}/bind-message")
def bind_message(
    trace_id: str,
    payload: TraceBindRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    _require_session_owner(payload.session_id, db, actor)
    try:
        trace = bind_trace_message(
            db,
            trace_id=trace_id,
            session_id=payload.session_id,
            assistant_message_id=payload.assistant_message_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="trace not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "trace_id": trace.id,
        "session_id": trace.session_id,
        "assistant_message_id": trace.assistant_message_id,
        "status": trace.status,
    }


@router.get("/sessions/{session_id}/export")
def export_session(
    session_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    _require_session_owner(session_id, db, actor)
    return export_session_traces(db, session_id)


@router.get("/{trace_id}/export")
def export(
    trace_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    _require_session_owner(trace.session_id, db, actor)
    return export_trace(db, trace_id)
