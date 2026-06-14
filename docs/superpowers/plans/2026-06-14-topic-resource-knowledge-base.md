# Topic Resource Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a topic-first knowledge base where users create topics, upload one resource button per topic, the backend auto-detects media type, documents enter the existing RAG ingestion path, and image/audio/video resources store metadata only.

**Architecture:** Add `KnowledgeTopic` as the topic boundary and extend `KnowledgeFile` into the canonical uploaded resource table. Keep `KnowledgeItem` as the document entity consumed by the existing engine ingestion pipeline. Replace the current frontend local-directory grouping with API-backed topics and resources.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, pytest, React 18, TypeScript, Vite, Tailwind CSS, lucide-react.

---

## File Structure

- Modify: `backend/app/models/knowledge_item.py`
  - Add `KnowledgeTopic`.
  - Extend `KnowledgeFile` with topic/resource metadata fields and relationships.
- Modify: `backend/app/models/__init__.py`
  - Export `KnowledgeTopic`.
- Modify: `backend/app/schemas/knowledge.py`
  - Add topic and resource request/response schemas.
- Modify: `backend/app/api/knowledge.py`
  - Keep current item CRUD.
  - Add topic CRUD endpoints.
  - Add resource upload/list/get/delete endpoints.
- Create: `backend/app/utils/media_type.py`
  - Infer `document`, `image`, `audio`, `video` from extension and MIME type.
  - Expose supported upload extensions for frontend parity.
- Modify: `backend/app/utils/file_parser.py`
  - Add `.doc` unsupported parse message while keeping metadata support available through upload validation.
  - Add `count_pages()` helper used by resource metadata.
- Modify: `backend/app/utils/auto_migrate.py`
  - Add missing unique constraints/index creation support only for this feature's known constraints.
- Modify: `backend/tests/test_models.py`
  - Cover topic/resource relationships and uniqueness.
- Modify: `backend/tests/test_knowledge_api.py`
  - Cover topic CRUD, upload dedupe, media filters, metadata-only uploads, and delete conflict.
- Modify: `frontend/src/app/api.ts`
  - Add `KnowledgeTopic`, `KnowledgeResource`, and topic/resource API calls.
  - Keep legacy `KnowledgeItem` API for manual text notes.
- Modify: `frontend/src/pages/KnowledgePage.tsx`
  - Render topic sidebar and selected topic resource workspace.
  - Use one upload button inside a topic.
  - Add media type filters and duplicate error display.
- Create: `frontend/tests/knowledge-topic-resource.test.mjs`
  - Static regression checks for the new page/API wiring.

---

### Task 1: Backend Model And Schema Foundation

**Files:**
- Modify: `backend/app/models/knowledge_item.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/knowledge.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append these tests to `backend/tests/test_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic, KnowledgeChunk, ChatSession, ChatMessage


def test_topic_resource_relationship_and_metadata(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Product Docs", description="Launch files")
    db_session.add(topic)
    db_session.commit()

    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="Roadmap",
        original_filename="roadmap.md",
        media_type="document",
        mime_type="text/markdown",
        file_ext=".md",
        file_size=18,
        md5="md5-roadmap",
        storage_path="uploads/default-user/topic/roadmap.md",
        processing_status="completed",
        description="Q3 notes",
        tags=["roadmap", "q3"],
        source_type="upload",
        page_count=1,
        content_text="# Roadmap",
    )
    db_session.add(resource)
    db_session.commit()

    loaded = db_session.query(KnowledgeTopic).filter_by(name="Product Docs").one()
    assert loaded.resources[0].title == "Roadmap"
    assert loaded.resources[0].tags == ["roadmap", "q3"]
    assert loaded.resources[0].uploaded_at is not None


def test_duplicate_resource_md5_is_rejected_per_user_topic(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Research")
    db_session.add(topic)
    db_session.commit()

    first = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A",
        original_filename="a.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a.txt",
        processing_status="completed",
    )
    second = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A Copy",
        original_filename="a-copy.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a-copy.txt",
        processing_status="completed",
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_models.py -q
```

Expected: FAIL with an import error for `KnowledgeTopic` or missing fields on `KnowledgeFile`.

- [ ] **Step 3: Add models**

In `backend/app/models/knowledge_item.py`, update imports:

```python
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, synonym
```

Insert `KnowledgeTopic` before `KnowledgeItem`:

```python
class KnowledgeTopic(Base):
    __tablename__ = "knowledge_topic"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_knowledge_topic_user_name"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, comment="User id")
    name = Column(String(255), nullable=False, comment="Topic name")
    description = Column(Text, comment="Topic description")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resources = relationship("KnowledgeFile", back_populates="topic", cascade="all, delete-orphan")
