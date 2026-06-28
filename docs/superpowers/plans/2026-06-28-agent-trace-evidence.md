# Agent Trace Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add machine-analyzable agent traces with normalized retrieval evidence for every Prism assistant answer.

**Architecture:** Persist each answer run in `agent_trace`, each model/tool event in `agent_trace_step`, and each returned evidence item in `agent_trace_evidence`. The engine records traces during streaming, the backend exposes bind/export APIs, and the frontend stores the `trace_id` with the assistant message then binds it after persistence.

**Tech Stack:** Python, FastAPI, SQLAlchemy, MySQL/SQLite tests, LangChain tools, React/TypeScript, Zustand, Vitest-style Node tests where existing.

---

## File Structure

- Create `backend/app/models/agent_trace.py`: SQLAlchemy trace, step, and evidence models.
- Modify `backend/app/models/__init__.py`: register trace models for `Base.metadata` and auto-migration.
- Create `backend/app/services/agent_trace.py`: bind/export helpers used by API and tests.
- Create `backend/app/api/traces.py`: `/api/v1/traces/{trace_id}/bind-message` and `/api/v1/traces/{trace_id}/export`.
- Modify `backend/app/api/__init__.py`: include trace router.
- Create `backend/tests/test_agent_trace_models.py`: persistence model test.
- Create `backend/tests/test_agent_trace_api.py`: bind/export API tests.
- Create `engine/app/agent/tools/evidence.py`: shared Evidence Schema adapter.
- Modify `engine/app/agent/tools/knowledge.py`: add `evidence_items`.
- Modify `engine/app/agent/tools/knowledge_governance.py`: add `evidence_items` to knowledge tools.
- Create `engine/tests/test_agent_evidence.py`: adapter unit tests.
- Create `engine/tests/test_agent_tool_evidence_payloads.py`: tool payload evidence tests.
- Create `engine/app/agent/trace.py`: resilient trace recorder used by the runner.
- Modify `engine/app/agent/events.py`: add `trace_event` and pass evidence through `tool_result_event`.
- Modify `engine/app/api/chat.py`: accept `session_id` and `user_message_id`; stream trace id.
- Modify `engine/app/chat/answer.py`: create recorder and pass it into runner.
- Modify `engine/app/agent/runner.py`: record model/tool/final/error steps and include `evidence_items` in stream events.
- Modify `engine/tests/test_agent_runner.py`: trace event and trace recorder behavior tests.
- Modify `frontend/src/app/api.ts`: add trace API methods and request fields.
- Modify `frontend/src/app/chatStore.ts`: store `traceId` and `evidenceItems` in message/tool run state.
- Modify `frontend/src/pages/ChatPage.tsx`: handle `trace` event, persist trace id in assistant process, and bind after assistant persistence.
- Add a frontend stream test for trace event handling in the existing frontend test style.

## Task 1: Backend Trace Models

**Files:**
- Create: `backend/app/models/agent_trace.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_agent_trace_models.py`

- [ ] **Step 1: Write the failing model persistence test**

Create `backend/tests/test_agent_trace_models.py`:

```python
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep


def test_agent_trace_models_persist(db_session):
    trace = AgentTrace(
        session_id="session-1",
        user_message_id="user-1",
        user_query="What is this chunk?",
        status="running",
        model="test-model",
    )
    db_session.add(trace)
    db_session.flush()

    step = AgentTraceStep(
        trace_id=trace.id,
        step_index=1,
        step_type="tool_result",
        tool_name="raw_document_search",
        tool_call_id="call_1",
        input_json={"query": "chunk"},
        output_json={"status": "success", "summary": "found"},
        status="success",
        latency_ms=12,
    )
    db_session.add(step)
    db_session.flush()

    evidence = AgentTraceEvidence(
        trace_step_id=step.id,
        evidence_id="document_chunk:chunk-1",
        source_kind="document_chunk",
        source_id="chunk-1",
        chunk_id="chunk-1",
        parent_chunk_id="parent-1",
        item_id="item-1",
        display_title="Doc",
        excerpt="raw excerpt",
        hit_reason="matched raw document search result",
        score=0.9,
        retrieval_path_json=["raw_document_search"],
        metadata_json={"chunk_type": "child", "chunk_index": 3},
    )
    db_session.add(evidence)
    db_session.commit()

    loaded = db_session.query(AgentTrace).filter_by(id=trace.id).one()
    assert loaded.steps[0].evidence_items[0].chunk_id == "chunk-1"
    assert loaded.steps[0].evidence_items[0].metadata_json["chunk_index"] == 3
```

- [ ] **Step 2: Run the model test and verify it fails**

Run:

```powershell
pytest backend/tests/test_agent_trace_models.py -q
```

Expected: FAIL with an import error for `AgentTrace`.

- [ ] **Step 3: Add SQLAlchemy trace models**

Create `backend/app/models/agent_trace.py`:

