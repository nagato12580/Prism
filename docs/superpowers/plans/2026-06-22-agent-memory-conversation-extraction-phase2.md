# Agent Memory Conversation Extraction Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build conversation-to-memory extraction so saved chat history can create reviewable memory drafts.

**Architecture:** Add a backend extraction service that owns prompt construction, LLM JSON parsing, candidate normalization, deduplication, and draft persistence. Expose manual extraction through the memory API and add a guarded best-effort chat hook behind an environment flag.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Pydantic, OpenAI-compatible chat completions, pytest.

---

## File Structure

### Backend

- Create `backend/app/prompts/memory_extraction.py`
  - Builds strict JSON extraction messages from `ChatMessage` rows.

- Create `backend/app/services/memory_extraction.py`
  - Parses LLM output.
  - Normalizes candidates.
  - Deduplicates against `MemoryStatement` and `MemoryDraft`.
  - Creates `MemorySource` and `MemoryDraft`.
  - Returns a result dataclass.

- Modify `backend/app/schemas/memory.py`
  - Add `MemoryExtractionRequest` and `MemoryExtractionOut`.

- Modify `backend/app/api/memories.py`
  - Add `POST /memories/extract/session/{session_id}`.

- Modify `backend/app/config.py`
  - Add `MEMORY_EXTRACTION_AUTO_ENABLED`.

- Modify `backend/app/api/chat.py`
  - After assistant messages are saved, optionally trigger extraction in a daemon thread.

- Create `backend/tests/test_memory_extraction_service.py`
  - Service unit tests.

- Create `backend/tests/test_memory_extraction_api.py`
  - Manual extraction endpoint and chat hook tests.

---

## Task 1: Add Prompt and Extraction Service

**Files:**
- Create: `backend/app/prompts/memory_extraction.py`
- Create: `backend/app/services/memory_extraction.py`
- Create: `backend/tests/test_memory_extraction_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_memory_extraction_service.py`:

```python
import json

from backend.app.models import ChatMessage, ChatSession, MemoryDraft, MemorySource, MemoryStatement
from backend.app.services import memory_extraction as svc


def test_build_memory_extraction_messages_include_recent_chat_context(db_session):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    db_session.add_all(
        [
            ChatMessage(session_id=session.id, role="user", content="我希望 agent 记住我关心什么话题。"),
            ChatMessage(session_id=session.id, role="assistant", content="我们会先做 Memory Inbox。"),
        ]
    )
    db_session.commit()

    messages = svc.load_session_messages(db_session, session.id, limit=10)
    prompt_messages = svc.build_memory_extraction_messages(messages)
    joined = json.dumps(prompt_messages, ensure_ascii=False)

    assert "candidates" in joined
    assert "evidence_message_id" in joined
    assert "我希望 agent 记住我关心什么话题" in joined
    assert "Memory Inbox" in joined


def test_parse_memory_candidates_accepts_fenced_json():
    raw = """```json
    {
      "candidates": [
        {
          "content": "用户希望 agent 记住长期讨论的问题。",
          "statement_type": "preference",
          "temporal_type": "stable",
          "confidence": 0.88,
          "importance": 0.8,
          "risk_level": "medium",
          "decision_hint": "review",
          "evidence_message_id": "msg-1"
        }
      ]
    }
    ```"""

    candidates = svc.parse_memory_candidates(raw)

    assert len(candidates) == 1
    assert candidates[0].content == "用户希望 agent 记住长期讨论的问题。"
    assert candidates[0].statement_type == "preference"
    assert candidates[0].evidence_message_id == "msg-1"


def test_parse_memory_candidates_skips_invalid_candidates():
    raw = {
        "candidates": [
            {"content": "", "statement_type": "preference"},
            {"content": "有效记忆", "confidence": 1.4, "importance": -1},
            {"content": "低置信度记忆", "confidence": 0.2},
        ]
    }

    candidates = svc.parse_memory_candidates(json.dumps(raw, ensure_ascii=False))

    assert len(candidates) == 1
    assert candidates[0].content == "有效记忆"
    assert candidates[0].confidence == 1.0
    assert candidates[0].importance == 0.0


def test_extract_session_memories_creates_traceable_drafts(db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        session_id=session.id,
        role="user",
        content="我希望 agent 记住我正在设计长期记忆系统。",
    )
    db_session.add(message)
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": "用户正在设计长期记忆系统。",
                        "statement_type": "current_focus",
                        "temporal_type": "current",
                        "confidence": 0.9,
                        "importance": 0.85,
                        "risk_level": "medium",
                        "decision_hint": "review",
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    result = svc.extract_session_memories(db_session, session.id)

    assert result.messages_scanned == 1
    assert result.candidates_found == 1
    assert result.drafts_created == 1
    draft = db_session.query(MemoryDraft).one()
    source = db_session.query(MemorySource).one()
    assert draft.payload["content"] == "用户正在设计长期记忆系统。"
    assert draft.payload["statement_type"] == "current_focus"
    assert draft.source_id == source.id
    assert source.source_type == "chat_message"
    assert source.session_id == session.id
    assert source.message_id == message.id


def test_extract_session_memories_skips_duplicate_drafts_and_statements(db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(session_id=session.id, role="user", content="我偏好审核台优先。")
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id=message.id,
        session_id=session.id,
        message_id=message.id,
        span_text=message.content,
    )
    existing = MemoryStatement(
        user_id="default-user",
        content="用户偏好审核台优先。",
        statement_type="preference",
        status="confirmed",
        source=source,
    )
    db_session.add_all([message, source, existing])
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": " 用户偏好审核台优先。 ",
                        "statement_type": "preference",
                        "confidence": 0.9,
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    result = svc.extract_session_memories(db_session, session.id)

    assert result.drafts_created == 0
    assert result.candidates_skipped == 1
    assert db_session.query(MemoryDraft).count() == 0
```

