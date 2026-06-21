# Agent Long-Term Memory Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 long-term memory foundation: graph-friendly relational models, review APIs, and a minimal Memory Inbox UI before LLM extraction is added.

**Architecture:** Keep Prism's current FastAPI + SQLAlchemy + auto-migrate pattern. Add new memory graph abstraction tables beside the existing `MemoryEntry`, expose review operations through `/api/v1/memories/*`, and add a frontend Memory Inbox page for manual draft governance.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Pydantic, pytest, React, TypeScript, Vite, Tailwind, lightweight Node static tests.

---

## Scope

This plan implements only Phase 1 from `docs/superpowers/specs/2026-06-21-agent-long-term-memory-design.md`.

Included:

- Data skeleton for memory source, statement, entity, relation, event, insight, and draft.
- Draft review APIs for list, create, confirm, reject, and supersede.
- Confirmed-only memory listing for new statement memories.
- Minimal Memory Inbox frontend.
- Tests for model defaults, state transitions, source traceability, and frontend wiring.

Excluded:

- LLM extraction.
- Active recall.
- `memory_search` engine upgrade.
- Lightweight reflection generation.
- Neo4j sync.

## File Structure

### Backend

- Modify `backend/app/models/memory.py`
  - Keep existing `MemoryEntry`.
  - Add new SQLAlchemy models:
    - `MemorySource`
    - `MemoryStatement`
    - `MemoryEntity`
    - `MemoryRelation`
    - `MemoryEvent`
    - `MemoryInsight`
    - `MemoryDraft`
  - Add string constants for statuses and draft types.

- Modify `backend/app/models/__init__.py`
  - Export new memory models so `Base.metadata.create_all` and `auto_migrate` see them.

- Modify `backend/app/schemas/memory.py`
  - Keep `MemoryEntryOut`.
  - Add request and response schemas for source, statement, draft, and review actions.

- Modify `backend/app/api/memories.py`
  - Keep existing `GET /memories` behavior for `MemoryEntry`.
  - Add Phase 1 endpoints:
    - `GET /memories/drafts`
    - `POST /memories/drafts`
    - `POST /memories/drafts/{draft_id}/confirm`
    - `POST /memories/drafts/{draft_id}/reject`
    - `POST /memories/drafts/{draft_id}/supersede`
    - `GET /memories/statements`

- Create `backend/tests/test_memory_phase1_models.py`
  - Model default and source traceability tests.

- Create `backend/tests/test_memory_phase1_api.py`
  - API state transition tests.

### Frontend

- Modify `frontend/src/app/api.ts`
  - Add `MemoryDraft`, `MemoryStatement`, create/review payload types.
  - Extend `memoryApi` with draft and statement endpoints.

- Create `frontend/src/pages/MemoryInboxPage.tsx`
  - Minimal review UI.

- Modify `frontend/src/app/routes.tsx`
  - Add route `/memory/inbox`.

- Modify `frontend/src/layouts/MainLayout.tsx`
  - Add a navigation entry for Memory Inbox if the current navigation structure has memory nav items.

- Create `frontend/tests/memory-inbox-api.test.mjs`
  - Static test for API and route wiring.

---

### Task 1: Add Memory Graph Models

**Files:**
- Modify: `backend/app/models/memory.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_memory_phase1_models.py`

- [ ] **Step 1: Write failing model tests**

Create `backend/tests/test_memory_phase1_models.py`:

