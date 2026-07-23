# backend/app/api/knowledge_files.py
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import KnowledgeFile
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeNotFound,
)
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import (
    DuplicateKnowledgeFile,
    KnowledgeUploadService,
    RedisJobPublisher,
    UploadRequest,
)
from backend.app.storage.files import LocalFileStorage

router = APIRouter(prefix="/knowledge-bases/{kb_uid}/files", tags=["knowledge-files"])


class FileMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    relative_path: str | None = Field(default=None, max_length=1024)


def _get_storage() -> LocalFileStorage:
    from backend.app.config import settings
    from pathlib import Path
    return LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))


def _get_publisher() -> RedisJobPublisher:
    from backend.app.config import settings
    return RedisJobPublisher(settings.REDIS_URL, settings.KNOWLEDGE_INGEST_QUEUE)


def _public_file(file_row: KnowledgeFile) -> dict:
    base = f"/api/v1/knowledge-bases/{file_row.kb_uid}/files/{file_row.file_uid}"
    return {
        "file_uid": file_row.file_uid,
        "kb_uid": file_row.kb_uid,
        "original_filename": file_row.original_filename,
        "relative_path": file_row.relative_path,
        "media_type": file_row.media_type,
        "mime_type": file_row.mime_type,
        "parse_status": file_row.parse_status,
        "index_status": file_row.index_status,
        "graph_status": file_row.graph_status,
        "content_sha256": file_row.content_sha256,
        "size_bytes": file_row.size_bytes,
        "preview_url": f"{base}/preview",
        "download_url": f"{base}/download",
    }


