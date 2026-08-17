from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models.chat import ChatSession
from ..models.memory import MemoryDraft, MemoryEntity, MemoryEntry, MemoryRelation, MemorySource, MemoryStatement, MemoryStatus
from ..security.actor import ActorContext, get_actor_context
from ..schemas.memory import (
    MemoryDraftConfirmOut,
    MemoryDraftCreate,
    MemoryDraftOut,
    MemoryEntryOut,
    MemoryExtractionOut,
    MemoryExtractionRequest,
    MemoryStatementOut,
    MemorySupersedePayload,
    memory_source_to_out,
)
from ..services.memory_extraction import extract_session_memories
from ..services.memory_consolidation import consolidation_candidates, run_consolidation
from ..services.memory_entity import extract_and_link_entities
from ..services.memory_reflection import list_insights, run_reflection
from ..services.memory_vectors import upsert_statement_vector
from ..utils.time import local_now

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryEntryOut])
def list_memories(
    memory_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    query = db.query(MemoryEntry).filter(MemoryEntry.user_id == actor.actor_id)
    if memory_type:
        query = query.filter(MemoryEntry.memory_type == memory_type)
    return query.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit).all()


def _create_source(source_in, db: Session, user_id: str) -> MemorySource:
    data = source_in.model_dump()
    metadata = data.pop("metadata", {})
    source = MemorySource(user_id=user_id, source_metadata=metadata, **data)
    db.add(source)
    return source


def _statement_from_draft(draft: MemoryDraft) -> MemoryStatement:
    if draft.draft_type != "statement":
        raise HTTPException(
            status_code=400,
            detail="Only statement memory drafts can be confirmed as statements",
        )
    payload = draft.payload or {}
    raw_content = payload.get("content")
    if not isinstance(raw_content, str):
        raise HTTPException(
            status_code=400,
            detail="Memory statement content must be a non-empty string",
        )
    content = raw_content.strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Memory statement content must be a non-empty string",
        )
    return MemoryStatement(
        user_id=draft.user_id,
        content=content,
        statement_type=payload.get("statement_type", "fact"),
        temporal_type=payload.get("temporal_type", "stable"),
        confidence=payload.get("confidence", draft.confidence),
        importance=payload.get("importance", 0.6),
        status=MemoryStatus.CONFIRMED,
        source=draft.source,
    )