```

Replace the existing `KnowledgeFile` class with:

```python
class KnowledgeFile(Base):
    __tablename__ = "knowledge_file"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", "md5", name="uq_knowledge_file_user_topic_md5"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, comment="User id")
    topic_id = Column(CHAR(36), ForeignKey("knowledge_topic.id", ondelete="CASCADE"), nullable=True)
    item_id = Column(CHAR(36), ForeignKey("knowledge_item.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False, default="", comment="Resource title")
    original_filename = Column("original_name", String(255), nullable=False, default="", comment="Original filename")
    media_type = Column(String(20), nullable=False, default="document", comment="document/image/audio/video")
    mime_type = Column(String(100), comment="MIME type")
    file_ext = Column("file_type", String(20), nullable=False, default="", comment="File extension")
    file_size = Column(Integer, default=0, comment="File size in bytes")
    md5 = Column(String(32), nullable=False, default="", comment="File MD5")
    storage_path = Column("file_path", String(500), nullable=False, default="", comment="Stored file path")
    processing_status = Column("parse_status", String(20), default="pending", comment="pending/processing/completed/failed/metadata_only")
    description = Column(Text, comment="Resource description")
    tags = Column(JSON, comment="Tags")
    source_type = Column(String(20), default="upload", comment="upload")
    page_count = Column(Integer, nullable=True, comment="Document page count")
    content_text = Column(Text, comment="Parsed text")
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    last_modified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_message = Column(Text, comment="Processing error")

    topic = relationship("KnowledgeTopic", back_populates="resources")
    item = relationship("KnowledgeItem")
    original_name = synonym("original_filename")
    file_path = synonym("storage_path")
    file_type = synonym("file_ext")
    parse_status = synonym("processing_status")
```

- [ ] **Step 4: Export the model**

Replace `backend/app/models/__init__.py` with:

```python
# prism/backend/app/models/__init__.py
from .knowledge_item import KnowledgeTopic, KnowledgeItem, KnowledgeChunk, KnowledgeFile
from .chat import ChatSession, ChatMessage

__all__ = [
    "KnowledgeTopic",
    "KnowledgeItem",
    "KnowledgeChunk",
    "KnowledgeFile",
    "ChatSession",
    "ChatMessage",
]
```

- [ ] **Step 5: Add schemas**

Append to `backend/app/schemas/knowledge.py`:

```python
from typing import Literal


class KnowledgeTopicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeTopicOut(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    resource_count: int = 0

    class Config:
        from_attributes = True


class KnowledgeResourceOut(BaseModel):
    id: str
    user_id: str
    topic_id: Optional[str]
    item_id: Optional[str]
    title: str
    original_filename: str
    media_type: Literal["document", "image", "audio", "video"]
    mime_type: Optional[str]
    file_ext: str
    file_size: int
    md5: str
    storage_path: str
    processing_status: str
    description: Optional[str]
    tags: Optional[list[str]]
    source_type: str
    page_count: Optional[int]
    content_text: Optional[str]
    uploaded_at: datetime
    last_modified_at: datetime
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str]

    class Config:
        from_attributes = True
```

- [ ] **Step 6: Run model tests and verify they pass**

Run:

```bash
cd backend
python -m pytest tests/test_models.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/knowledge_item.py backend/app/models/__init__.py backend/app/schemas/knowledge.py backend/tests/test_models.py
git commit -m "feat: add topic resource data model"
```

---

### Task 2: Media Type Utilities

**Files:**
- Create: `backend/app/utils/media_type.py`
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing utility tests**

Append to `backend/tests/test_knowledge_api.py`:

```python
from backend.app.utils.media_type import infer_media_type, supported_accept_extensions


def test_infer_media_type_by_extension_and_mime():
    assert infer_media_type("notes.md", "text/markdown") == "document"
    assert infer_media_type("photo.webp", "image/webp") == "image"
    assert infer_media_type("call.m4a", "audio/mp4") == "audio"
    assert infer_media_type("demo.webm", "video/webm") == "video"


def test_unsupported_media_type_rejected():
    try:
        infer_media_type("archive.zip", "application/zip")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("zip files must be rejected")


def test_supported_accept_extensions_contains_all_resource_types():
    extensions = supported_accept_extensions()
    assert ".pdf" in extensions
    assert ".png" in extensions
    assert ".mp3" in extensions
    assert ".mp4" in extensions
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_infer_media_type_by_extension_and_mime -q
```

Expected: FAIL because `backend.app.utils.media_type` does not exist.

- [ ] **Step 3: Create the utility**

Create `backend/app/utils/media_type.py`:

```python
from pathlib import Path

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md", ".markdown"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

EXTENSION_TO_MEDIA_TYPE = {
    **{ext: "document" for ext in DOCUMENT_EXTENSIONS},
    **{ext: "image" for ext in IMAGE_EXTENSIONS},
    **{ext: "audio" for ext in AUDIO_EXTENSIONS},
    **{ext: "video" for ext in VIDEO_EXTENSIONS},
}


def infer_media_type(filename: str, mime_type: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in EXTENSION_TO_MEDIA_TYPE:
        return EXTENSION_TO_MEDIA_TYPE[ext]

    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime in {"application/pdf", "text/plain", "text/markdown"}:
        return "document"

    raise ValueError(f"Unsupported file type: {ext or mime or 'unknown'}")


def supported_accept_extensions() -> str:
    return ",".join(sorted(EXTENSION_TO_MEDIA_TYPE))
```

- [ ] **Step 4: Run utility tests**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_infer_media_type_by_extension_and_mime tests/test_knowledge_api.py::test_unsupported_media_type_rejected tests/test_knowledge_api.py::test_supported_accept_extensions_contains_all_resource_types -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/media_type.py backend/tests/test_knowledge_api.py
git commit -m "feat: infer knowledge resource media types"
```

---

### Task 3: Topic API

**Files:**
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing topic API tests**

Append to `backend/tests/test_knowledge_api.py`:

```python
def test_create_list_update_topic(client):
    create = client.post("/api/v1/knowledge/topics", json={
        "name": "Product Docs",
        "description": "Launch docs",
    })
    assert create.status_code == 200
    topic = create.json()
    assert topic["name"] == "Product Docs"
    assert topic["description"] == "Launch docs"
    assert topic["resource_count"] == 0

    listing = client.get("/api/v1/knowledge/topics")
    assert listing.status_code == 200
    assert [item["name"] for item in listing.json()] == ["Product Docs"]

    update = client.put(f"/api/v1/knowledge/topics/{topic['id']}", json={
        "name": "Product Handbook",
        "description": "Updated",
    })
    assert update.status_code == 200
    assert update.json()["name"] == "Product Handbook"


def test_duplicate_topic_name_is_conflict(client):
    first = client.post("/api/v1/knowledge/topics", json={"name": "Research"})
    second = client.post("/api/v1/knowledge/topics", json={"name": "Research"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_topic_name"


def test_delete_empty_topic(client):
    create = client.post("/api/v1/knowledge/topics", json={"name": "Empty"})
    topic_id = create.json()["id"]

    delete = client.delete(f"/api/v1/knowledge/topics/{topic_id}")
    assert delete.status_code == 200
    assert delete.json()["detail"] == "deleted"
```

- [ ] **Step 2: Run topic tests and verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_create_list_update_topic -q
```

Expected: FAIL with 404 for `/api/v1/knowledge/topics`.

- [ ] **Step 3: Add imports and helpers**

In `backend/app/api/knowledge.py`, extend imports:

```python
from sqlalchemy import cast, String, func
from sqlalchemy.exc import IntegrityError
from ..models.knowledge_item import KnowledgeItem, KnowledgeTopic, KnowledgeFile
from ..schemas.knowledge import (
    KnowledgeItemCreate, KnowledgeItemUpdate, KnowledgeItemOut, KnowledgeItemListOut,
    KnowledgeTopicCreate, KnowledgeTopicUpdate, KnowledgeTopicOut, KnowledgeResourceOut,
)
```

Add helper functions below `router = ...`:

```python
DEFAULT_USER_ID = "default-user"


def _topic_out(topic: KnowledgeTopic, resource_count: int = 0) -> KnowledgeTopicOut:
    return KnowledgeTopicOut(
        id=topic.id,
        user_id=topic.user_id,
        name=topic.name,
        description=topic.description,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
        resource_count=resource_count,
    )


def _get_topic_or_404(topic_id: str, db: Session) -> KnowledgeTopic:
    topic = db.query(KnowledgeTopic).filter(
        KnowledgeTopic.id == topic_id,
        KnowledgeTopic.user_id == DEFAULT_USER_ID,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail={"code": "topic_not_found", "message": "Topic not found"})
    return topic
```

- [ ] **Step 4: Add topic endpoints before `@router.get("/{item_id}")`**

Insert this block above the legacy item detail route:

```python
@router.post("/topics", response_model=KnowledgeTopicOut)
def create_topic(payload: KnowledgeTopicCreate, db: Session = Depends(get_db)):
    topic = KnowledgeTopic(
        user_id=DEFAULT_USER_ID,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(topic)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
        )
    db.refresh(topic)
    return _topic_out(topic, 0)


@router.get("/topics", response_model=list[KnowledgeTopicOut])
def list_topics(db: Session = Depends(get_db)):
    rows = (
        db.query(KnowledgeTopic, func.count(KnowledgeFile.id))
        .outerjoin(KnowledgeFile, KnowledgeFile.topic_id == KnowledgeTopic.id)
        .filter(KnowledgeTopic.user_id == DEFAULT_USER_ID)
        .group_by(KnowledgeTopic.id)
        .order_by(KnowledgeTopic.updated_at.desc())
        .all()
    )
    return [_topic_out(topic, resource_count) for topic, resource_count in rows]


@router.get("/topics/{topic_id}", response_model=KnowledgeTopicOut)
def get_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    return _topic_out(topic, count)


@router.put("/topics/{topic_id}", response_model=KnowledgeTopicOut)
def update_topic(topic_id: str, payload: KnowledgeTopicUpdate, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        topic.name = data["name"].strip()
    if "description" in data:
        topic.description = data["description"]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_topic_name", "message": "Topic name already exists"},
        )
    db.refresh(topic)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    return _topic_out(topic, count)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: str, db: Session = Depends(get_db)):
    topic = _get_topic_or_404(topic_id, db)
    count = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic.id).count()
    if count:
        raise HTTPException(
            status_code=409,
            detail={"code": "topic_not_empty", "message": "Delete resources before deleting the topic"},
        )
    db.delete(topic)
    db.commit()
    return {"detail": "deleted"}
```

- [ ] **Step 5: Run topic tests**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_create_list_update_topic tests/test_knowledge_api.py::test_duplicate_topic_name_is_conflict tests/test_knowledge_api.py::test_delete_empty_topic -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/knowledge.py backend/tests/test_knowledge_api.py
git commit -m "feat: add knowledge topic api"
```

---

### Task 4: Resource Upload API

**Files:**
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/utils/file_parser.py`
- Modify: `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing resource tests**

Append to `backend/tests/test_knowledge_api.py`:

```python
def _create_topic(client, name="Uploads"):
    response = client.post("/api/v1/knowledge/topics", json={"name": name})
    assert response.status_code == 200
    return response.json()


def test_upload_document_resource_creates_item(client, monkeypatch):
    topic = _create_topic(client)
    called = []
    monkeypatch.setattr("backend.app.api.knowledge._trigger_ingestion", lambda item_id: called.append(item_id))

    response = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
        data={"description": "Greeting", "tags": "intro,hello"},
    )

    assert response.status_code == 200
    resource = response.json()
    assert resource["title"] == "notes"
    assert resource["media_type"] == "document"
    assert resource["processing_status"] == "completed"
    assert resource["description"] == "Greeting"
    assert resource["tags"] == ["intro", "hello"]
    assert resource["content_text"] == "hello document"
    assert resource["item_id"]
    assert called == [resource["item_id"]]


def test_duplicate_resource_in_same_topic_is_conflict(client):
    topic = _create_topic(client)
    files = {"file": ("same.txt", b"same", "text/plain")}

    first = client.post(f"/api/v1/knowledge/topics/{topic['id']}/resources", files=files)
    second = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("same-copy.txt", b"same", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_resource_in_topic"


def test_upload_image_audio_video_as_metadata_only(client):
    topic = _create_topic(client)
    samples = [
        ("photo.png", b"png bytes", "image/png", "image"),
        ("voice.mp3", b"mp3 bytes", "audio/mpeg", "audio"),
        ("clip.mp4", b"mp4 bytes", "video/mp4", "video"),
    ]

    for filename, content, mime, expected_type in samples:
        response = client.post(
            f"/api/v1/knowledge/topics/{topic['id']}/resources",
            files={"file": (filename, content, mime)},
        )
        assert response.status_code == 200
        resource = response.json()
        assert resource["media_type"] == expected_type
        assert resource["processing_status"] == "metadata_only"
        assert resource["item_id"] is None


def test_list_resources_filter_by_media_type(client):
    topic = _create_topic(client)
    client.post(f"/api/v1/knowledge/topics/{topic['id']}/resources", files={"file": ("notes.txt", b"text", "text/plain")})
    client.post(f"/api/v1/knowledge/topics/{topic['id']}/resources", files={"file": ("photo.png", b"image", "image/png")})

    response = client.get(f"/api/v1/knowledge/topics/{topic['id']}/resources", params={"media_type": "image"})

    assert response.status_code == 200
    resources = response.json()
    assert len(resources) == 1
    assert resources[0]["media_type"] == "image"


def test_topic_delete_blocked_when_resources_exist(client):
    topic = _create_topic(client, "Blocked")
    client.post(f"/api/v1/knowledge/topics/{topic['id']}/resources", files={"file": ("notes.txt", b"text", "text/plain")})

    response = client.delete(f"/api/v1/knowledge/topics/{topic['id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "topic_not_empty"
```

- [ ] **Step 2: Run one resource test and verify it fails**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_upload_document_resource_creates_item -q
```

Expected: FAIL with 404 for `/resources`.

- [ ] **Step 3: Add parser helper**

Append to `backend/app/utils/file_parser.py`:

```python
def count_pages(file_path: str) -> int | None:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        import fitz
        with fitz.open(file_path) as doc:
            return len(doc)
    if ext == ".docx":
        from docx import Document
        doc = Document(file_path)
        return max(1, len(doc.paragraphs))
    if ext in (".md", ".txt", ".markdown"):
        return 1
    return None
```

Update `extract_text()` in the same file so `.doc` produces a clear parse failure:

```python
    if ext == ".doc":
        raise ValueError(".doc parsing is not available; convert to .docx or upload for metadata only")
```

- [ ] **Step 4: Add resource imports and helpers**

In `backend/app/api/knowledge.py`, add imports:

```python
import hashlib
import shutil
from pathlib import Path
from fastapi import UploadFile, File, Form

from ..config import settings
from ..utils.file_parser import extract_text, count_pages
from ..utils.media_type import infer_media_type
```

Add constants and helpers after `DEFAULT_USER_ID`:

```python
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _resource_title(filename: str) -> str:
    return Path(filename or "resource").stem or "resource"


def _save_upload(file: UploadFile, topic_id: str) -> tuple[Path, bytes, str]:
    content = file.file.read()
    md5 = hashlib.md5(content).hexdigest()
    ext = Path(file.filename or "").suffix.lower()
    topic_dir = UPLOAD_DIR / DEFAULT_USER_ID / topic_id
    topic_dir.mkdir(parents=True, exist_ok=True)
    saved_path = topic_dir / f"{md5}{ext}"
    saved_path.write_bytes(content)
    return saved_path, content, md5
```

Import `_trigger_ingestion` from the current upload module near imports:

```python
from .upload import _trigger_ingestion
```

- [ ] **Step 5: Add resource endpoints before item detail route**

Insert above `@router.get("/{item_id}")`:

```python
@router.post("/topics/{topic_id}/resources", response_model=KnowledgeResourceOut)
async def upload_topic_resource(
    topic_id: str,
    file: UploadFile = File(...),
    description: str | None = Form(None),
    tags: str | None = Form(None),
    db: Session = Depends(get_db),
):
    topic = _get_topic_or_404(topic_id, db)
    try:
        media_type = infer_media_type(file.filename or "", file.content_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "unsupported_file_type", "message": str(exc)},
        )

    saved_path, content, md5 = _save_upload(file, topic.id)
    duplicate = db.query(KnowledgeFile).filter(
        KnowledgeFile.user_id == DEFAULT_USER_ID,
        KnowledgeFile.topic_id == topic.id,
        KnowledgeFile.md5 == md5,
    ).first()
    if duplicate:
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_resource_in_topic", "message": "Resource already exists in this topic"},
        )

    resource = KnowledgeFile(
        user_id=DEFAULT_USER_ID,
        topic_id=topic.id,
        title=_resource_title(file.filename or ""),
        original_filename=file.filename or "resource",
        media_type=media_type,
        mime_type=file.content_type,
        file_ext=Path(file.filename or "").suffix.lower(),
        file_size=len(content),
        md5=md5,
        storage_path=str(saved_path),
        processing_status="metadata_only" if media_type != "document" else "processing",
        description=description,
        tags=_parse_tags(tags),
        source_type="upload",
    )
    db.add(resource)
    db.flush()

    if media_type == "document":
        try:
            text = extract_text(str(saved_path))
            resource.content_text = text
            resource.page_count = count_pages(str(saved_path))
            item = KnowledgeItem(
                title=resource.title,
                content=text,
                source_type="file",
                source_ref=str(saved_path),
                tags=resource.tags or [],
                category=topic.name,
                user_id=DEFAULT_USER_ID,
            )
            db.add(item)
            db.flush()
            resource.item_id = item.id
            resource.processing_status = "completed"
        except Exception as exc:
            resource.processing_status = "failed"
            resource.error_message = str(exc)

    db.commit()
    db.refresh(resource)

    if resource.item_id and resource.processing_status == "completed":
        _trigger_ingestion(resource.item_id)

    return resource


