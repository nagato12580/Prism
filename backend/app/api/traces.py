from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.agent_trace import bind_trace_message, export_trace


router = APIRouter(prefix="/traces", tags=["traces"])


class TraceBindRequest(BaseModel):
    session_id: str
    assistant_message_id: str


@router.post("/{trace_id}/bind-message")
def bind_message(trace_id: str, payload: TraceBindRequest, db: Session = Depends(get_db)):
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


@router.get("/{trace_id}/export")
def export(trace_id: str, db: Session = Depends(get_db)):
    try:
        return export_trace(db, trace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="trace not found") from exc
