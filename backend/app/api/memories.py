from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.memory import MemoryDraft, MemoryEntry, MemorySource, MemoryStatement, MemoryStatus
from ..schemas.memory import (
    MemoryDraftConfirmOut,
    MemoryDraftCreate,
    MemoryDraftOut,
    MemoryEntryOut,
    MemoryStatementOut,
    MemorySupersedePayload,
    memory_source_to_out,
)
from ..utils.time import local_now

router = APIRouter(prefix="/memories", tags=["memories"])
DEFAULT_USER_ID = "default-user"


@router.get("", response_model=list[MemoryEntryOut])
def list_memories(
    memory_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(MemoryEntry).filter(MemoryEntry.user_id == DEFAULT_USER_ID)
    if memory_type:
        query = query.filter(MemoryEntry.memory_type == memory_type)
    return query.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit).all()


def _create_source(source_in, db: Session) -> MemorySource:
    data = source_in.model_dump()
    metadata = data.pop("metadata", {})
    source = MemorySource(user_id=DEFAULT_USER_ID, source_metadata=metadata, **data)
    db.add(source)
    return source


def _statement_from_draft(draft: MemoryDraft) -> MemoryStatement:
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


def _get_draft_or_404(draft_id: str, db: Session) -> MemoryDraft:
    draft = (
        db.query(MemoryDraft)
        .filter(MemoryDraft.user_id == DEFAULT_USER_ID, MemoryDraft.id == draft_id)
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


@router.get("/drafts", response_model=list[MemoryDraftOut])
def list_memory_drafts(
    status: Optional[str] = Query(None),
    draft_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(MemoryDraft).filter(MemoryDraft.user_id == DEFAULT_USER_ID)
    if status:
        query = query.filter(MemoryDraft.status == status)
    if draft_type:
        query = query.filter(MemoryDraft.draft_type == draft_type)
    drafts = query.order_by(MemoryDraft.created_at.desc()).all()
    return [_draft_to_out(draft) for draft in drafts]


@router.post("/drafts", response_model=MemoryDraftOut)
def create_memory_draft(payload: MemoryDraftCreate, db: Session = Depends(get_db)):
    source = _create_source(payload.source, db) if payload.source else None
    draft = MemoryDraft(
        user_id=DEFAULT_USER_ID,
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


@router.post("/drafts/{draft_id}/confirm", response_model=MemoryDraftConfirmOut)
def confirm_memory_draft(draft_id: str, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(draft_id, db)
    _ensure_draft_reviewable(draft)
    statement = _statement_from_draft(draft)
    draft.status = MemoryStatus.CONFIRMED
    draft.reviewed_at = local_now()
    db.add(statement)
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return MemoryDraftConfirmOut(draft=_draft_to_out(draft), statement=_statement_to_out(statement))


@router.post("/drafts/{draft_id}/reject", response_model=MemoryDraftOut)
def reject_memory_draft(draft_id: str, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(draft_id, db)
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
):
    draft = _get_draft_or_404(draft_id, db)
    _ensure_draft_reviewable(draft)
    old_statement = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == DEFAULT_USER_ID,
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
    old_statement.superseded_by_id = statement.id
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return MemoryDraftConfirmOut(draft=_draft_to_out(draft), statement=_statement_to_out(statement))


@router.get("/statements", response_model=list[MemoryStatementOut])
def list_memory_statements(
    status: str = Query(MemoryStatus.CONFIRMED),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statements = (
        db.query(MemoryStatement)
        .filter(MemoryStatement.user_id == DEFAULT_USER_ID, MemoryStatement.status == status)
        .order_by(MemoryStatement.importance.desc(), MemoryStatement.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [_statement_to_out(statement) for statement in statements]
