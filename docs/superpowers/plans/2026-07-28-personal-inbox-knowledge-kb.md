# Personal Inbox Knowledge KB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visible system knowledge base named `个人随手记` that syncs confirmed `PersonalAssetUnit` records as downloadable/indexable Markdown files and participates in chat only when the user enables `包含个人随手记`.

**Architecture:** `PersonalAssetUnit` remains the source of truth. Backend owns a focused `personal_inbox` service that creates the system KB, renders Units to Markdown, creates or updates derived `KnowledgeFile` records, triggers normal parse/index jobs, and performs source-level cascade deletion. Chat keeps using the authorized KB tool path; when the switch is enabled, Backend appends the actor's personal inbox KB to the signed scope and Engine `query_kb` searches all authorized KBs by default.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, MySQL, Redis knowledge jobs, existing local knowledge file storage, Engine knowledge tools, React/TypeScript.

---

## File Structure

Create:

- `backend/app/services/personal_inbox.py` — source-of-truth service for system KB creation, Markdown rendering, Unit sync/backfill, and cascade deletion.
- `backend/tests/test_personal_inbox_service.py` — focused unit tests for rendering, idempotent sync, backfill, and cascade deletion.
- `backend/alembic/versions/20260728_01_personal_inbox_kb.py` — migration for system/source marker columns.

Modify:

- `backend/app/models/knowledge_item.py` — add `KnowledgeTopic.system_type/is_system/delete_disabled` and `KnowledgeFile.source_kind/source_id/system_type`.
- `backend/app/api/knowledge_bases.py` — expose system flags and block deleting the system KB.
- `backend/app/api/knowledge_files.py` — route deletion of personal-inbox derived files through source cascade deletion.
- `backend/app/api/assets.py` — sync confirmed/edited Units into the personal inbox KB.
- `backend/app/api/agent_chat_proxy.py` — accept `include_personal_inbox` and append the actor's system KB server-side.
- `engine/app/agent/tools/knowledge_base.py` — make `query_kb` default to all authorized KBs when more than one KB is scoped.
- `engine/app/chat/answer.py` — allow retrieval service queries across a list of KBs or keep per-KB calls inside the tool.
- `frontend/src/features/knowledge/api/knowledgeBases.ts` — expose system KB flags.
- `frontend/src/features/knowledge/api/files.ts` — expose source markers if the file API returns them.
- `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx` — show system KB marker and cascade delete confirmation for personal inbox derived files.
- `frontend/src/pages/ChatPage.tsx` — add the `包含个人随手记` switch and send `include_personal_inbox`.

Test:

- `backend/tests/test_knowledge_bases_v1_api.py`
- `backend/tests/test_knowledge_files_v1_api.py`
- `backend/tests/test_agent_chat_proxy.py`
- `engine/tests/test_knowledge_base_tools.py`
- `frontend/tests/chat-dev-proxy.test.mjs` or a new `frontend/tests/chat-personal-inbox.test.mjs`
- `frontend/tests/knowledge-product.spec.ts` if e2e coverage is needed.

---

### Task 1: Add explicit system/source marker columns

**Files:**
- Create: `backend/alembic/versions/20260728_01_personal_inbox_kb.py`
- Modify: `backend/app/models/knowledge_item.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Add these tests to `backend/tests/test_models.py`:

```python
def test_knowledge_topic_system_flags(db_session):
    from backend.app.models import KnowledgeTopic

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        name="个人随手记",
        system_type="personal_inbox",
        is_system=True,
        delete_disabled=True,
    )
    db_session.add(topic)
    db_session.commit()

    saved = db_session.query(KnowledgeTopic).filter_by(kb_uid=topic.kb_uid).one()
    assert saved.system_type == "personal_inbox"
    assert saved.is_system is True
    assert saved.delete_disabled is True


def test_knowledge_file_source_markers(db_session):
    from backend.app.models import KnowledgeFile

    file_row = KnowledgeFile(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        file_uid="file-a",
        original_filename="unit.md",
        source_kind="personal_asset_unit",
        source_id="unit-a",
        system_type="personal_inbox",
    )
    db_session.add(file_row)
    db_session.commit()

    saved = db_session.query(KnowledgeFile).filter_by(file_uid="file-a").one()
    assert saved.source_kind == "personal_asset_unit"
    assert saved.source_id == "unit-a"
    assert saved.system_type == "personal_inbox"
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_models.py::test_knowledge_topic_system_flags backend/tests/test_models.py::test_knowledge_file_source_markers -v
```

Expected: FAIL with an invalid keyword/unknown column error for `system_type`, `is_system`, `delete_disabled`, `source_kind`, or `source_id`.

- [ ] **Step 3: Update SQLAlchemy models**

In `backend/app/models/knowledge_item.py`, add `Boolean` to the SQLAlchemy imports:

```python
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
```

In `KnowledgeTopic`, add:

```python
    system_type = Column(String(64), nullable=True, index=True)
    is_system = Column(Boolean, nullable=False, default=False, server_default="0")
    delete_disabled = Column(Boolean, nullable=False, default=False, server_default="0")
```

In `KnowledgeFile`, add:

```python
    source_kind = Column(String(64), nullable=True, index=True)
    source_id = Column(String(128), nullable=True, index=True)
    system_type = Column(String(64), nullable=True, index=True)
