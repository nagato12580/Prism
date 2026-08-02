# backend/app/api/knowledge_files.py
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from uuid import uuid4

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import KnowledgeFile
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import (
    DuplicateKnowledgeFile,
    KnowledgeUploadService,
    RedisJobPublisher,
    UploadRequest,
)
from backend.app.services.personal_inbox import (
    delete_personal_inbox_file_cascade,
    is_personal_inbox_asset_unit_file,
)
from backend.app.storage.files import LocalFileStorage

router = APIRouter(prefix="/knowledge-bases/{kb_uid}/files", tags=["knowledge-files"])

TEXT_PREVIEW_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/markdown",
}
TEXT_PREVIEW_EXTENSIONS = {".txt", ".md", ".markdown"}


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
        "parse_error": file_row.parse_error,
        "index_error": file_row.index_error,
        "graph_error": file_row.graph_error,
        "last_job_id": file_row.last_job_id,
        "content_sha256": file_row.content_sha256,
        "size_bytes": file_row.size_bytes,
        "source_kind": file_row.source_kind,
        "source_id": file_row.source_id,
        "system_type": file_row.system_type,
        "preview_url": f"{base}/preview",
        "download_url": f"{base}/download",
    }


def _require_file(db: Session, actor: ActorContext, kb_uid: str, file_uid: str, *, capability: Literal["read", "contribute", "edit"]) -> KnowledgeFile:
    try:
        policy = KnowledgeAccessPolicy(db)
        if capability == "read":
            policy.require_read(actor, kb_uid)
        elif capability == "contribute":
            policy.require_contribute(actor, kb_uid)
        else:
            policy.require_edit(actor, kb_uid)
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
    error_message = job.error_message
    if error_message and len(error_message) > 1000:
        error_message = f"{error_message[:1000]}..."
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "stage": job.stage,
        "error_code": job.error_code,
        "error_message": error_message,
    }


def _publish_job(db: Session, job) -> None:
    try:
        _get_publisher().publish(job.id)
        KnowledgeJobService(db).stage_enqueued(job.id)
    except Exception:
        db.rollback()


def _can_preview_original_as_text(file_row: KnowledgeFile) -> bool:
    mime_type = (file_row.mime_type or "").split(";", 1)[0].strip().lower()
    if mime_type in TEXT_PREVIEW_MIME_TYPES:
        return True
    filename = (file_row.original_filename or "").lower()
    return any(filename.endswith(ext) for ext in TEXT_PREVIEW_EXTENSIONS)


@router.post("", status_code=202)
def upload_file(
    kb_uid: str,
    file: UploadFile = File(...),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
    relative_path: str = Form(""),
    auto_index: str = Form("false"),
):
    try:
        KnowledgeAccessPolicy(db).require_contribute(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")

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
    file_row = _require_file(db, actor, kb_uid, file_uid, capability="edit")
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
    file_row = _require_file(db, actor, kb_uid, file_uid, capability="read")
    if file_row.content_text:
        return {"file_uid": file_uid, "content": file_row.content_text}
    if not _can_preview_original_as_text(file_row):
        return {"file_uid": file_uid, "content": ""}
    content = _get_storage().read_bytes(file_row.storage_uri)
    return {"file_uid": file_uid, "content": content.decode("utf-8", errors="replace")}


@router.get("/{file_uid}/download")
def download_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    file_row = _require_file(db, actor, kb_uid, file_uid, capability="read")
    content = _get_storage().read_bytes(file_row.storage_uri)
    safe_name = file_row.original_filename.replace('"', "")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


def _create_file_job(db: Session, actor: ActorContext, kb_uid: str, file_uid: str, job_type: str, *, capability: Literal["contribute", "edit"] = "contribute"):
    file_row = _require_file(db, actor, kb_uid, file_uid, capability=capability)
    version = file_row.parsed_content_version or 0
    base_key = f"{kb_uid}:{file_uid}:{job_type}:v{version}"
    from backend.app.models import KnowledgeJob
    if job_type == "index":
        kb_active = (
            db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.tenant_id == actor.tenant_id,
                KnowledgeJob.kb_uid == kb_uid,
                KnowledgeJob.job_type == "index",
                KnowledgeJob.status.in_({"queued", "claimed", "running"}),
            )
            .order_by(KnowledgeJob.created_at.desc(), KnowledgeJob.id.desc())
            .first()
        )
        if kb_active is not None:
            file_row.last_job_id = kb_active.id
            file_row.index_status = "running"
            if kb_active.status == "queued":
                kb_active.error_code = None
                kb_active.error_message = None
                kb_active.retryable = False
            db.commit()
            if kb_active.status == "queued":
                _publish_job(db, kb_active)
                db.refresh(kb_active)
            return _job_snapshot(kb_active)
    existing = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.kb_uid == kb_uid,
            KnowledgeJob.file_uid == file_uid,
            KnowledgeJob.job_type == job_type,
            KnowledgeJob.idempotency_key.like(f"{base_key}%"),
        )
        .order_by(KnowledgeJob.created_at.desc(), KnowledgeJob.id.desc())
        .all()
    )
    active = next(
        (job for job in existing if job.status in {"queued", "claimed", "running"}),
        None,
    )
    if active is not None:
        file_row.last_job_id = active.id
        if job_type == "parse":
            file_row.parse_status = "running"
        elif job_type == "index":
            file_row.index_status = "running"
        elif job_type == "graph":
            file_row.graph_status = "running"
        if active.status == "queued":
            active.error_code = None
            active.error_message = None
            active.retryable = False
        db.commit()
        if active.status == "queued":
            _publish_job(db, active)
            db.refresh(active)
        return _job_snapshot(active)

    idempotency_key = base_key
    if existing:
        latest = existing[0]
        idempotency_key = f"{base_key}:retry:{len(existing) + 1}:{latest.id}:{uuid4()}"
    job = KnowledgeJobService(db).create(
        JobCommand(job_type, actor.tenant_id, kb_uid, file_uid, {}),
        idempotency_key,
    )
    file_row.last_job_id = job.id
    if job_type == "parse":
        file_row.parse_status = "running"
    elif job_type == "index":
        file_row.index_status = "running"
    elif job_type == "graph":
        file_row.graph_status = "running"
    db.commit()
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


@router.post("/{file_uid}/graph", status_code=202)
def graph_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    return _create_file_job(db, actor, kb_uid, file_uid, "graph", capability="edit")


@router.delete("/{file_uid}", status_code=202)
def delete_file(
    kb_uid: str,
    file_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    from backend.app.utils.time import local_now
    file_row = _require_file(db, actor, kb_uid, file_uid, capability="edit")
    if is_personal_inbox_asset_unit_file(file_row):
        job = delete_personal_inbox_file_cascade(
            db,
            file_row,
            tenant_id=actor.tenant_id,
        )
    else:
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
        "error_message": (job.error_message[:1000] + "...") if job.error_message and len(job.error_message) > 1000 else job.error_message,
    }