@router.get("/topics/{topic_id}/resources", response_model=list[KnowledgeResourceOut])
def list_topic_resources(
    topic_id: str,
    media_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    processing_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    _get_topic_or_404(topic_id, db)
    query = db.query(KnowledgeFile).filter(KnowledgeFile.topic_id == topic_id)
    if media_type:
        query = query.filter(KnowledgeFile.media_type == media_type)
    if processing_status:
        query = query.filter(KnowledgeFile.processing_status == processing_status)
    if tag:
        query = query.filter(cast(KnowledgeFile.tags, String).contains(f'"{tag}"'))
    return query.order_by(KnowledgeFile.uploaded_at.desc()).all()


@router.get("/resources/{resource_id}", response_model=KnowledgeResourceOut)
def get_resource(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "Resource not found"})
    return resource


@router.delete("/resources/{resource_id}")
def delete_resource(resource_id: str, db: Session = Depends(get_db)):
    resource = db.query(KnowledgeFile).filter(
        KnowledgeFile.id == resource_id,
        KnowledgeFile.user_id == DEFAULT_USER_ID,
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail={"code": "resource_not_found", "message": "Resource not found"})
    storage_path = Path(resource.storage_path)
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == resource.item_id).first() if resource.item_id else None
    db.delete(resource)
    if item:
        db.delete(item)
    db.commit()
    storage_path.unlink(missing_ok=True)
    return {"detail": "deleted"}