```python
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class AgentTrace(Base):
    __tablename__ = "agent_trace"
    __table_args__ = (
        Index("ix_agent_trace_session_started", "session_id", "started_at"),
        Index("ix_agent_trace_assistant_message", "assistant_message_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    session_id = Column(CHAR(36), nullable=True, index=True)
    user_message_id = Column(CHAR(36), nullable=True, index=True)
    assistant_message_id = Column(CHAR(36), nullable=True, index=True)
    user_query = Column(Text, default="")
    status = Column(String(32), default="running", index=True)
    model = Column(String(128), default="")
    started_at = Column(DateTime, default=local_now)
    ended_at = Column(DateTime, nullable=True)
    trace_json = Column(JSON, nullable=True, default=None)

    steps = relationship(
        "AgentTraceStep",
        back_populates="trace",
        cascade="all, delete-orphan",
        order_by="AgentTraceStep.step_index",
    )


class AgentTraceStep(Base):
    __tablename__ = "agent_trace_step"
    __table_args__ = (
        Index("ix_agent_trace_step_trace_index", "trace_id", "step_index"),
        Index("ix_agent_trace_step_tool_call", "tool_call_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    trace_id = Column(CHAR(36), ForeignKey("agent_trace.id", ondelete="CASCADE"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False, default=0)
    step_type = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(128), nullable=True, default=None)
    tool_call_id = Column(String(128), nullable=True, default=None)
    input_json = Column(JSON, nullable=True, default=None)
    output_json = Column(JSON, nullable=True, default=None)
    status = Column(String(32), default="success", index=True)
    latency_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=local_now)
    ended_at = Column(DateTime, nullable=True)

    trace = relationship("AgentTrace", back_populates="steps")
    evidence_items = relationship(
        "AgentTraceEvidence",
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="AgentTraceEvidence.id",
    )


class AgentTraceEvidence(Base):
    __tablename__ = "agent_trace_evidence"
    __table_args__ = (
        Index("ix_agent_trace_evidence_chunk", "chunk_id"),
        Index("ix_agent_trace_evidence_source", "source_kind", "source_id"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    trace_step_id = Column(CHAR(36), ForeignKey("agent_trace_step.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(String(255), nullable=False, index=True)
    source_kind = Column(String(64), default="", index=True)
    source_id = Column(String(128), default="", index=True)
    chunk_id = Column(String(128), default="", index=True)
    parent_chunk_id = Column(String(128), default="")
    item_id = Column(String(128), default="", index=True)
    display_title = Column(String(512), default="")
    excerpt = Column(Text, default="")
    hit_reason = Column(Text, default="")
    score = Column(Float, nullable=True)
    retrieval_path_json = Column(JSON, nullable=True, default=None)
    metadata_json = Column(JSON, nullable=True, default=None)

    step = relationship("AgentTraceStep", back_populates="evidence_items")
```

- [ ] **Step 4: Register the models**

Modify `backend/app/models/__init__.py` by adding:

```python
from .agent_trace import AgentTrace, AgentTraceEvidence, AgentTraceStep
```

and add these names to `__all__`:

```python
"AgentTrace",
"AgentTraceStep",
"AgentTraceEvidence",
```

- [ ] **Step 5: Run the model test and verify it passes**

Run:

```powershell
pytest backend/tests/test_agent_trace_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add backend/app/models/agent_trace.py backend/app/models/__init__.py backend/tests/test_agent_trace_models.py
git commit -m "feat: add agent trace models"
```

## Task 2: Backend Trace Service and API

**Files:**
- Create: `backend/app/services/agent_trace.py`
- Create: `backend/app/api/traces.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_agent_trace_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_agent_trace_api.py`:

```python
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep


def _seed_trace(db_session):
    trace = AgentTrace(
        session_id="session-1",
        user_message_id="user-1",
        user_query="query",
        status="success",
        model="test-model",
    )
    db_session.add(trace)
    db_session.flush()
    step = AgentTraceStep(
        trace_id=trace.id,
        step_index=1,
        step_type="tool_result",
        tool_name="raw_document_search",
        tool_call_id="call_1",
        input_json={"query": "query"},
        output_json={"status": "success", "summary": "found"},
        status="success",
        latency_ms=10,
    )
    db_session.add(step)
    db_session.flush()
    db_session.add(
        AgentTraceEvidence(
            trace_step_id=step.id,
            evidence_id="document_chunk:chunk-1",
            source_kind="document_chunk",
            source_id="chunk-1",
            chunk_id="chunk-1",
            item_id="item-1",
            display_title="Doc",
            excerpt="excerpt",
            hit_reason="matched",
            score=1.0,
            retrieval_path_json=["raw_document_search"],
            metadata_json={"chunk_index": 1},
        )
    )
    db_session.commit()
    return trace.id


def test_bind_trace_message(client, db_session):
    trace_id = _seed_trace(db_session)

    resp = client.post(
        f"/api/v1/traces/{trace_id}/bind-message",
        json={"session_id": "session-1", "assistant_message_id": "assistant-1"},
    )

    assert resp.status_code == 200
    assert resp.json()["assistant_message_id"] == "assistant-1"
    db_session.expire_all()
    trace = db_session.query(AgentTrace).filter_by(id=trace_id).one()
    assert trace.assistant_message_id == "assistant-1"


def test_export_trace(client, db_session):
    trace_id = _seed_trace(db_session)

    resp = client.get(f"/api/v1/traces/{trace_id}/export")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["trace_id"] == trace_id
    assert payload["steps"][0]["tool_name"] == "raw_document_search"
    assert payload["steps"][0]["evidence_items"][0]["chunk_id"] == "chunk-1"
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```powershell
pytest backend/tests/test_agent_trace_api.py -q
```

Expected: FAIL because `/api/v1/traces/...` does not exist.

- [ ] **Step 3: Add trace service helpers**

Create `backend/app/services/agent_trace.py`:

```python
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import AgentTrace, AgentTraceStep


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
    trace.session_id = session_id
    trace.assistant_message_id = assistant_message_id
    if trace.status == "running":
        trace.status = "orphaned"
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


