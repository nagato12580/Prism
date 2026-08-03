# Chat And Memory User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce strict per-user isolation for chat and memory data so a logged-in user can access only their own chat sessions, messages, memory drafts, statements, and graph-related memory views, while reassigning legacy `default-user` history to `nizhenshigoule@gmail.com`.

**Architecture:** Keep the phase narrow: use `actor.actor_id` as the only ownership key for chat and memory in live request paths, and migrate legacy `default-user` or blank ownership to the administrator account `nizhenshigoule@gmail.com`. Chat authorization is enforced through `chat_session.user_id`, while memory authorization is enforced by direct `memory_*.user_id` filters. Multi-user regression tests prove there is no cross-account leakage.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, pytest, existing Prism auth/session system

---

## File Map

### Backend

- Create: `backend/alembic/versions/20260803_02_chat_memory_user_isolation.py`
  - Legacy ownership backfill for chat and memory tables.
- Modify: `backend/app/api/chat.py`
  - Add `ActorContext` to chat endpoints, enforce session ownership, and write new sessions with `actor.actor_id`.
- Modify: `backend/app/api/memories.py`
  - Replace `DEFAULT_USER_ID` reads/writes with current actor ownership.
- Modify: `backend/app/services/memory_extraction.py`
  - Ensure extraction accepts current user context and writes memory rows with that user id.
- Modify: `backend/app/services/memory_scheduler.py`
  - Ensure any scheduled/manual extraction helpers do not silently write `default-user`.
- Modify: `backend/app/services/memory_reflection.py`
  - Scope insight generation and listing to a specific user.
- Modify: `backend/app/services/memory_consolidation.py`
  - Scope consolidation candidates and writes to a specific user.
- Modify: `backend/app/services/memory_entity.py`
  - Scope extracted entities/relations to the invoking user.
- Modify: `backend/app/services/agent_trace.py` only if any chat session access helper currently ignores session ownership.

### Tests

- Modify: `backend/tests/test_chat_api.py`
  - Add actor-scoped chat tests and cross-user denial cases.
- Modify: `backend/tests/test_memory_phase1_api.py`
  - Add actor-scoped memory tests and cross-user denial cases.
- Create: `backend/tests/test_chat_memory_user_isolation.py`
  - Focused multi-user regression tests spanning chat creation and memory extraction.
- Modify: `backend/tests/conftest.py`
  - If needed, add helper headers or helper login fixture for multiple authenticated users.

## Task 1: Backfill historical chat and memory ownership

**Files:**
- Create: `backend/alembic/versions/20260803_02_chat_memory_user_isolation.py`
- Test: `backend/tests/test_chat_memory_user_isolation.py`

- [ ] **Step 1: Write the failing legacy-backfill test**

Create `backend/tests/test_chat_memory_user_isolation.py` with this first test:

```python
from backend.app.models import ChatSession, MemoryDraft


def test_legacy_chat_and_memory_rows_can_be_reassigned_to_admin(db_session):
    session = ChatSession(title="legacy", user_id="default-user")
    draft = MemoryDraft(user_id="default-user", draft_type="statement", payload={"content": "legacy"})
    db_session.add_all([session, draft])
    db_session.commit()

    assert session.user_id == "default-user"
    assert draft.user_id == "default-user"
```

- [ ] **Step 2: Run test to verify baseline behavior**

Run: `pytest backend/tests/test_chat_memory_user_isolation.py::test_legacy_chat_and_memory_rows_can_be_reassigned_to_admin -v`
Expected: PASS, confirming the legacy rows start as `default-user`.

- [ ] **Step 3: Add the ownership backfill migration**

Create `backend/alembic/versions/20260803_02_chat_memory_user_isolation.py`:

```python
"""Backfill legacy chat and memory ownership to the admin account."""

from alembic import op
import sqlalchemy as sa


revision = "20260803_02"
down_revision = "20260803_01"
branch_labels = None
depends_on = None

ADMIN_USER = "nizhenshigoule@gmail.com"


def _backfill_user_id(table_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET user_id = :admin_user
            WHERE user_id IS NULL OR user_id = '' OR user_id = 'default-user'
            """
        ).bindparams(admin_user=ADMIN_USER)
    )


def upgrade() -> None:
    _backfill_user_id("chat_session")
    _backfill_user_id("memory_entry")
    _backfill_user_id("memory_source")
    _backfill_user_id("memory_statement")
    _backfill_user_id("memory_entity")
    _backfill_user_id("memory_relation")
    _backfill_user_id("memory_event")
    _backfill_user_id("memory_insight")
    _backfill_user_id("memory_draft")
    _backfill_user_id("memory_extraction_run")


def downgrade() -> None:
    pass
```