def _get_draft_or_404(draft_id: str, db: Session, user_id: str) -> MemoryDraft:
    draft = (
        db.query(MemoryDraft)
        .filter(MemoryDraft.user_id == user_id, MemoryDraft.id == draft_id)
        .first()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Memory draft not found")
    return draft


def _draft_to_out(draft: MemoryDraft) -> MemoryDraftOut:
    return MemoryDraftOut(
        id=draft.id,
        user_id=draft.user_id,
        draft_type=draft.draft_type,
        payload=draft.payload or {},
        decision_hint=draft.decision_hint,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        status=draft.status,
        conflict_ids=draft.conflict_ids or [],
        source=memory_source_to_out(draft.source) if draft.source else None,
        reviewed_at=draft.reviewed_at,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _statement_to_out(statement: MemoryStatement) -> MemoryStatementOut:
    return MemoryStatementOut(
        id=statement.id,
        user_id=statement.user_id,
        content=statement.content,
        statement_type=statement.statement_type,
        temporal_type=statement.temporal_type,
        confidence=statement.confidence,
        importance=statement.importance,
        status=statement.status,
        valid_from=statement.valid_from,
        valid_until=statement.valid_until,
        superseded_by_id=statement.superseded_by_id,
        source=memory_source_to_out(statement.source) if statement.source else None,
        created_at=statement.created_at,
        updated_at=statement.updated_at,
    )


def _ensure_draft_reviewable(draft: MemoryDraft) -> None:
    if draft.status != MemoryStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Memory draft has already been reviewed")


def _confirmed_statement_for_draft(db: Session, draft: MemoryDraft) -> MemoryStatement | None:
    payload = draft.payload or {}
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    query = db.query(MemoryStatement).filter(
        MemoryStatement.user_id == draft.user_id,
        MemoryStatement.content == content.strip(),
        MemoryStatement.status == MemoryStatus.CONFIRMED,
    )
    if draft.source_id:
        query = query.filter(MemoryStatement.source_id == draft.source_id)
    return query.order_by(MemoryStatement.created_at.asc()).first()


def _claim_draft_for_review(db: Session, draft: MemoryDraft) -> bool:
    reviewed_at = local_now()
    result = db.execute(
        update(MemoryDraft)
        .where(
            MemoryDraft.id == draft.id,
            MemoryDraft.user_id == draft.user_id,
            MemoryDraft.status == MemoryStatus.DRAFT,
        )
        .values(status=MemoryStatus.CONFIRMED, reviewed_at=reviewed_at)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    draft.status = MemoryStatus.CONFIRMED
    draft.reviewed_at = reviewed_at
    return True


def _index_statement_vector(statement: MemoryStatement) -> None:
    """确认后为 statement 建向量索引；失败不阻塞审阅，仅标记 pending 供回填。"""
    try:
        vector_id = upsert_statement_vector(statement)
    except Exception:
        vector_id = ""
    if vector_id:
        statement.embedding_ref = vector_id
        statement.embedding_model = settings.EMBEDDING_MODEL
        statement.embedding_status = "done"
    else:
        statement.embedding_status = "pending"


def _link_statement_entities(db: Session, statement: MemoryStatement) -> None:
    """确认后抽取核心实体并关联；失败不阻塞审阅。"""
    try:
        extract_and_link_entities(
            db,
            content=statement.content,
            source_id=statement.id,
            statement_id=statement.id,
            user_id=statement.user_id,
        )
    except Exception:
        pass


@router.get("/drafts", response_model=list[MemoryDraftOut])
def list_memory_drafts(
    status: Optional[str] = Query(None),
    draft_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    query = db.query(MemoryDraft).filter(MemoryDraft.user_id == actor.actor_id)
    if status:
        query = query.filter(MemoryDraft.status == status)
    if draft_type:
        query = query.filter(MemoryDraft.draft_type == draft_type)
    drafts = query.order_by(MemoryDraft.created_at.desc()).all()
    return [_draft_to_out(draft) for draft in drafts]


@router.get("/drafts/count")
def count_memory_drafts(
    status: str = Query("draft"),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """Return count of drafts (default: draft status) for badge display."""
    count = (
        db.query(MemoryDraft)
        .filter(
            MemoryDraft.user_id == actor.actor_id,
            MemoryDraft.status == status,
        )
        .count()
    )
    risks = (
        db.query(MemoryDraft.risk_level, func.count())
        .filter(
            MemoryDraft.user_id == actor.actor_id,
            MemoryDraft.status == status,
        )
        .group_by(MemoryDraft.risk_level)
        .all()
    )
    return {
        "count": count,
        "by_risk": {risk: c for risk, c in risks},
    }


@router.post("/drafts", response_model=MemoryDraftOut)
def create_memory_draft(
    payload: MemoryDraftCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    # Semantic dedup: check if similar memory already exists
    content = payload.payload.get("content") if isinstance(payload.payload, dict) else None
    if isinstance(content, str) and content.strip():
        from backend.app.services.memory_extraction import _check_semantic_duplicate
        is_dup, _ = _check_semantic_duplicate(db, content.strip(), user_id=actor.actor_id)
        if is_dup:
            raise HTTPException(status_code=409, detail="Similar memory already exists")
    source = _create_source(payload.source, db, actor.actor_id) if payload.source else None
    draft = MemoryDraft(
        user_id=actor.actor_id,
        draft_type=payload.draft_type,
        payload=payload.payload,
        decision_hint=payload.decision_hint,
        risk_level=payload.risk_level,
        confidence=payload.confidence,
        conflict_ids=payload.conflict_ids,
        source=source,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.post("/extract/session/{session_id}", response_model=MemoryExtractionOut)
def extract_memory_from_session(
    session_id: str,
    payload: MemoryExtractionRequest | None = None,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    # Only the session owner may trigger extraction on it.
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session is None or session.user_id != actor.actor_id:
        raise HTTPException(status_code=404, detail="Chat session not found")
    limit = payload.limit if payload else 20
    result = extract_session_memories(db, session_id=session_id, limit=limit)
    drafts = (
        db.query(MemoryDraft)
        .filter(MemoryDraft.id.in_(result.draft_ids))
        .order_by(MemoryDraft.created_at.desc())
        .all()
        if result.draft_ids
        else []
    )
    return MemoryExtractionOut(
        session_id=result.session_id,
        messages_scanned=result.messages_scanned,
        candidates_found=result.candidates_found,
        drafts_created=result.drafts_created,
        candidates_skipped=result.candidates_skipped,
        draft_ids=result.draft_ids,
        drafts=[_draft_to_out(draft) for draft in drafts],
    )


@router.post("/drafts/{draft_id}/confirm", response_model=MemoryDraftConfirmOut)
def confirm_memory_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    draft = _get_draft_or_404(draft_id, db, actor.actor_id)
    statement = _statement_from_draft(draft)
    if not _claim_draft_for_review(db, draft):
        db.refresh(draft)
        if draft.status == MemoryStatus.CONFIRMED:
            existing = _confirmed_statement_for_draft(db, draft)
            if existing is not None:
                return MemoryDraftConfirmOut(draft=_draft_to_out(draft), statement=_statement_to_out(existing))
        _ensure_draft_reviewable(draft)

    db.add(statement)
    db.flush()
    _index_statement_vector(statement)
    _link_statement_entities(db, statement)
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return MemoryDraftConfirmOut(draft=_draft_to_out(draft), statement=_statement_to_out(statement))


@router.post("/drafts/{draft_id}/reject", response_model=MemoryDraftOut)
def reject_memory_draft(
    draft_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    draft = _get_draft_or_404(draft_id, db, actor.actor_id)
    _ensure_draft_reviewable(draft)
    draft.status = MemoryStatus.REJECTED
    draft.reviewed_at = local_now()
    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.post("/drafts/{draft_id}/supersede", response_model=MemoryDraftConfirmOut)
def supersede_memory_draft(
    draft_id: str,
    payload: MemorySupersedePayload,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    draft = _get_draft_or_404(draft_id, db, actor.actor_id)
    _ensure_draft_reviewable(draft)
    old_statement = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == actor.actor_id,
            MemoryStatement.id == payload.superseded_statement_id,
        )
        .first()
    )
    if old_statement is None:
        raise HTTPException(status_code=404, detail="Superseded memory statement not found")
    if old_statement.status != MemoryStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="Only confirmed statements can be superseded")
    statement = _statement_from_draft(draft)
    draft.status = MemoryStatus.CONFIRMED
    draft.reviewed_at = local_now()
    old_statement.status = MemoryStatus.SUPERSEDED
    db.add(statement)
    db.flush()
    _index_statement_vector(statement)
    _link_statement_entities(db, statement)
    old_statement.superseded_by_id = statement.id
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return MemoryDraftConfirmOut(draft=_draft_to_out(draft), statement=_statement_to_out(statement))


@router.post("/extract/scheduled", response_model=dict)
def trigger_scheduled_extraction():
    """Manually trigger one round of scheduled extraction."""
    from backend.app.services.memory_scheduler import _scheduled_extraction_round
    stats = _scheduled_extraction_round()
    return stats


@router.get("/statements", response_model=list[MemoryStatementOut])
def list_memory_statements(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    statements = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == actor.actor_id,
            MemoryStatement.status == MemoryStatus.CONFIRMED,
        )
        .order_by(MemoryStatement.importance.desc(), MemoryStatement.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [_statement_to_out(statement) for statement in statements]


@router.get("/entities", response_model=dict)
def list_memory_entities(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    entities = (
        db.query(MemoryEntity)
        .filter(MemoryEntity.user_id == actor.actor_id, MemoryEntity.status == MemoryStatus.CONFIRMED)
        .order_by(MemoryEntity.mention_count.desc(), MemoryEntity.updated_at.desc())
        .limit(limit)
        .all()
    )
    entity_ids = [e.id for e in entities]
    relations = (
        db.query(MemoryRelation)
        .filter(
            MemoryRelation.user_id == actor.actor_id,
            MemoryRelation.status == MemoryStatus.CONFIRMED,
            MemoryRelation.subject_entity_id.in_(entity_ids),
            MemoryRelation.object_entity_id.in_(entity_ids),
        )
        .all()
    )
    return {
        "entities": [
            {
                "id": e.id,
                "name": e.name,
                "entity_type": e.entity_type,
                "description": e.description,
                "mention_count": e.mention_count,
                "importance": e.importance,
                "source_ids": e.source_ids or [],
            }
            for e in entities
        ],
        "relations": [
            {
                "id": r.id,
                "subject_entity_id": r.subject_entity_id,
                "object_entity_id": r.object_entity_id,
                "predicate": r.predicate,
                "statement_id": r.statement_id,
            }
            for r in relations
        ],
    }


@router.post("/reflect", response_model=dict)
def trigger_reflection(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """手动触发记忆反思：LLM 归纳已确认记忆为高层洞察 Insight。"""
    result = run_reflection(db, user_id=actor.actor_id)
    return result


@router.get("/insights", response_model=list[dict])
def get_insights(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    insights = list_insights(db, user_id=actor.actor_id, limit=limit)
    return [
        {
            "id": i.id,
            "theme": i.theme,
            "content": i.content,
            "insight_type": i.insight_type,
            "importance": i.importance,
            "created_at": i.created_at,
            "updated_at": i.updated_at,
        }
        for i in insights
    ]


@router.get("/consolidate/preview", response_model=dict)
def preview_consolidation(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """预览巩固候选：展示将提升重要度的高频记忆，不修改数据。"""
    return consolidation_candidates(db, user_id=actor.actor_id)


@router.post("/consolidate", response_model=dict)
def trigger_consolidation(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """手动触发巩固：高频被召回但重要度偏低的记忆提升重要度。"""
    return run_consolidation(db, user_id=actor.actor_id)
