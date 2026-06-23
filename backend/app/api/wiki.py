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
    db.delete(doc)  # CASCADE 删除所有关联数据
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
                f"{settings.ENGINE_BASE_URL}/api/v1/wiki/extract",
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
