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
from backend.app.models.memory import MemoryDraft, MemoryEntry, MemorySource, MemoryStatement, MemoryStatus
from backend.app.prompts.memory_extraction import build_memory_extraction_messages
from backend.app.services.memory_vectors import search_memory_vectors, upsert_statement_vector
from backend.app.utils.time import local_now

DEFAULT_USER_ID = "default-user"
MIN_CONFIDENCE = 0.35

# Auto-confirm decision engine constants
TYPE_RISK_BASELINE = {
    "fact": 1.0,
    "preference": 0.9,
    "project_context": 0.85,
    "topic_interest": 0.80,
    "goal": 0.70,
    "constraint": 0.65,
    "decision": 0.60,
    "question": 0.50,
}

# Scoring weights
W_CONFIDENCE = 0.25
W_EXPLICITNESS = 0.15
W_SENSITIVITY = 0.10
W_TYPE_RISK = 0.15
W_NO_CONFLICT = 0.15
W_CORROBORATION = 0.10
W_CROSS_SESSION = 0.10

# Thresholds
HIGH_STAKES_CONFLICT_SIMILARITY = 0.80
HIGH_STAKES_CONFLICT_IMPORTANCE = 0.7
DUPLICATION_SIMILARITY = 0.85
CORROBORATION_SIMILARITY = 0.85


@dataclass
class MemoryCandidate:
    content: str
    statement_type: str = "fact"
    temporal_type: str = "stable"
    confidence: float = 0.7
    importance: float = 0.6
    explicitness: float = 0.7
    sensitivity_flag: bool = False
    evidence_message_id: str = ""
    decision_hint: str = "review"
    risk_level: str = "medium"


@dataclass
class MemoryExtractionResult:
    session_id: str
    messages_scanned: int
    candidates_found: int = 0
    drafts_created: int = 0
    auto_confirmed: int = 0
    candidates_skipped: int = 0
    draft_ids: list[str] = field(default_factory=list)
    statement_ids: list[str] = field(default_factory=list)


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


