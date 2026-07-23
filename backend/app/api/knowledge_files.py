# backend/app/api/knowledge_files.py
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import KnowledgeFile, KnowledgeTopic
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeNotFound,
)
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import (
    DuplicateKnowledgeFile,
    KnowledgeUploadService,
    UploadRequest,
)
from backend.app.storage.files import LocalFileStorage

router = APIRouter(prefix="/knowledge-bases/{kb_uid}/files", tags=["knowledge-files"])


def _get_storage() -> LocalFileStorage:
    from backend.app.config import settings
    from pathlib import Path
    return LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))


class FileResponse(dict):
    pass


class UploadResponse(dict):
    pass


@router.post("", status_code=202)
def upload_file(
    kb_uid: str,
    file: UploadFile = File(...),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
    relative_path: str = Form(""),
    auto_index: str = Form("false"),
):
    storage = _get_storage()
    svc = KnowledgeUploadService(db, storage)
    try:
        content = file.file.read()
        file_row, _ = svc.register(
            actor,
            UploadRequest(
                kb_uid=kb_uid,
                filename=file.filename or "unnamed",
                relative_path=relative_path,
                media_type=file.content_type or "application/octet-stream",
                content=content,
                auto_index=auto_index.lower() == "true",
            ),
        )
        job_service = KnowledgeJobService(db)
        command = JobCommand(
            "parse",
            file_row.tenant_id,
            file_row.kb_uid,
            file_row.file_uid,
            {"auto_index": auto_index.lower() == "true"},
        )
        job = job_service.create(command, f"{file_row.kb_uid}:{file_row.file_uid}:parse:v1")
        return {
            "file": {
                "file_uid": file_row.file_uid,
                "kb_uid": file_row.kb_uid,
                "original_filename": file_row.original_filename,
                "relative_path": file_row.relative_path,
                "parse_status": file_row.parse_status,
                "storage_uri": file_row.storage_uri,
                "size_bytes": file_row.size_bytes,
            },
            "job": {
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status,
            },
        }
    except DuplicateKnowledgeFile as e:
        raise ApiProblem(409, "DUPLICATE_FILE", f"File already registered: {e.file_uid}")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")


@router.get("")
def list_files(
    kb_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy
    try:
        KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    files = (
        db.query(KnowledgeFile)
        .filter_by(kb_uid=kb_uid, deleted_at=None)
        .all()
    )
    return {
        "items": [
            {
                "file_uid": f.file_uid,
                "kb_uid": f.kb_uid,
                "original_filename": f.original_filename,
                "relative_path": f.relative_path,
                "parse_status": f.parse_status,
                "index_status": f.index_status,
                "graph_status": f.graph_status,
                "size_bytes": f.size_bytes,
            }
            for f in files
        ],
        "total": len(files),
    }


@router.get("/{file_uid}")
def get_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy
    try:
        KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    file_row = (
        db.query(KnowledgeFile)
        .filter_by(file_uid=file_uid, kb_uid=kb_uid, deleted_at=None)
        .one_or_none()
    )
    if file_row is None:
        raise ApiProblem(404, "FILE_NOT_FOUND", f"File {file_uid} not found")
    return {
        "file_uid": file_row.file_uid,
        "kb_uid": file_row.kb_uid,
        "tenant_id": file_row.tenant_id,
        "original_filename": file_row.original_filename,
        "relative_path": file_row.relative_path,
        "parse_status": file_row.parse_status,
        "index_status": file_row.index_status,
        "graph_status": file_row.graph_status,
        "storage_uri": file_row.storage_uri,
        "content_sha256": file_row.content_sha256,
        "size_bytes": file_row.size_bytes,
    }
