# prism/backend/app/api/chat.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.chat import ChatSession, ChatMessage
from ..schemas.chat import (
    ChatSessionCreate, ChatSessionOut, ChatMessageOut, ChatMessageCreate
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionOut)
def create_session(payload: ChatSessionCreate, db: Session = Depends(get_db)):
    session = ChatSession(title=payload.title or "新对话", user_id="default-user")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def list_messages(session_id: str, db: Session = Depends(get_db)):
    return db.query(ChatMessage).filter(ChatMessage.session_id == session_id)\
        .order_by(ChatMessage.created_at).all()


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageOut)
def add_message(session_id: str, payload: ChatMessageCreate, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    msg = ChatMessage(
        session_id=session_id, role=payload.role,
        content=payload.content, sources=payload.sources,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"detail": "已删除"}