```

- [ ] **Step 6: Run resource tests**

Run:

```bash
cd backend
python -m pytest tests/test_knowledge_api.py::test_upload_document_resource_creates_item tests/test_knowledge_api.py::test_duplicate_resource_in_same_topic_is_conflict tests/test_knowledge_api.py::test_upload_image_audio_video_as_metadata_only tests/test_knowledge_api.py::test_list_resources_filter_by_media_type tests/test_knowledge_api.py::test_topic_delete_blocked_when_resources_exist -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/knowledge.py backend/app/utils/file_parser.py backend/tests/test_knowledge_api.py
git commit -m "feat: add topic resource upload api"
```

---

### Task 5: Auto Migration Support

**Files:**
- Modify: `backend/app/utils/auto_migrate.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Write a migration helper test**

Append to `backend/tests/test_models.py`:

```python
def test_knowledge_file_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeFile.__table__.constraints}
    assert "uq_knowledge_file_user_topic_md5" in constraints


def test_knowledge_topic_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeTopic.__table__.constraints}
    assert "uq_knowledge_topic_user_name" in constraints
```

- [ ] **Step 2: Run tests**

Run:

```bash
cd backend
python -m pytest tests/test_models.py::test_knowledge_file_model_has_named_unique_constraint tests/test_models.py::test_knowledge_topic_model_has_named_unique_constraint -q
```