```python
from backend.app.models import (
    MemoryDraft,
    MemorySource,
    MemoryStatement,
)


def test_memory_source_preserves_chat_traceability(db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        session_id="session-1",
        message_id="msg-1",
        span_text="We decided to build Memory Inbox first.",
        source_metadata={"prompt_version": "manual"},
    )
    db_session.add(source)
    db_session.commit()

    saved = db_session.query(MemorySource).one()

    assert saved.source_type == "chat_message"
    assert saved.session_id == "session-1"
    assert saved.message_id == "msg-1"
    assert saved.span_text == "We decided to build Memory Inbox first."
    assert saved.source_metadata == {"prompt_version": "manual"}


def test_memory_statement_defaults_exclude_unconfirmed_memory(db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user chose hybrid memory writes.",
    )
    statement = MemoryStatement(
        user_id="default-user",
        content="The user chose hybrid memory writes.",
        statement_type="decision",
        temporal_type="stable",
        source=source,
    )
    db_session.add(statement)
    db_session.commit()

    saved = db_session.query(MemoryStatement).one()

    assert saved.status == "draft"
    assert saved.confidence == 0.7
    assert saved.importance == 0.6
    assert saved.source.span_text == "The user chose hybrid memory writes."


def test_memory_draft_defaults_to_pending_review(db_session):
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={"content": "The user wants Memory Inbox first."},
        decision_hint="review",
        risk_level="medium",
        confidence=0.65,
    )
    db_session.add(draft)
    db_session.commit()

    saved = db_session.query(MemoryDraft).one()

    assert saved.status == "draft"
    assert saved.conflict_ids == []
    assert saved.payload["content"] == "The user wants Memory Inbox first."
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py -q
```

Expected: FAIL with import errors for `MemorySource`, `MemoryStatement`, or `MemoryDraft`.

- [ ] **Step 3: Add models**

Modify `backend/app/models/memory.py` so it contains the existing `MemoryEntry` plus these additions:

```python
class MemoryStatus:
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class MemorySource(Base):
    __tablename__ = "memory_source"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    source_type = Column(String(64), nullable=False, index=True)
    source_id = Column(String(128), nullable=False, default="")
    session_id = Column(CHAR(36), default="", index=True)
    message_id = Column(CHAR(36), default="", index=True)
    span_text = Column(Text, default="")
    occurred_at = Column(DateTime, default=local_now, index=True)
    source_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)


class MemoryStatement(Base):
    __tablename__ = "memory_statement"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    content = Column(Text, nullable=False)
    statement_type = Column(String(64), default="fact", index=True)
    temporal_type = Column(String(64), default="stable", index=True)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    valid_from = Column(DateTime, default=local_now)
    valid_until = Column(DateTime, nullable=True)
    superseded_by_id = Column(CHAR(36), default="", index=True)
    source_id = Column(CHAR(36), ForeignKey("memory_source.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source = relationship("MemorySource")


class MemoryEntity(Base):
    __tablename__ = "memory_entity"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    name = Column(String(255), nullable=False, index=True)
    entity_type = Column(String(64), default="topic", index=True)
    description = Column(Text, default="")
    aliases = Column(JSON, default=list)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    mention_count = Column(Integer, default=1)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    source_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryRelation(Base):
    __tablename__ = "memory_relation"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    subject_entity_id = Column(CHAR(36), ForeignKey("memory_entity.id"), nullable=False, index=True)
    predicate = Column(String(64), nullable=False, index=True)
    object_entity_id = Column(CHAR(36), ForeignKey("memory_entity.id"), nullable=False, index=True)
    statement_id = Column(CHAR(36), ForeignKey("memory_statement.id"), nullable=True, index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    valid_from = Column(DateTime, default=local_now)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryEvent(Base):
    __tablename__ = "memory_event"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    event_time = Column(DateTime, nullable=True, index=True)
    event_type = Column(String(64), default="decision", index=True)
    related_entity_ids = Column(JSON, default=list)
    statement_id = Column(CHAR(36), ForeignKey("memory_statement.id"), nullable=True, index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryInsight(Base):
    __tablename__ = "memory_insight"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    theme = Column(String(128), nullable=False, index=True)
    content = Column(Text, nullable=False)
    insight_type = Column(String(64), default="recent_focus", index=True)
    source_statement_ids = Column(JSON, default=list)
    confidence = Column(Float, default=0.7)
    importance = Column(Float, default=0.6)
    status = Column(String(32), default=MemoryStatus.CONFIRMED, index=True)
    valid_from = Column(DateTime, default=local_now)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class MemoryDraft(Base):
    __tablename__ = "memory_draft"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)
    draft_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    decision_hint = Column(String(64), default="review")
    risk_level = Column(String(32), default="medium", index=True)
    confidence = Column(Float, default=0.7)
    status = Column(String(32), default=MemoryStatus.DRAFT, index=True)
    conflict_ids = Column(JSON, default=list)
    source_id = Column(CHAR(36), ForeignKey("memory_source.id"), nullable=True, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source = relationship("MemorySource")
```