def _serialize_evidence(item) -> dict[str, Any]:
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
```

- [ ] **Step 4: Add trace API router**

Create `backend/app/api/traces.py`:

```python
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
    except LookupError:
        raise HTTPException(status_code=404, detail="trace not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
    except LookupError:
        raise HTTPException(status_code=404, detail="trace not found")
```

- [ ] **Step 5: Register trace router**

Modify `backend/app/api/__init__.py`:

```python
from .traces import router as traces_router
```

and include it in `register_routers`:

```python
api_prefix.include_router(traces_router)
```

- [ ] **Step 6: Run API tests and verify they pass**

Run:

```powershell
pytest backend/tests/test_agent_trace_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add backend/app/services/agent_trace.py backend/app/api/traces.py backend/app/api/__init__.py backend/tests/test_agent_trace_api.py
git commit -m "feat: add agent trace export api"
```

## Task 3: Evidence Schema Adapter

**Files:**
- Create: `engine/app/agent/tools/evidence.py`
- Test: `engine/tests/test_agent_evidence.py`

- [ ] **Step 1: Write failing adapter tests**

Create `engine/tests/test_agent_evidence.py`:

```python
from engine.app.agent.tools.evidence import normalize_evidence_items


def test_normalize_document_source_to_evidence_item():
    payload = {
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "chunk_id": "chunk-1",
                "parent_id": "parent-1",
                "item_id": "item-1",
                "display_title": "Doc",
                "snippet": "text",
                "score": 0.8,
                "chunk_type": "child",
                "chunk_index": 2,
            }
        ]
    }

    items = normalize_evidence_items("raw_document_search", payload)

    assert items == [
        {
            "evidence_id": "document_chunk:chunk-1",
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
            "chunk_id": "chunk-1",
            "parent_chunk_id": "parent-1",
            "item_id": "item-1",
            "display_title": "Doc",
            "excerpt": "text",
            "hit_reason": "matched raw_document_search result",
            "score": 0.8,
            "retrieval_path": ["raw_document_search"],
            "metadata": {"chunk_type": "child", "chunk_index": 2},
        }
    ]


def test_normalize_material_raw_evidence():
    payload = {
        "materials": [
            {
                "raw_evidence": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-2",
                        "chunk_id": "chunk-2",
                        "item_id": "item-2",
                        "display_title": "Doc 2",
                        "text": "material text",
                    }
                ]
            }
        ]
    }

    items = normalize_evidence_items("knowledge_material_search", payload)

    assert items[0]["evidence_id"] == "document_chunk:chunk-2"
    assert items[0]["excerpt"] == "material text"
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run:

```powershell
pytest engine/tests/test_agent_evidence.py -q
```

Expected: FAIL because `engine.app.agent.tools.evidence` does not exist.

- [ ] **Step 3: Add Evidence Schema adapter**

Create `engine/app/agent/tools/evidence.py`:

```python
from __future__ import annotations

from typing import Any


MAX_EXCERPT_CHARS = 1600


def normalize_evidence_items(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in payload.get("sources") or []:
        if isinstance(source, dict):
            candidates.append(source)
    for source in payload.get("evidence") or []:
        if isinstance(source, dict):
            candidates.append(source)
    for material in payload.get("materials") or []:
        if not isinstance(material, dict):
            continue
        for source in material.get("raw_evidence") or []:
            if isinstance(source, dict):
                candidates.append(source)
        source = material.get("source")
        if isinstance(source, dict):
            candidates.append(source)

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in candidates:
        item = _source_to_evidence(tool_name, source)
        if item is None:
            continue
        key = item["evidence_id"]
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def _source_to_evidence(tool_name: str, source: dict[str, Any]) -> dict[str, Any] | None:
    source_kind = str(source.get("source_kind") or source.get("ref_type") or "")
    chunk_id = _string_or_empty(source.get("chunk_id"))
    source_id = _string_or_empty(source.get("source_id") or source.get("ref_id") or chunk_id)
    item_id = _string_or_empty(source.get("item_id") or source.get("display_id"))
    if not source_kind and chunk_id:
        source_kind = "document_chunk"
    if not source_id and not chunk_id and not item_id:
        return None

    evidence_key = source_id or chunk_id or item_id
    evidence_kind = source_kind or "source"
    excerpt = _bounded_excerpt(
        source.get("snippet")
        or source.get("text")
        or source.get("evidence_span")
        or source.get("summary")
        or source.get("content")
        or ""
    )
    metadata = {
        key: value
        for key, value in {
            "chunk_type": source.get("chunk_type"),
            "chunk_index": source.get("chunk_index"),
            "display_type": source.get("display_type"),
            "display_id": source.get("display_id"),
        }.items()
        if value is not None
    }
    return {
        "evidence_id": f"{evidence_kind}:{evidence_key}",
        "source_kind": evidence_kind,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "parent_chunk_id": _string_or_empty(source.get("parent_chunk_id") or source.get("parent_id")),
        "item_id": item_id,
        "display_title": _string_or_empty(source.get("display_title") or source.get("doc_name") or source.get("title")),
        "excerpt": excerpt,
        "hit_reason": _string_or_empty(source.get("hit_reason")) or f"matched {tool_name} result",
        "score": _number_or_none(source.get("score") or source.get("raw_score")),
        "retrieval_path": [tool_name],
        "metadata": metadata,
    }


def _string_or_empty(value: Any) -> str:
    return str(value) if value is not None else ""


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_excerpt(value: Any) -> str:
    text = str(value or "")
    return text[:MAX_EXCERPT_CHARS]
```

- [ ] **Step 4: Run adapter tests and verify they pass**

Run:

```powershell
pytest engine/tests/test_agent_evidence.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add engine/app/agent/tools/evidence.py engine/tests/test_agent_evidence.py
git commit -m "feat: normalize agent evidence items"
```

## Task 4: Add Evidence Items to Knowledge Tool Payloads

**Files:**
- Modify: `engine/app/agent/tools/knowledge.py`
- Modify: `engine/app/agent/tools/knowledge_governance.py`
- Test: `engine/tests/test_agent_tool_evidence_payloads.py`

- [ ] **Step 1: Add failing tests for tool payload evidence**

Create `engine/tests/test_agent_tool_evidence_payloads.py`:

```python
import json

from engine.app.agent.tools.base import ToolContext
from engine.app.agent.tools.evidence import normalize_evidence_items
from engine.app.agent.tools.knowledge import build as build_knowledge_search


class FakeRagResult:
    status = "sufficient"
    summary = "found"
    missing = []
    clarify = None
    iterations = 1
    sources = [
        {
            "source_kind": "document_chunk",
            "source_id": "c1",
            "chunk_id": "c1",
            "item_id": "i1",
            "display_title": "Doc",
            "text": "source text",
            "score": 1.0,
            "chunk_type": "child",
            "chunk_index": 2,
        }
    ]
    evidence = []


class FakeRagRunner:
    def run(self, query):
        return FakeRagResult()


def test_knowledge_search_payload_includes_evidence_items():
    tool = build_knowledge_search(ToolContext(rag_runner=FakeRagRunner()))
    payload = json.loads(tool.invoke({"query": "q"}))

    assert payload["evidence_items"][0]["evidence_id"] == "document_chunk:c1"
    assert payload["evidence_items"][0]["chunk_id"] == "c1"
    assert payload["evidence_items"][0]["excerpt"] == "source text"


def test_payload_json_with_evidence_items_is_serializable():
    payload = {
        "status": "sufficient",
        "summary": "found",
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "chunk_id": "chunk-1",
                "item_id": "item-1",
                "display_title": "Doc",
                "snippet": "text",
                "score": 1.0,
            }
        ],
    }

    payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)

    serialized = json.loads(json.dumps(payload, ensure_ascii=False))
    assert serialized["evidence_items"][0]["chunk_id"] == "chunk-1"
```

- [ ] **Step 2: Run the tool tests and verify they fail**

Run:

```powershell
pytest engine/tests/test_agent_tool_evidence_payloads.py -q
```

Expected: FAIL on missing `evidence_items` for `knowledge_search`.

- [ ] **Step 3: Add evidence adapter imports**

Modify `engine/app/agent/tools/knowledge.py`:

```python
from engine.app.agent.tools.evidence import normalize_evidence_items
```

Modify `engine/app/agent/tools/knowledge_governance.py`:

```python
from engine.app.agent.tools.evidence import normalize_evidence_items
```

- [ ] **Step 4: Add evidence items in `knowledge_search`**

In `engine/app/agent/tools/knowledge.py`, after `payload` is created and before `return json.dumps(...)`, add:

```python
payload["evidence_items"] = normalize_evidence_items(KEY, payload)
```

Also add `evidence_items: []` to the "not configured" payload.

- [ ] **Step 5: Add evidence items in governance tools**

In each return payload in `engine/app/agent/tools/knowledge_governance.py`, build the payload in a variable before dumping. For `knowledge_topic_search`, use:

```python
payload = {
    "status": _result_status(topics, knowledge_results),
    "summary": f"Found {len(topics)} CKP topics and {len(knowledge_results)} synthesized knowledge items.",
    "query_terms": terms,
    "topics": topics,
    "synthesized_knowledge": knowledge_results,
    "sources": sources,
}
payload["evidence_items"] = normalize_evidence_items("knowledge_topic_search", payload)
return json.dumps(payload, ensure_ascii=False)
```

For `knowledge_evidence_search`, use:

```python
payload = {
    "status": _result_status(evidence),
    "summary": f"Found {len(evidence)} PKU evidence items across governed knowledge sources.",
    "query_terms": terms,
    "evidence": evidence,
    "sources": sources,
}
payload["evidence_items"] = normalize_evidence_items("knowledge_evidence_search", payload)
return json.dumps(payload, ensure_ascii=False)
```

For `knowledge_material_search`, use:

```python
payload = {
    "status": _result_status(materials),
    "summary": f"Found {len(materials)} source materials through CKP/PKU backtracking.",
    "query_terms": terms,
    "intent": intent,
    "materials": materials,
    "sources": sources,
}
payload["evidence_items"] = normalize_evidence_items("knowledge_material_search", payload)
return json.dumps(payload, ensure_ascii=False)
```

For `_raw_document_payload`, add:

```python
payload = {
    "status": getattr(result, "status", "insufficient"),
    "summary": getattr(result, "summary", ""),
    "missing": getattr(result, "missing", []),
    "clarify": getattr(result, "clarify", None),
    "sources": normalized_sources,
    "evidence": getattr(result, "evidence", []),
}
payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)
return payload
```

For `_raw_chunk_payload_from_query`, add `evidence_items` before returning:

```python
payload = {
    "status": "sufficient",
    "summary": "Found the requested raw document chunk by source_id.",
    "sources": [source],
    "evidence": [{**source}],
    "missing": [],
}
payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)
return payload
```

For every error or not-configured payload in this file, include:

```python
"evidence_items": []
```

- [ ] **Step 6: Run tool tests and verify they pass**

Run:

```powershell
pytest engine/tests/test_agent_evidence.py engine/tests/test_agent_tool_evidence_payloads.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
git add engine/app/agent/tools/knowledge.py engine/app/agent/tools/knowledge_governance.py engine/tests/test_agent_tool_evidence_payloads.py
git commit -m "feat: include evidence items in knowledge tools"
```

## Task 5: Engine Trace Recorder

**Files:**
- Create: `engine/app/agent/trace.py`
- Test: `engine/tests/test_agent_trace_recorder.py`

- [ ] **Step 1: Write failing recorder tests**

