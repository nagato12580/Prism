# Wiki 文档知识抽取 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 cake-master 的三阶段文档知识抽取管线集成到 Prism，提供独立 Wiki 上传入口和知识浏览页面。

**Architecture:** Backend 负责 CRUD + Engine 触发，Engine 负责异步执行三阶段管线（Extract→Merge→Write），Frontend 新增 4 个 Wiki 页面。文件上传统一走 knowledge_file 表，Wiki 特有数据存 6 张新表。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic + React + Zustand + OpenAI SDK + httpx

**Source Spec:** `docs/superpowers/specs/2026-06-16-wiki-knowledge-extraction-design.md`

**Reference Code:** `docs/doc-knowledge-extraction-reference/code/`

---

## File Map

### 新建文件 (12)
| 文件 | 职责 |
|------|------|
| `backend/app/models/wiki.py` | 6 个 Wiki ORM 模型 |
| `backend/app/schemas/wiki.py` | Pydantic 请求/响应 Schema |
| `backend/app/api/wiki.py` | Wiki CRUD + Engine 触发 |
| `engine/app/wiki/__init__.py` | 空文件，包标记 |
| `engine/app/wiki/prompts.py` | 提取 + 文章生成 + 描述生成提示词 |
| `engine/app/wiki/extraction_engine.py` | 三阶段管线核心逻辑 |
| `engine/app/api/wiki.py` | Engine 侧 extract 端点 |
| `frontend/src/pages/WikiPage.tsx` | Wiki 主页（文档列表 + 知识点） |
| `frontend/src/pages/WikiUploadPage.tsx` | Wiki 上传页 |
| `frontend/src/pages/WikiDocDetail.tsx` | 文档详情 + 管线进度 |
| `frontend/src/pages/WikiPointDetail.tsx` | 知识点文章阅读 |
| `frontend/src/app/wikiStore.ts` | Zustand store |

### 修改文件 (7)
| 文件 | 改动 |
|------|------|
| `backend/app/models/__init__.py` | 导出 Wiki 模型 |
| `backend/app/api/__init__.py` | 注册 wiki router |
| `backend/app/api/upload.py` | source_type=wiki 时创建 wiki_document + 触发提取 |
| `backend/app/utils/auto_migrate.py` | 追加 6 张表 |
| `engine/run.py` | 注册 wiki extract router |
| `frontend/src/app/api.ts` | 追加 Wiki API 类型 + 函数 |
| `frontend/src/app/routes.tsx` | 追加 4 条 Wiki 路由 |

---

### Task 1: Backend — Wiki 数据模型

**Files:**
- Create: `backend/app/models/wiki.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`

- [ ] **Step 1: 创建 `backend/app/models/wiki.py`**

```python
# prism/backend/app/models/wiki.py
"""Wiki 文档知识抽取 — 数据模型"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.orm import relationship

from ..database import Base


def _uuid():
    return str(uuid.uuid4())


class WikiDocument(Base):
    """Wiki 管线特有数据，关联 knowledge_file。"""
    __tablename__ = "wiki_document"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    file_id = Column(CHAR(36), ForeignKey("knowledge_file.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="pending", comment="pending/processing/completed/failed")
    extract_stage = Column(String(50), default="", comment="Current stage name")
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    user_id = Column(CHAR(36), default="default-user")
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("KnowledgeFile")
    concepts = relationship("WikiConcept", back_populates="document", cascade="all, delete-orphan")
    knowledge_points = relationship("WikiKnowledgePoint", back_populates="document", cascade="all, delete-orphan")
    images = relationship("WikiImage", back_populates="document", cascade="all, delete-orphan")
    logs = relationship("WikiExtractionLog", back_populates="document", cascade="all, delete-orphan")


class WikiConcept(Base):
    """LLM 提取的原始概念（Stage 2 中间产物）。"""
    __tablename__ = "wiki_concept"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(512), nullable=False, comment="Concept name (Chinese)")
    type = Column(String(32), default="concept", comment="concept/technique/source/claim/artifact")
    description = Column(Text, comment="Specific factual description")
    aliases = Column(String(1024), default="", comment="Aliases, comma separated")
    group_name = Column(String(256), default="", index=True, comment="LLM assigned group name")
    category = Column(String(128), default="", comment="Category")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("WikiDocument", back_populates="concepts")


class WikiKnowledgePoint(Base):
    """合并后的最终知识点（Stage 3 产物）。"""
    __tablename__ = "wiki_knowledge_point"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False, comment="Knowledge point title")
    description = Column(Text, comment="Refined description (100-200 chars, Stage 3.5a)")
    content = Column(Text, comment="Structured Markdown article (Stage 3.5b)")
    category = Column(String(128), default="", comment="Category")
    tags = Column(String(1024), default="", comment="Tags, comma separated")
    aliases = Column(String(1024), default="", comment="Aliases, comma separated")
    group_name = Column(String(256), default="", comment="Group name")
    status = Column(String(16), default="整理中", comment="整理中/已发布")
    images = Column(Text, comment="Associated images JSON: [{'id':'uuid','caption':'desc'},...]")
    user_id = Column(CHAR(36), default="default-user")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("WikiDocument", back_populates="knowledge_points")


class WikiKnowledgeRelation(Base):
    """知识点间关系。"""
    __tablename__ = "wiki_knowledge_relation"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    from_point_id = Column(CHAR(36), ForeignKey("wiki_knowledge_point.id", ondelete="CASCADE"), nullable=False)
    to_point_id = Column(CHAR(36), ForeignKey("wiki_knowledge_point.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(64), default="", comment="implements/extends/optimizes/contradicts/cites/prerequisite_of/trades_off/derived_from")
    confidence = Column(Float, default=1.0, comment="Confidence 0.0~1.0")
    created_at = Column(DateTime, default=datetime.utcnow)


class WikiImage(Base):
    """文档内嵌图片及视觉 LLM 描述（Stage 1.5）。"""
    __tablename__ = "wiki_image"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    image_index = Column(Integer, default=0, comment="Image sequence (1-based)")
    storage_path = Column(String(500), default="", comment="Storage path")
    caption = Column(Text, comment="Vision LLM description")
    mime_type = Column(String(100), default="", comment="MIME type")
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("WikiDocument", back_populates="images")


class WikiExtractionLog(Base):
    """管线执行日志。"""
    __tablename__ = "wiki_extraction_log"

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    document_id = Column(CHAR(36), ForeignKey("wiki_document.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(50), default="", comment="Stage name")
    message = Column(Text, comment="Log content")
    status = Column(String(16), default="info", comment="info/warning/error")
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("WikiDocument", back_populates="logs")
```

- [ ] **Step 2: 修改 `backend/app/models/__init__.py`**

```python
# prism/backend/app/models/__init__.py
from .knowledge_item import KnowledgeTopic, KnowledgeItem, KnowledgeChunk, KnowledgeFile
from .chat import ChatSession, ChatMessage
from .wiki import WikiDocument, WikiConcept, WikiKnowledgePoint, WikiKnowledgeRelation, WikiImage, WikiExtractionLog

__all__ = [
    "KnowledgeTopic",
    "KnowledgeItem",
    "KnowledgeChunk",
    "KnowledgeFile",
    "ChatSession",
    "ChatMessage",
    "WikiDocument",
    "WikiConcept",
    "WikiKnowledgePoint",
    "WikiKnowledgeRelation",
    "WikiImage",
    "WikiExtractionLog",
]
```

- [ ] **Step 3: 修改 `backend/app/utils/auto_migrate.py` 添加表名注册**

```python
# 在 auto_migrate.py 顶部 KNOWN_UNIQUE_CONSTRAINTS 之后，保持不变。
# 表的自动创建由 Base.metadata.tables 遍历完成，新模型导入后自动生效。
# 无需修改 auto_migrate.py 本身 — 只要 main.py 中有 `from .models import *` 即可。
```

- [ ] **Step 4: 验证模型可导入**

Run:
```bash
cd backend && python -c "from app.models.wiki import WikiDocument, WikiConcept, WikiKnowledgePoint, WikiKnowledgeRelation, WikiImage, WikiExtractionLog; print('Models OK')"
```
Expected: `Models OK`

- [ ] **Step 5: 启动 Backend 验证自动建表**

Run:
```bash
cd backend && python -m backend.run
```
检查输出中是否有 `[auto_migrate] Create table: wiki_document` 等日志。

Expected: 6 张 wiki_* 表全部创建

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/wiki.py backend/app/models/__init__.py
git commit -m "feat: add Wiki ORM models (6 tables)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Backend — Wiki Schema

**Files:**
- Create: `backend/app/schemas/wiki.py`

- [ ] **Step 1: 创建 `backend/app/schemas/wiki.py`**

