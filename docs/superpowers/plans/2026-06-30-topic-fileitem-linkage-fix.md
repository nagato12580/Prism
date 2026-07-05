# Topic FileItem Linkage Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every uploaded document that belongs to a topic has a `KnowledgeFile` row with original file metadata, `topic_id`, and `item_id`, while chunks continue to be created from `KnowledgeItem.content`.

**Architecture:** Keep the canonical relationship as `KnowledgeTopic -> KnowledgeFile -> KnowledgeItem -> KnowledgeChunk`. `KnowledgeFile` owns topic membership and original resource metadata; `KnowledgeItem` owns parsed text for chunking and retrieval; `KnowledgeChunk` points only to `KnowledgeItem`. Legacy `/upload/file` should either create the same linkage when `topic_id` is provided or be treated as unscoped global upload when no topic is provided.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Pydantic schemas, pytest, React/TypeScript API client.

---

## File Structure

- Modify: `backend/app/api/upload.py`
  - Add optional `topic_id` form field to legacy file upload.
  - Validate topic ownership when `topic_id` is present.
  - Create `KnowledgeFile` with complete resource metadata: `user_id`, `topic_id`, `item_id`, `title`, `original_filename`, `media_type`, `mime_type`, `file_ext`, `file_size`, `md5`, `storage_path`, `processing_status`, `source_type`, `content_text`.
- Modify: `backend/tests/test_knowledge_api.py`
  - Add regression coverage for legacy upload with `topic_id`.
  - Add coverage for invalid `topic_id`.
  - Add coverage confirming topic-scoped resource upload already keeps the intended relationship.
- Modify: `frontend/src/app/api.ts`
  - Make legacy `knowledgeApi.uploadFile` accept optional `topicId` only if still needed by any caller.
  - Prefer `knowledgeApi.uploadResource(topicId, file)` for topic pages.
- Optional create: `backend/app/scripts/backfill_file_topic_links.py`
  - Only if existing production data has orphaned `KnowledgeFile` rows that can be safely linked by `KnowledgeItem.category` or another explicit rule.
- Optional test: `backend/tests/test_backfill_file_topic_links.py`
  - Only if the backfill script is created.

---

### Task 1: Document the Intended Table Relationship in Tests

**Files:**
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write the failing regression test**

Add this test near the existing topic resource upload tests:

```python
def test_legacy_file_upload_with_topic_id_links_file_item_to_topic(client, db_session, monkeypatch):
    topic = _create_topic(client, "Legacy Uploads")
    called = []
    monkeypatch.setattr("backend.app.api.upload._trigger_ingestion", lambda item_id: called.append(item_id))

    response = client.post(
        "/api/v1/upload/file",
        files={"file": ("legacy.txt", b"legacy document", "text/plain")},
        data={"topic_id": topic["id"]},
    )

    assert response.status_code == 200
    item = response.json()
    resource = db_session.query(KnowledgeFile).filter_by(item_id=item["id"]).one()
    assert resource.topic_id == topic["id"]
    assert resource.user_id == "default-user"
    assert resource.title == "legacy"
    assert resource.original_filename == "legacy.txt"
    assert resource.media_type == "document"
    assert resource.mime_type == "text/plain"
    assert resource.file_ext == ".txt"
    assert resource.md5
    assert resource.content_text == "legacy document"
    assert called == [item["id"]]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest backend/tests/test_knowledge_api.py::test_legacy_file_upload_with_topic_id_links_file_item_to_topic -v
```

Expected: FAIL because `/api/v1/upload/file` currently ignores `topic_id`, so `resource.topic_id` is `None`.

- [ ] **Step 3: Add invalid topic coverage**

Add this test in the same file:

```python
def test_legacy_file_upload_rejects_unknown_topic_id(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.upload._trigger_ingestion", lambda item_id: None)

    response = client.post(
        "/api/v1/upload/file",
        files={"file": ("legacy.txt", b"legacy document", "text/plain")},
        data={"topic_id": "missing-topic"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "topic_not_found"
```