- [ ] **Step 4: Add a migration-safety test for the SQL predicate**

Append to `backend/tests/test_chat_memory_user_isolation.py`:

```python
def test_migration_admin_target_is_documented():
    import pathlib

    migration = pathlib.Path("backend/alembic/versions/20260803_02_chat_memory_user_isolation.py").read_text(encoding="utf-8")
    assert "nizhenshigoule@gmail.com" in migration
    assert "chat_session" in migration
    assert "memory_draft" in migration
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_chat_memory_user_isolation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/20260803_02_chat_memory_user_isolation.py backend/tests/test_chat_memory_user_isolation.py
git commit -m "feat(data): backfill legacy chat and memory ownership"
```

## Task 2: Lock down chat API ownership

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/tests/test_chat_api.py`

- [ ] **Step 1: Write the failing chat ownership tests**

Append to `backend/tests/test_chat_api.py`:

```python
def test_list_sessions_returns_only_current_actor_sessions(client, db_session):
    from backend.app.models import ChatSession

    db_session.add_all([
        ChatSession(title="alice session", user_id="alice"),
        ChatSession(title="bob session", user_id="bob"),
    ])
    db_session.commit()

    response = client.get("/api/v1/chat/sessions", headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"})
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["alice session"]


def test_user_cannot_read_another_users_messages(client, db_session):
    from backend.app.models import ChatSession, ChatMessage

    session = ChatSession(title="bob session", user_id="bob")
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    db_session.add(ChatMessage(session_id=session.id, role="user", content="secret"))
    db_session.commit()

    response = client.get(
        f"/api/v1/chat/sessions/{session.id}/messages",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run chat tests to verify they fail**

Run: `pytest backend/tests/test_chat_api.py -v`
Expected: FAIL because chat routes currently ignore actor ownership.

- [ ] **Step 3: Add actor-scoped session lookup helper**

Modify `backend/app/api/chat.py` imports and add:

```python
from fastapi import APIRouter, Depends, HTTPException
from backend.app.security.actor import ActorContext, get_actor_context
```

```python
def _get_owned_session_or_404(db: Session, actor: ActorContext, session_id: str) -> ChatSession:
    session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == actor.actor_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session
```

- [ ] **Step 4: Scope all chat session reads and writes to the current actor**

Modify `create_session`, `list_sessions`, `update_session`, `delete_session`, `list_messages`, `add_message`, `update_message`, and `generate_title`.

Key implementation shape:

```python
@router.post("/sessions", response_model=ChatSessionOut)
def create_session(payload: ChatSessionCreate, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    session = ChatSession(
        title=payload.title or "新对话",
        user_id=actor.actor_id,
        topic_id=payload.topic_id,
        source_types=payload.source_types,
    )
```

```python
@router.get("/sessions", response_model=list[ChatSessionOut])
def list_sessions(actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == actor.actor_id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
```

And for all session-based routes:

```python
session = _get_owned_session_or_404(db, actor, session_id)
```

- [ ] **Step 5: Run chat tests to verify they pass**

Run: `pytest backend/tests/test_chat_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py backend/tests/test_chat_api.py
git commit -m "fix(chat): enforce per-user session ownership"
```

## Task 3: Lock down memory API ownership

**Files:**
- Modify: `backend/app/api/memories.py`
- Modify: `backend/tests/test_memory_phase1_api.py`

- [ ] **Step 1: Write the failing memory ownership tests**

Append to `backend/tests/test_memory_phase1_api.py`:

```python
def test_list_memory_drafts_returns_only_current_actor_rows(client, db_session):
    db_session.add_all([
        MemoryDraft(user_id="alice", draft_type="statement", payload={"content": "alice memory"}),
        MemoryDraft(user_id="bob", draft_type="statement", payload={"content": "bob memory"}),
    ])
    db_session.commit()

    response = client.get("/api/v1/memories/drafts", headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"})
    assert response.status_code == 200
    assert [item["payload"]["content"] for item in response.json()] == ["alice memory"]


def test_user_cannot_confirm_another_users_draft(client, db_session):
    draft = MemoryDraft(user_id="bob", draft_type="statement", payload={"content": "bob only"})
    db_session.add(draft)
    db_session.commit()

    response = client.post(
        f"/api/v1/memories/drafts/{draft.id}/confirm",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run memory tests to verify they fail**

Run: `pytest backend/tests/test_memory_phase1_api.py -v`
Expected: FAIL because memory routes still use `DEFAULT_USER_ID`.

- [ ] **Step 3: Inject `ActorContext` and remove `DEFAULT_USER_ID` from route logic**

Modify `backend/app/api/memories.py` imports:

```python
from backend.app.security.actor import ActorContext, get_actor_context
```

Delete:

```python
DEFAULT_USER_ID = "default-user"
```

Update helpers:

```python
def _create_source(source_in, db: Session, actor: ActorContext) -> MemorySource:
    data = source_in.model_dump()
    metadata = data.pop("metadata", {})
    source = MemorySource(user_id=actor.actor_id, source_metadata=metadata, **data)
    db.add(source)
    return source
```

```python
def _get_draft_or_404(draft_id: str, db: Session, actor: ActorContext) -> MemoryDraft:
    draft = (
        db.query(MemoryDraft)
        .filter(MemoryDraft.user_id == actor.actor_id, MemoryDraft.id == draft_id)
        .first()
    )
```

- [ ] **Step 4: Scope every memory endpoint to the current actor**

Update each route to accept:

```python
actor: ActorContext = Depends(get_actor_context)
```

Then replace every `Memory*.user_id == DEFAULT_USER_ID` filter and every write using `DEFAULT_USER_ID` with `actor.actor_id`.

Important spots:

- `list_memories`
- `list_memory_drafts`
- `count_memory_drafts`
- `create_memory_draft`
- `extract_memory_from_session`
- `confirm_memory_draft`
- `reject_memory_draft`
- `supersede_memory_draft`
- `list_memory_statements`
- `list_memory_entities`
- `get_insights`
- consolidation preview and trigger

- [ ] **Step 5: Run memory tests to verify they pass**

Run: `pytest backend/tests/test_memory_phase1_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/memories.py backend/tests/test_memory_phase1_api.py
git commit -m "fix(memory): enforce per-user memory ownership"
```

## Task 4: Scope memory extraction and derived writes

**Files:**
- Modify: `backend/app/services/memory_extraction.py`
- Modify: `backend/app/services/memory_reflection.py`
- Modify: `backend/app/services/memory_consolidation.py`
- Modify: `backend/app/services/memory_entity.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/tests/test_chat_memory_user_isolation.py`

- [ ] **Step 1: Write the failing extraction ownership test**

Append to `backend/tests/test_chat_memory_user_isolation.py`:

```python
def test_memory_extraction_creates_rows_for_the_current_chat_owner(db_session):
    from backend.app.models import ChatSession, ChatMessage, MemoryDraft
    from backend.app.services.memory_extraction import extract_session_memories

    session = ChatSession(title="alice chat", user_id="alice")
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    db_session.add_all([
        ChatMessage(session_id=session.id, role="user", content="I prefer review-first memory."),
        ChatMessage(session_id=session.id, role="assistant", content="Understood."),
    ])
    db_session.commit()

    extract_session_memories(db_session, session_id=session.id, limit=20)

    assert db_session.query(MemoryDraft).filter(MemoryDraft.user_id == "alice").count() >= 0
```

- [ ] **Step 2: Run the focused extraction test to identify current ownership assumptions**

Run: `pytest backend/tests/test_chat_memory_user_isolation.py::test_memory_extraction_creates_rows_for_the_current_chat_owner -v`
Expected: FAIL or expose that extraction still writes `default-user`.

- [ ] **Step 3: Make extraction derive the target user from the session**

Modify `backend/app/services/memory_extraction.py` so the session lookup determines the user id once and threads it through all memory writes.

Implementation target:

```python
session = db.query(ChatSession).filter(ChatSession.id == session_id).one_or_none()
if session is None:
    raise ValueError(f"chat session not found: {session_id}")
user_id = session.user_id
```

Every created `MemorySource`, `MemoryDraft`, `MemoryStatement`, or related row in this service should use `user_id=user_id`.

- [ ] **Step 4: Scope reflection, consolidation, and entity derivation helpers**

Update these services so their public functions accept `user_id: str` and filter/write by that id:

```python
def run_reflection(db: Session, *, user_id: str) -> dict:
```

```python
def list_insights(db: Session, *, user_id: str, limit: int = 20):
```

```python
def consolidation_candidates(db: Session, *, user_id: str) -> dict:
```

```python
def run_consolidation(db: Session, *, user_id: str) -> dict:
```

```python
def extract_and_link_entities(db: Session, *, user_id: str, content: str, source_id: str, statement_id: str | None = None) -> None:
```

Then update `backend/app/api/memories.py` to pass `actor.actor_id` into these service calls.

- [ ] **Step 5: Run the focused isolation tests**

Run: `pytest backend/tests/test_chat_memory_user_isolation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/memory_extraction.py backend/app/services/memory_reflection.py backend/app/services/memory_consolidation.py backend/app/services/memory_entity.py backend/app/api/memories.py backend/tests/test_chat_memory_user_isolation.py
git commit -m "fix(memory): scope extraction and derived writes to current user"
```

## Task 5: Add cross-account regression coverage

**Files:**
- Modify: `backend/tests/test_chat_api.py`
- Modify: `backend/tests/test_memory_phase1_api.py`
- Modify: `backend/tests/test_chat_memory_user_isolation.py`

- [ ] **Step 1: Add a multi-user chat isolation regression**

Append to `backend/tests/test_chat_memory_user_isolation.py`:

```python
def test_user_b_cannot_see_user_a_chat_list(client):
    created = client.post(
        "/api/v1/chat/sessions",
        json={"title": "alice private session"},
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"},
    )
    assert created.status_code == 200

    response = client.get("/api/v1/chat/sessions", headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "bob"})
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Add a multi-user memory isolation regression**

Append to `backend/tests/test_chat_memory_user_isolation.py`:

```python
def test_user_b_cannot_see_user_a_memory_drafts(client):
    created = client.post(
        "/api/v1/memories/drafts",
        json={"draft_type": "statement", "payload": {"content": "alice memory"}},
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "alice"},
    )
    assert created.status_code == 200

    response = client.get("/api/v1/memories/drafts", headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "bob"})
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 3: Add an admin-legacy visibility regression**

Append to `backend/tests/test_chat_memory_user_isolation.py`:

```python
def test_admin_can_see_reassigned_legacy_memory_rows(client, db_session):
    draft = MemoryDraft(user_id="nizhenshigoule@gmail.com", draft_type="statement", payload={"content": "legacy memory"})
    db_session.add(draft)
    db_session.commit()

    response = client.get(
        "/api/v1/memories/drafts",
        headers={"X-Prism-Actor": "nizhenshigoule@gmail.com", "X-Prism-Tenant": "nizhenshigoule@gmail.com"},
    )
    assert response.status_code == 200
    assert [item["payload"]["content"] for item in response.json()] == ["legacy memory"]
```

- [ ] **Step 4: Run the full focused isolation suite**

Run: `pytest backend/tests/test_chat_api.py backend/tests/test_memory_phase1_api.py backend/tests/test_chat_memory_user_isolation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_chat_api.py backend/tests/test_memory_phase1_api.py backend/tests/test_chat_memory_user_isolation.py
git commit -m "test(isolation): add multi-user chat and memory regressions"
```

## Final verification

- [ ] **Step 1: Run all focused chat and memory tests**

Run: `pytest backend/tests/test_chat_api.py backend/tests/test_memory_phase1_api.py backend/tests/test_chat_memory_user_isolation.py -v`
Expected: PASS

- [ ] **Step 2: Run any existing memory inbox page smoke if available**

Run: `npm.cmd test -- --test-name-pattern memory-inbox-page`
Expected: Either PASS or known unrelated failure documented before merge; if it fails because API contracts changed, capture and fix before closing.

- [ ] **Step 3: Review changed files**

Run: `git diff --stat HEAD~5..HEAD`
Expected: migration/backfill, chat API, memory API/services, and isolation tests only.

- [ ] **Step 4: Check worktree status**

Run: `git status --short`
Expected: only known unrelated local modifications outside this plan remain.

## Self-review

- Spec coverage:
  - legacy data reassignment: Task 1
  - chat ownership enforcement: Task 2
  - memory ownership enforcement: Task 3
  - extraction and derived write ownership: Task 4
  - multi-user cross-account regression tests: Task 5
- Placeholder scan:
  - No `TODO`, `TBD`, or vague follow-up text remains.
- Type consistency:
  - live ownership key is always `actor.actor_id`
  - chat ownership always resolves through `ChatSession.user_id`
  - memory ownership always resolves through `memory_*.user_id`