```python
# prism/backend/app/schemas/wiki.py
"""Wiki API 请求/响应 Schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── WikiDocument ──────────────────────────────────────────

class WikiDocumentOut(BaseModel):
    id: str
    file_id: str
    status: str
    extract_stage: str
    progress_current: int
    progress_total: int
    user_id: str
    created_at: datetime
    # 从 knowledge_file join 的额外字段
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    class Config:
        from_attributes = True


class WikiDocumentDetailOut(WikiDocumentOut):
    """文档详情，含日志。"""
    logs: list["WikiExtractionLogOut"] = []


# ── WikiConcept ──────────────────────────────────────────

class WikiConceptOut(BaseModel):
    id: str
    document_id: str
    name: str
    type: str
    description: Optional[str]
    aliases: str
    group_name: str
    category: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiKnowledgePoint ──────────────────────────────────

class WikiKnowledgePointOut(BaseModel):
    id: str
    document_id: str
    title: str
    description: Optional[str]
    content: Optional[str]
    category: str
    tags: str
    aliases: str
    group_name: str
    status: str
    images: Optional[str]
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class WikiKnowledgePointListOut(BaseModel):
    """列表项（不含 content，避免响应过大）。"""
    id: str
    document_id: str
    title: str
    description: Optional[str]
    category: str
    tags: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiKnowledgeRelation ───────────────────────────────

class WikiKnowledgeRelationOut(BaseModel):
    id: str
    from_point_id: str
    to_point_id: str
    type: str
    confidence: float
    created_at: datetime
    # 关联知识点标题（查询时 join 填充）
    from_title: Optional[str] = None
    to_title: Optional[str] = None

    class Config:
        from_attributes = True


# ── WikiImage ────────────────────────────────────────────

class WikiImageOut(BaseModel):
    id: str
    document_id: str
    image_index: int
    storage_path: str
    caption: Optional[str]
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── WikiExtractionLog ───────────────────────────────────

class WikiExtractionLogOut(BaseModel):
    id: str
    document_id: str
    stage: str
    message: str
    status: str
    progress_current: int
    progress_total: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── Request schemas ─────────────────────────────────────

class WikiExtractRequest(BaseModel):
    doc_id: str = Field(..., description="wiki_document.id")
```

- [ ] **Step 2: 验证 Schema 可导入**

Run:
```bash
cd backend && python -c "from app.schemas.wiki import WikiDocumentOut, WikiKnowledgePointOut; print('Schemas OK')"
```
Expected: `Schemas OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/wiki.py
git commit -m "feat: add Wiki API schemas

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Backend — Wiki API CRUD

**Files:**
- Create: `backend/app/api/wiki.py`

- [ ] **Step 1: 创建 `backend/app/api/wiki.py`**

```python
# prism/backend/app/api/wiki.py
"""Wiki CRUD + Engine 触发"""
import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..models.knowledge_item import KnowledgeFile
from ..models.wiki import (
    WikiDocument, WikiConcept, WikiKnowledgePoint,
    WikiKnowledgeRelation, WikiImage, WikiExtractionLog,
)
from ..schemas.wiki import (
    WikiDocumentOut, WikiDocumentDetailOut,
    WikiConceptOut,
    WikiKnowledgePointOut, WikiKnowledgePointListOut,
    WikiKnowledgeRelationOut,
    WikiImageOut,
    WikiExtractionLogOut,
    WikiExtractRequest,
)

router = APIRouter(prefix="/wiki", tags=["wiki"])


def _doc_out(doc: WikiDocument) -> WikiDocumentOut:
    """构建文档输出，join knowledge_file 获取文件名等信息。"""
    return WikiDocumentOut(
        id=doc.id,
        file_id=doc.file_id,
        status=doc.status,
        extract_stage=doc.extract_stage,
        progress_current=doc.progress_current,
        progress_total=doc.progress_total,
        user_id=doc.user_id,
        created_at=doc.created_at,
        original_filename=doc.file.original_filename if doc.file else None,
        mime_type=doc.file.mime_type if doc.file else None,
        file_size=doc.file.file_size if doc.file else None,
    )


def _get_doc_or_404(doc_id: str, db: Session) -> WikiDocument:
    doc = db.query(WikiDocument).filter(WikiDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "wiki_doc_not_found", "message": "Wiki document not found"})
    return doc


# ── Document CRUD ────────────────────────────────────────

@router.get("/documents", response_model=list[WikiDocumentOut])
def list_documents(db: Session = Depends(get_db)):
    docs = (
        db.query(WikiDocument)
        .options(joinedload(WikiDocument.file))
        .order_by(WikiDocument.created_at.desc())
        .all()
    )
    return [_doc_out(d) for d in docs]