Create `engine/tests/test_agent_trace_recorder.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
from engine.app.agent.trace import AgentTraceRecorder


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_trace_recorder_records_step_and_evidence():
    Session = _session_factory()
    recorder = AgentTraceRecorder(
        session_factory=Session,
        session_id="session-1",
        user_message_id="user-1",
        user_query="query",
        model="test-model",
    )

    trace_id = recorder.start()
    recorder.record_step(
        step_type="tool_result",
        tool_name="raw_document_search",
        tool_call_id="call_1",
        input_json={"query": "query"},
        output_json={"status": "success"},
        status="success",
        latency_ms=5,
        evidence_items=[
            {
                "evidence_id": "document_chunk:chunk-1",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "chunk_id": "chunk-1",
                "parent_chunk_id": "",
                "item_id": "item-1",
                "display_title": "Doc",
                "excerpt": "excerpt",
                "hit_reason": "matched",
                "score": 1.0,
                "retrieval_path": ["raw_document_search"],
                "metadata": {"chunk_index": 1},
            }
        ],
    )
    recorder.finish("success")

    db = Session()
    try:
        trace = db.query(AgentTrace).filter_by(id=trace_id).one()
        assert trace.status == "success"
        assert db.query(AgentTraceStep).count() == 1
        assert db.query(AgentTraceEvidence).one().chunk_id == "chunk-1"
    finally:
        db.close()
```

- [ ] **Step 2: Run recorder tests and verify they fail**

Run:

```powershell
pytest engine/tests/test_agent_trace_recorder.py -q
```

Expected: FAIL because `engine.app.agent.trace` does not exist.

- [ ] **Step 3: Implement resilient trace recorder**

Create `engine/app/agent/trace.py`:

```python
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
from backend.app.utils.time import local_now
from engine.app.config import settings
from engine.app.observability import logger, quoted


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class AgentTraceRecorder:
    def __init__(
        self,
        *,
        session_id: str | None,
        user_message_id: str | None,
        user_query: str,
        model: str,
        session_factory: Callable[[], Any] = _Session,
    ) -> None:
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.user_query = user_query
        self.model = model
        self.session_factory = session_factory
        self.trace_id: str | None = None
        self.step_index = 0
        self.disabled = False

    def start(self) -> str | None:
        if self.disabled:
            return self.trace_id
        db = self.session_factory()
        try:
            trace = AgentTrace(
                session_id=self.session_id,
                user_message_id=self.user_message_id,
                user_query=self.user_query,
                status="running",
                model=self.model,
            )
            db.add(trace)
            db.commit()
            db.refresh(trace)
            self.trace_id = trace.id
            return self.trace_id
        except Exception as exc:
            self.disabled = True
            logger.warning("[agent.trace] start_failed error=%s", quoted(str(exc), limit=200))
            return None
        finally:
            db.close()

    def record_step(
        self,
        *,
        step_type: str,
        input_json: dict[str, Any] | None = None,
        output_json: dict[str, Any] | None = None,
        status: str = "success",
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        latency_ms: int | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> str | None:
        if self.disabled or not self.trace_id:
            return None
        self.step_index += 1
        db = self.session_factory()
        try:
            now = local_now()
            step = AgentTraceStep(
                trace_id=self.trace_id,
                step_index=self.step_index,
                step_type=step_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                input_json=input_json,
                output_json=output_json,
                status=status,
                latency_ms=latency_ms,
                started_at=now,
                ended_at=now,
            )
            db.add(step)
            db.flush()
            for item in evidence_items or []:
                db.add(_evidence_row(step.id, item))
            db.commit()
            db.refresh(step)
            return step.id
        except Exception as exc:
            db.rollback()
            self.disabled = True
            logger.warning("[agent.trace] record_step_failed type=%s error=%s", step_type, quoted(str(exc), limit=200))
            return None
        finally:
            db.close()

    def finish(self, status: str) -> None:
        if self.disabled or not self.trace_id:
            return
        db = self.session_factory()
        try:
            trace = db.query(AgentTrace).filter(AgentTrace.id == self.trace_id).first()
            if trace is not None:
                trace.status = status
                trace.ended_at = local_now()
                db.commit()
        except Exception as exc:
            db.rollback()
            self.disabled = True
            logger.warning("[agent.trace] finish_failed error=%s", quoted(str(exc), limit=200))
        finally:
            db.close()


def _evidence_row(step_id: str, item: dict[str, Any]) -> AgentTraceEvidence:
    return AgentTraceEvidence(
        trace_step_id=step_id,
        evidence_id=str(item.get("evidence_id") or ""),
        source_kind=str(item.get("source_kind") or ""),
        source_id=str(item.get("source_id") or ""),
        chunk_id=str(item.get("chunk_id") or ""),
        parent_chunk_id=str(item.get("parent_chunk_id") or ""),
        item_id=str(item.get("item_id") or ""),
        display_title=str(item.get("display_title") or ""),
        excerpt=str(item.get("excerpt") or ""),
        hit_reason=str(item.get("hit_reason") or ""),
        score=item.get("score"),
        retrieval_path_json=item.get("retrieval_path") or [],
        metadata_json=item.get("metadata") or {},
    )
```

- [ ] **Step 4: Run recorder tests and verify they pass**

Run:

```powershell
pytest engine/tests/test_agent_trace_recorder.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```powershell
git add engine/app/agent/trace.py engine/tests/test_agent_trace_recorder.py
git commit -m "feat: add engine agent trace recorder"
```

## Task 6: Runner Trace Recording and Stream Events

**Files:**
- Modify: `engine/app/agent/events.py`
- Modify: `engine/app/api/chat.py`
- Modify: `engine/app/chat/answer.py`
- Modify: `engine/app/agent/runner.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Add failing runner tests for trace event and evidence passthrough**

Append to `engine/tests/test_agent_runner.py`:

```python
class FakeRecorder:
    def __init__(self):
        self.trace_id = "trace-1"
        self.steps = []
        self.finished = []

    def record_step(self, **kwargs):
        self.steps.append(kwargs)
        return f"step-{len(self.steps)}"

    def finish(self, status):
        self.finished.append(status)


class FakeEvidenceTool:
    name = "raw_document_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "found",
                "evidence_items": [
                    {
                        "evidence_id": "document_chunk:c1",
                        "source_kind": "document_chunk",
                        "source_id": "c1",
                        "chunk_id": "c1",
                        "excerpt": "text",
                    }
                ],
            }
        )


class FakeEvidenceModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "raw_document_search",
                        "args": {"query": "q"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer")


def test_runner_records_trace_steps_and_emits_evidence_items():
    recorder = FakeRecorder()
    runner = LangChainAgentRunner(model=FakeEvidenceModel(), tools=[FakeEvidenceTool()])

    lines = list(runner.stream("How?", [{"role": "user", "content": "previous"}], trace_recorder=recorder))

    tool_result = next(json.loads(line) for line in lines if json.loads(line)["type"] == "tool_result")
    assert tool_result["data"]["evidence_items"][0]["chunk_id"] == "c1"
    assert [step["step_type"] for step in recorder.steps] == [
        "model_invoke",
        "model_response",
        "tool_call",
        "tool_result",
        "model_invoke",
        "model_response",
        "final_answer",
    ]
    assert recorder.finished == ["success"]
```

- [ ] **Step 2: Run runner tests and verify they fail**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_runner_records_trace_steps_and_emits_evidence_items -q
```

Expected: FAIL because `stream()` has no `trace_recorder` argument and `tool_result_event` does not include `evidence_items`.

- [ ] **Step 3: Add trace event and evidence event field**

Modify `engine/app/agent/events.py`:

```python
def trace_event(trace_id: str) -> str:
    return ndjson_event("trace", {"trace_id": trace_id})
```

Update `tool_result_event` signature:

```python
def tool_result_event(
    tool: str,
    status: str,
    summary: str,
    query: str = "",
    stats: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    trace_steps: list[dict[str, Any]] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
) -> str:
```

Before returning, add:

```python
if evidence_items:
    data["evidence_items"] = evidence_items
```

- [ ] **Step 4: Update runner stream signature and record model steps**

Modify `engine/app/agent/runner.py`.

Import type only if desired:

```python
from .trace import AgentTraceRecorder
```

Change stream signature:

```python
def stream(
    self,
    query: str,
    history: list[dict[str, Any]] | None = None,
    trace_recorder: Any | None = None,
):
```

Before `response = model.invoke(messages)`, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="model_invoke",
        input_json={
            "iteration": iteration,
            "message_count": len(messages),
            "message_roles": _message_role_summary(messages),
        },
        status="success",
    )
```

After `tool_calls = ...`, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="model_response",
        output_json={
            "iteration": iteration,
            "tool_calls": [
                {
                    "id": str(_call_value(call, "id", "")),
                    "name": str(_call_value(call, "name", "")),
                    "args": _call_value(call, "args", {}) or {},
                }
                for call in tool_calls
            ],
            "content_preview": _message_content(response)[:1000],
        },
        status="success",
    )
```

When no tool calls and final text is known, before `done_event()`, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="final_answer",
        output_json={"content": text},
        status="success",
    )
    trace_recorder.finish("success")
```

In the max-iterations branch, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="error",
        output_json={"message": "Agent reached the maximum tool iteration limit."},
        status="error",
    )
    trace_recorder.finish("error")
```

In the exception handler, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="error",
        output_json={"message": str(exc)},
        status="error",
    )
    trace_recorder.finish("error")
```

- [ ] **Step 5: Record tool call and tool result steps**

Inside the tool call loop, after logging/yielding `tool_call_event`, add:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="tool_call",
        tool_name=name,
        tool_call_id=tool_call_id,
        input_json={"args": args, "query": query_arg},
        status="success",
    )
```

After payload parsing and trace_steps extraction, add:

```python
evidence_items = payload.get("evidence_items") or []
if not isinstance(evidence_items, list):
    evidence_items = []
```

Pass it to `tool_result_event`:

```python
yield tool_result_event(
    tool=name,
    status=status,
    summary=summary,
    query=query_arg,
    stats=stats,
    latency_ms=latency_ms,
    trace_steps=trace_steps,
    evidence_items=evidence_items,
)
```

Record the result step:

```python
if trace_recorder is not None:
    trace_recorder.record_step(
        step_type="tool_result",
        tool_name=name,
        tool_call_id=tool_call_id,
        input_json={"args": args, "query": query_arg},
        output_json={
            "status": status,
            "summary": summary,
            "stats": stats,
            "trace_steps": trace_steps,
        },
        status=status,
        latency_ms=latency_ms,
        evidence_items=evidence_items,
    )
```

- [ ] **Step 6: Create trace in answer stream and emit trace id**

Modify `engine/app/api/chat.py` `ChatRequest`:

```python
session_id: Optional[str] = None
user_message_id: Optional[str] = None
```

Pass fields into `answer_stream(...)`.

Modify `engine/app/chat/answer.py` imports:

```python
from ..agent.events import error_event, trace_event
from ..agent.trace import AgentTraceRecorder
```

Update `answer_stream` signature:

```python
def answer_stream(
    query: str,
    history: list[dict] | None = None,
    topic_id: str | None = None,
    source_types: list[str] | None = None,
    deep_search_enabled: bool = False,
    deep_search_depth: str = "standard",
    session_id: str | None = None,
    user_message_id: str | None = None,
):
```

After runner is built, create and emit trace:

```python
trace_recorder = AgentTraceRecorder(
    session_id=session_id,
    user_message_id=user_message_id,
    user_query=query,
    model=settings.LLM_MODEL,
)
trace_id = trace_recorder.start()
if trace_id:
    yield trace_event(trace_id)
