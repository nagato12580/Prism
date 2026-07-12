# prism/backend/app/api/chat.py
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models.chat import ChatSession, ChatMessage
from ..schemas.chat import (
    ChatSessionCreate, ChatSessionOut, ChatSessionUpdate,
    ChatMessageOut, ChatMessageCreate, ChatMessageUpdate,
)
from ..config import settings
from ..services.memory_extraction import extract_session_memories
from ..utils.time import local_now

router = APIRouter(prefix="/chat", tags=["chat"])


def _run_memory_extraction_best_effort(session_id: str, limit: int = 20):
    db = None
    try:
        db = SessionLocal()
        extract_session_memories(db, session_id=session_id, limit=limit)
    except Exception as exc:
        print(f"[memory_extraction] auto extraction failed: {exc}")
    finally:
        if db is not None:
            db.close()


def _maybe_trigger_memory_extraction(session_id: str, role: str, content: str | None = None):
    if role != "assistant" or not (content or "").strip() or not settings.MEMORY_EXTRACTION_AUTO_ENABLED:
        return
    try:
        thread = threading.Thread(
            target=_run_memory_extraction_best_effort,
            args=(session_id,),
            daemon=True,
        )
        thread.start()
    except Exception as exc:
        print(f"[memory_extraction] auto extraction could not start: {exc}")


# ── Session CRUD ──────────────────────────────────────────────

@router.post("/sessions", response_model=ChatSessionOut)
def create_session(payload: ChatSessionCreate, db: Session = Depends(get_db)):
    session = ChatSession(
        title=payload.title or "新对话",
        user_id="default-user",
        topic_id=payload.topic_id,
        source_types=payload.source_types,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()


@router.put("/sessions/{session_id}", response_model=ChatSessionOut)
def update_session(session_id: str, payload: ChatSessionUpdate, db=Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(session, key, value)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(session)
    db.commit()
    return {"detail": "已删除"}


# ── Messages ──────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def list_messages(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
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
        clarify=payload.clarify, process=payload.process,
    )
    db.add(msg)
    # Touch session.updated_at so list order reflects recent activity
    session.updated_at = local_now()
    db.commit()
    db.refresh(msg)
    _maybe_trigger_memory_extraction(session_id, payload.role, payload.content)
    return msg


@router.patch("/sessions/{session_id}/messages/{message_id}", response_model=ChatMessageOut)
def update_message(
    session_id: str,
    message_id: str,
    payload: ChatMessageUpdate,
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    msg = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id, ChatMessage.id == message_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="message not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(msg, key, value)

    session.updated_at = local_now()
    db.commit()
    db.refresh(msg)
    _maybe_trigger_memory_extraction(session_id, msg.role, msg.content)
    return msg


# ── Title generation ──────────────────────────────────────────

@router.post("/sessions/{session_id}/generate-title", response_model=ChatSessionOut)
def generate_title(session_id: str, db=Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .limit(2)
        .all()
    )
    if len(messages) < 2:
        raise HTTPException(status_code=400, detail="至少需要一轮问答才能生成标题")

    user_msg = messages[0].content or ""
    assistant_msg = messages[1].content or ""

    try:
        title = _generate_title_via_llm(user_msg, assistant_msg)
    except Exception:
        title = user_msg[:30] + ("..." if len(user_msg) > 30 else "")

    session.title = title
    db.commit()
    db.refresh(session)
    return session


def _generate_title_via_llm(user_msg: str, assistant_msg: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    prompt = (
        "用简体中文生成一个简短的会话标题（10个字以内），概括以下问答内容：\n"
        f"用户问：{user_msg}\n"
        f"助手答：{assistant_msg[:500]}\n"
        "标题："
    )
    resp = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=20,
        temperature=0.3,
    )
    result = resp.choices[0].message.content.strip()
    result = result.strip('"''""').strip()
    return result[:30] or "新对话"