@router.get("/documents/{doc_id}", response_model=WikiDocumentDetailOut)
def get_document(doc_id: str, db: Session = Depends(get_db)):
    doc = (
        db.query(WikiDocument)
        .options(joinedload(WikiDocument.file), joinedload(WikiDocument.logs))
        .filter(WikiDocument.id == doc_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail={"code": "wiki_doc_not_found", "message": "Wiki document not found"})
    out = _doc_out(doc)
    out.logs = [
        WikiExtractionLogOut(
            id=log.id, document_id=log.document_id, stage=log.stage,
            message=log.message, status=log.status,
            progress_current=log.progress_current, progress_total=log.progress_total,
            created_at=log.created_at,
        )
        for log in (doc.logs or [])
    ]
    return out


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    doc = _get_doc_or_404(doc_id, db)
    db.delete(doc)  # CASCADE 会删除所有关联数据
    db.commit()
    return {"detail": "已删除"}


# ── Trigger extraction ───────────────────────────────────

@router.post("/extract")
def trigger_extraction(payload: WikiExtractRequest, db: Session = Depends(get_db)):
    doc = _get_doc_or_404(payload.doc_id, db)
    if doc.status == "processing":
        raise HTTPException(status_code=409, detail={"code": "already_processing", "message": "Document is already being processed"})

    doc.status = "processing"
    doc.extract_stage = "starting"
    doc.progress_current = 0
    doc.progress_total = 0
    db.commit()

    # Fire-and-forget 调用 Engine
    def _call_engine():
        try:
            httpx.post(
                f"http://127.0.0.1:{settings.ENGINE_PORT}/api/v1/wiki/extract",
                json={"doc_id": doc.id, "file_id": doc.file_id},
                timeout=30,
            )
        except Exception as exc:
            print(f"[wiki] Engine extract trigger failed doc_id={doc.id}: {exc}")

    threading.Thread(target=_call_engine, daemon=True).start()
    return {"doc_id": doc.id, "status": "processing"}


# ── Knowledge Points ────────────────────────────────────

@router.get("/points", response_model=list[WikiKnowledgePointListOut])
def list_points(doc_id: str = None, db: Session = Depends(get_db)):
    query = db.query(WikiKnowledgePoint)
    if doc_id:
        query = query.filter(WikiKnowledgePoint.document_id == doc_id)
    return query.order_by(WikiKnowledgePoint.created_at.desc()).all()


@router.get("/points/{point_id}", response_model=WikiKnowledgePointOut)
def get_point(point_id: str, db: Session = Depends(get_db)):
    point = db.query(WikiKnowledgePoint).filter(WikiKnowledgePoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail={"code": "point_not_found", "message": "Knowledge point not found"})
    return point


@router.get("/points/{point_id}/relations", response_model=list[WikiKnowledgeRelationOut])
def get_point_relations(point_id: str, db: Session = Depends(get_db)):
    """获取某知识点的所有关联关系（含 from/to 标题）。"""
    point = db.query(WikiKnowledgePoint).filter(WikiKnowledgePoint.id == point_id).first()
    if not point:
        raise HTTPException(status_code=404, detail={"code": "point_not_found", "message": "Knowledge point not found"})

    relations = (
        db.query(WikiKnowledgeRelation)
        .filter(
            (WikiKnowledgeRelation.from_point_id == point_id)
            | (WikiKnowledgeRelation.to_point_id == point_id)
        )
        .all()
    )

    # 批量获取关联知识点标题
    point_ids = set()
    for r in relations:
        point_ids.add(r.from_point_id)
        point_ids.add(r.to_point_id)
    title_map = {}
    if point_ids:
        pts = db.query(WikiKnowledgePoint).filter(WikiKnowledgePoint.id.in_(point_ids)).all()
        title_map = {p.id: p.title for p in pts}

    return [
        WikiKnowledgeRelationOut(
            id=r.id,
            from_point_id=r.from_point_id,
            to_point_id=r.to_point_id,
            type=r.type,
            confidence=r.confidence,
            created_at=r.created_at,
            from_title=title_map.get(r.from_point_id),
            to_title=title_map.get(r.to_point_id),
        )
        for r in relations
    ]


# ── Concepts (for debugging / inspection) ───────────────

@router.get("/concepts", response_model=list[WikiConceptOut])
def list_concepts(doc_id: str = None, db: Session = Depends(get_db)):
    query = db.query(WikiConcept)
    if doc_id:
        query = query.filter(WikiConcept.document_id == doc_id)
    return query.order_by(WikiConcept.created_at.desc()).all()


# ── Images ──────────────────────────────────────────────

@router.get("/images", response_model=list[WikiImageOut])
def list_images(doc_id: str = None, db: Session = Depends(get_db)):
    query = db.query(WikiImage)
    if doc_id:
        query = query.filter(WikiImage.document_id == doc_id)
    return query.order_by(WikiImage.image_index).all()
```

- [ ] **Step 2: 注册 Wiki Router**

修改 `backend/app/api/__init__.py`：

```python
# prism/backend/app/api/__init__.py
from fastapi import APIRouter

from .knowledge import router as knowledge_router
from .upload import router as upload_router
from .chat import router as chat_router
from .wiki import router as wiki_router


def register_routers(app):
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    api_prefix.include_router(upload_router)
    api_prefix.include_router(chat_router)
    api_prefix.include_router(wiki_router)
    app.include_router(api_prefix)
```

- [ ] **Step 3: 验证 API 可启动**

Run:
```bash
cd backend && python -c "from app.main import app; print('App OK, routes:', [r.path for r in app.routes])"
```
Expected: 看到 `/api/v1/wiki/*` 等路由

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/wiki.py backend/app/api/__init__.py
git commit -m "feat: add Wiki CRUD API endpoints

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Backend — 修改 Upload 支持 Wiki

**Files:**
- Modify: `backend/app/api/upload.py`

- [ ] **Step 1: 在 upload.py 添加 Wiki 文件上传端点**

在文件末尾 `_trigger_ingestion` 函数之后追加：

```python
# ── Wiki Upload ─────────────────────────────────────────────

@router.post("/wiki")
async def upload_wiki_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Wiki 独立上传入口：保存文件 → 创建 knowledge_file + wiki_document → 触发提取。"""
    from ..models.wiki import WikiDocument

    ext = Path(file.filename).suffix
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".markdown"}
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content_bytes = await file.read()
    saved_path.write_bytes(content_bytes)

    # 解析文本
    try:
        text = extract_text(str(saved_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

    # 创建 knowledge_file（source_type=wiki）
    kfile = KnowledgeFile(
        original_name=file.filename,
        file_path=str(saved_path),
        file_type=ext.lstrip("."),
        file_size=len(content_bytes),
        parse_status="completed",
        source_type="wiki",
        content_text=text,
    )
    db.add(kfile)
    db.flush()

    # 创建 wiki_document 关联
    wiki_doc = WikiDocument(
        file_id=kfile.id,
        status="pending",
        user_id="default-user",
    )
    db.add(wiki_doc)
    db.commit()
    db.refresh(wiki_doc)

    # 触发提取
    _trigger_wiki_extraction(wiki_doc.id)

    return {
        "file_id": kfile.id,
        "wiki_doc_id": wiki_doc.id,
        "status": "pending",
    }


def _trigger_wiki_extraction(doc_id: str):
    """Fire-and-forget 调用 Engine wiki 提取。"""
    try:
        def _call():
            try:
                httpx.post(
                    f"http://127.0.0.1:{settings.ENGINE_PORT}/api/v1/wiki/extract",
                    json={"doc_id": doc_id},
                    timeout=30,
                )
            except Exception as exc:
                print(f"[wiki] Engine extract trigger failed doc_id={doc_id}: {exc}")
        threading.Thread(target=_call, daemon=True).start()
    except Exception as e:
        print(f"[wiki] Extract trigger failed: {e}")
```

注意需要在文件顶部添加 `from ..models.wiki import WikiDocument`，但实际上因为在函数内部导入了，外部导入可选。确保函数内 `from ..models.wiki import WikiDocument` 正确。

- [ ] **Step 2: 验证 Upload 端点**

Run:
```bash
cd backend && python -c "from app.api.upload import router; print([r.path for r in router.routes])"
```
Expected: 看到 `/upload/wiki` 路由

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/upload.py
git commit -m "feat: add Wiki file upload endpoint with extraction trigger

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Engine — Wiki 提示词

**Files:**
- Create: `engine/app/wiki/__init__.py`
- Create: `engine/app/wiki/prompts.py`

- [ ] **Step 1: 创建 `engine/app/wiki/__init__.py`**

```python
# prism/engine/app/wiki/__init__.py
```

- [ ] **Step 2: 创建 `engine/app/wiki/prompts.py`**

```python
# prism/engine/app/wiki/prompts.py
"""Wiki 知识抽取 — LLM 提示词模板"""

EXTRACT_CONCEPTS_PROMPT = """从以下文档片段中提取细粒度知识点及其之间的关系。

文档来源：{SourcePath}

文档片段：
{ChunkContent}

规则：
1. 每个知识点的描述必须包含具体的、可验证的事实（数字、条件、角色名称、阈值、精确规则）。不要写模糊的概述。
2. 对于流程节点：提取角色、动作和输出作为知识点。
3. 对于条件逻辑：提取完整的触发条件和对应的执行动作。
4. 对于表格内容：将有意义的每一行作为单独的知识点，包含其具体数据。
5. 保留技术术语的原文精确措辞。
6. 如果片段包含审批条件，包含精确的阈值和涉及的角色。
7. 所有文本内容用中文撰写，JSON字段名保持英文。
8. 不要将文档结构标题作为独立知识点提取。只有当片段包含关于该主题的实质性知识时才提取。
9. 类似"文档第X节定义的章节，用于描述..."这样的描述不是有效知识点。每个知识点必须在描述中包含具体的事实内容。
10. 尽可能全面提取，不要遗漏有价值的知识点。
11. 尽可能提取知识点之间的关系。

JSON格式：
{{
  "concepts": [
    {{
      "name": "中文名称",
      "type": "concept|technique|source|claim|artifact",
      "group": "可选分组名称",
      "description": "包含数字、条件和细节的具体事实描述",
      "aliases": ["别名1", "别名2"],
      "category": "分类",
      "tags": ["标签1", "标签2"]
    }}
  ],
  "relations": [
    {{
      "from": "知识点A名称",
      "to": "知识点B名称",
      "type": "implements|extends|optimizes|contradicts|cites|prerequisite_of|trades_off|derived_from",
      "confidence": 0.9
    }}
  ]
}}

## type 枚举说明
- concept: 普通概念/知识点
- technique: 技术/方法/工艺
- source: 信息来源/参考
- claim: 声明/主张/规定
- artifact: 产出物/文档/表单

## group 分组规则
- "group" 是可选字段。当多个细粒度知识点属于同一更广泛主题时使用。
- 相同 "group" 值的知识点将在后续合并。
- 分组名称应简短。
- 如果知识点足够独立可以单独成文，省略 group 字段。
- 每组目标3-8个相关知识点，避免超过10个。

## relation 关系类型说明
- implements: A 实现了 B
- extends: A 扩展了 B
- optimizes: A 优化了 B
- contradicts: A 与 B 矛盾
- cites: A 引用了 B
- prerequisite_of: A 是 B 的前置条件
- trades_off: A 与 B 存在权衡
- derived_from: A 派生自 B

只输出原始JSON，不要输出思考过程、解释或markdown代码块。"""


DESC_GEN_PROMPT = """请为以下知识点生成一段简洁、准确的描述（100-200字），概括其核心含义。

知识点名称：{Title}
分类：{Category}
原始概念描述（参考）：
{Description}

要求：
1. 用专业、简洁的语言概括该知识点的核心内容
2. 涵盖关键要素和适用范围
3. 不要使用列表格式，输出为一段完整的文字
4. 只输出描述文本，不要输出标题或其他内容"""


WRITE_ARTICLE_PROMPT = """根据以下知识点信息，撰写一篇结构化的知识文章。

知识点标题：{Title}
知识点描述：{Description}
分类：{Category}
标签：{Tags}
来源文档：{SourcePath}
{ImageContext}

请按以下结构撰写文章（使用 Markdown 格式）：

# {Title}

## 概述
简要介绍该知识点的核心概念和作用。

## 关键要点
列出该知识点的关键事实、规则、条件或数据（保留原文中的具体数字、阈值、角色名称等）。

## 适用场景
说明该知识点在什么场景下适用或被引用。

## 注意事项
如果描述中包含限制条件、例外情况或特殊要求，在此列出。

要求：
1. 保留原文中的所有具体事实（数字、阈值、条件、角色名称等），不要概括或模糊化
2. 使用清晰的标题层级和列表结构
3. 如有表格数据，使用 Markdown 表格呈现
4. 只输出 Markdown 内容，不要输出其他说明
5. 如果提供的图片中有与当前知识点语义相关的图片，在文章合适位置使用 ![{图片描述}](doc_image://{图片ID}) 格式嵌入。只在图片确实有助于理解内容时才引用，不要为了放图而放图。"""


# 系统提示词
EXTRACTION_SYSTEM_PROMPT = (
    "你是一个专业的知识工程师和知识图谱专家，正在从文档中提取结构化知识点及其关系。"
    "所有知识点名称、描述、别名、分组名必须用中文撰写。JSON字段名和type枚举值保持英文。"
    "只输出原始JSON，不要输出思考过程、解释或markdown代码块。"
)

DESC_GEN_SYSTEM_PROMPT = "你是一个专业的知识工程师。请为知识点生成简洁准确的描述。"

ARTICLE_GEN_SYSTEM_PROMPT = (
    "你是一个专业的技术文档撰写专家。根据提供的知识点信息，"
    "撰写结构清晰的 Markdown 格式知识文章。只输出 Markdown 内容。"
)
```

- [ ] **Step 3: 验证提示词可导入**

Run:
```bash
cd engine && python -c "from engine.app.wiki.prompts import EXTRACT_CONCEPTS_PROMPT, WRITE_ARTICLE_PROMPT, DESC_GEN_PROMPT; print('Prompts OK')"
```
Expected: `Prompts OK`

- [ ] **Step 4: Commit**

```bash
git add engine/app/wiki/__init__.py engine/app/wiki/prompts.py
git commit -m "feat: add Wiki extraction prompts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Engine — Wiki 管线核心引擎

**Files:**
- Create: `engine/app/wiki/extraction_engine.py`

- [ ] **Step 1: 创建 `engine/app/wiki/extraction_engine.py`**

```python
# prism/engine/app/wiki/extraction_engine.py
"""Wiki 文档知识抽取引擎 — 三阶段管线"""
import json
import logging
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from ..config import settings
from ..llm.client import chat as llm_chat
from .prompts import (
    EXTRACT_CONCEPTS_PROMPT, DESC_GEN_PROMPT, WRITE_ARTICLE_PROMPT,
    EXTRACTION_SYSTEM_PROMPT, DESC_GEN_SYSTEM_PROMPT, ARTICLE_GEN_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# Engine 独立 DB session
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

# 并发配置
_KN_MAX_CONCURRENCY = 3

# 分块参数
MAX_CHUNK_SIZE = 4000
OVERLAP_SIZE = 200
MIN_CHUNK_SIZE = 300

# Section 边界识别正则（中文文档适配）
SECTION_PATTERNS = [
    re.compile(r'^#{1,3}\s+'),
    re.compile(r'^\d+[\.\s]+\S'),
    re.compile(r'^（[一二三四五六七八九十]+）'),
    re.compile(r'^\d+[、\)\）]'),
    re.compile(r'^[第第]\s*\d+\s*[章节]'),
]


def _is_section_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    return any(p.match(stripped) for p in SECTION_PATTERNS)


def _chunk_text(text: str) -> list[str]:
    """Section-boundary-aware 文本分块。"""
    if not text or len(text) <= MAX_CHUNK_SIZE:
        return [text] if text else []

    # 按 section 边界切
    sections = []
    current = []
    for line in text.split('\n'):
        if _is_section_boundary(line) and current:
            sections.append('\n'.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append('\n'.join(current))

    # 超长 section 按段落再切
    chunks = []
    for sec in sections:
        if len(sec) <= MAX_CHUNK_SIZE:
            chunks.append(sec)
        else:
            paragraphs = re.split(r'\n\s*\n', sec)
            cur = ''
            for para in paragraphs:
                if not para.strip():
                    continue
                if len(cur) + len(para) + 2 > MAX_CHUNK_SIZE:
                    if cur:
                        chunks.append(cur)
                    cur = para
                else:
                    cur = (cur + '\n\n' + para) if cur else para
            if cur:
                chunks.append(cur)

    # 添加重叠
    if OVERLAP_SIZE > 0 and len(chunks) > 1:
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = chunks[i - 1][-OVERLAP_SIZE:] + '\n' + chunk
            overlapped.append(chunk)
        chunks = overlapped

    # 合并过小的 chunk
    merged = [chunks[0]] if chunks else []
    for chunk in chunks[1:]:
        if len(chunk) < MIN_CHUNK_SIZE and merged:
            merged[-1] = merged[-1] + '\n' + chunk
        else:
            merged.append(chunk)

    return [c for c in merged if c.strip()]


def _repair_json(text: str) -> dict:
    """从 LLM 响应中提取并修复 JSON。"""
    cleaned = text.strip()
    # 找到 JSON 起止
    lines = cleaned.split('\n')
    json_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if not found and (stripped.startswith('{') or stripped.startswith('[')):
            found = True
        if found:
            json_lines.append(line)
    if json_lines:
        cleaned = '\n'.join(json_lines)
    json_end = max(cleaned.rfind('}'), cleaned.rfind(']'))
    if json_end != -1:
        cleaned = cleaned[:json_end + 1]
    return json.loads(cleaned)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM（复用 engine LLM client）。"""
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]
    return llm_chat(messages)


# ── Stage 2: 概念提取 ───────────────────────────────────

def _extract_from_chunk(chunk_text: str, source_path: str) -> tuple[list, list]:
    """对单个 chunk 提取概念和关系。"""
    prompt = EXTRACT_CONCEPTS_PROMPT.replace('{SourcePath}', source_path).replace('{ChunkContent}', chunk_text)
    response = _call_llm(EXTRACTION_SYSTEM_PROMPT, prompt)
    try:
        data = _repair_json(response)
    except json.JSONDecodeError:
        logger.warning(f"JSON repair failed for chunk, raw response: {response[:200]}")
        return [], []
    return data.get('concepts', []), data.get('relations', [])


def _merge_concepts(all_concepts: list) -> tuple[list, dict]:
    """同名概念去重，描述拼接。"""
    seen = {}
    alias_map = {}
    for c in all_concepts:
        name = c.get('name', '').strip()
        if not name:
            continue
        if name in seen:
            existing_desc = seen[name].get('description', '')
            new_desc = c.get('description', '')
            if new_desc and new_desc not in existing_desc:
                seen[name]['description'] = existing_desc + '; ' + new_desc if existing_desc else new_desc
            existing_aliases = seen[name].get('aliases', [])
            for a in c.get('aliases', []):
                if a not in existing_aliases:
                    existing_aliases.append(a)
                alias_map[a.strip()] = name
            seen[name]['aliases'] = existing_aliases
            if c.get('group') and not seen[name].get('group'):
                seen[name]['group'] = c['group']
            if c.get('category') and not seen[name].get('category'):
                seen[name]['category'] = c['category']
        else:
            seen[name] = dict(c)
            alias_map[name] = name
            for a in c.get('aliases', []):
                alias_map[a.strip()] = name
    return list(seen.values()), alias_map


# ── Stage 3: 知识点合并 ─────────────────────────────────

def _merge_groups(concepts: list) -> list:
    """按 group 字段合并概念为知识点。"""
    groups = defaultdict(list)
    ungrouped = []
    for c in concepts:
        grp = c.get('group', '').strip()
        if grp:
            groups[grp].append(c)
        else:
            ungrouped.append(c)

    merged = []
    for group_name, members in groups.items():
        parts = []
        all_aliases = []
        for m in members:
            if m.get('description'):
                parts.append(f"{m.get('name', '')}：{m['description']}")
            all_aliases.extend(m.get('aliases', []))
        merged.append({
            'name': group_name,
            'description': '\n\n'.join(parts),
            'category': members[0].get('category', '') if members else '',
            'aliases': list(dict.fromkeys(all_aliases)),
            'group': group_name,
            'type': members[0].get('type', 'concept') if members else 'concept',
            'sub_concept_names': [m.get('name', '') for m in members],
        })

    for c in ungrouped:
        merged.append({
            'name': c.get('name', ''),
            'description': c.get('description', ''),
            'category': c.get('category', ''),
            'aliases': c.get('aliases', []),
            'group': '',
            'type': c.get('type', 'concept'),
            'sub_concept_names': [c.get('name', '')],
        })

    return merged


# ── Stage 3.5: 描述 + 文章生成 ──────────────────────────

def _gen_description(title: str, description: str, category: str) -> str | None:
    """生成 100-200 字精炼描述。"""
    prompt = DESC_GEN_PROMPT.replace('{Title}', title).replace('{Description}', description or '').replace('{Category}', category or '')
    try:
        return _call_llm(DESC_GEN_SYSTEM_PROMPT, prompt)
    except Exception as e:
        logger.warning(f"Description generation failed for '{title}': {e}")
        return None


def _gen_article(title: str, description: str, category: str, tags: str, source_name: str, doc_images: list | None = None) -> str:
    """生成结构化 Markdown 文章。"""
    img_ctx = ''
    if doc_images:
        img_lines = [f'  - 图片ID={im["id"]}, 描述: {im["caption"]}' for im in doc_images if im.get('caption')]
        if img_lines:
            img_ctx = '\n文档中包含以下图片（可根据语义相关性选择引用）：\n' + '\n'.join(img_lines)

    prompt = (
        WRITE_ARTICLE_PROMPT
        .replace('{Title}', title)
        .replace('{Description}', description or '')
        .replace('{Category}', category or '')
        .replace('{Tags}', tags or '')
        .replace('{SourcePath}', source_name)
        .replace('{ImageContext}', img_ctx)
    )
    return _call_llm(ARTICLE_GEN_SYSTEM_PROMPT, prompt)


# ── 日志辅助 ────────────────────────────────────────────

def _log(db: Session, doc_id: str, stage: str, message: str, status: str = 'info', current: int = 0, total: int = 0):
    from backend.app.models.wiki import WikiExtractionLog
    log = WikiExtractionLog(
        document_id=doc_id, stage=stage, message=message,
        status=status, progress_current=current, progress_total=total,
    )
    db.add(log)
    db.commit()


# ── 主管线 ─────────────────────────────────────────────

def run_extraction(doc_id: str, file_id: str):
    """执行完整的三阶段知识抽取管线。"""
    from backend.app.models.knowledge_item import KnowledgeFile
    from backend.app.models.wiki import (
        WikiDocument, WikiConcept, WikiKnowledgePoint, WikiKnowledgeRelation,
    )

    db = _Session()
    try:
        doc = db.query(WikiDocument).filter(WikiDocument.id == doc_id).first()
        kfile = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
        if not doc or not kfile:
            _log(db, doc_id, 'error', 'Document or file not found', 'error')
            return

        text = kfile.content_text or ''
        if not text.strip():
            doc.status = 'failed'
            doc.extract_stage = 'No content'
            _log(db, doc_id, 'error', 'File content is empty', 'error')
            db.commit()
            return

        source_name = kfile.original_filename or 'unknown'
        _log(db, doc_id, 'start', f'Starting extraction, {len(text)} chars', 'info')

        # ── 断点续抽检测 ──
        existing_concepts = db.query(WikiConcept).filter(WikiConcept.document_id == doc_id).all()
        existing_kps = db.query(WikiKnowledgePoint).filter(WikiKnowledgePoint.document_id == doc_id).all()

        all_concepts = []
        all_relations = []
        alias_map = {}

        if existing_kps:
            _log(db, doc_id, 'resume', f'Found {len(existing_kps)} existing KPs, skipping to article generation', 'info')
            doc.extract_stage = 'resume: KPs exist'
        elif existing_concepts:
            _log(db, doc_id, 'resume', f'Found {len(existing_concepts)} existing concepts, skipping to merge', 'info')
            doc.extract_stage = 'resume: concepts exist'
        else:
            # ── Stage 2: 概念提取 ──
            doc.extract_stage = 'Stage 2: concept extraction'
            doc.progress_current = 0
            db.commit()

            chunks = _chunk_text(text)
            total = len(chunks)
            doc.progress_total = total
            db.commit()
            _log(db, doc_id, 'Stage 2', f'Text split into {total} chunks', 'info')

            done = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(_extract_from_chunk, chunk, source_name): i
                    for i, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    i = futures[future]
                    done += 1
                    try:
                        concepts, relations = future.result()
                        all_concepts.extend(concepts)
                        all_relations.extend(relations)
                        _log(db, doc_id, 'Stage 2', f'Chunk {i+1}/{total}: {len(concepts)} concepts', 'info', current=done, total=total)
                    except Exception as e:
                        _log(db, doc_id, 'Stage 2', f'Chunk {i+1}/{total} failed: {e}', 'warning', current=done, total=total)
                    doc.progress_current = done
                    db.commit()

            if not all_concepts:
                doc.status = 'failed'
                doc.extract_stage = 'Stage 2 failed: no concepts'
                _log(db, doc_id, 'Stage 2', 'All chunks returned no results', 'error')
                db.commit()
                return

            # 去重
            deduped, alias_map = _merge_concepts(all_concepts)
            _log(db, doc_id, 'Stage 2', f'{len(all_concepts)} raw → {len(deduped)} deduped concepts', 'info')

            # 写入 wiki_concept
            for c in deduped:
                name = c.get('name', '').strip()
                if not name:
                    continue
                concept = WikiConcept(
                    document_id=doc_id, name=name,
                    type=c.get('type', 'concept'),
                    description=c.get('description', ''),
                    aliases=','.join(c.get('aliases', [])),
                    group_name=c.get('group', ''),
                    category=c.get('category', ''),
                )
                db.add(concept)
            db.commit()
            all_concepts = deduped  # 用去重后的继续

        # ── Stage 3: 知识点合并 ──
        if not existing_kps:
            doc.extract_stage = 'Stage 3: merge'
            db.commit()

            if existing_concepts:
                # 从已有概念合并
                concepts_for_merge = []
                for c in existing_concepts:
                    concepts_for_merge.append({
                        'name': c.name, 'type': c.type, 'description': c.description or '',
                        'aliases': [a.strip() for a in c.aliases.split(',') if a.strip()] if c.aliases else [],
                        'group': c.group_name, 'category': c.category,
                    })
                grouped = _merge_groups(concepts_for_merge)
            else:
                grouped = _merge_groups(all_concepts)

            _log(db, doc_id, 'Stage 3', f'{len(grouped)} knowledge points created', 'info')

            name_to_kp = {}
            kp_records = []
            for entry in grouped:
                name = entry['name']
                kp = WikiKnowledgePoint(
                    document_id=doc_id, title=name,
                    description=entry['description'],
                    category=entry['category'],
                    tags='',
                    aliases=','.join(entry['aliases']),
                    group_name=entry['group'],
                    status='整理中',
                )
                db.add(kp)
                db.flush()
                kp_records.append(kp)
                name_to_kp[name] = kp
                for a in entry['aliases']:
                    alias_map[a.strip()] = name
                for sub_name in entry.get('sub_concept_names', []):
                    alias_map[sub_name] = name

            # 写入关系
            for rel in all_relations:
                from_name = alias_map.get(rel['from'], rel['from'])
                to_name = alias_map.get(rel['to'], rel['to'])
                from_kp = name_to_kp.get(from_name)
                to_kp = name_to_kp.get(to_name)
                if from_kp and to_kp:
                    db.add(WikiKnowledgeRelation(
                        from_point_id=from_kp.id, to_point_id=to_kp.id,
                        type=rel.get('type', ''), confidence=rel.get('confidence', 1.0),
                    ))
            db.commit()
            existing_kps = kp_records

        # ── Stage 3.5a: 描述生成 ──
        kps_need_desc = [kp for kp in existing_kps if not (kp.description or '').strip() or kp.description == entry.get('description', '')]
        if kps_need_desc:
            doc.extract_stage = 'Stage 3.5a: description generation'
            doc.progress_total = len(kps_need_desc)
            db.commit()
            _log(db, doc_id, 'Stage 3.5a', f'Generating descriptions for {len(kps_need_desc)} KPs', 'info')

            ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(_gen_description, kp.title, kp.description or '', kp.category or ''): kp
                    for kp in kps_need_desc
                }
                for future in as_completed(futures):
                    kp = futures[future]
                    try:
                        new_desc = future.result()
                        if new_desc:
                            kp.description = new_desc
                            ok += 1
                    except Exception as e:
                        _log(db, doc_id, 'Stage 3.5a', f'Desc fail for "{kp.title}": {e}', 'warning')
                    doc.progress_current = ok
                    db.commit()
            _log(db, doc_id, 'Stage 3.5a', f'Descriptions: {ok}/{len(kps_need_desc)}', 'info')

        # ── Stage 3.5b: 文章生成 ──
        kps_need_article = [kp for kp in existing_kps if not (kp.content or '').strip()]
        if kps_need_article:
            doc.extract_stage = 'Stage 3.5b: article generation'
            doc.progress_total = len(kps_need_article)
            db.commit()
            _log(db, doc_id, 'Stage 3.5b', f'Generating articles for {len(kps_need_article)} KPs', 'info')

            ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(
                        _gen_article,
                        kp.title, kp.description or '', kp.category or '',
                        kp.tags or '', source_name, None,
                    ): kp
                    for kp in kps_need_article
                }
                for future in as_completed(futures):
                    kp = futures[future]
                    try:
                        article = future.result()
                        kp.content = article
                        kp.status = '已发布'
                        ok += 1
                        _log(db, doc_id, 'Stage 3.5b', f'Article done: "{kp.title}"', 'info')
                    except Exception as e:
                        _log(db, doc_id, 'Stage 3.5b', f'Article fail for "{kp.title}": {e}', 'warning')
                    doc.progress_current = ok
                    db.commit()
            _log(db, doc_id, 'Stage 3.5b', f'Articles: {ok}/{len(kps_need_article)}', 'info')

        # ── 完成 ──
        doc.status = 'completed'
        doc.extract_stage = 'done'
        doc.progress_current = doc.progress_total
        db.commit()
        _log(db, doc_id, 'done', f'Extraction complete: {len(existing_kps)} KPs', 'info')
        logger.info(f"Wiki extraction complete for doc_id={doc_id}")

    except Exception as e:
        logger.exception(f"Wiki extraction failed doc_id={doc_id}")
        try:
            doc = db.query(WikiDocument).filter(WikiDocument.id == doc_id).first()
            if doc:
                doc.status = 'failed'
                doc.extract_stage = f'error: {str(e)[:200]}'
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
```

- [ ] **Step 2: 验证引擎可导入**

Run:
```bash
cd engine && python -c "from engine.app.wiki.extraction_engine import run_extraction, _chunk_text; print('Engine OK')"
```
Expected: `Engine OK`

- [ ] **Step 3: Commit**

```bash
git add engine/app/wiki/extraction_engine.py
git commit -m "feat: add Wiki extraction engine (3-stage pipeline)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Engine — Wiki Extract API 端点

**Files:**
- Create: `engine/app/api/wiki.py`
- Modify: `engine/run.py`

- [ ] **Step 1: 创建 `engine/app/api/wiki.py`**

```python
# prism/engine/app/api/wiki.py
"""Engine Wiki extract endpoint"""
import threading
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..wiki.extraction_engine import run_extraction

router = APIRouter(prefix="/wiki", tags=["wiki"])
logger = logging.getLogger(__name__)


class WikiExtractRequest(BaseModel):
    doc_id: str = Field(..., description="wiki_document.id")
    file_id: str = Field(..., description="knowledge_file.id")


@router.post("/extract")
def extract(request: WikiExtractRequest):
    """异步启动 Wiki 知识抽取管线。"""
    logger.info(f"Wiki extraction triggered: doc_id={request.doc_id}")

    def _run():
        try:
            run_extraction(request.doc_id, request.file_id)
        except Exception as e:
            logger.exception(f"Wiki extraction failed: doc_id={request.doc_id}: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return {"doc_id": request.doc_id, "status": "processing"}
```

- [ ] **Step 2: 修改 `engine/run.py` 注册 Wiki router**

```python
# prism/engine/run.py
import uvicorn
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from engine.app.config import settings
from engine.app.milvus_client import connect, ensure_collection
from engine.app.es_client import ensure_index
from engine.app.api.ingest import router as ingest_router
from engine.app.api.chat import router as chat_router
from engine.app.api.wiki import router as wiki_router


def create_app():
    app = FastAPI(title="Prism Engine")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    prefixed = APIRouter(prefix="/api/v1")
    prefixed.include_router(ingest_router)
    prefixed.include_router(chat_router)
    prefixed.include_router(wiki_router)
    app.include_router(prefixed)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    def startup():
        connect()
        ensure_collection()
        print("[engine] Milvus 已连接")
        try:
            ensure_index()
            print("[engine] ES 索引已就绪")
        except Exception as e:
            print(f"[engine] ES 初始化失败（检索将回退到 MySQL BM25）: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("engine.run:app", host=settings.ENGINE_HOST, port=settings.ENGINE_PORT, reload=False)
```

- [ ] **Step 3: 验证 Engine 启动**

Run:
```bash
cd engine && python -c "from engine.run import app; print([r.path for r in app.routes if 'wiki' in r.path])"
```
Expected: 看到 `/api/v1/wiki/extract` 路由

- [ ] **Step 4: Commit**

```bash
git add engine/app/api/wiki.py engine/run.py
git commit -m "feat: add Engine wiki extract endpoint

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Frontend — API 类型与函数

**Files:**
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: 在 `frontend/src/app/api.ts` 末尾追加 Wiki 类型和函数**

```typescript
// ── Wiki types ────────────────────────────────────────────────

export interface WikiDocument {
  id: string
  file_id: string
  status: string
  extract_stage: string
  progress_current: number
  progress_total: number
  user_id: string
  created_at: string
  original_filename?: string | null
  mime_type?: string | null
  file_size?: number | null
}

export interface WikiDocumentDetail extends WikiDocument {
  logs: WikiExtractionLog[]
}

export interface WikiKnowledgePoint {
  id: string
  document_id: string
  title: string
  description?: string | null
  content?: string | null
  category: string
  tags: string
  aliases: string
  group_name: string
  status: string
  images?: string | null
  user_id: string
  created_at: string
}

export interface WikiKnowledgePointListItem {
  id: string
  document_id: string
  title: string
  description?: string | null
  category: string
  tags: string
  status: string
  created_at: string
}

export interface WikiKnowledgeRelation {
  id: string
  from_point_id: string
  to_point_id: string
  type: string
  confidence: number
  created_at: string
  from_title?: string | null
  to_title?: string | null
}

export interface WikiExtractionLog {
  id: string
  document_id: string
  stage: string
  message: string
  status: string
  progress_current: number
  progress_total: number
  created_at: string
}

// ── Wiki API functions ────────────────────────────────────────

export async function fetchWikiDocuments(): Promise<WikiDocument[]> {
  return request('/wiki/documents')
}

export async function fetchWikiDocument(id: string): Promise<WikiDocumentDetail> {
  return request(`/wiki/documents/${id}`)
}

export async function deleteWikiDocument(id: string): Promise<void> {
  await request(`/wiki/documents/${id}`, { method: 'DELETE' })
}

export async function fetchWikiPoints(docId?: string): Promise<WikiKnowledgePointListItem[]> {
  const params = docId ? `?doc_id=${encodeURIComponent(docId)}` : ''
  return request(`/wiki/points${params}`)
}

export async function fetchWikiPoint(id: string): Promise<WikiKnowledgePoint> {
  return request(`/wiki/points/${id}`)
}

export async function fetchWikiPointRelations(id: string): Promise<WikiKnowledgeRelation[]> {
  return request(`/wiki/points/${id}/relations`)
}

export async function uploadWikiFile(file: File): Promise<{ file_id: string; wiki_doc_id: string; status: string }> {
  const form = new FormData()
  form.append('file', file)
  return uploadRequest('/upload/wiki', form)
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run:
```bash
cd frontend && pnpm exec tsc --noEmit src/app/api.ts 2>&1 | head -20
```
Expected: No errors related to Wiki types

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api.ts
git commit -m "feat: add Wiki API types and functions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Frontend — Wiki Zustand Store

**Files:**
- Create: `frontend/src/app/wikiStore.ts`

- [ ] **Step 1: 创建 `frontend/src/app/wikiStore.ts`**

```typescript
import { create } from 'zustand'
import type {
  WikiDocument, WikiDocumentDetail, WikiKnowledgePoint,
  WikiKnowledgePointListItem, WikiKnowledgeRelation,
} from './api'
import * as api from './api'

interface WikiState {
  // Document list
  documents: WikiDocument[]
  documentsLoading: boolean
  loadDocuments: () => Promise<void>

  // Selected document detail
  selectedDoc: WikiDocumentDetail | null
  selectedDocLoading: boolean
  loadDocument: (id: string) => Promise<void>

  // Knowledge points
  points: WikiKnowledgePointListItem[]
  pointsLoading: boolean
  loadPoints: (docId?: string) => Promise<void>

  // Selected point detail
  selectedPoint: WikiKnowledgePoint | null
  selectedPointLoading: boolean
  selectedPointRelations: WikiKnowledgeRelation[]
  loadPoint: (id: string) => Promise<void>

  // Upload
  uploading: boolean
  uploadFile: (file: File) => Promise<{ wiki_doc_id: string }>

  // Delete
  deleteDocument: (id: string) => Promise<void>
}

export const useWikiStore = create<WikiState>((set, get) => ({
  documents: [],
  documentsLoading: false,
  async loadDocuments() {
    set({ documentsLoading: true })
    try {
      const documents = await api.fetchWikiDocuments()
      set({ documents })
    } finally {
      set({ documentsLoading: false })
    }
  },

  selectedDoc: null,
  selectedDocLoading: false,
  async loadDocument(id: string) {
    set({ selectedDocLoading: true })
    try {
      const selectedDoc = await api.fetchWikiDocument(id)
      set({ selectedDoc })
    } finally {
      set({ selectedDocLoading: false })
    }
  },

  points: [],
  pointsLoading: false,
  async loadPoints(docId?: string) {
    set({ pointsLoading: true })
    try {
      const points = await api.fetchWikiPoints(docId)
      set({ points })
    } finally {
      set({ pointsLoading: false })
    }
  },

  selectedPoint: null,
  selectedPointLoading: false,
  selectedPointRelations: [],
  async loadPoint(id: string) {
    set({ selectedPointLoading: true })
    try {
      const [selectedPoint, selectedPointRelations] = await Promise.all([
        api.fetchWikiPoint(id),
        api.fetchWikiPointRelations(id),
      ])
      set({ selectedPoint, selectedPointRelations })
    } finally {
      set({ selectedPointLoading: false })
    }
  },

  uploading: false,
  async uploadFile(file: File) {
    set({ uploading: true })
    try {
      const result = await api.uploadWikiFile(file)
      return { wiki_doc_id: result.wiki_doc_id }
    } finally {
      set({ uploading: false })
    }
  },

  async deleteDocument(id: string) {
    await api.deleteWikiDocument(id)
    set({ documents: get().documents.filter(d => d.id !== id) })
  },
}))
```

- [ ] **Step 2: 验证编译**

Run:
```bash
cd frontend && pnpm exec tsc --noEmit src/app/wikiStore.ts 2>&1
```
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/wikiStore.ts
git commit -m "feat: add Wiki Zustand store

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Frontend — Wiki 页面

**Files:**
- Create: `frontend/src/pages/WikiPage.tsx`
- Create: `frontend/src/pages/WikiUploadPage.tsx`
- Create: `frontend/src/pages/WikiDocDetail.tsx`
- Create: `frontend/src/pages/WikiPointDetail.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1: 创建 `frontend/src/pages/WikiPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'
import type { WikiDocument } from '@/app/api'

export function WikiPage() {
  const navigate = useNavigate()
  const { documents, documentsLoading, loadDocuments, points, pointsLoading, loadPoints } = useWikiStore()
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    if (selectedDocId) {
      loadPoints(selectedDocId)
    }
  }, [selectedDocId, loadPoints])

  const selectedDoc = documents.find(d => d.id === selectedDocId)

  const statusLabel = (status: string) => {
    switch (status) {
      case 'pending': return '⏳ 待处理'
      case 'processing': return '🔄 处理中'
      case 'completed': return '✅ 已完成'
      case 'failed': return '❌ 失败'
      default: return status
    }
  }

  return (
    <div style={{ display: 'flex', height: '100%', padding: '1.5rem', gap: '1.5rem' }}>
      {/* 左侧：文档列表 */}
      <div style={{ width: '320px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>Wiki 知识库</h2>
          <button
            onClick={() => navigate('/wiki/upload')}
            style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', borderRadius: 6, border: '1px solid #d0d5dd', background: '#fff' }}
          >
            + 上传文档
          </button>
        </div>

        {documentsLoading ? (
          <p style={{ color: '#667085' }}>加载中...</p>
        ) : documents.length === 0 ? (
          <p style={{ color: '#667085' }}>暂无文档，点击上传开始</p>
        ) : (
          documents.map(doc => (
            <div
              key={doc.id}
              onClick={() => setSelectedDocId(doc.id)}
              style={{
                padding: '0.75rem 1rem',
                border: selectedDocId === doc.id ? '2px solid #4f46e5' : '1px solid #e5e7eb',
                borderRadius: 8,
                cursor: 'pointer',
                background: selectedDocId === doc.id ? '#eef2ff' : '#fff',
              }}
            >
              <div style={{ fontWeight: 500, marginBottom: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                📄 {doc.original_filename || doc.id}
              </div>
              <div style={{ fontSize: '0.8rem', color: '#667085' }}>{statusLabel(doc.status)}</div>
              {doc.status === 'processing' && doc.progress_total > 0 && (
                <div style={{ marginTop: '0.25rem', height: 4, background: '#e5e7eb', borderRadius: 2 }}>
                  <div style={{
                    height: '100%', width: `${Math.round((doc.progress_current / doc.progress_total) * 100)}%`,
                    background: '#4f46e5', borderRadius: 2, transition: 'width 0.3s',
                  }} />
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* 右侧：知识点列表 */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {selectedDoc ? (
          <>
            <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '1.25rem', fontWeight: 600 }}>
              {selectedDoc.original_filename || '文档详情'}
              <span style={{ fontSize: '0.85rem', fontWeight: 400, color: '#667085', marginLeft: '0.75rem' }}>
                {statusLabel(selectedDoc.status)}
              </span>
            </h2>

            {pointsLoading ? (
              <p style={{ color: '#667085' }}>加载知识点...</p>
            ) : points.length === 0 ? (
              <p style={{ color: '#667085' }}>
                {selectedDoc.status === 'completed' ? '该文档未提取到知识点' : '文档处理中，完成后将显示知识点'}
              </p>
            ) : (
              points.map(point => (
                <div
                  key={point.id}
                  onClick={() => navigate(`/wiki/points/${point.id}`)}
                  style={{
                    padding: '0.75rem 1rem', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer',
                    transition: 'box-shadow 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)')}
                  onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
                >
                  <div style={{ fontWeight: 500 }}>🔗 {point.title}</div>
                  <div style={{ fontSize: '0.8rem', color: '#667085', marginTop: '0.25rem' }}>
                    {point.category && `${point.category} · `}{point.status}
                  </div>
                </div>
              ))
            )}
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af' }}>
            选择左侧文档查看知识点
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 创建 `frontend/src/pages/WikiUploadPage.tsx`**

```tsx
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

const ALLOWED_EXTS = ['.pdf', '.docx', '.xlsx', '.md', '.txt', '.markdown']

export function WikiUploadPage() {
  const navigate = useNavigate()
  const { uploadFile, uploading } = useWikiStore()
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(`不支持的文件类型: ${ext}`)
      return
    }
    setError(null)
    try {
      const { wiki_doc_id } = await uploadFile(file)
      navigate(`/wiki/documents/${wiki_doc_id}`)
    } catch (e: any) {
      setError(e.message || '上传失败')
    }
  }

  return (
    <div style={{ maxWidth: 600, margin: '3rem auto', padding: '1.5rem' }}>
      <h2 style={{ marginBottom: '1rem', fontSize: '1.25rem', fontWeight: 600 }}>上传 Wiki 文档</h2>

      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => {
          e.preventDefault()
          setDragOver(false)
          const file = e.dataTransfer.files[0]
          if (file) handleFile(file)
        }}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? '#4f46e5' : '#d0d5dd'}`,
          borderRadius: 12,
          padding: '3rem 2rem',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragOver ? '#eef2ff' : '#f9fafb',
          transition: 'all 0.2s',
        }}
      >
        {uploading ? (
          <p>上传中...</p>
        ) : (
          <>
            <p style={{ fontSize: '1.1rem', fontWeight: 500, marginBottom: '0.5rem' }}>
              拖拽文档到此处，或点击选择文件
            </p>
            <p style={{ color: '#667085', fontSize: '0.85rem' }}>
              支持 PDF / DOCX / XLSX / MD / TXT
            </p>
          </>
        )}
      </div>

      {error && (
        <p style={{ color: '#dc2626', marginTop: '0.75rem', fontSize: '0.9rem' }}>{error}</p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={ALLOWED_EXTS.join(',')}
        style={{ display: 'none' }}
        onChange={e => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
        }}
      />

      <button
        onClick={() => navigate('/wiki')}
        style={{
          marginTop: '1rem', padding: '0.5rem 1rem', cursor: 'pointer',
          border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff',
        }}
      >
        ← 返回列表
      </button>
    </div>
  )
}
```

- [ ] **Step 3: 创建 `frontend/src/pages/WikiDocDetail.tsx`**

```tsx
import { useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

export function WikiDocDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { selectedDoc, selectedDocLoading, loadDocument, points, pointsLoading, loadPoints, deleteDocument } = useWikiStore()
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    if (!id) return
    loadDocument(id)
    loadPoints(id)

    // Poll for progress if processing
    pollRef.current = setInterval(() => {
      loadDocument(id)
      loadPoints(id)
    }, 3000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [id, loadDocument, loadPoints])

  // Stop polling when done
  useEffect(() => {
    if (selectedDoc && (selectedDoc.status === 'completed' || selectedDoc.status === 'failed')) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = undefined
      }
    }
  }, [selectedDoc])

  const handleDelete = async () => {
    if (!id || !confirm('确定删除该文档及所有提取的知识点？')) return
    await deleteDocument(id)
    navigate('/wiki')
  }

  if (selectedDocLoading || !selectedDoc) {
    return <p style={{ padding: '2rem', color: '#667085' }}>加载中...</p>
  }

  const progressPct = selectedDoc.progress_total > 0
    ? Math.round((selectedDoc.progress_current / selectedDoc.progress_total) * 100)
    : 0

  return (
    <div style={{ maxWidth: 800, margin: '1.5rem auto', padding: '1.5rem' }}>
      <button
        onClick={() => navigate('/wiki')}
        style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff', marginBottom: '1rem' }}
      >
        ← 返回
      </button>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 600 }}>
            📄 {selectedDoc.original_filename || '文档详情'}
          </h2>
          <p style={{ color: '#667085', fontSize: '0.85rem', marginTop: '0.25rem' }}>
            状态：{selectedDoc.status} · 阶段：{selectedDoc.extract_stage || '—'}
          </p>
        </div>
        <button
          onClick={handleDelete}
          style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #fca5a5', borderRadius: 6, background: '#fef2f2', color: '#dc2626' }}
        >
          删除
        </button>
      </div>

      {/* Progress bar */}
      {selectedDoc.status === 'processing' && selectedDoc.progress_total > 0 && (
        <div style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#667085', marginBottom: '0.25rem' }}>
            <span>{selectedDoc.extract_stage}</span>
            <span>{progressPct}%</span>
          </div>
          <div style={{ height: 6, background: '#e5e7eb', borderRadius: 3 }}>
            <div style={{
              height: '100%', width: `${progressPct}%`,
              background: '#4f46e5', borderRadius: 3, transition: 'width 0.5s',
            }} />
          </div>
        </div>
      )}

      {/* Logs */}
      {selectedDoc.logs && selectedDoc.logs.length > 0 && (
        <details style={{ marginBottom: '1.5rem' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 500, fontSize: '0.95rem' }}>
            管线日志 ({selectedDoc.logs.length})
          </summary>
          <div style={{ maxHeight: 200, overflow: 'auto', marginTop: '0.5rem', background: '#f9fafb', borderRadius: 6, padding: '0.5rem 0.75rem', fontSize: '0.8rem' }}>
            {selectedDoc.logs.map(log => (
              <div key={log.id} style={{ padding: '0.2rem 0', color: log.status === 'error' ? '#dc2626' : log.status === 'warning' ? '#d97706' : '#374151' }}>
                [{log.stage}] {log.message}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Knowledge points */}
      <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.75rem' }}>
        知识点 {points.length > 0 && `(${points.length})`}
      </h3>

      {pointsLoading ? (
        <p style={{ color: '#667085' }}>加载中...</p>
      ) : points.length === 0 ? (
        <p style={{ color: '#667085' }}>暂无知识点</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {points.map(point => (
            <div
              key={point.id}
              onClick={() => navigate(`/wiki/points/${point.id}`)}
              style={{
                padding: '0.75rem 1rem', border: '1px solid #e5e7eb', borderRadius: 8, cursor: 'pointer',
                transition: 'box-shadow 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)')}
              onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
            >
              <div style={{ fontWeight: 500 }}>{point.title}</div>
              {point.description && (
                <div style={{ fontSize: '0.85rem', color: '#667085', marginTop: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {point.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 创建 `frontend/src/pages/WikiPointDetail.tsx`**

```tsx
import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWikiStore } from '@/app/wikiStore'

export function WikiPointDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { selectedPoint, selectedPointLoading, selectedPointRelations, loadPoint } = useWikiStore()

  useEffect(() => {
    if (!id) return
    loadPoint(id)
  }, [id, loadPoint])

  if (selectedPointLoading || !selectedPoint) {
    return <p style={{ padding: '2rem', color: '#667085' }}>加载中...</p>
  }

  const tags = selectedPoint.tags ? selectedPoint.tags.split(',').filter(Boolean) : []

  return (
    <div style={{ maxWidth: 800, margin: '1.5rem auto', padding: '1.5rem' }}>
      <button
        onClick={() => navigate(-1)}
        style={{ padding: '0.4rem 0.8rem', cursor: 'pointer', border: '1px solid #d0d5dd', borderRadius: 6, background: '#fff', marginBottom: '1rem' }}
      >
        ← 返回
      </button>

      <article>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.75rem' }}>{selectedPoint.title}</h1>

        {/* Meta */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1.5rem', fontSize: '0.85rem', color: '#667085' }}>
          {selectedPoint.category && <span style={{ background: '#f3f4f6', padding: '0.2rem 0.6rem', borderRadius: 4 }}>📁 {selectedPoint.category}</span>}
          {tags.map(tag => (
            <span key={tag} style={{ background: '#eef2ff', color: '#4f46e5', padding: '0.2rem 0.6rem', borderRadius: 4 }}>{tag}</span>
          ))}
          <span style={{ background: '#f3f4f6', padding: '0.2rem 0.6rem', borderRadius: 4 }}>{selectedPoint.status}</span>
        </div>

        {/* Content: render Markdown as plain text with basic formatting */}
        {selectedPoint.content ? (
          <div
            style={{ lineHeight: 1.8, fontSize: '0.95rem' }}
            dangerouslySetInnerHTML={{
              __html: selectedPoint.content
                .replace(/^### (.+)$/gm, '<h3 style="font-size:1.1rem;font-weight:600;margin:1rem 0 0.5rem">$1</h3>')
                .replace(/^## (.+)$/gm, '<h2 style="font-size:1.2rem;font-weight:600;margin:1.25rem 0 0.5rem">$1</h2>')
                .replace(/^# (.+)$/gm, '<h1 style="font-size:1.4rem;font-weight:700;margin:1.5rem 0 0.5rem">$1</h1>')
                .replace(/^- (.+)$/gm, '<li style="margin-left:1.5rem">$1</li>')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\n\n/g, '<br/><br/>')
            }}
          />
        ) : (
          <p style={{ color: '#667085' }}>{selectedPoint.description || '暂无内容'}</p>
        )}

        {/* Relations */}
        {selectedPointRelations.length > 0 && (
          <div style={{ marginTop: '2rem', paddingTop: '1.5rem', borderTop: '1px solid #e5e7eb' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.75rem' }}>
              关联知识点 ({selectedPointRelations.length})
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {selectedPointRelations.map(rel => {
                const isFrom = rel.from_point_id === selectedPoint.id
                const otherTitle = isFrom ? rel.to_title : rel.from_title
                const otherId = isFrom ? rel.to_point_id : rel.from_point_id
                const dirLabel = isFrom ? `→ ${rel.type}` : `${rel.type} →`
                return (
                  <div
                    key={rel.id}
                    onClick={() => navigate(`/wiki/points/${otherId}`)}
                    style={{
                      padding: '0.5rem 0.75rem', border: '1px solid #e5e7eb', borderRadius: 6, cursor: 'pointer',
                      fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem',
                    }}
                  >
                    <span style={{ color: '#667085', fontSize: '0.8rem' }}>{dirLabel}</span>
                    <span style={{ fontWeight: 500 }}>{otherTitle || otherId}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </article>
    </div>
  )
}
```

- [ ] **Step 5: 修改 `frontend/src/app/routes.tsx`**

```tsx
import { createBrowserRouter } from 'react-router-dom'
import { MainLayout } from '@/layouts/MainLayout'
import { ChatPage } from '@/pages/ChatPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { WikiPage } from '@/pages/WikiPage'
import { WikiUploadPage } from '@/pages/WikiUploadPage'
import { WikiDocDetail } from '@/pages/WikiDocDetail'
import { WikiPointDetail } from '@/pages/WikiPointDetail'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      { index: true, element: <ChatPage /> },
      { path: 'chat', element: <ChatPage /> },
      { path: 'knowledge', element: <KnowledgePage /> },
      { path: 'wiki', element: <WikiPage /> },
      { path: 'wiki/upload', element: <WikiUploadPage /> },
      { path: 'wiki/documents/:id', element: <WikiDocDetail /> },
      { path: 'wiki/points/:id', element: <WikiPointDetail /> },
    ],
  },
])
```

- [ ] **Step 6: 验证前端构建**

Run:
```bash
cd frontend && pnpm build 2>&1
```
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/WikiPage.tsx frontend/src/pages/WikiUploadPage.tsx frontend/src/pages/WikiDocDetail.tsx frontend/src/pages/WikiPointDetail.tsx frontend/src/app/routes.tsx
git commit -m "feat: add Wiki frontend pages (list, upload, detail, point)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: End-to-End 验证

- [ ] **Step 1: 启动全栈**

```bash
# Term 1: Infrastructure
docker-compose up -d

# Term 2: Backend + Engine
cd backend && python -m backend.run
# Wait for both services to start

# Term 3: Frontend
cd frontend && pnpm dev
```

- [ ] **Step 2: 验证上传+提取流程**

```bash
# 上传测试文件
curl -X POST http://localhost:5175/api/v1/upload/wiki \
  -F "file=@docs/2026-06-15-prism-v1.1-chat-enhancement.md"
```
Expected: 返回 `{"file_id":"...", "wiki_doc_id":"...", "status":"pending"}`

- [ ] **Step 3: 检查提取进度**

```bash
# Replace DOC_ID with actual wiki_doc_id from previous response
curl http://localhost:5175/api/v1/wiki/documents/DOC_ID
```
Expected: `status` 为 `processing` 或 `completed`，包含日志

- [ ] **Step 4: 检查知识点**

```bash
curl http://localhost:5175/api/v1/wiki/points
```
Expected: 知识点列表（含 title、description、content 等）

- [ ] **Step 5: 浏览器验证**

打开 [http://localhost:5173/wiki](http://localhost:5173/wiki)，验证：
- 文档列表显示上传的文档
- 点击文档可查看进度和知识点
- 点击知识点可阅读 Markdown 文章
- 上传页面可正常拖拽上传

- [ ] **Step 6: Commit any fixes**

If any issues found, fix and commit with message:
```bash
git commit -m "fix: Wiki end-to-end fixes

Co-Authored-By: Claude <noreply@anthropic.com>"
```