Also add these imports at the top of `backend/app/models/memory.py`:

```python
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
```

Keep the existing MySQL `JSON` and `CHAR` imports.

- [ ] **Step 4: Export models**

Modify `backend/app/models/__init__.py`:

```python
from .memory import (
    MemoryDraft,
    MemoryEntity,
    MemoryEntry,
    MemoryEvent,
    MemoryInsight,
    MemoryRelation,
    MemorySource,
    MemoryStatement,
)
```

Add the same names to `__all__`.

- [ ] **Step 5: Run model tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add backend/app/models/memory.py backend/app/models/__init__.py backend/tests/test_memory_phase1_models.py
git commit -m "feat: add phase 1 memory graph models"
```

---

### Task 2: Add Memory Schemas and Draft Review APIs

**Files:**
- Modify: `backend/app/schemas/memory.py`
- Modify: `backend/app/api/memories.py`
- Create: `backend/tests/test_memory_phase1_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_memory_phase1_api.py`:

```python
from backend.app.models import MemoryDraft, MemorySource, MemoryStatement


def test_create_and_list_memory_drafts(client):
    response = client.post(
        "/api/v1/memories/drafts",
        json={
            "draft_type": "statement",
            "payload": {
                "content": "The user chose a phased hybrid memory design.",
                "statement_type": "decision",
                "temporal_type": "stable",
            },
            "decision_hint": "auto_confirm",
            "risk_level": "low",
            "confidence": 0.88,
            "source": {
                "source_type": "chat_message",
                "source_id": "msg-1",
                "session_id": "session-1",
                "message_id": "msg-1",
                "span_text": "We choose phased hybrid.",
                "metadata": {"prompt_version": "manual"},
            },
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["draft_type"] == "statement"
    assert created["status"] == "draft"
    assert created["source"]["span_text"] == "We choose phased hybrid."

    listed = client.get("/api/v1/memories/drafts").json()

    assert [item["id"] for item in listed] == [created["id"]]


def test_confirm_statement_draft_creates_confirmed_statement(client, db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user wants Memory Inbox first.",
    )
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": "The user wants Memory Inbox first.",
            "statement_type": "preference",
            "temporal_type": "current",
            "importance": 0.8,
        },
        confidence=0.9,
        risk_level="low",
        source=source,
    )
    db_session.add(draft)
    db_session.commit()

    response = client.post(f"/api/v1/memories/drafts/{draft.id}/confirm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["status"] == "confirmed"
    assert payload["statement"]["content"] == "The user wants Memory Inbox first."
    assert payload["statement"]["status"] == "confirmed"

    statements = client.get("/api/v1/memories/statements").json()
    assert [item["content"] for item in statements] == ["The user wants Memory Inbox first."]


def test_reject_draft_marks_it_rejected(client, db_session):
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={"content": "Uncertain memory"},
    )
    db_session.add(draft)
    db_session.commit()

    response = client.post(f"/api/v1/memories/drafts/{draft.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_supersede_draft_confirms_new_statement_and_supersedes_old(client, db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user now prefers review-first memory.",
    )
    old = MemoryStatement(
        user_id="default-user",
        content="The user prefers automatic memory writes.",
        statement_type="preference",
        temporal_type="current",
        status="confirmed",
    )
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": "The user prefers review-first memory.",
            "statement_type": "preference",
            "temporal_type": "current",
        },
        conflict_ids=[],
        source=source,
    )
    db_session.add_all([old, draft])
    db_session.commit()

    response = client.post(
        f"/api/v1/memories/drafts/{draft.id}/supersede",
        json={"superseded_statement_id": old.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["statement"]["status"] == "confirmed"

    db_session.refresh(old)
    assert old.status == "superseded"
    assert old.superseded_by_id == payload["statement"]["id"]

    statements = client.get("/api/v1/memories/statements").json()
    assert [item["content"] for item in statements] == ["The user prefers review-first memory."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_api.py -q
```

Expected: FAIL with missing schemas or missing endpoints.

- [ ] **Step 3: Add schemas**

Append these schemas to `backend/app/schemas/memory.py`:

```python
from typing import Any, Optional

from pydantic import Field


class MemorySourceCreate(BaseModel):
    source_type: str
    source_id: str = ""
    session_id: str = ""
    message_id: str = ""
    span_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySourceOut(MemorySourceCreate):
    id: str
    user_id: str
    occurred_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


def memory_source_to_out(source) -> MemorySourceOut:
    return MemorySourceOut(
        id=source.id,
        user_id=source.user_id,
        source_type=source.source_type,
        source_id=source.source_id,
        session_id=source.session_id,
        message_id=source.message_id,
        span_text=source.span_text,
        metadata=source.source_metadata or {},
        occurred_at=source.occurred_at,
        created_at=source.created_at,
    )


class MemoryDraftCreate(BaseModel):
    draft_type: str
    payload: dict[str, Any]
    decision_hint: str = "review"
    risk_level: str = "medium"
    confidence: float = 0.7
    conflict_ids: list[str] = []
    source: Optional[MemorySourceCreate] = None


class MemoryDraftOut(BaseModel):
    id: str
    user_id: str
    draft_type: str
    payload: dict[str, Any]
    decision_hint: str
    risk_level: str
    confidence: float
    status: str
    conflict_ids: list[str]
    source: Optional[MemorySourceOut] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemoryStatementOut(BaseModel):
    id: str
    user_id: str
    content: str
    statement_type: str
    temporal_type: str
    confidence: float
    importance: float
    status: str
    valid_from: datetime
    valid_until: Optional[datetime] = None
    superseded_by_id: str
    source: Optional[MemorySourceOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemoryDraftConfirmOut(BaseModel):
    draft: MemoryDraftOut
    statement: MemoryStatementOut


class MemorySupersedePayload(BaseModel):
    superseded_statement_id: str
```

- [ ] **Step 4: Add API endpoints**

Modify `backend/app/api/memories.py` by importing the new models and schemas:

```python
from ..models.memory import MemoryDraft, MemorySource, MemoryStatement, MemoryStatus
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
```

Add helper functions:

```python
def _create_source(db: Session, payload) -> MemorySource | None:
    if payload is None:
        return None
    data = payload.model_dump()
    metadata = data.pop("metadata", {})
    source = MemorySource(user_id=DEFAULT_USER_ID, source_metadata=metadata, **data)
    db.add(source)
    db.flush()
    return source


def _statement_from_draft(draft: MemoryDraft) -> MemoryStatement:
    payload = draft.payload or {}
    return MemoryStatement(
        user_id=draft.user_id,
        content=str(payload.get("content") or "").strip(),
        statement_type=str(payload.get("statement_type") or "fact"),
        temporal_type=str(payload.get("temporal_type") or "stable"),
        confidence=float(payload.get("confidence", draft.confidence or 0.7)),
        importance=float(payload.get("importance", 0.6)),
        status=MemoryStatus.CONFIRMED,
        source_id=draft.source_id,
    )


def _get_draft_or_404(db: Session, draft_id: str) -> MemoryDraft:
    draft = db.query(MemoryDraft).filter(MemoryDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="memory draft not found")
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
```

Add the endpoints:

```python
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
    source = _create_source(db, payload.source)
    draft = MemoryDraft(
        user_id=DEFAULT_USER_ID,
        draft_type=payload.draft_type,
        payload=payload.payload,
        decision_hint=payload.decision_hint,
        risk_level=payload.risk_level,
        confidence=payload.confidence,
        conflict_ids=payload.conflict_ids,
        source_id=source.id if source else None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.post("/drafts/{draft_id}/confirm", response_model=MemoryDraftConfirmOut)
def confirm_memory_draft(draft_id: str, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(db, draft_id)
    if draft.status != MemoryStatus.DRAFT:
        raise HTTPException(status_code=400, detail="memory draft is not reviewable")
    statement = _statement_from_draft(draft)
    if not statement.content:
        raise HTTPException(status_code=400, detail="statement draft content is required")
    draft.status = MemoryStatus.CONFIRMED
    draft.reviewed_at = local_now()
    db.add(statement)
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return {"draft": _draft_to_out(draft), "statement": _statement_to_out(statement)}


@router.post("/drafts/{draft_id}/reject", response_model=MemoryDraftOut)
def reject_memory_draft(draft_id: str, db: Session = Depends(get_db)):
    draft = _get_draft_or_404(db, draft_id)
    if draft.status != MemoryStatus.DRAFT:
        raise HTTPException(status_code=400, detail="memory draft is not reviewable")
    draft.status = MemoryStatus.REJECTED
    draft.reviewed_at = local_now()
    db.commit()
    db.refresh(draft)
    return _draft_to_out(draft)


@router.post("/drafts/{draft_id}/supersede", response_model=MemoryDraftConfirmOut)
def supersede_memory_statement(
    draft_id: str,
    payload: MemorySupersedePayload,
    db: Session = Depends(get_db),
):
    draft = _get_draft_or_404(db, draft_id)
    old = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.id == payload.superseded_statement_id,
            MemoryStatement.user_id == DEFAULT_USER_ID,
        )
        .first()
    )
    if old is None:
        raise HTTPException(status_code=404, detail="superseded statement not found")
    statement = _statement_from_draft(draft)
    if not statement.content:
        raise HTTPException(status_code=400, detail="statement draft content is required")
    draft.status = MemoryStatus.CONFIRMED
    draft.reviewed_at = local_now()
    old.status = MemoryStatus.SUPERSEDED
    db.add(statement)
    db.flush()
    old.superseded_by_id = statement.id
    db.commit()
    db.refresh(draft)
    db.refresh(statement)
    return {"draft": _draft_to_out(draft), "statement": _statement_to_out(statement)}


@router.get("/statements", response_model=list[MemoryStatementOut])
def list_memory_statements(
    status: str = Query(MemoryStatus.CONFIRMED),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statements = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == DEFAULT_USER_ID,
            MemoryStatement.status == status,
        )
        .order_by(MemoryStatement.importance.desc(), MemoryStatement.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [_statement_to_out(statement) for statement in statements]
```

Also add `HTTPException` to the existing FastAPI imports.

- [ ] **Step 5: Run API tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Run existing memory API tests**

Run:

```powershell
python -m pytest backend/tests/test_memories_api.py backend/tests/test_memory_phase1_api.py backend/tests/test_memory_phase1_models.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add backend/app/schemas/memory.py backend/app/api/memories.py backend/tests/test_memory_phase1_api.py
git commit -m "feat: add memory draft review api"
```

---

### Task 3: Add Frontend API Client and Static Wiring Tests

**Files:**
- Modify: `frontend/src/app/api.ts`
- Create: `frontend/tests/memory-inbox-api.test.mjs`

- [ ] **Step 1: Write failing frontend static test**

Create `frontend/tests/memory-inbox-api.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')

assert.match(api, /interface MemoryDraft/, 'API client exposes MemoryDraft type.')
assert.match(api, /interface MemoryStatement/, 'API client exposes MemoryStatement type.')
assert.match(api, /listDrafts:/, 'memoryApi lists memory drafts.')
assert.match(api, /createDraft:/, 'memoryApi creates memory drafts.')
assert.match(api, /confirmDraft:/, 'memoryApi confirms memory drafts.')
assert.match(api, /rejectDraft:/, 'memoryApi rejects memory drafts.')
assert.match(api, /supersedeDraft:/, 'memoryApi supersedes old statements from drafts.')
assert.match(api, /listStatements:/, 'memoryApi lists confirmed statements.')
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-api.test.mjs
```

Expected: FAIL on missing `MemoryDraft` or missing API methods.

- [ ] **Step 3: Add frontend types and API methods**

Modify `frontend/src/app/api.ts` near the existing `MemoryEntry` and `memoryApi` definitions:

```typescript
export interface MemorySource {
  id: string
  user_id: string
  source_type: string
  source_id: string
  session_id: string
  message_id: string
  span_text: string
  metadata: Record<string, unknown>
  occurred_at: string
  created_at: string
}

export interface MemoryDraft {
  id: string
  user_id: string
  draft_type: string
  payload: Record<string, unknown>
  decision_hint: string
  risk_level: string
  confidence: number
  status: string
  conflict_ids: string[]
  source?: MemorySource | null
  reviewed_at?: string | null
  created_at: string
  updated_at: string
}

export interface MemoryStatement {
  id: string
  user_id: string
  content: string
  statement_type: string
  temporal_type: string
  confidence: number
  importance: number
  status: string
  valid_from: string
  valid_until?: string | null
  superseded_by_id: string
  source?: MemorySource | null
  created_at: string
  updated_at: string
}

export interface MemoryDraftCreate {
  draft_type: string
  payload: Record<string, unknown>
  decision_hint?: string
  risk_level?: string
  confidence?: number
  conflict_ids?: string[]
  source?: {
    source_type: string
    source_id?: string
    session_id?: string
    message_id?: string
    span_text?: string
    metadata?: Record<string, unknown>
  } | null
}
```

Extend `memoryApi`:

```typescript
  listDrafts: (params?: { status?: string; draft_type?: string }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set('status', params.status)
    if (params?.draft_type) search.set('draft_type', params.draft_type)
    const qs = search.toString() ? `?${search.toString()}` : ''
    return request<MemoryDraft[]>(`/memories/drafts${qs}`)
  },
  createDraft: (data: MemoryDraftCreate) =>
    request<MemoryDraft>('/memories/drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  confirmDraft: (id: string) =>
    request<{ draft: MemoryDraft; statement: MemoryStatement }>(`/memories/drafts/${id}/confirm`, {
      method: 'POST',
    }),
  rejectDraft: (id: string) =>
    request<MemoryDraft>(`/memories/drafts/${id}/reject`, {
      method: 'POST',
    }),
  supersedeDraft: (id: string, superseded_statement_id: string) =>
    request<{ draft: MemoryDraft; statement: MemoryStatement }>(`/memories/drafts/${id}/supersede`, {
      method: 'POST',
      body: JSON.stringify({ superseded_statement_id }),
    }),
  listStatements: (params?: { status?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.status) search.set('status', params.status)
    if (params?.limit) search.set('limit', String(params.limit))
    const qs = search.toString() ? `?${search.toString()}` : ''
    return request<MemoryStatement[]>(`/memories/statements${qs}`)
  },
```

- [ ] **Step 4: Run frontend static test**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-api.test.mjs
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add frontend/src/app/api.ts frontend/tests/memory-inbox-api.test.mjs
git commit -m "feat: add memory inbox api client"
```

---

### Task 4: Add Minimal Memory Inbox Page

**Files:**
- Create: `frontend/src/pages/MemoryInboxPage.tsx`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Create: `frontend/tests/memory-inbox-page.test.mjs`

- [ ] **Step 1: Write failing static UI test**

Create `frontend/tests/memory-inbox-page.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/MemoryInboxPage.tsx'), 'utf8')

assert.match(routes, /MemoryInboxPage/, 'Routes import MemoryInboxPage.')
assert.match(routes, /memory\/inbox/, 'Routes expose /memory/inbox.')
assert.match(page, /data-testid="memory-inbox-page"/, 'Memory Inbox page has a stable test id.')
assert.match(page, /memoryApi\.listDrafts/, 'Memory Inbox page loads drafts.')
assert.match(page, /memoryApi\.confirmDraft/, 'Memory Inbox page can confirm drafts.')
assert.match(page, /memoryApi\.rejectDraft/, 'Memory Inbox page can reject drafts.')
assert.match(page, /Source/, 'Memory Inbox page shows source evidence.')
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-page.test.mjs
```

Expected: FAIL because `MemoryInboxPage.tsx` does not exist or route is missing.

- [ ] **Step 3: Create Memory Inbox page**

Create `frontend/src/pages/MemoryInboxPage.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react'
import { Check, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { memoryApi, type MemoryDraft } from '@/app/api'

function draftTitle(draft: MemoryDraft) {
  const content = draft.payload?.content
  if (typeof content === 'string' && content.trim()) return content
  return `${draft.draft_type} draft`
}

function formatPayload(payload: Record<string, unknown>) {
  return JSON.stringify(payload, null, 2)
}

export function MemoryInboxPage() {
  const [drafts, setDrafts] = useState<MemoryDraft[]>([])
  const [status, setStatus] = useState('draft')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return drafts
    return drafts.filter((draft) =>
      [
        draft.draft_type,
        draft.risk_level,
        draft.decision_hint,
        draft.source?.span_text ?? '',
        formatPayload(draft.payload),
      ]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [drafts, query])

  const loadDrafts = async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await memoryApi.listDrafts(status ? { status } : undefined)
      setDrafts(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDrafts()
  }, [status])

  const review = async (draft: MemoryDraft, action: 'confirm' | 'reject') => {
    setError(null)
    try {
      if (action === 'confirm') await memoryApi.confirmDraft(draft.id)
      else await memoryApi.rejectDraft(draft.id)
      await loadDrafts()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div data-testid="memory-inbox-page" className="min-h-[calc(100vh-9rem)] space-y-4 text-[13px]">
      <section className="border-b border-[var(--prism-line)] pb-3">
        <div className="text-xs font-medium text-slate-500">Memory governance</div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Memory Inbox</h1>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-[var(--prism-line)] bg-white p-3 md:flex-row md:items-center">
        <label className="relative min-w-0 flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search memory drafts"
            placeholder="Search drafts, source text, payload"
            className="h-9 w-full rounded-md border border-[var(--prism-line)] bg-white pl-8 pr-3 text-xs outline-none focus:border-[var(--prism-blue)]"
          />
        </label>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-9 rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs"
        >
          <option value="draft">Draft</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
        <button
          type="button"
          onClick={loadDrafts}
          disabled={loading}
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600 disabled:opacity-50"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          Refresh
        </button>
      </section>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div> : null}

      <section className="grid gap-3">
        {filtered.map((draft) => (
          <article key={draft.id} className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.draft_type}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">risk: {draft.risk_level}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">confidence: {Math.round(draft.confidence * 100)}%</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.status}</span>
                </div>
                <h2 className="mt-2 text-sm font-semibold text-slate-950">{draftTitle(draft)}</h2>
                {draft.source?.span_text ? (
                  <blockquote className="mt-3 rounded-md border-l-2 border-blue-300 bg-blue-50 px-3 py-2 text-xs leading-5 text-slate-600">
                    <div className="mb-1 font-medium text-slate-700">Source</div>
                    {draft.source.span_text}
                  </blockquote>
                ) : null}
                <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                  {formatPayload(draft.payload)}
                </pre>
              </div>
              {draft.status === 'draft' ? (
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => review(draft, 'confirm')}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-xs font-medium text-white"
                  >
                    <Check size={14} />
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => review(draft, 'reject')}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600"
                  >
                    <X size={14} />
                    Reject
                  </button>
                </div>
              ) : null}
            </div>
          </article>
        ))}
        {!loading && filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-white p-8 text-center text-xs text-slate-500">
            No memory drafts match the current filters.
          </div>
        ) : null}
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Add route**

Modify `frontend/src/app/routes.tsx`:

```tsx
import { MemoryInboxPage } from '@/pages/MemoryInboxPage'
```

Add this child route:

```tsx
{ path: 'memory/inbox', element: <MemoryInboxPage /> },
```

- [ ] **Step 5: Add navigation entry**

Modify the `navItems` array in `frontend/src/layouts/MainLayout.tsx` by inserting this item before `/memory/profile`:

```tsx
{ to: '/memory/inbox', label: '记忆审核', icon: Inbox },
```

Also add this `NavItem` at the top of the `用户记忆` section in `NavList`, before the existing `/memory/profile` item:

```tsx
<NavItem
  to="/memory/inbox"
  label="记忆审核"
  icon={Inbox}
  active={location.pathname === '/memory/inbox'}
  isDark={isDark}
  onNavigate={onNavigate}
/>
```

- [ ] **Step 6: Run frontend static tests**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-api.test.mjs
node .\tests\memory-inbox-page.test.mjs
```

Expected: PASS.

- [ ] **Step 7: Run frontend build**

Run:

```powershell
cd frontend
pnpm.cmd build
```

Expected: build exits 0.

- [ ] **Step 8: Commit**

Run:

```powershell
git add frontend/src/pages/MemoryInboxPage.tsx frontend/src/app/routes.tsx frontend/src/layouts/MainLayout.tsx frontend/tests/memory-inbox-page.test.mjs
git commit -m "feat: add memory inbox page"
```

---

### Task 5: Add Confirmed Memory Statement Compatibility and Final Verification

**Files:**
- Modify: `backend/app/api/memories.py`
- Modify: `backend/tests/test_memory_phase1_api.py`
- Test existing files.

- [ ] **Step 1: Add regression test for confirmed-only listing**

Append to `backend/tests/test_memory_phase1_api.py`:

```python
def test_list_memory_statements_excludes_superseded_and_drafts(client, db_session):
    db_session.add_all(
        [
            MemoryStatement(
                user_id="default-user",
                content="Confirmed memory",
                statement_type="fact",
                status="confirmed",
                importance=0.7,
            ),
            MemoryStatement(
                user_id="default-user",
                content="Draft memory",
                statement_type="fact",
                status="draft",
                importance=0.9,
            ),
            MemoryStatement(
                user_id="default-user",
                content="Superseded memory",
                statement_type="fact",
                status="superseded",
                importance=1.0,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/memories/statements")

    assert response.status_code == 200
    assert [item["content"] for item in response.json()] == ["Confirmed memory"]
```

- [ ] **Step 2: Run test**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_api.py::test_list_memory_statements_excludes_superseded_and_drafts -q
```

Expected: PASS because `list_memory_statements` defaults to `status=confirmed` and filters exactly on that status.

- [ ] **Step 3: Run backend Phase 1 test set**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py backend/tests/test_memory_phase1_api.py backend/tests/test_memories_api.py -q
```

Expected: PASS.

- [ ] **Step 4: Run frontend Phase 1 static test set**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-api.test.mjs
node .\tests\memory-inbox-page.test.mjs
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```powershell
cd frontend
pnpm.cmd build
```

Expected: build exits 0.

- [ ] **Step 6: Commit final verification adjustments**

If Step 2 required code changes, commit them:

```powershell
git add backend/app/api/memories.py backend/tests/test_memory_phase1_api.py
git commit -m "test: verify confirmed memory statement filtering"
```

If no code changed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Data skeleton: Task 1.
  - Review APIs: Task 2.
  - Minimal Memory Inbox frontend: Tasks 3 and 4.
  - Source traceability: Tasks 1 and 2.
  - Supersede behavior: Tasks 2 and 5.
  - Confirmed-only recall filtering foundation: Task 5.
  - Existing `MemoryEntry` compatibility: Task 2 runs existing memory tests.

- Intentional gaps:
  - LLM extraction is Phase 2 and not implemented here.
  - Active recall and `memory_search` upgrade are Phase 3 and not implemented here.
  - Lightweight reflection is Phase 4 and not implemented here.
  - Neo4j evolution is later and not implemented here.

- Verification commands:
  - `python -m pytest backend/tests/test_memory_phase1_models.py backend/tests/test_memory_phase1_api.py backend/tests/test_memories_api.py -q`
  - `cd frontend && node .\tests\memory-inbox-api.test.mjs && node .\tests\memory-inbox-page.test.mjs`
  - `cd frontend && pnpm.cmd build`
