# backend/app/api/citations.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.knowledge_citation import KnowledgeCitation
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy, KnowledgeNotFound
from backend.app.api.errors import ApiProblem

router = APIRouter(prefix="/citations", tags=["citations"])


class CitationCreate(BaseModel):
    kb_uid: str
    file_uid: str | None = None
    chunk_uid: str | None = None
    citation_text: str | None = None


@router.post("", status_code=201)
def create_citation(
    body: CitationCreate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    try:
        KnowledgeAccessPolicy(db).require_read(actor, body.kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {body.kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {body.kb_uid}")

    citation = KnowledgeCitation(
        tenant_id=actor.tenant_id,
        kb_uid=body.kb_uid,
        file_uid=body.file_uid,
        chunk_uid=body.chunk_uid,
        citation_text=body.citation_text,
    )
    db.add(citation)
    db.commit()
    db.refresh(citation)
    return {
        "id": citation.id,
        "kb_uid": citation.kb_uid,
        "file_uid": citation.file_uid,
        "chunk_uid": citation.chunk_uid,
        "citation_text": citation.citation_text,
    }


@router.get("/{citation_id}")
def get_citation(
    citation_id: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    citation = db.query(KnowledgeCitation).filter_by(id=citation_id).one_or_none()
    if citation is None:
        raise ApiProblem(404, "CITATION_NOT_FOUND", f"Citation {citation_id} not found")
    try:
        KnowledgeAccessPolicy(db).require_read(actor, citation.kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", "KB not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Access denied")

    return {
        "id": citation.id,
        "kb_uid": citation.kb_uid,
        "file_uid": citation.file_uid,
        "chunk_uid": citation.chunk_uid,
        "citation_text": citation.citation_text,
        "created_at": citation.created_at.isoformat() if citation.created_at else None,
    }