Expected: PASS after Task 1.

- [ ] **Step 3: Add known unique constraint creation to migration**

In `backend/app/utils/auto_migrate.py`, add this import:

```python
from sqlalchemy import UniqueConstraint
```

At the end of the existing table loop, after the missing-column loop, add:

```python
        existing_unique_names = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        for constraint in table_obj.constraints:
            if not isinstance(constraint, UniqueConstraint):
                continue
            if not constraint.name or constraint.name in existing_unique_names:
                continue
            columns = [f"`{column.name}`" for column in constraint.columns]
            if not columns:
                continue
            alter_sql = (
                f"ALTER TABLE `{table_name}` "
                f"ADD CONSTRAINT `{constraint.name}` UNIQUE ({', '.join(columns)})"
            )
            print(f"[auto_migrate] 添加唯一约束 {table_name}.{constraint.name}")
            with engine.connect() as conn:
                try:
                    conn.execute(text(alter_sql))
                    conn.commit()
                except Exception as e:
                    raise RuntimeError(
                        f"[auto_migrate] Failed to add unique constraint {table_name}.{constraint.name}: {e}"
                    ) from e
```

- [ ] **Step 4: Run backend tests**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/auto_migrate.py backend/tests/test_models.py
git commit -m "feat: migrate topic resource constraints"
```

---

### Task 6: Frontend API Client

**Files:**
- Modify: `frontend/src/app/api.ts`
- Create: `frontend/tests/knowledge-topic-resource.test.mjs`

- [ ] **Step 1: Write failing frontend static test**

Create `frontend/tests/knowledge-topic-resource.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/KnowledgePage.tsx'), 'utf8')

assert.match(api, /interface KnowledgeTopic/, 'API client exposes KnowledgeTopic type.')
assert.match(api, /interface KnowledgeResource/, 'API client exposes KnowledgeResource type.')
assert.match(api, /listTopics:/, 'API client lists topics.')
assert.match(api, /uploadResource:/, 'API client uploads resources into a topic.')
assert.match(page, /data-testid="knowledge-topic-sidebar"/, 'Knowledge page renders a topic sidebar.')
assert.match(page, /data-testid="knowledge-resource-filter"/, 'Knowledge page renders media type filters.')
assert.match(page, /duplicate_resource_in_topic/, 'Knowledge page maps duplicate upload errors.')
```

- [ ] **Step 2: Run frontend static test and verify it fails**

Run:

```bash
cd frontend
node tests/knowledge-topic-resource.test.mjs
```

Expected: FAIL because the API and page are not wired yet.

- [ ] **Step 3: Add API types and methods**

In `frontend/src/app/api.ts`, add these types after `KnowledgeItem`:

```typescript
export type ResourceMediaType = 'document' | 'image' | 'audio' | 'video'
export type ResourceFilterType = 'all' | ResourceMediaType