- [ ] **Step 4: Run the invalid topic test**

Run:

```bash
pytest backend/tests/test_knowledge_api.py::test_legacy_file_upload_rejects_unknown_topic_id -v
```

Expected: FAIL because the endpoint currently accepts the upload and does not validate `topic_id`.

---

### Task 2: Fix Legacy File Upload Linkage

**Files:**
- Modify: `backend/app/api/upload.py`

- [ ] **Step 1: Add imports and constants**

Update the imports near the top of `backend/app/api/upload.py`:

```python
import hashlib
import threading
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import httpx

from ..database import get_db
from ..config import settings
from ..models.knowledge_item import KnowledgeItem, KnowledgeFile, KnowledgeTopic
from ..utils.file_parser import extract_text, extract_url
from ..schemas.knowledge import KnowledgeItemOut
```

Add this constant below `UPLOAD_DIR`:

```python
DEFAULT_USER_ID = "default-user"
```

- [ ] **Step 2: Add a local topic lookup helper**

Add this helper above `upload_file`:

```python
def _get_topic_or_404(topic_id: str | None, db: Session) -> KnowledgeTopic | None:
    if not topic_id:
        return None
    topic = db.query(KnowledgeTopic).filter(
        KnowledgeTopic.id == topic_id,
        KnowledgeTopic.user_id == DEFAULT_USER_ID,
    ).first()
    if not topic:
        raise HTTPException(
            status_code=404,
            detail={"code": "topic_not_found", "message": "Topic not found"},
        )
    return topic
```

- [ ] **Step 3: Accept `topic_id` and write complete `KnowledgeFile` metadata**

Change the `upload_file` signature and the `KnowledgeFile` creation block:

```python
@router.post("/file", response_model=KnowledgeItemOut)
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form(None),
    topic_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    topic = _get_topic_or_404(topic_id, db)
    ext = Path(file.filename).suffix
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".markdown"}
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content_bytes = await file.read()
    md5 = hashlib.md5(content_bytes).hexdigest()
    saved_path.write_bytes(content_bytes)

    try:
        text = extract_text(str(saved_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

    title = Path(file.filename).stem
    item = KnowledgeItem(
        title=title,
        content=text,
        source_type="file",
        source_ref=str(saved_path),
        tags=[],
        category=category or (topic.name if topic else None),
        user_id=DEFAULT_USER_ID,
    )
    db.add(item)
    db.flush()

    kfile = KnowledgeFile(
        user_id=DEFAULT_USER_ID,
        topic_id=topic.id if topic else None,
        item_id=item.id,
        title=title,
        original_filename=file.filename,
        media_type="document",
        mime_type=file.content_type,
        file_ext=ext.lower(),
        file_size=len(content_bytes),
        md5=md5,
        storage_path=str(saved_path),
        processing_status="done",
        source_type="upload",
        content_text=text,
    )
    db.add(kfile)
    db.commit()

    _trigger_ingestion(item.id)

    db.refresh(item)
    return item
```

This preserves the old response shape while making the topic linkage discoverable through `KnowledgeFile`.

- [ ] **Step 4: Run the targeted legacy upload tests**

Run:

```bash
pytest backend/tests/test_knowledge_api.py::test_legacy_file_upload_with_topic_id_links_file_item_to_topic backend/tests/test_knowledge_api.py::test_legacy_file_upload_rejects_unknown_topic_id -v
```

Expected: PASS.

---

### Task 3: Confirm the Preferred Topic Resource Path Still Works

**Files:**
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Strengthen the existing resource upload test**

In `test_upload_document_resource_creates_item`, add assertions after `resource = response.json()`:

```python
assert resource["topic_id"] == topic["id"]
assert resource["original_filename"] == "notes.txt"
assert resource["storage_path"]
assert resource["md5"]
```

- [ ] **Step 2: Run the resource upload test**

Run:

```bash
pytest backend/tests/test_knowledge_api.py::test_upload_document_resource_creates_item -v
```

Expected: PASS. If this fails, fix `backend/app/api/knowledge.py` without changing the table relationship.

---

### Task 4: Align Frontend API Naming With the Relationship

**Files:**
- Modify: `frontend/src/app/api.ts`
- Inspect: `frontend/src/pages/KnowledgePage.tsx`

- [ ] **Step 1: Confirm topic page uses resource upload**

Run:

```bash
rg -n "uploadResource|uploadFile\\(" frontend/src/pages frontend/src/app/api.ts
```

Expected: `KnowledgePage.tsx` uses `knowledgeApi.uploadResource(activeTopicId, file)` for topic uploads.

- [ ] **Step 2: If legacy upload still needs topic support, extend the API method**

Change only `knowledgeApi.uploadFile` in `frontend/src/app/api.ts`:

```ts
uploadFile: async (file: File, category?: string, topicId?: string): Promise<KnowledgeItem> => {
  const form = new FormData()
  form.append('file', file)
  if (category) form.append('category', category)
  if (topicId) form.append('topic_id', topicId)
  return uploadRequest<KnowledgeItem>('/upload/file', form)
},
```

If no caller needs legacy topic upload, skip this code change and leave the frontend using `uploadResource` for topic pages.

- [ ] **Step 3: Run frontend typecheck**

Run:

```bash
cd frontend
pnpm build
```

Expected: TypeScript build passes.

---

### Task 5: Verify Retrieval and Queue Assumptions

**Files:**
- Test only: `backend/tests/test_knowledge_job_queue.py`
- Test only: `engine/tests/test_ingestion_governance.py`
- Test only: `engine/tests/test_ingest_workers.py`

- [ ] **Step 1: Run backend topic/resource tests**

Run:

```bash
pytest backend/tests/test_knowledge_api.py backend/tests/test_knowledge_job_queue.py -v
```

Expected: PASS.

- [ ] **Step 2: Run ingestion tests that rely on `KnowledgeFile.item_id`**

Run:

```bash
pytest engine/tests/test_ingestion_governance.py engine/tests/test_ingest_workers.py -v
```

Expected: PASS.

- [ ] **Step 3: Manually verify the data path in one local upload**

Start the backend if needed:

```bash
python -m backend.run
```

Then upload a text file to a topic from the Knowledge page. Confirm in the database:

```sql
SELECT id, topic_id, item_id, title, original_name, file_path, md5
FROM knowledge_file
WHERE topic_id = '<topic id>'
ORDER BY created_at DESC
LIMIT 1;
```

Expected: `topic_id` and `item_id` are both non-null for document uploads.

---

### Task 6: Optional Backfill for Existing Orphaned Rows

Only do this task if local or production data already contains uploaded files that should belong to a topic but have `knowledge_file.topic_id IS NULL`.

**Files:**
- Create: `backend/app/scripts/backfill_file_topic_links.py`
- Create: `backend/tests/test_backfill_file_topic_links.py`

- [ ] **Step 1: Decide the explicit backfill rule**

Use this rule only if it matches real data:

```text
If KnowledgeFile.item_id points to a KnowledgeItem whose category exactly equals a KnowledgeTopic.name for the same user, set KnowledgeFile.topic_id to that topic id.
```

Do not infer from fuzzy title matching.

- [ ] **Step 2: Create the script**

Create `backend/app/scripts/backfill_file_topic_links.py`:

```python
from backend.app.database import SessionLocal
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic


def backfill_topic_links(dry_run: bool = True) -> int:
    db = SessionLocal()
    changed = 0
    try:
        files = (
            db.query(KnowledgeFile)
            .filter(KnowledgeFile.topic_id.is_(None), KnowledgeFile.item_id.isnot(None))
            .all()
        )
        for resource in files:
            item = db.query(KnowledgeItem).filter(KnowledgeItem.id == resource.item_id).first()
            if not item or not item.category:
                continue
            topic = db.query(KnowledgeTopic).filter(
                KnowledgeTopic.user_id == resource.user_id,
                KnowledgeTopic.name == item.category,
            ).first()
            if not topic:
                continue
            changed += 1
            if not dry_run:
                resource.topic_id = topic.id
        if not dry_run:
            db.commit()
        return changed
    finally:
        db.close()


if __name__ == "__main__":
    count = backfill_topic_links(dry_run=True)
    print(f"dry_run matched {count} resources")
```

- [ ] **Step 3: Add a unit test for the backfill rule**

Create `backend/tests/test_backfill_file_topic_links.py`:

```python
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic
from backend.app.scripts.backfill_file_topic_links import backfill_topic_links


def test_backfill_links_file_to_topic_by_item_category(db_session, monkeypatch):
    topic = KnowledgeTopic(user_id="default-user", name="Research")
    item = KnowledgeItem(
        user_id="default-user",
        title="Paper",
        content="text",
        source_type="file",
        category="Research",
    )
    db_session.add_all([topic, item])
    db_session.flush()
    resource = KnowledgeFile(
        user_id="default-user",
        item_id=item.id,
        title="Paper",
        original_filename="paper.txt",
        media_type="document",
        file_ext=".txt",
        file_size=4,
        md5="abcd",
        storage_path="/tmp/paper.txt",
    )
    db_session.add(resource)
    db_session.commit()

    class FakeSessionFactory:
        def __call__(self):
            return db_session

    monkeypatch.setattr(
        "backend.app.scripts.backfill_file_topic_links.SessionLocal",
        FakeSessionFactory(),
    )

    assert backfill_topic_links(dry_run=False) == 1
    db_session.refresh(resource)
    assert resource.topic_id == topic.id
```

- [ ] **Step 4: Run the backfill test**

Run:

```bash
pytest backend/tests/test_backfill_file_topic_links.py -v
```

Expected: PASS.

---

### Task 7: Final Verification and Commit

**Files:**
- All modified files.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
pytest backend/tests/test_knowledge_api.py backend/tests/test_knowledge_job_queue.py -v
```

Expected: PASS.

- [ ] **Step 2: Run targeted engine tests**

Run:

```bash
pytest engine/tests/test_ingestion_governance.py engine/tests/test_ingest_workers.py -v
```

Expected: PASS.

- [ ] **Step 3: Run frontend build if `frontend/src/app/api.ts` changed**

Run:

```bash
cd frontend
pnpm build
```

Expected: PASS.

- [ ] **Step 4: Review the diff**

Run:

```bash
git diff -- backend/app/api/upload.py backend/tests/test_knowledge_api.py frontend/src/app/api.ts backend/app/scripts/backfill_file_topic_links.py backend/tests/test_backfill_file_topic_links.py
```

Expected: Diff only changes legacy upload linkage, tests, optional frontend helper, and optional backfill.

- [ ] **Step 5: Commit**

Run:

```bash
git add backend/app/api/upload.py backend/tests/test_knowledge_api.py frontend/src/app/api.ts
git commit -m "fix: link legacy uploads to knowledge topics"
```

If the optional backfill was added, include it:

```bash
git add backend/app/scripts/backfill_file_topic_links.py backend/tests/test_backfill_file_topic_links.py
git commit -m "chore: add knowledge file topic backfill"
```

---

## Self-Review

- Spec coverage: The plan preserves `KnowledgeFile` as the original resource metadata table, keeps chunking through `KnowledgeItem`, and fixes the missing topic link for legacy uploads.
- Placeholder scan: No implementation step relies on unspecified validation or unnamed tests.
- Type consistency: The plan uses existing model fields: `KnowledgeFile.topic_id`, `KnowledgeFile.item_id`, `KnowledgeFile.original_filename`, `KnowledgeFile.file_ext`, `KnowledgeFile.storage_path`, and `KnowledgeItem.content`.