```

- [ ] **Step 4: Add Alembic migration**

Create `backend/alembic/versions/20260728_01_personal_inbox_kb.py`:

```python
"""personal inbox KB system/source markers

Revision ID: 20260728_01_personal_inbox_kb
Revises: 20260722_03_graph_outbox_governance
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_01_personal_inbox_kb"
down_revision = "20260722_03_graph_outbox_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_topic", sa.Column("system_type", sa.String(length=64), nullable=True))
    op.add_column("knowledge_topic", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("knowledge_topic", sa.Column("delete_disabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.create_index("ix_knowledge_topic_system_type", "knowledge_topic", ["system_type"])

    op.add_column("knowledge_file", sa.Column("source_kind", sa.String(length=64), nullable=True))
    op.add_column("knowledge_file", sa.Column("source_id", sa.String(length=128), nullable=True))
    op.add_column("knowledge_file", sa.Column("system_type", sa.String(length=64), nullable=True))
    op.create_index("ix_knowledge_file_source_kind", "knowledge_file", ["source_kind"])
    op.create_index("ix_knowledge_file_source_id", "knowledge_file", ["source_id"])
    op.create_index("ix_knowledge_file_system_type", "knowledge_file", ["system_type"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_file_system_type", table_name="knowledge_file")
    op.drop_index("ix_knowledge_file_source_id", table_name="knowledge_file")
    op.drop_index("ix_knowledge_file_source_kind", table_name="knowledge_file")
    op.drop_column("knowledge_file", "system_type")
    op.drop_column("knowledge_file", "source_id")
    op.drop_column("knowledge_file", "source_kind")

    op.drop_index("ix_knowledge_topic_system_type", table_name="knowledge_topic")
    op.drop_column("knowledge_topic", "delete_disabled")
    op.drop_column("knowledge_topic", "is_system")
    op.drop_column("knowledge_topic", "system_type")
```

If the repository's current Alembic head differs, replace `down_revision` with the output of:

```powershell
Get-ChildItem backend/alembic/versions/*.py | Sort-Object Name | Select-Object -Last 1
```

- [ ] **Step 5: Run model tests and migration syntax check**

Run:

```powershell
python -m pytest backend/tests/test_models.py::test_knowledge_topic_system_flags backend/tests/test_models.py::test_knowledge_file_source_markers -v
python -m py_compile backend/alembic/versions/20260728_01_personal_inbox_kb.py
```

Expected: both commands PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/knowledge_item.py backend/alembic/versions/20260728_01_personal_inbox_kb.py backend/tests/test_models.py
git commit -m "feat(knowledge): add personal inbox source markers"
```

---

### Task 2: Implement Personal Inbox service

**Files:**
- Create: `backend/app/services/personal_inbox.py`
- Create: `backend/tests/test_personal_inbox_service.py`
- Modify: none outside service in this task

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_personal_inbox_service.py`:

```python
from pathlib import Path


def test_render_personal_asset_unit_markdown_includes_unit_and_source_items(db_session):
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services.personal_inbox import render_personal_asset_unit_markdown

    item = PersonalAssetItem(
        id="item-a",
        user_id="default-user",
        raw_text="raw should not appear by default",
        title="Fragment A",
        summary="Fragment summary",
        rewritten_content="Clean rewritten fragment",
        status="confirmed",
    )
    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="default-user",
        title="Inbox Unit",
        summary="Unit summary",
        content="Unit content",
        tags=["tag-a"],
        source_asset_ids=["item-a"],
        status="confirmed",
    )
    db_session.add_all([item, unit])
    db_session.commit()

    markdown = render_personal_asset_unit_markdown(db_session, unit)

    assert "# Inbox Unit" in markdown
    assert "Unit summary" in markdown
    assert "Unit content" in markdown
    assert "Fragment A" in markdown
    assert "Fragment summary" in markdown
    assert "Clean rewritten fragment" in markdown
    assert "raw should not appear by default" not in markdown


def test_ensure_personal_inbox_kb_is_idempotent(db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    first = ensure_personal_inbox_kb(db_session, tenant_id="tenant-a", owner_user_id="user-a")
    second = ensure_personal_inbox_kb(db_session, tenant_id="tenant-a", owner_user_id="user-a")

    assert first.kb_uid == second.kb_uid
    assert first.name == "个人随手记"
    assert first.system_type == "personal_inbox"
    assert first.is_system is True
    assert first.delete_disabled is True


def test_sync_confirmed_unit_creates_single_markdown_file(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))
    published = []
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: published.append(job_id))

    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="user-a",
        title="Unit A",
        summary="Summary A",
        content="Content A",
        source_asset_ids=[],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()

    first = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    rows = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit", source_id="unit-a").all()
    assert len(rows) == 1
    assert first.file_uid == second.file_uid
    assert rows[0].original_filename.endswith(".md")
    assert rows[0].mime_type == "text/markdown"
    assert rows[0].system_type == "personal_inbox"
    assert rows[0].content_text and "Content A" in rows[0].content_text
    assert published
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py -v
```

Expected: FAIL because `backend.app.services.personal_inbox` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/personal_inbox.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import KnowledgeFile, KnowledgeJob, KnowledgeTopic, PersonalAssetItem, PersonalAssetUnit
from backend.app.models.knowledge_types import StageStatus, uuid4_str
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import RedisJobPublisher
from backend.app.storage.files import LocalFileStorage
from backend.app.utils.time import local_now


PERSONAL_INBOX_NAME = "个人随手记"
PERSONAL_INBOX_SYSTEM_TYPE = "personal_inbox"
PERSONAL_ASSET_UNIT_SOURCE_KIND = "personal_asset_unit"


def _storage() -> LocalFileStorage:
    return LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))


def _publisher() -> RedisJobPublisher:
    return RedisJobPublisher(settings.REDIS_URL, settings.KNOWLEDGE_INGEST_QUEUE)


def _publish_job(job_id: str) -> None:
    _publisher().publish(job_id)


def _safe_filename(title: str, unit_id: str) -> str:
    cleaned = re.sub(r"[\\\\/:*?\"<>|\\s]+", "-", (title or "personal-asset-unit").strip())
    cleaned = cleaned.strip("-")[:80] or "personal-asset-unit"
    return f"{cleaned}-{unit_id[:8]}.md"


def _item_text(item: PersonalAssetItem) -> str:
    return (item.rewritten_content or item.body or item.summary or "").strip()


def ensure_personal_inbox_kb(db: Session, *, tenant_id: str, owner_user_id: str) -> KnowledgeTopic:
    existing = (
        db.query(KnowledgeTopic)
        .filter(
            KnowledgeTopic.tenant_id == tenant_id,
            KnowledgeTopic.owner_user_id == owner_user_id,
            KnowledgeTopic.system_type == PERSONAL_INBOX_SYSTEM_TYPE,
            KnowledgeTopic.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    topic = KnowledgeTopic(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        name=PERSONAL_INBOX_NAME,
        description="系统自动生成的个人资产知识库。",
        system_type=PERSONAL_INBOX_SYSTEM_TYPE,
        is_system=True,
        delete_disabled=True,
    )
    db.add(topic)
    db.flush()
    return topic


def render_personal_asset_unit_markdown(db: Session, unit: PersonalAssetUnit) -> str:
    item_ids = [str(item_id) for item_id in (unit.source_asset_ids or []) if item_id]
    items = []
    if item_ids:
        items = (
            db.query(PersonalAssetItem)
            .filter(PersonalAssetItem.id.in_(item_ids), PersonalAssetItem.user_id == unit.user_id)
            .all()
        )
    items_by_id = {item.id: item for item in items}
    ordered_items = [items_by_id[item_id] for item_id in item_ids if item_id in items_by_id]

    lines = [
        f"# {unit.title or unit.id}",
        "",
        "> 来源：个人随手记",
        "> 类型：PersonalAssetUnit",
        f"> 更新时间：{unit.updated_at or unit.created_at or ''}",
        "",
        "## 摘要",
        "",
        unit.summary or "",
        "",
        "## 正文",
        "",
        unit.content or "",
        "",
        "## 标签",
        "",
    ]
    for tag in unit.tags or []:
        lines.append(f"- {tag}")
    if not unit.tags:
        lines.append("- 无")

    lines.extend(["", "## 来源碎片", ""])
    for item in ordered_items:
        lines.append(f"- {item.title or item.raw_title or item.id}")
        if item.summary:
            lines.append(f"  - 摘要：{item.summary}")
        text = _item_text(item)
        if text:
            lines.append(f"  - 内容：{text}")
    if not ordered_items:
        lines.append("- 无")

    return "\\n".join(lines).strip() + "\\n"


def _find_derived_file(db: Session, *, tenant_id: str, kb_uid: str, unit_id: str) -> KnowledgeFile | None:
    return (
        db.query(KnowledgeFile)
        .filter(
            KnowledgeFile.tenant_id == tenant_id,
            KnowledgeFile.kb_uid == kb_uid,
            KnowledgeFile.source_kind == PERSONAL_ASSET_UNIT_SOURCE_KIND,
            KnowledgeFile.source_id == unit_id,
            KnowledgeFile.deleted_at.is_(None),
        )
        .one_or_none()
    )


def sync_personal_asset_unit_to_kb(
    db: Session,
    unit: PersonalAssetUnit,
    *,
    tenant_id: str,
    owner_user_id: str,
    publish: bool = True,
) -> KnowledgeFile:
    if unit.status != "confirmed":
        raise ValueError("Only confirmed PersonalAssetUnit records can be synced")

    topic = ensure_personal_inbox_kb(db, tenant_id=tenant_id, owner_user_id=owner_user_id)
    content = render_personal_asset_unit_markdown(db, unit).encode("utf-8")
    filename = _safe_filename(unit.title or unit.id, unit.id)
    storage = _storage()
    existing = _find_derived_file(db, tenant_id=tenant_id, kb_uid=topic.kb_uid, unit_id=unit.id)
    file_uid = existing.file_uid if existing is not None else uuid4_str()
    staged = storage.stage(tenant_id, topic.kb_uid, file_uid, filename, content)
    storage_uri = storage.commit(staged)

    if existing is None:
        file_row = KnowledgeFile(
            file_uid=file_uid,
            tenant_id=tenant_id,
            kb_uid=topic.kb_uid,
            topic_id=topic.id,
            user_id=unit.user_id,
            title=unit.title,
            original_filename=filename,
            relative_path=filename,
            media_type="document",
            mime_type="text/markdown",
            storage_uri=storage_uri,
            content_sha256=staged.sha256,
            size_bytes=staged.size_bytes,
            file_size=staged.size_bytes,
            content_text=content.decode("utf-8"),
            source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
            source_id=unit.id,
            system_type=PERSONAL_INBOX_SYSTEM_TYPE,
            parse_status=StageStatus.PENDING.value,
            index_status=StageStatus.PENDING.value,
            graph_status=StageStatus.PENDING.value,
        )
        db.add(file_row)
    else:
        file_row = existing
        old_uri = file_row.storage_uri
        file_row.title = unit.title
        file_row.original_filename = filename
        file_row.relative_path = filename
        file_row.mime_type = "text/markdown"
        file_row.storage_uri = storage_uri
        file_row.content_sha256 = staged.sha256
        file_row.size_bytes = staged.size_bytes
        file_row.file_size = staged.size_bytes
        file_row.content_text = content.decode("utf-8")
        file_row.parsed_content_version = (file_row.parsed_content_version or 0) + 1
        file_row.parse_status = StageStatus.PENDING.value
        file_row.index_status = StageStatus.PENDING.value
        file_row.graph_status = StageStatus.PENDING.value
        file_row.parse_error = None
        file_row.index_error = None
        file_row.graph_error = None
        if old_uri and old_uri != storage_uri:
            try:
                storage.delete(old_uri)
            except Exception:
                pass

    db.flush()
    job = KnowledgeJobService(db).create(
        JobCommand("parse", tenant_id, topic.kb_uid, file_row.file_uid, {"auto_index": True}),
        f"{topic.kb_uid}:{file_row.file_uid}:parse:v{file_row.parsed_content_version or 0}",
        commit=False,
    )
    file_row.last_job_id = job.id
    db.commit()
    if publish:
        try:
            _publish_job(job.id)
            KnowledgeJobService(db).stage_enqueued(job.id)
        except Exception:
            db.rollback()
    db.refresh(file_row)
    return file_row


def backfill_personal_inbox(db: Session, *, tenant_id: str, owner_user_id: str, publish: bool = True) -> int:
    units = (
        db.query(PersonalAssetUnit)
        .filter(PersonalAssetUnit.user_id == owner_user_id, PersonalAssetUnit.status == "confirmed")
        .order_by(PersonalAssetUnit.updated_at.asc(), PersonalAssetUnit.id.asc())
        .all()
    )
    count = 0
    for unit in units:
        try:
            sync_personal_asset_unit_to_kb(
                db,
                unit,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                publish=publish,
            )
            count += 1
        except Exception:
            db.rollback()
    return count
```

- [ ] **Step 4: Run service tests**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py -v
```

Expected: PASS for the three service tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/personal_inbox.py backend/tests/test_personal_inbox_service.py
git commit -m "feat(knowledge): sync personal asset units to inbox KB"
```

---

### Task 3: Expose and protect system KBs in Backend API

**Files:**
- Modify: `backend/app/api/knowledge_bases.py`
- Test: `backend/tests/test_knowledge_bases_v1_api.py`

- [ ] **Step 1: Write failing API tests**

Add tests:

```python
def test_system_personal_inbox_kb_is_listed_with_flags(client, db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    topic = ensure_personal_inbox_kb(db_session, tenant_id="default-tenant", owner_user_id="default-user")
    db_session.commit()

    body = client.get("/api/v1/knowledge-bases").json()
    item = next(row for row in body["items"] if row["kb_uid"] == topic.kb_uid)

    assert item["name"] == "个人随手记"
    assert item["system_type"] == "personal_inbox"
    assert item["is_system"] is True
    assert item["delete_disabled"] is True


def test_system_personal_inbox_kb_cannot_be_deleted(client, db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    topic = ensure_personal_inbox_kb(db_session, tenant_id="default-tenant", owner_user_id="default-user")
    db_session.commit()

    response = client.delete(f"/api/v1/knowledge-bases/{topic.kb_uid}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SYSTEM_KB_DELETE_DISABLED"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_knowledge_bases_v1_api.py::test_system_personal_inbox_kb_is_listed_with_flags backend/tests/test_knowledge_bases_v1_api.py::test_system_personal_inbox_kb_cannot_be_deleted -v
```

Expected: FAIL because response schema lacks system fields and delete does not block system KBs.

- [ ] **Step 3: Update response schema**

In `KnowledgeBaseResponse`, add:

```python
    system_type: str | None = None
    is_system: bool = False
    delete_disabled: bool = False
```

- [ ] **Step 4: Block deletion**

In `delete_knowledge_base`, after loading `topic` with `with_for_update()`, add:

```python
    if topic.is_system or topic.delete_disabled:
        raise ApiProblem(
            409,
            "SYSTEM_KB_DELETE_DISABLED",
            "System knowledge bases cannot be deleted",
        )
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_knowledge_bases_v1_api.py::test_system_personal_inbox_kb_is_listed_with_flags backend/tests/test_knowledge_bases_v1_api.py::test_system_personal_inbox_kb_cannot_be_deleted -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/knowledge_bases.py backend/tests/test_knowledge_bases_v1_api.py
git commit -m "fix(knowledge): protect personal inbox system KB"
```

---

### Task 4: Wire asset Unit confirm/edit to sync derived Markdown

**Files:**
- Modify: `backend/app/api/assets.py`
- Test: `backend/tests/test_assets_api.py`

- [ ] **Step 1: Write failing asset API tests**

Add tests:

```python
def test_confirm_personal_asset_unit_syncs_to_personal_inbox(client, db_session, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetItem
    from backend.app.services import personal_inbox

    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)
    monkeypatch.setattr("backend.app.api.assets._ai_synthesize_knowledge", lambda assets, title="", instruction="": {
        "title": title or "Unit",
        "summary": "Unit summary",
        "content": "Unit content",
        "tags": [],
        "outline": [],
        "confidence": {},
        "rationale": "",
    })
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)

    item_payload = {"content": "fragment content", "title": "Fragment"}
    item = client.post("/api/v1/assets/items", json=item_payload).json()
    client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={})
    unit = client.post("/api/v1/assets/personal_asset_units", json={"asset_ids": [item["id"]], "title": "Unit"}).json()

    response = client.post(f"/api/v1/assets/personal_asset_units/{unit['id']}/confirm")

    assert response.status_code == 200
    file_row = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit", source_id=unit["id"]).one()
    assert file_row.original_filename.endswith(".md")
    assert file_row.content_text and "Unit content" in file_row.content_text


def test_update_confirmed_personal_asset_unit_resyncs_existing_file(client, db_session, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="default-user",
        title="Old",
        summary="Old summary",
        content="Old content",
        source_asset_ids=[],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()
    personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="default-tenant",
        owner_user_id="default-user",
        publish=False,
    )
    file_uid = db_session.query(KnowledgeFile).filter_by(source_id="unit-a").one().file_uid

    response = client.put("/api/v1/assets/personal_asset_units/unit-a", json={"title": "New", "content": "New content"})

    assert response.status_code == 200
    updated = db_session.query(KnowledgeFile).filter_by(source_id="unit-a").one()
    assert updated.file_uid == file_uid
    assert "New content" in updated.content_text
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_syncs_to_personal_inbox backend/tests/test_assets_api.py::test_update_confirmed_personal_asset_unit_resyncs_existing_file -v
```

Expected: FAIL because confirm/edit do not sync derived Markdown.

- [ ] **Step 3: Sync after confirm**

In `backend/app/api/assets.py`, import:

```python
from backend.app.services.personal_inbox import sync_personal_asset_unit_to_kb
```

In `confirm_personal_asset_unit`, after the Unit status is changed to confirmed and governance/graph ingestion is scheduled, call:

```python
    sync_personal_asset_unit_to_kb(
        db,
        unit,
        tenant_id=DEFAULT_TENANT_ID,
        owner_user_id=DEFAULT_USER_ID,
    )
```

`backend/app/api/assets.py` currently defines `DEFAULT_USER_ID = "default-user"` and does not define a tenant constant. Add this beside `DEFAULT_USER_ID`:

```python
DEFAULT_TENANT_ID = "default-tenant"
```

- [ ] **Step 4: Sync after confirmed Unit edit**

In `update_personal_asset_unit`, after applying patch fields and before returning, add:

```python
    if unit.status == "confirmed":
        sync_personal_asset_unit_to_kb(
            db,
            unit,
            tenant_id=DEFAULT_TENANT_ID,
            owner_user_id=DEFAULT_USER_ID,
        )
```

If the endpoint currently commits before return, ensure the Unit fields are flushed before sync:

```python
    db.flush()
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_assets_api.py::test_confirm_personal_asset_unit_syncs_to_personal_inbox backend/tests/test_assets_api.py::test_update_confirmed_personal_asset_unit_resyncs_existing_file -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/assets.py backend/tests/test_assets_api.py
git commit -m "feat(assets): publish confirmed units to personal inbox KB"
```

---

### Task 5: Add personal inbox backfill entrypoint

**Files:**
- Modify: `backend/app/services/personal_inbox.py`
- Modify: `backend/app/utils/auto_migrate.py`
- Test: `backend/tests/test_personal_inbox_service.py`

- [ ] **Step 1: Write failing backfill test**

Add:

```python
def test_backfill_personal_inbox_syncs_existing_confirmed_units(db_session, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    confirmed = PersonalAssetUnit(
        id="confirmed-unit",
        user_id="default-user",
        title="Confirmed",
        content="Confirmed content",
        source_asset_ids=[],
        status="confirmed",
    )
    pending = PersonalAssetUnit(
        id="pending-unit",
        user_id="default-user",
        title="Pending",
        content="Pending content",
        source_asset_ids=[],
        status="pending_review",
    )
    db_session.add_all([confirmed, pending])
    db_session.commit()

    count = personal_inbox.backfill_personal_inbox(
        db_session,
        tenant_id="default-tenant",
        owner_user_id="default-user",
        publish=False,
    )

    assert count == 1
    assert db_session.query(KnowledgeFile).filter_by(source_id="confirmed-unit").count() == 1
    assert db_session.query(KnowledgeFile).filter_by(source_id="pending-unit").count() == 0
```

- [ ] **Step 2: Run backfill test**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py::test_backfill_personal_inbox_syncs_existing_confirmed_units -v
```

Expected: PASS if Task 2 included the backfill implementation. If it fails, adjust `backfill_personal_inbox` to filter `status == "confirmed"`.

- [ ] **Step 3: Wire startup migration helper**

In `backend/app/utils/auto_migrate.py`, add an idempotent call after DB tables are available:

```python
def ensure_personal_inbox_backfill() -> None:
    from backend.app.database import SessionLocal
    from backend.app.services.personal_inbox import backfill_personal_inbox, ensure_personal_inbox_kb

    db = SessionLocal()
    try:
        ensure_personal_inbox_kb(db, tenant_id="default-tenant", owner_user_id="default-user")
        backfill_personal_inbox(db, tenant_id="default-tenant", owner_user_id="default-user")
        db.commit()
    finally:
        db.close()
```

Call `ensure_personal_inbox_backfill()` from the existing auto-migration entrypoint. If the file has a single `run_auto_migrations()` function, append it there. If it has top-level migration functions called by app startup, call it from the same sequence.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py::test_backfill_personal_inbox_syncs_existing_confirmed_units -v
python -m py_compile backend/app/utils/auto_migrate.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/personal_inbox.py backend/app/utils/auto_migrate.py backend/tests/test_personal_inbox_service.py
git commit -m "feat(knowledge): backfill personal inbox KB"
```

---

### Task 6: Cascade delete from personal inbox files

**Files:**
- Modify: `backend/app/services/personal_inbox.py`
- Modify: `backend/app/api/knowledge_files.py`
- Test: `backend/tests/test_personal_inbox_service.py`
- Test: `backend/tests/test_knowledge_files_v1_api.py`

- [ ] **Step 1: Write service cascade tests**

Add:

```python
def test_delete_personal_inbox_file_deletes_unit_and_orphan_item(db_session, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetItem, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    item = PersonalAssetItem(id="item-a", user_id="default-user", raw_text="raw", title="Item", status="confirmed")
    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="default-user",
        title="Unit",
        content="Content",
        source_asset_ids=["item-a"],
        status="confirmed",
    )
    db_session.add_all([item, unit])
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="default-tenant",
        owner_user_id="default-user",
        publish=False,
    )

    personal_inbox.delete_personal_inbox_file_cascade(db_session, file_row, tenant_id="default-tenant")
    db_session.commit()

    assert db_session.query(PersonalAssetUnit).filter_by(id="unit-a").first() is None
    assert db_session.query(PersonalAssetItem).filter_by(id="item-a").first() is None
    assert db_session.query(KnowledgeFile).filter_by(file_uid=file_row.file_uid).first().deleted_at is not None


def test_delete_personal_inbox_file_preserves_shared_item(db_session, monkeypatch):
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    item = PersonalAssetItem(id="item-a", user_id="default-user", raw_text="raw", title="Item", status="confirmed")
    unit_a = PersonalAssetUnit(id="unit-a", user_id="default-user", title="Unit A", content="A", source_asset_ids=["item-a"], status="confirmed")
    unit_b = PersonalAssetUnit(id="unit-b", user_id="default-user", title="Unit B", content="B", source_asset_ids=["item-a"], status="confirmed")
    db_session.add_all([item, unit_a, unit_b])
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit_a,
        tenant_id="default-tenant",
        owner_user_id="default-user",
        publish=False,
    )

    personal_inbox.delete_personal_inbox_file_cascade(db_session, file_row, tenant_id="default-tenant")
    db_session.commit()

    assert db_session.query(PersonalAssetUnit).filter_by(id="unit-a").first() is None
    assert db_session.query(PersonalAssetUnit).filter_by(id="unit-b").first() is not None
    assert db_session.query(PersonalAssetItem).filter_by(id="item-a").first() is not None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py::test_delete_personal_inbox_file_deletes_unit_and_orphan_item backend/tests/test_personal_inbox_service.py::test_delete_personal_inbox_file_preserves_shared_item -v
```

Expected: FAIL because `delete_personal_inbox_file_cascade` does not exist.

- [ ] **Step 3: Implement cascade service**

Add to `backend/app/services/personal_inbox.py`:

```python
def _unit_references_item(unit: PersonalAssetUnit, item_id: str) -> bool:
    return item_id in {str(value) for value in (unit.source_asset_ids or [])}


def delete_personal_inbox_file_cascade(db: Session, file_row: KnowledgeFile, *, tenant_id: str) -> KnowledgeJob:
    if (
        file_row.system_type != PERSONAL_INBOX_SYSTEM_TYPE
        or file_row.source_kind != PERSONAL_ASSET_UNIT_SOURCE_KIND
        or not file_row.source_id
    ):
        raise ValueError("File is not a derived personal inbox asset unit file")

    unit = (
        db.query(PersonalAssetUnit)
        .filter(PersonalAssetUnit.id == file_row.source_id)
        .with_for_update()
        .one_or_none()
    )
    source_asset_ids = [str(value) for value in ((unit.source_asset_ids if unit is not None else []) or []) if value]
    if unit is not None:
        db.delete(unit)
        db.flush()

    for item_id in source_asset_ids:
        still_referenced = (
            db.query(PersonalAssetUnit)
            .filter(PersonalAssetUnit.source_asset_ids.is_not(None))
            .all()
        )
        if any(_unit_references_item(other_unit, item_id) for other_unit in still_referenced):
            continue
        item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id).one_or_none()
        if item is not None:
            db.delete(item)

    file_row.deleted_at = local_now()
    job = KnowledgeJobService(db).create(
        JobCommand("delete", tenant_id, file_row.kb_uid, file_row.file_uid, {"source_kind": PERSONAL_ASSET_UNIT_SOURCE_KIND}),
        f"{file_row.kb_uid}:{file_row.file_uid}:delete",
        commit=False,
    )
    file_row.last_job_id = job.id
    db.flush()
    return job
```

- [ ] **Step 4: Route API delete**

In `backend/app/api/knowledge_files.py`, inside `delete_file` after `file_row = _require_file(...)`, add:

```python
    if file_row.system_type == "personal_inbox" and file_row.source_kind == "personal_asset_unit":
        from backend.app.services.personal_inbox import delete_personal_inbox_file_cascade
        job = delete_personal_inbox_file_cascade(db, file_row, tenant_id=actor.tenant_id)
        db.commit()
        _publish_job(db, job)
        db.refresh(job)
        return _job_snapshot(job)
```

Keep the existing ordinary file delete path below this branch.

- [ ] **Step 5: Add API test**

Add to `backend/tests/test_knowledge_files_v1_api.py`:

```python
def test_delete_personal_inbox_file_cascades_asset_unit(client, db_session, monkeypatch):
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    item = PersonalAssetItem(id="item-a", user_id="default-user", raw_text="raw", title="Item", status="confirmed")
    unit = PersonalAssetUnit(id="unit-a", user_id="default-user", title="Unit", content="Content", source_asset_ids=["item-a"], status="confirmed")
    db_session.add_all([item, unit])
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="default-tenant",
        owner_user_id="default-user",
        publish=False,
    )

    response = client.delete(f"/api/v1/knowledge-bases/{file_row.kb_uid}/files/{file_row.file_uid}")

    assert response.status_code == 202
    assert db_session.query(PersonalAssetUnit).filter_by(id="unit-a").first() is None
    assert db_session.query(PersonalAssetItem).filter_by(id="item-a").first() is None
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py::test_delete_personal_inbox_file_deletes_unit_and_orphan_item backend/tests/test_personal_inbox_service.py::test_delete_personal_inbox_file_preserves_shared_item backend/tests/test_knowledge_files_v1_api.py::test_delete_personal_inbox_file_cascades_asset_unit -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/personal_inbox.py backend/app/api/knowledge_files.py backend/tests/test_personal_inbox_service.py backend/tests/test_knowledge_files_v1_api.py
git commit -m "feat(knowledge): cascade delete personal inbox files"
```

---

### Task 7: Add chat authorization switch on Backend

**Files:**
- Modify: `backend/app/api/agent_chat_proxy.py`
- Test: `backend/tests/test_agent_chat_proxy.py`

- [ ] **Step 1: Write failing proxy test**

Add:

```python
def test_chat_proxy_appends_personal_inbox_scope_when_requested(client, db_session, monkeypatch):
    from backend.app.models import KnowledgeTopic
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb
    from backend.app.api import agent_chat_proxy

    main = KnowledgeTopic(
        tenant_id="default-tenant",
        owner_user_id="default-user",
        name="Main KB",
    )
    db_session.add(main)
    inbox = ensure_personal_inbox_kb(db_session, tenant_id="default-tenant", owner_user_id="default-user")
    db_session.commit()

    captured = {}

    async def fake_stream_engine_answer(signed_token, payload):
        captured["signed_token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done","data":{}}\\n'

    monkeypatch.setattr(agent_chat_proxy, "stream_engine_answer", fake_stream_engine_answer)
    monkeypatch.setattr(agent_chat_proxy.settings, "KNOWLEDGE_SCOPE_SECRET", "secret")

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "hello", "kb_uids": [main.kb_uid], "include_personal_inbox": True},
    )

    assert response.status_code == 200
    from backend.app.security.knowledge_scope import verify_scope
    scope = verify_scope(captured["signed_token"], "secret")
    assert main.kb_uid in scope.allowed_kb_uids
    assert inbox.kb_uid in scope.allowed_kb_uids
    assert captured["payload"]["include_personal_inbox"] is True
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest backend/tests/test_agent_chat_proxy.py::test_chat_proxy_appends_personal_inbox_scope_when_requested -v
```

Expected: FAIL because `include_personal_inbox` is forbidden by `extra="forbid"`.

- [ ] **Step 3: Update request and payload**

In `ChatAnswerRequest`, add:

```python
    include_personal_inbox: bool = False
```

In `_public_payload`, add:

```python
        "include_personal_inbox": req.include_personal_inbox,
```

- [ ] **Step 4: Append personal inbox KB server-side**

Add helper:

```python
def _append_personal_inbox_kb(db: Session, actor: ActorContext, allowed_kb_uids: list[str]) -> list[str]:
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb
    inbox = ensure_personal_inbox_kb(db, tenant_id=actor.tenant_id, owner_user_id=actor.actor_id)
    if inbox.kb_uid not in allowed_kb_uids:
        allowed_kb_uids.append(inbox.kb_uid)
    return allowed_kb_uids
```

In `chat_answer_proxy`, after `allowed_kb_uids = _authorize_kbs(...)`, add:

```python
    if req.include_personal_inbox:
        allowed_kb_uids = _append_personal_inbox_kb(db, actor, allowed_kb_uids)
        db.commit()
```

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest backend/tests/test_agent_chat_proxy.py::test_chat_proxy_appends_personal_inbox_scope_when_requested -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/agent_chat_proxy.py backend/tests/test_agent_chat_proxy.py
git commit -m "feat(chat): authorize personal inbox KB on request"
```

---

### Task 8: Make `query_kb` search all authorized KBs by default

**Files:**
- Modify: `engine/app/agent/tools/knowledge_base.py`
- Test: `engine/tests/test_knowledge_base_tools.py`

- [ ] **Step 1: Write failing tool test**

Add:

```python
def test_query_kb_defaults_to_all_authorized_kbs_when_multiple_scoped():
    from engine.app.agent.tools.base import ToolContext
    from engine.app.agent.tools.knowledge_base import build_tools

    class Scope:
        tenant_id = "tenant-a"
        allowed_kb_uids = ("kb-main", "kb-inbox")
        run_id = "run-a"

    class Retrieval:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "status": "ok",
                "evidence": [{
                    "kb_uid": kwargs["kb_uid"],
                    "file_uid": f"file-{kwargs['kb_uid']}",
                    "chunk_uid": f"chunk-{kwargs['kb_uid']}",
                    "excerpt": f"evidence {kwargs['kb_uid']}",
                }],
            }

    class Query:
        def filter(self, *args, **kwargs):
            return self
        def order_by(self, *args, **kwargs):
            return self
        def all(self):
            return []

    class DB:
        def query(self, *args, **kwargs):
            return Query()

    retrieval = Retrieval()
    ctx = ToolContext(db=DB(), knowledge_scope=Scope(), retrieval_service=retrieval, trace_id="trace-a")
    tool = build_tools(ctx)["query_kb"]

    result = tool.invoke({"query_text": "question"})

    assert result["status"] == "ok"
    assert [call["kb_uid"] for call in retrieval.calls] == ["kb-main", "kb-inbox"]
    assert {item["kb_uid"] for item in result["data"]["evidence"]} == {"kb-main", "kb-inbox"}
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
python -m pytest engine/tests/test_knowledge_base_tools.py::test_query_kb_defaults_to_all_authorized_kbs_when_multiple_scoped -v
```

Expected: FAIL because current `_resolve_allowed_kb` requires `kb_uid` when multiple KBs are authorized.

- [ ] **Step 3: Add target-KB resolver**

In `engine/app/agent/tools/knowledge_base.py`, add:

```python
def _resolve_target_kbs(ctx: ToolContext, kb_uid: str | None) -> tuple[Any, tuple[str, ...]]:
    scope = _require_scope(ctx)
    normalized = (kb_uid or "").strip()
    if normalized and normalized not in {"default", "all"}:
        if normalized not in scope.allowed_kb_uids:
            raise KnowledgeToolDenied(normalized)
        return scope, (normalized,)
    return scope, tuple(scope.allowed_kb_uids)
```

- [ ] **Step 4: Update `query_kb` relevance path**

In `_build_query_kb.run`, replace:

```python
            scope, resolved_kb_uid = _resolve_allowed_kb(ctx, kb_uid)
```

with:

```python
            scope, target_kb_uids = _resolve_target_kbs(ctx, kb_uid)
```

For `coverage == "per_file"`, reject all-KB coverage unless exactly one KB is targeted:

```python
            if coverage == "per_file" and len(target_kb_uids) != 1:
                raise KnowledgeToolInvalidRequest("coverage='per_file' requires a single kb_uid")
```

For the normal relevance path, loop over all target KBs:

```python
            evidence: list[EvidenceItem] = []
            retrieval_health: dict[str, Any] = {}
            warnings: list[ToolWarning] = []
            status_values: list[str] = []
            for resolved_kb_uid in target_kb_uids:
                response = retrieval.query(
                    tenant_id=scope.tenant_id,
                    kb_uid=resolved_kb_uid,
                    query=query_text,
                    mode="deep" if mode == "deep" else "fast",
                    file_uids=(),
                    top_k=10,
                )
                status_values.append(str(response.get("status") or "ok"))
                for warning in _warnings_from_response(response):
                    warnings.append(warning)
                health = response.get("retrieval_health")
                if isinstance(health, dict):
                    _merge_retrieval_health(retrieval_health, health)
                for item in response.get("evidence") or []:
                    if isinstance(item, dict):
                        evidence.append(_evidence_item_from_raw(item))
            data = QueryKbData(evidence=evidence, retrieval_health=retrieval_health)
            if all(status == "unavailable" for status in status_values):
                return ToolEnvelope.from_error(
                    ToolProblem(code="RETRIEVAL_UNAVAILABLE", message="retrieval is unavailable", retryable=True),
                    _trace(ctx),
                ).model_dump()
            if not evidence:
                return ToolEnvelope.no_hits(data, _trace(ctx)).model_dump()
            if warnings or any(status in {"degraded", "unavailable", "invalid_request"} for status in status_values):
                return ToolEnvelope.degraded(data, warnings, _trace(ctx)).model_dump()
            return ToolEnvelope.ok(data, _trace(ctx)).model_dump()
```

Keep the existing per-file coverage branch but use `resolved_kb_uid = target_kb_uids[0]`.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest engine/tests/test_knowledge_base_tools.py::test_query_kb_defaults_to_all_authorized_kbs_when_multiple_scoped -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add engine/app/agent/tools/knowledge_base.py engine/tests/test_knowledge_base_tools.py
git commit -m "feat(agent): query all authorized KBs by default"
```

---

### Task 9: Add Frontend chat switch and system KB display

**Files:**
- Modify: `frontend/src/features/knowledge/api/knowledgeBases.ts`
- Modify: `frontend/src/features/knowledge/api/files.ts`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/tests/chat-personal-inbox.test.mjs`
- Test: `frontend/tests/knowledge-file-stage-updates.test.mjs` or existing knowledge page test

- [ ] **Step 1: Update API types**

In `frontend/src/features/knowledge/api/knowledgeBases.ts`, extend `KnowledgeBase`:

```ts
  system_type: string | null
  is_system: boolean
  delete_disabled: boolean
```

In `frontend/src/features/knowledge/api/files.ts`, extend file DTO:

```ts
  source_kind?: string | null
  source_id?: string | null
  system_type?: string | null
```

- [ ] **Step 2: Add chat request test**

Create `frontend/tests/chat-personal-inbox.test.mjs` with a DOM or store-level test matching the existing frontend test style:

```js
import assert from 'node:assert/strict'

function buildChatPayload({ query, kbUid, includePersonalInbox }) {
  return {
    query,
    kb_uids: [kbUid],
    history: [],
    mode: 'standard',
    include_personal_inbox: includePersonalInbox,
  }
}

assert.deepEqual(
  buildChatPayload({ query: 'q', kbUid: 'kb-a', includePersonalInbox: false }),
  { query: 'q', kb_uids: ['kb-a'], history: [], mode: 'standard', include_personal_inbox: false },
)

assert.deepEqual(
  buildChatPayload({ query: 'q', kbUid: 'kb-a', includePersonalInbox: true }),
  { query: 'q', kb_uids: ['kb-a'], history: [], mode: 'standard', include_personal_inbox: true },
)
```

If the project has a helper for ChatPage payload construction, move this helper into `frontend/src/app/chatPayload.ts` and test that helper instead of duplicating logic.

- [ ] **Step 3: Add ChatPage switch**

In `frontend/src/pages/ChatPage.tsx`, add state near other chat options:

```ts
const [includePersonalInbox, setIncludePersonalInbox] = useState(false)
```

Render near the deep search controls:

```tsx
<label className="flex items-center gap-2 text-xs text-slate-600">
  <input
    type="checkbox"
    checked={includePersonalInbox}
    onChange={(event) => setIncludePersonalInbox(event.target.checked)}
  />
  包含个人随手记
</label>
```

In the fetch body, add:

```ts
include_personal_inbox: includePersonalInbox,
```

- [ ] **Step 4: Mark system KB and disable delete**

In the knowledge page where KB actions are rendered, compute:

```ts
const isSystemKb = activeKb?.is_system || activeKb?.delete_disabled
```

Show label:

```tsx
{isSystemKb ? <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">系统库</span> : null}
```

Disable delete:

```tsx
disabled={isSystemKb}
title={isSystemKb ? '系统知识库不可删除' : undefined}
```

- [ ] **Step 5: Add derived-file cascade delete confirmation**

In `KnowledgeFilesPage.tsx`, before delete confirmation for a file, branch:

```ts
const isPersonalInboxFile =
  file.system_type === 'personal_inbox' && file.source_kind === 'personal_asset_unit'
const message = isPersonalInboxFile
  ? '此文件由个人资产单元生成。删除后将同时删除对应的个人资产单元；若其来源碎片未被其他资产单元引用，也会一并删除。此操作会清理相关检索索引。'
  : '确认删除该文件？'
```

Use the existing confirm dialog or `window.confirm(message)` if that page currently uses browser confirmation.

- [ ] **Step 6: Run frontend tests/build**

Run:

```powershell
node frontend/tests/chat-personal-inbox.test.mjs
cd frontend
npm.cmd run build
```

Expected: test exits 0 and build succeeds.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/features/knowledge/api/knowledgeBases.ts frontend/src/features/knowledge/api/files.ts frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx frontend/src/pages/ChatPage.tsx frontend/tests/chat-personal-inbox.test.mjs
git commit -m "feat(frontend): add personal inbox chat switch"
```

---

### Task 10: Final integration verification

**Files:**
- No code changes expected.
- Use existing tests and local containers only if runtime verification is requested.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
python -m pytest backend/tests/test_personal_inbox_service.py backend/tests/test_knowledge_bases_v1_api.py backend/tests/test_knowledge_files_v1_api.py backend/tests/test_agent_chat_proxy.py -v
```

Expected: PASS.

- [ ] **Step 2: Run focused engine tests**

Run:

```powershell
python -m pytest engine/tests/test_knowledge_base_tools.py -v
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 4: Runtime smoke test using only knowledge-system-full containers**

Do not start any `prism-*` or extra empty container group. Use only the user's approved `knowledge-system-full-*` compose stack.

Run:

```powershell
docker compose ps
```

Expected: services are the `knowledge-system-full-*` stack.

Manual smoke path:

1. Open the frontend.
2. Confirm `个人随手记` appears in the KB list and has a system label.
3. Create/confirm a `PersonalAssetUnit`.
4. Confirm a `.md` file appears in `个人随手记`.
5. Preview/download the `.md`.
6. Ask a chat question with `包含个人随手记` off and confirm the personal inbox is not used.
7. Ask the same question with the switch on and confirm personal inbox evidence can appear.
8. Delete the derived `.md` and confirm the Unit and orphan Items are gone.

- [ ] **Step 5: Commit any verification-only fixture updates**

If tests require deterministic fixture changes, commit them:

```powershell
git add <exact fixture files>
git commit -m "test(knowledge): cover personal inbox integration"
```

If no files changed, do not create an empty commit.

---

## Self-Review

Spec coverage:

- System visible non-deletable KB: Tasks 1, 3, 9.
- Only confirmed `PersonalAssetUnit` sync: Tasks 2, 4, 5.
- Stable Markdown file per Unit: Task 2.
- Backfill existing confirmed Units: Task 5.
- Markdown content includes Unit plus Item summary/rewritten content, not raw text: Task 2.
- Explicit chat switch: Tasks 7, 9.
- Backend appends personal inbox KB server-side: Task 7.
- `query_kb` searches all authorized KBs by default: Task 8.
- Derived file cascade deletes Unit and orphan Items: Task 6.
- Preview/download through ordinary file path: Task 2 creates normal `KnowledgeFile`; Task 9 preserves normal UI.
- No separate primary `asset_search` tool: no task adds one.

Red-flag wording scan:

- This plan contains no unresolved implementation markers.
- Where existing code structure may vary, the plan names the exact file and exact behavior to preserve.

Type consistency:

- System KB marker uses `KnowledgeTopic.system_type == "personal_inbox"`.
- Derived file marker uses `KnowledgeFile.system_type == "personal_inbox"` and `KnowledgeFile.source_kind == "personal_asset_unit"`.
- Chat request field is `include_personal_inbox`.
- Frontend API field names match Backend response/request field names.