export interface KnowledgeTopic {
  id: string
  user_id: string
  name: string
  description?: string | null
  created_at: string
  updated_at: string
  resource_count: number
}

export interface KnowledgeResource {
  id: string
  user_id: string
  topic_id?: string | null
  item_id?: string | null
  title: string
  original_filename: string
  media_type: ResourceMediaType
  mime_type?: string | null
  file_ext: string
  file_size: number
  md5: string
  storage_path: string
  processing_status: string
  description?: string | null
  tags?: string[] | null
  source_type: string
  page_count?: number | null
  content_text?: string | null
  uploaded_at: string
  last_modified_at: string
  created_at: string
  updated_at: string
  error_message?: string | null
}
```

Add this helper below `request()`:

```typescript
async function uploadRequest<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'POST', body: form })
  if (!resp.ok) {
    const detail = await resp.text()
    throw new Error(detail)
  }
  return resp.json()
}
```

Add methods inside `knowledgeApi`:

```typescript
  listTopics: () => request<KnowledgeTopic[]>('/knowledge/topics'),
  createTopic: (data: Pick<KnowledgeTopic, 'name'> & { description?: string }) =>
    request<KnowledgeTopic>('/knowledge/topics', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateTopic: (id: string, data: Partial<Pick<KnowledgeTopic, 'name' | 'description'>>) =>
    request<KnowledgeTopic>(`/knowledge/topics/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteTopic: (id: string) =>
    request<{ detail: string }>(`/knowledge/topics/${id}`, { method: 'DELETE' }),
  listResources: (topicId: string, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<KnowledgeResource[]>(`/knowledge/topics/${topicId}/resources${qs}`)
  },
  uploadResource: async (
    topicId: string,
    file: File,
    options?: { description?: string; tags?: string[] },
  ): Promise<KnowledgeResource> => {
    const form = new FormData()
    form.append('file', file)
    if (options?.description) form.append('description', options.description)
    if (options?.tags?.length) form.append('tags', options.tags.join(','))
    return uploadRequest<KnowledgeResource>(`/knowledge/topics/${topicId}/resources`, form)
  },
  deleteResource: (id: string) =>
    request<{ detail: string }>(`/knowledge/resources/${id}`, { method: 'DELETE' }),
```

- [ ] **Step 4: Run TypeScript build**

Run:

```bash
cd frontend
npm run build
```

Expected: FAIL only because `KnowledgePage.tsx` has not been updated for static test expectations, not because `api.ts` has TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api.ts frontend/tests/knowledge-topic-resource.test.mjs
git commit -m "feat: add knowledge resource frontend api"
```

---

### Task 7: Knowledge Page Topic Resource UI

**Files:**
- Modify: `frontend/src/pages/KnowledgePage.tsx`

- [ ] **Step 1: Replace local directory state with topic/resource state**

In `frontend/src/pages/KnowledgePage.tsx`, replace the imports with:

```typescript
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import {
  knowledgeApi,
  type KnowledgeResource,
  type KnowledgeTopic,
  type ResourceFilterType,
  type ResourceMediaType,
} from '@/app/api'
import {
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderPlus,
  Loader2,
  Trash2,
  Upload,
} from 'lucide-react'
import { cn } from '@/lib/utils'
```

Replace top-level constants/helpers with:

```typescript
const ACCEPTED_RESOURCE_EXTENSIONS =
  '.pdf,.doc,.docx,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.aac,.flac,.ogg,.mp4,.mov,.avi,.mkv,.webm'

const FILTERS: Array<{ value: ResourceFilterType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'document', label: '文档' },
  { value: 'image', label: '图片' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
]

const MEDIA_LABEL: Record<ResourceMediaType, string> = {
  document: '文档',
  image: '图片',
  audio: '音频',
  video: '视频',
}
```

- [ ] **Step 2: Implement data loading**

Inside `KnowledgePage()`, use this state and load functions:

```typescript
const [topics, setTopics] = useState<KnowledgeTopic[]>([])
const [activeTopicId, setActiveTopicId] = useState<string | null>(null)
const [resources, setResources] = useState<KnowledgeResource[]>([])
const [filter, setFilter] = useState<ResourceFilterType>('all')
const [loadingTopics, setLoadingTopics] = useState(false)
const [loadingResources, setLoadingResources] = useState(false)
const [busy, setBusy] = useState(false)
const [showTopicForm, setShowTopicForm] = useState(false)
const [newTopicName, setNewTopicName] = useState('')
const [newTopicDescription, setNewTopicDescription] = useState('')
const [error, setError] = useState<string | null>(null)
const fileRef = useRef<HTMLInputElement>(null)

const activeTopic = topics.find((topic) => topic.id === activeTopicId) || null

const loadTopics = async () => {
  setLoadingTopics(true)
  try {
    const loaded = await knowledgeApi.listTopics()
    setTopics(loaded)
    setActiveTopicId((current) => current || loaded[0]?.id || null)
  } catch (err) {
    setError(`知识库主题加载失败：${getErrorMessage(err)}`)
  } finally {
    setLoadingTopics(false)
  }
}

const loadResources = async (topicId: string, nextFilter = filter) => {
  setLoadingResources(true)
  try {
    const params = nextFilter === 'all' ? undefined : { media_type: nextFilter }
    setResources(await knowledgeApi.listResources(topicId, params))
  } catch (err) {
    setError(`资源加载失败：${getErrorMessage(err)}`)
  } finally {
    setLoadingResources(false)
  }
}

useEffect(() => {
  loadTopics()
}, [])

useEffect(() => {
  if (activeTopicId) {
    loadResources(activeTopicId)
  } else {
    setResources([])
  }
}, [activeTopicId, filter])
```

- [ ] **Step 3: Implement create/upload/delete handlers**

Add these handlers inside `KnowledgePage()`:

```typescript
const createTopic = async () => {
  const name = newTopicName.trim()
  if (!name || busy) {
    setError('请先填写主题名称。')
    return
  }

  setBusy(true)
  setError(null)
  try {
    const topic = await knowledgeApi.createTopic({
      name,
      description: newTopicDescription.trim() || undefined,
    })
    setTopics((current) => [topic, ...current])
    setActiveTopicId(topic.id)
    setNewTopicName('')
    setNewTopicDescription('')
    setShowTopicForm(false)
  } catch (err) {
    setError(readApiError(err, '主题创建失败'))
  } finally {
    setBusy(false)
  }
}

const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
  const file = event.target.files?.[0]
  if (!file || busy || !activeTopicId) return

  setBusy(true)
  setError(null)
  try {
    await knowledgeApi.uploadResource(activeTopicId, file)
    await Promise.all([loadTopics(), loadResources(activeTopicId)])
  } catch (err) {
    setError(readApiError(err, '资源上传失败'))
  } finally {
    setBusy(false)
    if (fileRef.current) fileRef.current.value = ''
  }
}

const handleDeleteResource = async (resourceId: string) => {
  if (busy || !activeTopicId || !confirm('确认删除这个资源吗？')) return

  setBusy(true)
  setError(null)
  try {
    await knowledgeApi.deleteResource(resourceId)
    await Promise.all([loadTopics(), loadResources(activeTopicId)])
  } catch (err) {
    setError(readApiError(err, '资源删除失败'))
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 4: Add error helpers**

Replace `getErrorMessage()` with:

```typescript
function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function readApiError(error: unknown, fallback: string) {
  const raw = getErrorMessage(error)
  try {
    const parsed = JSON.parse(raw)
    const detail = parsed.detail
    if (detail?.code === 'duplicate_resource_in_topic') {
      return '这个文件已经上传到当前主题了。'
    }
    if (detail?.code === 'duplicate_topic_name') {
      return '这个主题名称已经存在。'
    }
    if (detail?.message) {
      return `${fallback}：${detail.message}`
    }
  } catch {
    return `${fallback}：${raw}`
  }
  return `${fallback}：${raw}`
}
```

- [ ] **Step 5: Render the workspace**

Replace the returned JSX in `KnowledgePage()` with a two-column workspace containing:

```tsx
return (
  <div className="grid min-h-[calc(100vh-8rem)] gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
    <aside
      data-testid="knowledge-topic-sidebar"
      className="prism-panel flex min-h-0 flex-col rounded-lg p-3"
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-slate-950">知识库</h1>
        <button
          type="button"
          onClick={() => setShowTopicForm((value) => !value)}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--prism-blue)] text-white"
          aria-label="新建主题"
        >
          <FolderPlus size={17} />
        </button>
      </div>

      {showTopicForm && (
        <div className="mb-3 space-y-2">
          <input
            value={newTopicName}
            onChange={(event) => setNewTopicName(event.target.value)}
            placeholder="主题名称"
            className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--prism-blue)]"
          />
          <textarea
            value={newTopicDescription}
            onChange={(event) => setNewTopicDescription(event.target.value)}
            placeholder="描述"
            rows={2}
            className="w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm outline-none focus:border-[var(--prism-blue)]"
          />
          <button
            type="button"
            disabled={busy}
            onClick={createTopic}
            className="inline-flex min-h-9 w-full items-center justify-center rounded-lg bg-[var(--prism-blue)] px-3 text-sm font-medium text-white disabled:opacity-55"
          >
            创建主题
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {loadingTopics ? (
          <LoadingState text="正在加载主题..." />
        ) : topics.length === 0 ? (
          <EmptyState icon={<FolderPlus size={26} />} title="还没有主题" description="先新建一个主题，再上传资源。" />
        ) : (
          <div className="space-y-2">
            {topics.map((topic) => (
              <button
                key={topic.id}
                type="button"
                onClick={() => setActiveTopicId(topic.id)}
                className={cn(
                  'flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition',
                  activeTopicId === topic.id
                    ? 'border-blue-200 bg-blue-50 text-[var(--prism-blue)]'
                    : 'border-transparent bg-white text-slate-700 hover:border-[var(--prism-line)]',
                )}
              >
                <Folder size={18} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block break-words text-sm font-semibold">{topic.name}</span>
                  <span className="mt-1 block text-xs text-slate-500">{topic.resource_count} 个资源</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>

    <main className="min-w-0 space-y-4">
      <ErrorMessage error={error} onClose={() => setError(null)} />
      {!activeTopic ? (
        <EmptyState icon={<FolderPlus size={28} />} title="请选择主题" description="主题里的资源会在这里显示。" />
      ) : (
        <>
          <section className="prism-panel rounded-lg p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <h2 className="break-words text-xl font-semibold text-slate-950">{activeTopic.name}</h2>
                {activeTopic.description && (
                  <p className="mt-2 text-sm leading-6 text-slate-500">{activeTopic.description}</p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  accept={ACCEPTED_RESOURCE_EXTENSIONS}
                  onChange={handleUpload}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => fileRef.current?.click()}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white disabled:opacity-55"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                  上传资源
                </button>
              </div>
            </div>
          </section>

          <section className="prism-panel rounded-lg p-3">
            <div data-testid="knowledge-resource-filter" className="flex flex-wrap gap-2">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  className={cn(
                    'min-h-9 rounded-lg px-3 text-sm font-medium transition',
                    filter === item.value
                      ? 'bg-[var(--prism-blue)] text-white'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </section>

          {loadingResources ? (
            <LoadingState text="正在加载资源..." />
          ) : resources.length === 0 ? (
            <EmptyState icon={<Upload size={28} />} title="当前主题还没有资源" description="点击上传资源，文档会进入问答检索，图片、音频、视频先保存元数据。" />
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">
              {resources.map((resource) => (
                <ResourceCard
                  key={resource.id}
                  resource={resource}
                  busy={busy}
                  onDelete={handleDeleteResource}
                />
              ))}
            </div>
          )}
        </>
      )}
    </main>
  </div>
)
```

- [ ] **Step 6: Add resource card helpers**

Replace `KnowledgeCard` with:

```tsx
function ResourceIcon({ mediaType }: { mediaType: ResourceMediaType }) {
  if (mediaType === 'image') return <FileImage size={18} />
  if (mediaType === 'audio') return <FileAudio size={18} />
  if (mediaType === 'video') return <FileVideo size={18} />
  return <FileText size={18} />
}

function formatSize(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function ResourceCard({
  resource,
  busy,
  onDelete,
}: {
  resource: KnowledgeResource
  busy: boolean
  onDelete: (id: string) => void
}) {
  const uploadedDate = formatDate(resource.uploaded_at)

  return (
    <article className="prism-panel flex min-h-44 flex-col rounded-lg p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-[var(--prism-blue)]">
          <ResourceIcon mediaType={resource.media_type} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="break-words text-sm font-semibold leading-5 text-slate-950">
            {resource.title || resource.original_filename}
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {MEDIA_LABEL[resource.media_type]}
            </span>
            <span className="rounded-md bg-emerald-50 px-2 py-1 font-medium text-emerald-700">
              {resource.processing_status}
            </span>
            <span>{formatSize(resource.file_size)}</span>
            {uploadedDate && <span>{uploadedDate}</span>}
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDelete(resource.id)}
          className="rounded-md p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
          aria-label={`删除 ${resource.title || resource.original_filename}`}
        >
          <Trash2 size={16} />
        </button>
      </div>

      {resource.error_message && (
        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
          {resource.error_message}
        </p>
      )}

      {resource.tags?.length ? (
        <div className="mt-auto flex flex-wrap gap-2 pt-4">
          {resource.tags.map((tag) => (
            <span key={tag} className="rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
              #{tag}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  )
}
```

- [ ] **Step 7: Run frontend checks**

Run:

```bash
cd frontend
node tests/knowledge-topic-resource.test.mjs
npm run build
```

Expected: PASS for the static test and TypeScript build.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/KnowledgePage.tsx frontend/tests/knowledge-topic-resource.test.mjs
git commit -m "feat: build topic resource knowledge page"
```

---

### Task 8: Full Verification

**Files:**
- No planned source edits unless verification reveals a failure.

- [ ] **Step 1: Run backend model and API tests**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run engine tests that protect document ingestion**

Run:

```bash
cd engine
python -m pytest tests/test_chunker.py -q
python -m pytest tests/test_agent_tools.py tests/test_hybrid_search.py -q
```

Expected: PASS or a documented external dependency skip/failure if Milvus or LLM credentials are unavailable.

- [ ] **Step 3: Run frontend tests and build**

Run:

```bash
cd frontend
node tests/chat-scroll-layout.test.mjs
node tests/knowledge-topic-resource.test.mjs
npm run build
```

Expected: PASS.

- [ ] **Step 4: Manual smoke test**

Run the services using the documented order:

```bash
python -m engine.run
```

In another terminal:

```bash
$env:SKIP_ENGINE="1"
uvicorn backend.app.main:app --host 0.0.0.0 --port 5175
```

Then run the frontend:

```bash
cd frontend
npm run dev
```

Open `/knowledge` and verify:

1. Create a topic.
2. Upload a `.txt` file and see status `completed`.
3. Upload the same file again in the same topic and see the duplicate error.
4. Upload `.png`, `.mp3`, and `.mp4` files and see status `metadata_only`.
5. Use the type filters to show only documents, images, audio, or video.

- [ ] **Step 5: Commit final fixes if verification required source edits**

```bash
git add <changed-files>
git commit -m "fix: stabilize topic resource knowledge base"
```

Skip this commit if no source edits were required.

---

## Spec Coverage Self-Review

- Topic-first workspace: covered by Tasks 1, 3, 6, and 7.
- One-level topics: covered by `KnowledgeTopic` only; no nested parent field is introduced.
- Default user id: covered by `DEFAULT_USER_ID = "default-user"` in Task 3 and Task 4.
- Single upload resource button: covered by Task 7.
- Backend media type detection: covered by Task 2 and Task 4.
- Per-user per-topic MD5 dedupe: covered by Task 1 and Task 4.
- Documents parse and trigger ingestion: covered by Task 4 and Task 8.
- Image/audio/video metadata-only: covered by Task 4 and Task 7.
- Required fields plus `description`, `tags`, `source_type`, `page_count`, `content_text`: covered by Task 1 and Task 4.
- API endpoints: covered by Tasks 3 and 4.
- Frontend filters and duplicate error display: covered by Tasks 6 and 7.
- Existing `KnowledgeItem` CRUD preservation: Task 3 and Task 4 add routes before `/{item_id}` so legacy endpoints remain available.
