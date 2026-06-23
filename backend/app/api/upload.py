# prism/backend/app/api/upload.py
import threading
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import httpx

from ..database import get_db
from ..config import settings
from ..models.knowledge_item import KnowledgeItem, KnowledgeFile
from ..utils.file_parser import extract_text, extract_url
from ..schemas.knowledge import KnowledgeItemOut

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/file", response_model=KnowledgeItemOut)
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form(None),
    db: Session = Depends(get_db),
):
    # 保存文件
    ext = Path(file.filename).suffix
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".markdown"}
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")
    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = UPLOAD_DIR / saved_name
    content_bytes = await file.read()
    saved_path.write_bytes(content_bytes)

    # 解析
    try:
        text = extract_text(str(saved_path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {e}")

    # 创建知识条目
    title = Path(file.filename).stem
    item = KnowledgeItem(
        title=title,
        content=text,
        source_type="file",
        source_ref=str(saved_path),
        tags=[],
        category=category,
        user_id="default-user",
    )
    db.add(item)
    db.commit()

    # 记录文件
    kfile = KnowledgeFile(
        original_name=file.filename,
        file_path=str(saved_path),
        file_type=ext.lstrip("."),
        file_size=len(content_bytes),
        parse_status="done",
        item_id=item.id,
    )
    db.add(kfile)
    db.commit()

    # 异步触发摄入管线（fire and forget）
    _trigger_ingestion(item.id)

    db.refresh(item)
    return item


@router.post("/url", response_model=KnowledgeItemOut)
async def upload_url(
    url: str = Form(...),
    category: str = Form(None),
    db: Session = Depends(get_db),
):
    try:
        text = extract_url(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"URL 抓取失败: {e}")

    title = url.split("/")[-1][:50] or "网页知识"
    item = KnowledgeItem(
        title=title,
        content=text,
        source_type="url",
        source_ref=url,
        tags=[],
        category=category,
        user_id="default-user",
    )
    db.add(item)
    db.commit()

    _trigger_ingestion(item.id)

    db.refresh(item)
    return item


def _trigger_ingestion(item_id: str):
    """通过 HTTP 调用 Engine 的摄入 API（fire and forget）。"""
    try:
        import threading
        def _call():
            try:
                httpx.post(
                    f"{settings.ENGINE_BASE_URL}/api/v1/ingest",
                    json={"item_id": item_id},
                    timeout=30,
                )
            except Exception as exc:
                print(f"[upload] 摄入触发失败 item_id={item_id}: {exc}")
        threading.Thread(target=_call, daemon=True).start()
    except Exception as e:
        print(f"[upload] 摄入触发失败: {e}")


# ── Wiki Upload ─────────────────────────────────────────────

@router.post("/wiki")
async def upload_wiki_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Wiki 独立上传入口：保存文件 → 创建 knowledge_file + wiki_document → 触发提取。"""
    from ..models.wiki import WikiDocument
    import hashlib
    import traceback

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

    try:
        # 创建 knowledge_file（source_type=wiki）
        kfile = KnowledgeFile(
            original_name=file.filename,
            file_path=str(saved_path),
            file_type=ext.lstrip("."),
            file_size=len(content_bytes),
            md5=hashlib.md5(content_bytes).hexdigest(),
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
    except Exception as e:
        db.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"数据库写入失败: {e}")

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
                    f"{settings.ENGINE_BASE_URL}/api/v1/wiki/extract",
                    json={"doc_id": doc_id},
                    timeout=30,
                )
            except Exception as exc:
                print(f"[wiki] Engine extract trigger failed doc_id={doc_id}: {exc}")
        threading.Thread(target=_call, daemon=True).start()
    except Exception as e:
        print(f"[wiki] Extract trigger failed: {e}")