yield from runner.stream(query, history, trace_recorder=trace_recorder)
```

- [ ] **Step 7: Run runner tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

Run:

```powershell
git add engine/app/agent/events.py engine/app/api/chat.py engine/app/chat/answer.py engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "feat: record agent trace during chat runs"
```

## Task 7: Frontend Trace Persistence and Binding

**Files:**
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/app/chatStore.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/tests/chat-trace-stream.test.mjs`

- [ ] **Step 1: Add trace types and API methods**

Modify `frontend/src/app/api.ts` with types:

```ts
export interface TraceBindRequest {
  session_id: string
  assistant_message_id: string
}

export interface TraceBindResponse {
  trace_id: string
  session_id: string
  assistant_message_id: string
  status: string
}
```

Add methods:

```ts
export const traceApi = {
  bindMessage: (traceId: string, data: TraceBindRequest) =>
    request<TraceBindResponse>(`/traces/${traceId}/bind-message`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  exportTrace: (traceId: string) =>
    request<Record<string, unknown>>(`/traces/${traceId}/export`),
}
```

- [ ] **Step 2: Add trace and evidence state types**

Modify `frontend/src/app/chatStore.ts`.

Add:

```ts
export interface EvidenceItem {
  evidence_id: string
  source_kind?: string
  source_id?: string
  chunk_id?: string
  parent_chunk_id?: string | null
  item_id?: string
  display_title?: string
  excerpt?: string
  hit_reason?: string
  score?: number | null
  retrieval_path?: string[]
  metadata?: Record<string, unknown>
}
```

Extend `ToolRun`:

```ts
evidenceItems?: EvidenceItem[]
```

Extend `Message`:

```ts
traceId?: string
```

Extend `ToolRunPatch`:

```ts
evidenceItems?: EvidenceItem[]
```

Add normalizer:

```ts
function normalizeEvidenceItems(value: unknown): EvidenceItem[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      evidence_id: typeof item.evidence_id === 'string' ? item.evidence_id : '',
      source_kind: typeof item.source_kind === 'string' ? item.source_kind : undefined,
      source_id: typeof item.source_id === 'string' ? item.source_id : undefined,
      chunk_id: typeof item.chunk_id === 'string' ? item.chunk_id : undefined,
      parent_chunk_id: typeof item.parent_chunk_id === 'string' ? item.parent_chunk_id : null,
      item_id: typeof item.item_id === 'string' ? item.item_id : undefined,
      display_title: typeof item.display_title === 'string' ? item.display_title : undefined,
      excerpt: typeof item.excerpt === 'string' ? item.excerpt : undefined,
      hit_reason: typeof item.hit_reason === 'string' ? item.hit_reason : undefined,
      score: typeof item.score === 'number' ? item.score : null,
      retrieval_path: Array.isArray(item.retrieval_path)
        ? item.retrieval_path.filter((entry): entry is string => typeof entry === 'string')
        : undefined,
      metadata: typeof item.metadata === 'object' && item.metadata !== null
        ? item.metadata as Record<string, unknown>
        : undefined,
    }))
    .filter((item) => item.evidence_id)
  return items.length > 0 ? items : undefined
}
```

Use it in `normalizeToolRuns`:

```ts
evidenceItems: normalizeEvidenceItems(run.evidenceItems ?? run.evidence_items),
```

In `toMessages`, set:

```ts
traceId: typeof process?.trace_id === 'string' ? process.trace_id : undefined,
```

- [ ] **Step 3: Persist trace id in assistant process**

Modify `buildAssistantProcess` in `frontend/src/pages/ChatPage.tsx`:

```ts
function buildAssistantProcess(message: Message) {
  return {
    trace_id: message.traceId || null,
    agent_status: message.agentStatus || null,
    tool_runs: message.toolRuns || [],
    thinking_steps: message.thinkingSteps || [],
  }
}
```

- [ ] **Step 4: Add store action for trace ids**

Modify `frontend/src/app/chatStore.ts`.

Add to `ChatState`:

```ts
setLastTraceId: (traceId: string, sessionId?: string, messageId?: string) => void
```

Add implementation in the store:

```ts
setLastTraceId: (traceId, sessionId, messageId) =>
  set((s) =>
    updateMessagesForSession(s, sessionId, (messages) =>
      replaceMessage(messages, messageId, (last) => ({ ...last, traceId })),
    ),
  ),
```

- [ ] **Step 5: Handle trace and evidence stream events**

Modify imports:

```ts
import { knowledgeApi, chatApi, traceApi, type KnowledgeTopic } from '@/app/api'
```

Add a local variable near stream state:

```ts
let traceId: string | null = null
```

In `ChatPage`, select the store action:

```ts
const setLastTraceId = useChatStore((s) => s.setLastTraceId)
```

In `handleStreamLine`, before the `agent_status` branch, add:

```ts
if (msg.type === 'trace') {
  traceId = safeString(msg.data?.trace_id)
  if (traceId) {
    setLastTraceId(traceId, sessionId, assistantMessageId)
    if (assistantPersistedId) persistAssistantProcessSnapshot(sessionId, assistantPersistedId)
  }
}
```

In the `tool_result` branch, pass evidence:

```ts
evidenceItems: normalizeEvidenceItems(msg.data?.evidence_items),
```

Export `normalizeEvidenceItems` from `chatStore.ts` and import it in `ChatPage.tsx` with the other store helpers.

- [ ] **Step 6: Send session and user message ids to engine**

Find the call that streams `/chat/answer`. Include:

```ts
session_id: sessionId,
user_message_id: userMessageId,
```

in the request body sent to the engine.

- [ ] **Step 7: Bind trace after assistant persistence**

After the assistant message has been persisted and after stream completion, call:

```ts
if (traceId && assistantPersistedId) {
  traceApi.bindMessage(traceId, {
    session_id: sessionId,
    assistant_message_id: assistantPersistedId,
  }).catch(() => {})
}
```

Place it after the final assistant content/process snapshot is persisted, so a bind failure does not break chat.

- [ ] **Step 8: Add and run frontend trace tests**

Create `frontend/tests/chat-trace-stream.test.mjs` following the existing `.mjs` test style. The test should simulate an NDJSON stream containing:

```json
{"type":"trace","data":{"trace_id":"trace-1"}}
{"type":"tool_call","data":{"tool":"raw_document_search","query":"q"}}
{"type":"tool_result","data":{"tool":"raw_document_search","status":"success","summary":"found","evidence_items":[{"evidence_id":"document_chunk:c1","chunk_id":"c1","excerpt":"text"}]}}
{"type":"token","data":"answer"}
{"type":"done"}
```

Assert that the persisted assistant process includes:

```json
{
  "trace_id": "trace-1",
  "tool_runs": [
    {
      "tool": "raw_document_search",
      "evidenceItems": [
        {
          "evidence_id": "document_chunk:c1",
          "chunk_id": "c1"
        }
      ]
    }
  ]
}
```

Run:

```powershell
cd frontend
pnpm test
```

If the repo does not have a full test script, run the existing targeted tests shown in `frontend/tests`, for example:

```powershell
node frontend/tests/chat-session-stream-cache.test.mjs
node frontend/tests/chat-trace-stream.test.mjs
```

Expected: existing tests and the new trace stream test PASS.

- [ ] **Step 9: Commit Task 7**

Run:

```powershell
git add frontend/src/app/api.ts frontend/src/app/chatStore.ts frontend/src/pages/ChatPage.tsx frontend/tests
git commit -m "feat: persist chat trace ids in frontend"
```

## Task 8: Prompt Constraint and Regression Coverage

**Files:**
- Modify: `engine/app/agent/prompts.py`
- Test: `engine/tests/test_agent_runner.py` or `engine/tests/test_agent_tools.py`

- [ ] **Step 1: Add prompt constraint text**

Modify `engine/app/agent/prompts.py` in the agent system prompt where tool grounding rules are listed. Add this rule:

```text
- 当你引用 chunk_id、source_id、evidence_id 或任何证据标识时，只能使用本轮工具返回 JSON 中 `evidence_items` 里真实出现过的 id。
- 如果用户要求解释某个证据 id，但本轮 `evidence_items` 没有该 id，你必须明确说“本轮工具返回中没有这个 id，无法确认”，不能编造或补全 id。
- 如果工具返回了 `evidence_items`，优先基于其中的 `excerpt`、`chunk_id`、`source_id` 回答；不要只根据 summary 猜测。
```

- [ ] **Step 2: Add a regression test for evidence passthrough**

In `engine/tests/test_agent_runner.py`, extend the evidence test from Task 6 to assert the `ToolMessage` content contains `evidence_items`. Add to `FakeEvidenceModel.invoke` when `self.calls == 2`:

```python
tool_messages = [message for message in messages if getattr(message, "tool_call_id", None)]
assert tool_messages
payload = json.loads(tool_messages[-1].content)
assert payload["evidence_items"][0]["chunk_id"] == "c1"
```

This proves the model can see the evidence ids it is constrained to use.

- [ ] **Step 3: Run prompt and runner tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit Task 8**

Run:

```powershell
git add engine/app/agent/prompts.py engine/tests/test_agent_runner.py
git commit -m "feat: constrain answers to returned evidence ids"
```

## Task 9: End-to-End Verification

**Files:**
- Verify existing source and test files from Tasks 1 through 8.

- [ ] **Step 1: Run backend tests for trace features**

Run:

```powershell
pytest backend/tests/test_agent_trace_models.py backend/tests/test_agent_trace_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run engine tests for evidence and trace features**

Run:

```powershell
pytest engine/tests/test_agent_evidence.py engine/tests/test_agent_trace_recorder.py engine/tests/test_agent_runner.py engine/tests/test_agent_tools.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend tests**

Run:

```powershell
cd frontend
pnpm test
```

Expected: PASS, or if no `test` script exists, run the existing targeted `.mjs` tests and record the exact passing commands.

- [ ] **Step 4: Manual smoke test**

Start backend and frontend using the repo's normal development commands. Ask a no-tool casual question and a knowledge question that calls `raw_document_search`.

Verify in MySQL:

```sql
SELECT id, session_id, user_message_id, assistant_message_id, status
FROM agent_trace
ORDER BY started_at DESC
LIMIT 5;
```

Verify evidence:

```sql
SELECT e.evidence_id, e.chunk_id, LEFT(e.excerpt, 120) AS excerpt
FROM agent_trace_evidence e
JOIN agent_trace_step s ON s.id = e.trace_step_id
ORDER BY s.started_at DESC
LIMIT 10;
```

Verify export:

```powershell
curl http://localhost:5175/api/v1/traces/<trace-id>/export
```

Expected: JSON includes ordered steps and evidence nested under the producing `tool_result`.

- [ ] **Step 5: Final commit if verification changed files**

If verification required test fixes, commit them:

```powershell
git add backend/app backend/tests engine/app engine/tests frontend/src frontend/tests
git commit -m "test: verify agent trace evidence flow"
```

## Self-Review Notes

- Spec coverage: the plan covers trace tables, evidence schema, no-tool traces, bind/export APIs, failure handling hooks, frontend trace persistence, prompt constraints, and tests.
- Scope: this is one cohesive feature across backend, engine, and frontend. It is split into independently testable tasks.
- Known implementation caution: the frontend currently has existing uncommitted changes in this workspace. During execution, inspect `git status --short` before each task and avoid overwriting unrelated edits.