- [ ] **Step 2: Run service tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_service.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `backend.app.services.memory_extraction`.

- [ ] **Step 3: Implement prompt module**

Create `backend/app/prompts/memory_extraction.py`:

```python
from __future__ import annotations

from typing import Iterable

from backend.app.models.chat import ChatMessage


SYSTEM_PROMPT = """你是 Prism 的长期记忆抽取器。
只从对话中抽取对未来有帮助、可长期保存的用户记忆。

应该抽取：
- 用户明确偏好、长期目标、稳定约束
- 当前持续关注的项目或探索主题
- 已做出的产品/技术决策
- 对 agent 行为的长期要求

不要抽取：
- 临时命令、寒暄、一次性调试步骤
- 密码、token、密钥或敏感凭据
- 助手内部实现细节，除非它表达了用户认可的长期项目上下文
- 没有长期价值的普通问答内容

只输出严格 JSON，不要 Markdown，不要解释。
JSON schema:
{
  "candidates": [
    {
      "content": "一句完整、可独立理解的中文记忆",
      "statement_type": "preference|goal|constraint|decision|current_focus|project_context|interest|fact",
      "temporal_type": "stable|current|episodic",
      "confidence": 0.0,
      "importance": 0.0,
      "risk_level": "low|medium|high",
      "decision_hint": "review|auto_confirm_candidate|confirm_supersede",
      "evidence_message_id": "原始消息 id"
    }
  ]
}
"""


def build_memory_extraction_messages(messages: Iterable[ChatMessage]) -> list[dict[str, str]]:
    transcript_lines: list[str] = []
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        transcript_lines.append(
            f"[message_id={message.id}] role={message.role}\\n{content[:1600]}"
        )
    transcript = "\\n\\n".join(transcript_lines) or "No conversation content."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"请从以下会话中抽取长期记忆候选：\\n\\n{transcript}",
        },
    ]
```

- [ ] **Step 4: Implement extraction service**

Create `backend/app/services/memory_extraction.py` with:

```python
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
    fenced = re.search(r"```(?:json)?\\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
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
    return re.sub(r"\\s+", " ", (content or "").strip()).lower()


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
```

- [ ] **Step 5: Run service tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add backend/app/prompts/memory_extraction.py backend/app/services/memory_extraction.py backend/tests/test_memory_extraction_service.py
git commit -m "feat: add conversation memory extraction service"
```

---

## Task 2: Add Manual Extraction API

**Files:**
- Modify: `backend/app/schemas/memory.py`
- Modify: `backend/app/api/memories.py`
- Create: `backend/tests/test_memory_extraction_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_memory_extraction_api.py`:

```python
import json

from backend.app.models import ChatMessage, ChatSession, MemoryDraft
from backend.app.services import memory_extraction as svc


def test_extract_session_endpoint_creates_memory_drafts(client, db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory extraction")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        session_id=session.id,
        role="user",
        content="我希望 Prism 记住我关注长期记忆系统设计。",
    )
    db_session.add(message)
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": "用户关注长期记忆系统设计。",
                        "statement_type": "current_focus",
                        "temporal_type": "current",
                        "confidence": 0.9,
                        "importance": 0.8,
                        "risk_level": "medium",
                        "decision_hint": "review",
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    response = client.post(f"/api/v1/memories/extract/session/{session.id}", json={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session.id
    assert payload["messages_scanned"] == 1
    assert payload["candidates_found"] == 1
    assert payload["drafts_created"] == 1
    assert payload["candidates_skipped"] == 0
    assert payload["drafts"][0]["payload"]["content"] == "用户关注长期记忆系统设计。"
    assert db_session.query(MemoryDraft).count() == 1


def test_extract_session_endpoint_returns_404_for_missing_session(client):
    response = client.post("/api/v1/memories/extract/session/missing-session", json={"limit": 10})

    assert response.status_code == 404
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_api.py -q
```

Expected: FAIL with 404 because endpoint does not exist.

- [ ] **Step 3: Add schemas**

Append to `backend/app/schemas/memory.py`:

```python
class MemoryExtractionRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class MemoryExtractionOut(BaseModel):
    session_id: str
    messages_scanned: int
    candidates_found: int
    drafts_created: int
    candidates_skipped: int
    draft_ids: list[str]
    drafts: list[MemoryDraftOut]
```

- [ ] **Step 4: Add manual endpoint**

Modify imports in `backend/app/api/memories.py`:

```python
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
```

Add endpoint before `/drafts/{draft_id}` routes:

```python
@router.post("/extract/session/{session_id}", response_model=MemoryExtractionOut)
def extract_memory_from_session(
    session_id: str,
    payload: MemoryExtractionRequest | None = None,
    db: Session = Depends(get_db),
):
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
```

- [ ] **Step 5: Run API tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_api.py -q
```

Expected: PASS.

- [ ] **Step 6: Run Phase 1 + Phase 2 backend tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py backend/tests/test_memory_phase1_api.py backend/tests/test_memories_api.py backend/tests/test_memory_extraction_service.py backend/tests/test_memory_extraction_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add backend/app/schemas/memory.py backend/app/api/memories.py backend/tests/test_memory_extraction_api.py
git commit -m "feat: add manual conversation memory extraction api"
```

---

## Task 3: Add Optional Automatic Extraction Hook

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/tests/test_memory_extraction_api.py`

- [ ] **Step 1: Add failing chat hook tests**

Append to `backend/tests/test_memory_extraction_api.py`:

```python
def test_add_assistant_message_triggers_auto_memory_extraction_when_enabled(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    calls = []

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api, "SessionLocal", lambda: db_session)

    def fake_extract(db, session_id, limit=20):
        calls.append((session_id, limit))

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"role": "assistant", "content": "好的，我们会记住这个长期偏好。"},
    )

    assert response.status_code == 200
    assert calls == [(session.id, 20)]


def test_add_assistant_message_ignores_auto_memory_extraction_failures(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api, "SessionLocal", lambda: db_session)

    def fake_extract(db, session_id, limit=20):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"role": "assistant", "content": "这条消息仍然应该保存。"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "这条消息仍然应该保存。"
```

- [ ] **Step 2: Run hook tests to verify they fail**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_api.py::test_add_assistant_message_triggers_auto_memory_extraction_when_enabled backend/tests/test_memory_extraction_api.py::test_add_assistant_message_ignores_auto_memory_extraction_failures -q
```

Expected: FAIL because config and hook do not exist.

- [ ] **Step 3: Add config flag**

Modify `backend/app/config.py`:

```python
    MEMORY_EXTRACTION_AUTO_ENABLED: bool = os.getenv("MEMORY_EXTRACTION_AUTO_ENABLED", "0") == "1"
```

- [ ] **Step 4: Add chat hook**

Modify imports in `backend/app/api/chat.py`:

```python
import threading

from ..database import get_db, SessionLocal
from ..services.memory_extraction import extract_session_memories
```