def load_session_messages_with_watermark(
    db: Session,
    session_id: str,
    last_extracted_message_id: str = "",
    context_window: int = 5,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """
    Returns (context_messages, new_messages) split by watermark.

    context_messages: already-extracted messages for context (up to context_window)
    new_messages: messages after the watermark that need extraction
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    all_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    # Find split point from watermark
    split_idx = 0
    if last_extracted_message_id:
        for i, msg in enumerate(all_messages):
            if msg.id == last_extracted_message_id:
                split_idx = i + 1
                break

    new_messages = all_messages[split_idx:]

    # Context window: messages before split, limited to context_window
    context_start = max(0, split_idx - context_window)
    context_messages = all_messages[context_start:split_idx]

    return context_messages, new_messages


SUMMARY_PROMPT = """你是一个对话摘要生成器。请根据已有的会话摘要和最近的新消息，生成更新后的会话摘要。

已有摘要：{existing_summary}

最近新消息：
{recent_messages}

要求：
- 用 1-3 句中文概括本对话的整体主题
- 包含已达成的重要结论或决定
- 包含用户当前关注的方向
- 保持简洁，不超过 200 字
- 如果是更新已有摘要，则增量式补充新内容

只输出摘要文本，不要 Markdown，不要解释。"""


def generate_or_update_summary(
    db: Session,
    session: ChatSession,
    new_messages: list[ChatMessage],
) -> str:
    """Generate or incrementally update the session summary via LLM."""
    existing_summary = session.summary or ""
    recent_text = "\n".join(
        f"[{m.role}] {(m.content or '')[:800]}" for m in new_messages
    )
    if not recent_text.strip():
        return existing_summary or ""

    prompt = SUMMARY_PROMPT.format(
        existing_summary=existing_summary or "(新会话，无已有摘要)",
        recent_messages=recent_text,
    )

    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        new_summary = (response.choices[0].message.content or "").strip()
    except Exception:
        new_summary = existing_summary or ""

    if new_summary and new_summary != existing_summary:
        session.summary = new_summary

    return new_summary or existing_summary or ""


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
        # Parse sensitivity_flag: accept bool or int/float
        sens_raw = item.get("sensitivity_flag", False)
        if isinstance(sens_raw, bool):
            sensitivity_flag = sens_raw
        else:
            sensitivity_flag = bool(sens_raw)
        candidates.append(
            MemoryCandidate(
                content=content.strip(),
                statement_type=str(item.get("statement_type") or "fact"),
                temporal_type=str(item.get("temporal_type") or "stable"),
                confidence=confidence,
                importance=_as_float(item.get("importance"), 0.6),
                explicitness=_as_float(item.get("explicitness"), 0.7),
                sensitivity_flag=sensitivity_flag,
                evidence_message_id=str(item.get("evidence_message_id") or ""),
                decision_hint=str(item.get("decision_hint") or "review"),
                risk_level=str(item.get("risk_level") or "medium"),
            )
        )
    return candidates


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", (content or "").strip()).lower()


def _tokenize(content: str) -> set[str]:
    """中文按字符 bigram，英文按词切分，混合用于重叠比对。"""
    norm = _normalize_content(content)
    tokens: set[str] = set()
    # 英文/数字词
    for tok in re.findall(r"[a-z0-9]{2,}", norm):
        tokens.add(tok)
    # 中文字符 bigram（剔除空白与 ASCII）
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", norm)
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i : i + 2])
    return tokens


def _existing_confirmed_statements(db: Session, user_id: str = DEFAULT_USER_ID) -> list[tuple[str, str, str]]:
    rows = (
        db.query(MemoryStatement.id, MemoryStatement.content, MemoryStatement.statement_type)
        .filter(MemoryStatement.user_id == user_id, MemoryStatement.status == MemoryStatus.CONFIRMED)
        .all()
    )
    return [(str(r[0]), str(r[1] or ""), str(r[2] or "")) for r in rows]


def _detect_conflicts(
    candidate: MemoryCandidate,
    confirmed: list[tuple[str, str, str]],
    min_overlap: float = 0.5,
) -> list[str]:
    """检测与已有确认 Statement 的潜在冲突：同类型 + 高词重叠。
    返回可能冲突的 statement_id 列表，供草稿审阅时提示。
    """
    if not confirmed:
        return []
    cand_tokens = _tokenize(candidate.content)
    if not cand_tokens:
        return []
    conflicts: list[str] = []
    for sid, content, stype in confirmed:
        if stype and candidate.statement_type and stype != candidate.statement_type:
            continue
        other_tokens = _tokenize(content)
        if not other_tokens:
            continue
        overlap = len(cand_tokens & other_tokens) / min(len(cand_tokens), len(other_tokens))
        if overlap >= min_overlap:
            conflicts.append(sid)
    return conflicts


def _existing_memory_contents(db: Session, user_id: str = DEFAULT_USER_ID) -> set[str]:
    contents: set[str] = set()
    statements = db.query(MemoryStatement.content).filter(MemoryStatement.user_id == user_id).all()
    contents.update(_normalize_content(row[0]) for row in statements if row[0])
    drafts = db.query(MemoryDraft.payload).filter(MemoryDraft.user_id == user_id).all()
    for row in drafts:
        payload = row[0] or {}
        if isinstance(payload, dict) and isinstance(payload.get("content"), str):
            contents.add(_normalize_content(payload["content"]))
    entries = db.query(MemoryEntry.title, MemoryEntry.content).filter(MemoryEntry.user_id == user_id).all()
    for title, content in entries:
        if content:
            contents.add(_normalize_content(content))
        if title:
            contents.add(_normalize_content(title))
    return contents


def _check_semantic_duplicate(
    db: Session,
    content: str,
    existing_exact: set[str] | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> tuple[bool, str]:
    """
    检查 content 是否与已有记忆重复（精确 + 语义）。
    Returns (is_duplicate, matched_statement_id).
    existing_exact: 预加载的精确匹配集合，传入则走快速路径。
    """
    normalized = _normalize_content(content)

    # Fast path: exact match against preloaded or freshly-loaded set
    if existing_exact is not None:
        if not normalized or normalized in existing_exact:
            return True, ""
        # Fall through to semantic check below
    else:
        # No cache: load and check exact match
        if not normalized:
            return True, ""
        if normalized in _existing_memory_contents(db, user_id):
            return True, ""

    # Slow path: embedding semantic similarity (only if exact miss)
    similar = _search_similar_statements(content, top_k=5, user_id=user_id)
    for hit in similar:
        if hit.get("kind") not in ("statement", "entry"):
            continue
        hit_score = float(hit.get("score", 0))
        if hit_score >= DUPLICATION_SIMILARITY:
            return True, str(hit.get("memory_id", ""))

    return False, ""


def _search_similar_statements(
    text: str,
    top_k: int = 10,
    user_id: str = DEFAULT_USER_ID,
) -> list[dict[str, Any]]:
    """Search Milvus for semantically similar confirmed statements."""
    try:
        return search_memory_vectors(
            text=text,
            user_id=user_id,
            top_k=top_k,
        )
    except Exception:
        return []


def _check_semantic_conflict(
    new_content: str,
    existing_content: str,
) -> bool:
    """Check if two high-similarity statements semantically conflict via negation scan."""
    negation_patterns = [
        r"不\w{0,2}(?:喜欢|想|需要|会|能|应该|再|用|做|是|再|打算)",
        r"没有\w+",
        r"拒绝|放弃|停止|取消|不再|改为|换成|改成",
    ]
    new_has_neg = any(re.search(p, new_content) for p in negation_patterns)
    existing_has_neg = any(re.search(p, existing_content) for p in negation_patterns)
    return new_has_neg != existing_has_neg


def evaluate_auto_confirm(
    db: Session,
    candidate: MemoryCandidate,
    session_id: str = "",
    user_id: str = DEFAULT_USER_ID,
) -> tuple[float, str, list[str]]:
    """
    Compute the auto_confirm_score and return (score, decision, conflict_ids).

    decision is one of: "auto_confirm", "review", "skip"
    """
    # ---- Veto Rule 1: Sensitivity gate ----
    if candidate.sensitivity_flag:
        return (0.0, "review", [])

    type_risk = TYPE_RISK_BASELINE.get(candidate.statement_type, 0.80)

    # ---- Semantic search for conflict & corroboration ----
    similar = _search_similar_statements(candidate.content, top_k=10, user_id=user_id)

    max_conflict_sim = 0.0
    conflict_ids: list[str] = []
    corroboration_count = 0
    cross_session_ids: set[str] = set()

    for hit in similar:
        if hit.get("kind") != "statement":
            continue
        hit_score = float(hit.get("score", 0))
        memory_id = str(hit.get("memory_id", ""))

        # Load the existing statement
        stmt = db.query(MemoryStatement).filter(
            MemoryStatement.id == memory_id,
            MemoryStatement.status == MemoryStatus.CONFIRMED,
        ).first()
        if not stmt:
            continue

        # ---- Duplication check ----
        if hit_score >= DUPLICATION_SIMILARITY:
            # Increment corroboration on existing
            stmt.corroboration_count = (stmt.corroboration_count or 0) + 1
            # Duplication = skip
            return (0.0, "skip", [memory_id])

        # ---- Corroboration check ----
        if hit_score >= CORROBORATION_SIMILARITY:
            corroboration_count += 1
            if stmt.source and stmt.source.session_id:
                cross_session_ids.add(stmt.source.session_id)
            if session_id and session_id in cross_session_ids:
                cross_session_ids.discard(session_id)

        # ---- Conflict check (same type, high similarity but lower than dup) ----
        if (
            hit_score >= HIGH_STAKES_CONFLICT_SIMILARITY
            and hit_score < DUPLICATION_SIMILARITY
            and stmt.statement_type == candidate.statement_type
        ):
            if _check_semantic_conflict(candidate.content, stmt.content or ""):
                max_conflict_sim = max(max_conflict_sim, hit_score)
                if (stmt.importance or 0) >= HIGH_STAKES_CONFLICT_IMPORTANCE:
                    conflict_ids.append(memory_id)

    # ---- Veto Rule 2: High-stakes conflict gate ----
    if conflict_ids:
        return (0.0, "review", conflict_ids)

    # ---- Compute corroboration boost ----
    corroboration_boost = min(1.0, corroboration_count / 3.0)

    # ---- Cross-session boost ----
    cross_session_count = len(cross_session_ids)
    if cross_session_count >= 2:
        cross_session_boost = 1.0
    elif cross_session_count == 1:
        cross_session_boost = 0.5
    else:
        cross_session_boost = 0.0

    # ---- Composite score ----
    score = (
        W_CONFIDENCE * candidate.confidence
        + W_EXPLICITNESS * candidate.explicitness
        + W_SENSITIVITY * (1.0 - (1.0 if candidate.sensitivity_flag else 0.0))
        + W_TYPE_RISK * type_risk
        + W_NO_CONFLICT * (1.0 - max_conflict_sim)
        + W_CORROBORATION * corroboration_boost
        + W_CROSS_SESSION * cross_session_boost
    )

    threshold = settings.MEMORY_AUTO_CONFIRM_THRESHOLD
    if score >= threshold:
        return (score, "auto_confirm", [])
    else:
        return (score, "review", [])


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

    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    user_id = session.user_id or DEFAULT_USER_ID if session else DEFAULT_USER_ID

    prompt_messages = build_memory_extraction_messages(messages)
    raw = _call_memory_extraction_llm(prompt_messages)
    candidates = parse_memory_candidates(raw)
    result.candidates_found = len(candidates)

    by_id = {message.id: message for message in messages}
    existing = _existing_memory_contents(db, user_id)
    confirmed_statements = _existing_confirmed_statements(db, user_id)

    for candidate in candidates:
        is_dup, dup_id = _check_semantic_duplicate(db, candidate.content, existing, user_id=user_id)
        if is_dup:
            result.candidates_skipped += 1
            continue
        normalized = _normalize_content(candidate.content)
        evidence = by_id.get(candidate.evidence_message_id) or messages[-1]
        source = MemorySource(
            user_id=user_id,
            source_type="chat_message",
            source_id=evidence.id,
            session_id=session_id,
            message_id=evidence.id,
            span_text=evidence.content or "",
            source_metadata={"extractor": "conversation_memory_phase2"},
        )
        conflict_ids = _detect_conflicts(candidate, confirmed_statements)
        draft = MemoryDraft(
            user_id=user_id,
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
            conflict_ids=conflict_ids,
            source=source,
        )
        db.add_all([source, draft])
        db.flush()
        existing.add(normalized)
        result.draft_ids.append(draft.id)
        result.drafts_created += 1

    db.commit()
    return result


def extract_session_memories_scheduled(
    db: Session,
    session_id: str,
    last_extracted_message_id: str = "",
    context_window: int = 5,
) -> MemoryExtractionResult:
    """
    Scheduled extraction variant with watermark, summary, and auto-confirm.
    """
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    user_id = session.user_id or DEFAULT_USER_ID

    context_messages, new_messages = load_session_messages_with_watermark(
        db, session_id, last_extracted_message_id, context_window,
    )

    result = MemoryExtractionResult(session_id=session_id, messages_scanned=len(new_messages))
    if not new_messages:
        return result

    # Step 1: Update session summary
    session_summary = generate_or_update_summary(db, session, new_messages)

    # Step 2: Build prompt and call LLM
    prompt_messages = build_memory_extraction_messages(
        new_messages=new_messages,
        context_messages=context_messages,
        session_summary=session_summary,
    )
    raw = _call_memory_extraction_llm(prompt_messages)
    candidates = parse_memory_candidates(raw)
    result.candidates_found = len(candidates)

    # Step 3: Process each candidate through decision engine
    by_id = {m.id: m for m in new_messages}
    existing = _existing_memory_contents(db, user_id)

    for candidate in candidates:
        # Semantic dedup: exact match + embedding similarity
        is_dup, dup_id = _check_semantic_duplicate(db, candidate.content, existing, user_id=user_id)
        if is_dup:
            result.candidates_skipped += 1
            continue

        normalized = _normalize_content(candidate.content)

        # Run auto-confirm decision engine
        auto_score, decision, conflict_ids = evaluate_auto_confirm(
            db, candidate, session_id=session_id, user_id=user_id,
        )

        evidence = by_id.get(candidate.evidence_message_id) or new_messages[-1]
        source = MemorySource(
            user_id=user_id,
            source_type="chat_message",
            source_id=evidence.id,
            session_id=session_id,
            message_id=evidence.id,
            span_text=evidence.content or "",
            source_metadata={"extractor": "memory_scheduled_v1"},
        )

        if decision == "skip":
            result.candidates_skipped += 1
            continue

        if decision == "auto_confirm":
            # Create confirmed MemoryStatement directly
            statement = MemoryStatement(
                user_id=user_id,
                content=candidate.content,
                statement_type=candidate.statement_type,
                temporal_type=candidate.temporal_type,
                confidence=candidate.confidence,
                importance=candidate.importance,
                explicitness=candidate.explicitness,
                sensitivity_flag=1.0 if candidate.sensitivity_flag else 0.0,
                auto_confirm_score=auto_score,
                corroboration_count=0,
                status=MemoryStatus.CONFIRMED,
                source=source,
            )
            db.add_all([source, statement])
            db.flush()
            # Index vector
            try:
                vector_id = upsert_statement_vector(statement)
                if vector_id:
                    statement.embedding_ref = vector_id
                    statement.embedding_model = settings.EMBEDDING_MODEL
                    statement.embedding_status = "done"
                else:
                    statement.embedding_status = "pending"
            except Exception:
                statement.embedding_status = "pending"
            result.statement_ids.append(statement.id)
            result.auto_confirmed += 1
        else:
            # decision == "review" — create draft for Memory Inbox
            draft = MemoryDraft(
                user_id=user_id,
                draft_type="statement",
                payload={
                    "content": candidate.content,
                    "statement_type": candidate.statement_type,
                    "temporal_type": candidate.temporal_type,
                    "importance": candidate.importance,
                },
                decision_hint="review",
                risk_level="medium" if auto_score >= 0.6 else "high",
                confidence=candidate.confidence,
                explicitness=candidate.explicitness,
                sensitivity_flag=1.0 if candidate.sensitivity_flag else 0.0,
                auto_confirm_score=auto_score,
                conflict_ids=conflict_ids,
                source=source,
            )
            db.add_all([source, draft])
            db.flush()
            result.draft_ids.append(draft.id)
            result.drafts_created += 1

        existing.add(normalized)

    # Step 4: Update watermark on session
    if new_messages:
        session.last_extracted_message_id = new_messages[-1].id
        session.last_extracted_at = local_now()

    db.commit()
    return result
