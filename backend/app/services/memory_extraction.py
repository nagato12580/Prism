from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from openai import OpenAI
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.memory import MemoryDraft, MemorySource, MemoryStatement
from backend.app.prompts.memory_extraction import build_memory_extraction_messages

DEFAULT_USER_ID = "default-user"
MIN_CONFIDENCE = 0.35


@dataclass
class MemoryCandidate:
    content: str
    statement_type: str = "fact"
    temporal_type: str = "stable"
    confidence: float = 0.7
    importance: float = 0.6
    risk_level: str = "medium"
    decision_hint: str = "review"
    evidence_message_id: str = ""


@dataclass
class MemoryExtractionResult:
    session_id: str
    messages_scanned: int
    candidates_found: int = 0
    drafts_created: int = 0
    candidates_skipped: int = 0
    draft_ids: list[str] = field(default_factory=list)


def load_session_messages(db: Session, session_id: str, limit: int = 20) -> list[ChatMessage]:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    query = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(query.all()))


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text


def _as_float(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, numeric))


def parse_memory_candidates(raw: str) -> list[MemoryCandidate]:
    try:
        data = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Memory extraction returned invalid JSON: {exc}") from exc
    items = data.get("candidates", []) if isinstance(data, dict) else []
    candidates: list[MemoryCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        confidence = _as_float(item.get("confidence"), 0.7)
        if confidence < MIN_CONFIDENCE:
            continue
        candidates.append(
            MemoryCandidate(
                content=content.strip(),
                statement_type=str(item.get("statement_type") or "fact"),
                temporal_type=str(item.get("temporal_type") or "stable"),
                confidence=confidence,
                importance=_as_float(item.get("importance"), 0.6),
                risk_level=str(item.get("risk_level") or "medium"),
                decision_hint=str(item.get("decision_hint") or "review"),
                evidence_message_id=str(item.get("evidence_message_id") or ""),
            )
        )
    return candidates


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", (content or "").strip()).lower()


def _existing_memory_contents(db: Session) -> set[str]:
    contents: set[str] = set()
    statements = db.query(MemoryStatement.content).filter(MemoryStatement.user_id == DEFAULT_USER_ID).all()
    contents.update(_normalize_content(row[0]) for row in statements if row[0])
    drafts = db.query(MemoryDraft.payload).filter(MemoryDraft.user_id == DEFAULT_USER_ID).all()
    for row in drafts:
        payload = row[0] or {}
        if isinstance(payload, dict) and isinstance(payload.get("content"), str):
            contents.add(_normalize_content(payload["content"]))
    return contents


def _call_memory_extraction_llm(prompt_messages: list[dict[str, str]]) -> str:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        raise HTTPException(status_code=503, detail="LLM is not configured for memory extraction")
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=prompt_messages,
        temperature=0.1,
    )
    return response.choices[0].message.content or "{}"


def extract_session_memories(db: Session, session_id: str, limit: int = 20) -> MemoryExtractionResult:
    messages = load_session_messages(db, session_id, limit=limit)
    result = MemoryExtractionResult(session_id=session_id, messages_scanned=len(messages))
    if not messages:
        return result

    prompt_messages = build_memory_extraction_messages(messages)
    raw = _call_memory_extraction_llm(prompt_messages)
    candidates = parse_memory_candidates(raw)
    result.candidates_found = len(candidates)

    by_id = {message.id: message for message in messages}
    existing = _existing_memory_contents(db)

    for candidate in candidates:
        normalized = _normalize_content(candidate.content)
        if not normalized or normalized in existing:
            result.candidates_skipped += 1
            continue
        evidence = by_id.get(candidate.evidence_message_id) or messages[-1]
        source = MemorySource(
            user_id=DEFAULT_USER_ID,
            source_type="chat_message",
            source_id=evidence.id,
            session_id=session_id,
            message_id=evidence.id,
            span_text=evidence.content or "",
            source_metadata={"extractor": "conversation_memory_phase2"},
        )
        draft = MemoryDraft(
            user_id=DEFAULT_USER_ID,
            draft_type="statement",
            payload={
                "content": candidate.content,
                "statement_type": candidate.statement_type,
                "temporal_type": candidate.temporal_type,
                "importance": candidate.importance,
            },
            decision_hint=candidate.decision_hint,
            risk_level=candidate.risk_level,
            confidence=candidate.confidence,
            conflict_ids=[],
            source=source,
        )
        db.add_all([source, draft])
        db.flush()
        existing.add(normalized)
        result.draft_ids.append(draft.id)
        result.drafts_created += 1

    db.commit()
    return result