Replace current `from ..database import get_db` import with the new one.

Add helper near the router:

```python
def _run_memory_extraction_best_effort(session_id: str, limit: int = 20):
    db = SessionLocal()
    try:
        extract_session_memories(db, session_id=session_id, limit=limit)
    except Exception as exc:
        print(f"[memory] conversation extraction failed for session {session_id}: {exc}")
    finally:
        db.close()


def _maybe_trigger_memory_extraction(session_id: str, role: str):
    if role != "assistant" or not settings.MEMORY_EXTRACTION_AUTO_ENABLED:
        return
    thread = threading.Thread(
        target=_run_memory_extraction_best_effort,
        args=(session_id,),
        daemon=True,
    )
    thread.start()
```

Call it after commit/refresh in `add_message`:

```python
    db.commit()
    db.refresh(msg)
    _maybe_trigger_memory_extraction(session_id, payload.role)
    return msg
```

- [ ] **Step 5: Make tests synchronous without changing production behavior**

In tests, monkeypatch `threading.Thread` if needed:

```python
class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)

monkeypatch.setattr(chat_api.threading, "Thread", ImmediateThread)
```

Add this patch to both hook tests before the request.

- [ ] **Step 6: Run hook tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_extraction_api.py::test_add_assistant_message_triggers_auto_memory_extraction_when_enabled backend/tests/test_memory_extraction_api.py::test_add_assistant_message_ignores_auto_memory_extraction_failures -q
```

Expected: PASS.

- [ ] **Step 7: Run backend memory test set**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py backend/tests/test_memory_phase1_api.py backend/tests/test_memories_api.py backend/tests/test_memory_extraction_service.py backend/tests/test_memory_extraction_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add backend/app/config.py backend/app/api/chat.py backend/tests/test_memory_extraction_api.py
git commit -m "feat: optionally extract memories after chat replies"
```

---

## Task 4: Final Verification and Review

**Files:**
- Test only unless review requires fixes.

- [ ] **Step 1: Run backend memory tests**

Run:

```powershell
python -m pytest backend/tests/test_memory_phase1_models.py backend/tests/test_memory_phase1_api.py backend/tests/test_memories_api.py backend/tests/test_memory_extraction_service.py backend/tests/test_memory_extraction_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend memory static tests**

Run:

```powershell
cd frontend
node .\tests\memory-inbox-api.test.mjs
node .\tests\memory-inbox-page.test.mjs
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
pnpm.cmd build
```

Expected: build exits 0. Vite chunk-size warning is acceptable.

- [ ] **Step 4: Dispatch final code review**

Ask reviewer to inspect:

- `backend/app/prompts/memory_extraction.py`
- `backend/app/services/memory_extraction.py`
- `backend/app/api/memories.py`
- `backend/app/api/chat.py`
- `backend/app/schemas/memory.py`
- `backend/app/config.py`
- `backend/tests/test_memory_extraction_service.py`
- `backend/tests/test_memory_extraction_api.py`

Review focus:

- No chat persistence regression.
- Manual extraction creates traceable drafts.
- Automatic extraction cannot break chat.
- LLM failures are handled correctly.
- Deduplication prevents obvious duplicate drafts.

- [ ] **Step 5: Fix review findings**

If reviewer reports blocking or important findings, fix with tests and rerun Step 1.

- [ ] **Step 6: Commit review fixes if needed**

Run:

```powershell
git add backend/app/prompts/memory_extraction.py backend/app/services/memory_extraction.py backend/app/api/memories.py backend/app/api/chat.py backend/app/schemas/memory.py backend/app/config.py backend/tests/test_memory_extraction_service.py backend/tests/test_memory_extraction_api.py
git commit -m "fix: harden conversation memory extraction"
```

Only commit if files changed.

---

## Self-Review Checklist

- Manual extraction endpoint exists and returns draft details.
- Extraction service keeps LLM/parsing/dedup/persistence logic out of route handlers.
- Created drafts keep `memory_source` traceability to `chat_message`.
- Duplicate confirmed statements and duplicate drafts are skipped.
- Automatic extraction is off by default.
- Automatic extraction failures do not fail `add_message`.
- Tests do not call real LLMs.
- Frontend Memory Inbox can show drafts created by extraction without changes.