def _require_file(db: Session, actor: ActorContext, kb_uid: str, file_uid: str, *, manage: bool) -> KnowledgeFile:
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy
    try:
        policy = KnowledgeAccessPolicy(db)
        (policy.require_manage if manage else policy.require_read)(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")
    file_row = db.query(KnowledgeFile).filter_by(
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_uid,
        deleted_at=None,
    ).one_or_none()
    if file_row is None:
        raise ApiProblem(404, "FILE_NOT_FOUND", f"File {file_uid} not found")
    return file_row


def _job_snapshot(job) -> dict:
    return {"id": job.id, "job_type": job.job_type, "status": job.status, "stage": job.stage}


def _publish_job(db: Session, job) -> None:
    try:
        _get_publisher().publish(job.id)
        KnowledgeJobService(db).stage_enqueued(job.id)
    except Exception:
        db.rollback()


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
    svc = KnowledgeUploadService(db, storage, _get_publisher())
    try:
        content = file.file.read()
        file_row, job = svc.register(
            actor,
            UploadRequest(
                kb_uid=kb_uid,
                filename=file.filename or "unnamed",
                relative_path=relative_path,
                media_type="document",
                mime_type=file.content_type or "application/octet-stream",
                content=content,
                auto_index=auto_index.lower() == "true",
            ),
        )
        return {
            "file": _public_file(file_row),
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
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    relative_path: str | None = None,
    media_type: str | None = None,
    parse_status: str | None = None,
    index_status: str | None = None,
    graph_status: str | None = None,
):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy
    try:
        KnowledgeAccessPolicy(db).require_read(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

    query = db.query(KnowledgeFile).filter_by(
        tenant_id=actor.tenant_id, kb_uid=kb_uid, deleted_at=None
    )
    if cursor:
        query = query.filter(KnowledgeFile.file_uid > cursor)
    if relative_path:
        query = query.filter(KnowledgeFile.relative_path.startswith(relative_path))
    if media_type:
        query = query.filter(KnowledgeFile.media_type == media_type)
    if parse_status:
        query = query.filter(KnowledgeFile.parse_status == parse_status)
    if index_status:
        query = query.filter(KnowledgeFile.index_status == index_status)
    if graph_status:
        query = query.filter(KnowledgeFile.graph_status == graph_status)
    files = query.order_by(KnowledgeFile.file_uid.asc()).limit(limit + 1).all()
    has_more = len(files) > limit
    files = files[:limit]
    return {
        "items": [
            _public_file(f)
            for f in files
        ],
        "total": len(files),
        "next_cursor": files[-1].file_uid if has_more else None,
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
    return _public_file(file_row)


@router.patch("/{file_uid}")
def update_file_metadata(
    kb_uid: str,
    file_uid: str,
    body: FileMetadataUpdate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    file_row = _require_file(db, actor, kb_uid, file_uid, manage=True)
    from engine.app.knowledge.enrichment import (
        mark_enrichment_stale,
        safe_display_name,
        safe_relative_path,
    )
    title = safe_display_name(body.title or file_row.title or file_row.original_filename)
    relative_path = safe_relative_path(
        body.relative_path if body.relative_path is not None else file_row.relative_path,
        fallback_basename=title,
    )
    file_row.title = title
    file_row.original_filename = title
    file_row.relative_path = relative_path
    mark_enrichment_stale(
        db, kb_uid, reason="file_renamed",
        renamed=[{"file_uid": file_uid, "title": title, "relative_path": relative_path}],
        commit=False,
    )
    db.commit()
    db.refresh(file_row)
    return _public_file(file_row)


@router.get("/{file_uid}/preview")
def preview_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    file_row = _require_file(db, actor, kb_uid, file_uid, manage=False)
    content = _get_storage().read_bytes(file_row.storage_uri)
    return {"file_uid": file_uid, "content": content.decode("utf-8", errors="replace")}


@router.get("/{file_uid}/download")
def download_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    file_row = _require_file(db, actor, kb_uid, file_uid, manage=False)
    content = _get_storage().read_bytes(file_row.storage_uri)
    safe_name = file_row.original_filename.replace('"', "")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


def _create_file_job(db: Session, actor: ActorContext, kb_uid: str, file_uid: str, job_type: str):
    file_row = _require_file(db, actor, kb_uid, file_uid, manage=True)
    version = file_row.parsed_content_version or 0
    job = KnowledgeJobService(db).create(
        JobCommand(job_type, actor.tenant_id, kb_uid, file_uid, {}),
        f"{kb_uid}:{file_uid}:{job_type}:v{version}",
    )
    _publish_job(db, job)
    db.refresh(job)
    return _job_snapshot(job)


@router.post("/{file_uid}/parse", status_code=202)
def parse_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    return _create_file_job(db, actor, kb_uid, file_uid, "parse")


@router.post("/{file_uid}/index", status_code=202)
def index_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    return _create_file_job(db, actor, kb_uid, file_uid, "index")


@router.delete("/{file_uid}", status_code=202)
def delete_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    from backend.app.utils.time import local_now
    file_row = _require_file(db, actor, kb_uid, file_uid, manage=True)
    job = KnowledgeJobService(db).create(
        JobCommand("delete", actor.tenant_id, kb_uid, file_uid, {}),
        f"{kb_uid}:{file_uid}:delete",
        commit=False,
    )
    file_row.deleted_at = local_now()
    file_row.last_job_id = job.id
    from engine.app.knowledge.enrichment import mark_enrichment_stale
    mark_enrichment_stale(
        db,
        kb_uid,
        reason="file_deleted",
        deleted_file_uids=[file_uid],
        commit=False,
    )
    db.commit()
    _publish_job(db, job)
    db.refresh(job)
    return _job_snapshot(job)


@router.get("/jobs/{job_id}")
def get_job_status(
    kb_uid: str,
    job_id: str,
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

    from backend.app.models import KnowledgeJob
    job = db.query(KnowledgeJob).filter_by(
        id=job_id,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
    ).one_or_none()
    if job is None:
        raise ApiProblem(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "stage": job.stage,
        "attempt": job.attempt,
        "error_code": job.error_code,
    }
