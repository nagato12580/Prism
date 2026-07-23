"""Authorized APIs for versioned knowledge enrichment and safe export."""
from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import KnowledgeJob, KnowledgeTopic
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy, KnowledgeNotFound
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from engine.app.knowledge.enrichment import apply_mindmap_diff, build_knowledge_export


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-enrichment"])


class _StrictDto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationRequest(_StrictDto):
    model: str | None = Field(default=None, min_length=1, max_length=255)
    prompt_version: str = Field(default="v1", min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)


class MindmapRename(_StrictDto):
    file_uid: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=500)
    relative_path: str | None = Field(default=None, max_length=1024)


class MindmapAdd(_StrictDto):
    file_uid: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    parent_id: str | None = Field(default=None, max_length=128)
    relative_path: str | None = Field(default=None, max_length=1024)
    complex: bool = False


class MindmapDiffRequest(_StrictDto):
    expected_version: int | None = Field(default=None, ge=0)
    added: list[MindmapAdd | str] = Field(default_factory=list, max_length=200)
    deleted: list[str] = Field(default_factory=list, max_length=200)
    renamed: list[MindmapRename] = Field(default_factory=list, max_length=200)


class JobDto(_StrictDto):
    id: str
    job_type: Literal["mindmap_generation", "sample_questions_generation"]
    status: str
    stage: str


class GenerationResponse(_StrictDto):
    job: JobDto


class MindmapResponse(_StrictDto):
    mindmap: dict[str, Any]


class MindmapUpdateResponse(_StrictDto):
    mindmap: dict[str, Any] | None = None
    job: JobDto | None = None


class SampleQuestionsResponse(_StrictDto):
    sample_questions: dict[str, Any]


def _topic_or_problem(db: Session, actor: ActorContext, kb_uid: str, *, manage: bool):
    try:
        policy = KnowledgeAccessPolicy(db)
        return (policy.require_manage if manage else policy.require_read)(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")


def _publish_job_id(job_id: str) -> None:
    from backend.app.config import settings
    from backend.app.services.knowledge_uploads import RedisJobPublisher

    RedisJobPublisher(settings.REDIS_URL, settings.KNOWLEDGE_INGEST_QUEUE).publish(job_id)


def _job_dto(job) -> dict[str, str]:
    return {"id": job.id, "job_type": job.job_type, "status": job.status, "stage": job.stage or ""}


def _lock_topic_for_cancel(db: Session, tenant_id: str, kb_uid: str) -> KnowledgeTopic:
    return (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=tenant_id, kb_uid=kb_uid, deleted_at=None)
        .populate_existing()
        .with_for_update()
        .one()
    )


def _lock_job_for_cancel(
    db: Session,
    job_id: str,
    tenant_id: str,
    kb_uid: str,
) -> KnowledgeJob | None:
    return (
        db.query(KnowledgeJob)
        .filter_by(id=job_id, tenant_id=tenant_id, kb_uid=kb_uid)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )


def _set_generating(topic, kind: str, payload: dict[str, Any]) -> None:
    attribute = "mindmap" if kind == "mindmap_generation" else "sample_questions"
    existing = deepcopy(getattr(topic, attribute)) if isinstance(getattr(topic, attribute), dict) else {}
    existing.update({
        "status": "generating",
        "index_generation": payload.get("index_generation"),
        "graph_generation": payload.get("graph_generation"),
        "model": payload.get("model"),
        "prompt_version": payload.get("prompt_version"),
    })
    existing.setdefault("input_revision", int(payload.get("expected_input_revision") or 0))
    existing.setdefault("nodes" if attribute == "mindmap" else "questions", [])
    setattr(topic, attribute, existing)


def _enqueue_generation(
    db: Session,
    topic,
    *,
    job_type: Literal["mindmap_generation", "sample_questions_generation"],
    model: str,
    prompt_version: str,
    idempotency_key: str,
    extra_payload: dict[str, Any] | None = None,
):
    snapshot_attribute = "mindmap" if job_type == "mindmap_generation" else "sample_questions"
    version_attribute = "mindmap_version" if job_type == "mindmap_generation" else "sample_questions_version"
    snapshot = getattr(topic, snapshot_attribute)
    expected_input_revision = int(snapshot.get("input_revision") or 0) if isinstance(snapshot, dict) else 0
    request_identity = {
        "job_type": job_type,
        "model": model,
        "prompt_version": prompt_version,
        "extra_payload": extra_payload or {},
    }
    request_fingerprint = sha256(json.dumps(request_identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {
        "index_generation": topic.active_index_generation,
        "graph_generation": topic.active_graph_generation,
        "model": model,
        "prompt_version": prompt_version,
        "expected_version": int(getattr(topic, version_attribute) or 0),
        "expected_input_revision": expected_input_revision,
        "request_fingerprint": request_fingerprint,
    }
    if extra_payload:
        payload.update(extra_payload)
    jobs = KnowledgeJobService(db)
    durable_key = f"{topic.tenant_id}:{topic.kb_uid}:{job_type}:{idempotency_key}"
    existing = db.query(KnowledgeJob).filter_by(idempotency_key=durable_key).with_for_update().one_or_none()
    if existing is not None:
        if (existing.payload or {}).get("request_fingerprint") != request_fingerprint:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request")
        job = existing
        created = False
    else:
        job = KnowledgeJob(
            job_type=job_type, tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
            file_uid=None, payload=payload, idempotency_key=durable_key,
            status="queued", stage="", max_attempts=3,
        )
        db.add(job)
        try:
            db.commit()
            created = True
        except IntegrityError:
            db.rollback()
            job = db.query(KnowledgeJob).filter_by(idempotency_key=durable_key).one()
            if (job.payload or {}).get("request_fingerprint") != request_fingerprint:
                raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request")
            created = False
    if created:
        _set_generating(topic, job_type, payload)
        db.commit()
    if job.stage != "enqueued":
        try:
            _publish_job_id(job.id)
            jobs.stage_enqueued(job.id)
        except Exception:
            db.rollback()
    db.refresh(job)
    return job


@router.get("/{kb_uid}/mindmap", response_model=MindmapResponse)
def get_mindmap(kb_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    topic = _topic_or_problem(db, actor, kb_uid, manage=False)
    value = deepcopy(topic.mindmap) if isinstance(topic.mindmap, dict) else {
        "status": "stale", "version": topic.mindmap_version or 0, "input_revision": 0, "nodes": [],
    }
    value.setdefault("input_revision", 0)
    return {"mindmap": value}


@router.post("/{kb_uid}/mindmap/generate", status_code=202, response_model=GenerationResponse)
def generate_mindmap(
    kb_uid: str,
    body: GenerationRequest,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    topic = _topic_or_problem(db, actor, kb_uid, manage=True)
    from backend.app.config import settings
    job = _enqueue_generation(
        db, topic, job_type="mindmap_generation", model=body.model or settings.LLM_MODEL,
        prompt_version=body.prompt_version, idempotency_key=body.idempotency_key,
    )
    return {"job": _job_dto(job)}


def _update_mindmap_impl(kb_uid: str, body: MindmapDiffRequest, actor: ActorContext, db: Session, if_match: str | None = None):
    _topic_or_problem(db, actor, kb_uid, manage=True)
    topic = db.query(KnowledgeTopic).filter_by(
        tenant_id=actor.tenant_id, kb_uid=kb_uid, deleted_at=None,
    ).with_for_update().one()
    header_version = None
    if if_match is not None:
        try:
            header_version = int(if_match.strip('"'))
        except ValueError as exc:
            raise ApiProblem(422, "INVALID_IF_MATCH", "If-Match must be an integer version") from exc
    if header_version is not None and body.expected_version is not None and header_version != body.expected_version:
        raise ApiProblem(422, "VERSION_HEADER_MISMATCH", "If-Match and expected_version differ")
    expected = body.expected_version if body.expected_version is not None else header_version
    if expected is not None and expected != int(topic.mindmap_version or 0):
        raise ApiProblem(409, "MINDMAP_VERSION_CONFLICT", "Mindmap version changed")
    renamed = [row.model_dump(exclude_none=True) for row in body.renamed]
    additions = [row.model_dump(exclude_none=True) if isinstance(row, MindmapAdd) else row for row in body.added]
    updated = apply_mindmap_diff(topic.mindmap, added=additions, deleted=body.deleted, renamed=renamed)
    simple_adds = [row for row in additions if isinstance(row, dict) and not row.get("complex") and row.get("title")]
    requires_llm = len(simple_adds) != len(additions) or updated.get("unplaced_file_uids")
    if body.deleted or body.renamed or simple_adds:
        topic.mindmap_version = int(topic.mindmap_version or updated.get("version") or 0) + 1
        updated["version"] = topic.mindmap_version
        updated["updated_without_model"] = True
        topic.mindmap = updated
        db.commit()
    if body.added and requires_llm:
        from backend.app.config import settings
        fingerprint = sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
        job = _enqueue_generation(
            db, topic, job_type="mindmap_generation", model=settings.LLM_MODEL, prompt_version="v1",
            idempotency_key=f"diff:{topic.mindmap_version or 0}:{fingerprint}",
            extra_payload={"added": additions},
        )
        return ResponseWithStatus({"mindmap": None, "job": _job_dto(job)}, 202)
    return ResponseWithStatus({"mindmap": updated, "job": None}, 200)


class ResponseWithStatus:
    """Internal return carrier so PATCH and PUT share one implementation."""

    def __init__(self, payload: dict[str, Any], status_code: int):
        self.payload = payload
        self.status_code = status_code


@router.patch("/{kb_uid}/mindmap", response_model=MindmapUpdateResponse)
def update_mindmap(
    kb_uid: str,
    body: MindmapDiffRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    result = _update_mindmap_impl(kb_uid, body, actor, db, if_match)
    response.status_code = result.status_code
    return result.payload


@router.put("/{kb_uid}/mindmap", response_model=MindmapUpdateResponse)
def replace_mindmap_diff(
    kb_uid: str,
    body: MindmapDiffRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    result = _update_mindmap_impl(kb_uid, body, actor, db, if_match)
    response.status_code = result.status_code
    return result.payload


@router.get("/{kb_uid}/sample-questions", response_model=SampleQuestionsResponse)
def get_sample_questions(kb_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    topic = _topic_or_problem(db, actor, kb_uid, manage=False)
    value = deepcopy(topic.sample_questions) if isinstance(topic.sample_questions, dict) else {
        "status": "stale", "version": topic.sample_questions_version or 0, "input_revision": 0, "questions": [],
    }
    value.setdefault("input_revision", 0)
    return {"sample_questions": value}


@router.post("/{kb_uid}/sample-questions/generate", status_code=202, response_model=GenerationResponse)
def generate_sample_questions(
    kb_uid: str,
    body: GenerationRequest,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    topic = _topic_or_problem(db, actor, kb_uid, manage=True)
    from backend.app.config import settings
    job = _enqueue_generation(
        db, topic, job_type="sample_questions_generation", model=body.model or settings.LLM_MODEL,
        prompt_version=body.prompt_version, idempotency_key=body.idempotency_key,
    )
    return {"job": _job_dto(job)}


@router.post("/{kb_uid}/jobs/{job_id}/cancel", response_model=GenerationResponse)
def cancel_enrichment_job(
    kb_uid: str,
    job_id: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    _topic_or_problem(db, actor, kb_uid, manage=True)
    topic = _lock_topic_for_cancel(db, actor.tenant_id, kb_uid)
    job = _lock_job_for_cancel(db, job_id, actor.tenant_id, kb_uid)
    if job is None or job.job_type not in {"mindmap_generation", "sample_questions_generation"}:
        raise ApiProblem(404, "JOB_NOT_FOUND", "Enrichment job not found")
    if job.status in {"succeeded", "failed", "canceled"}:
        result = {"job": _job_dto(job)}
        db.commit()
        return result
    if job.status in {"queued", "claimed", "running"}:
        job = KnowledgeJobService(db).request_cancel(job.id, actor.actor_id, commit=False)
        from engine.app.knowledge.enrichment import mark_topic_enrichment_stale
        mark_topic_enrichment_stale(
            topic,
            reason="generation_canceled",
            increment_input_revision=False,
        )
        db.commit()
        db.refresh(job)
    return {"job": _job_dto(job)}


@router.get("/{kb_uid}/export")
def export_knowledge(kb_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    topic = _topic_or_problem(db, actor, kb_uid, manage=False)
    try:
        archive = build_knowledge_export(db, topic)
    except ValueError as exc:
        raise ApiProblem(413, "KNOWLEDGE_EXPORT_TOO_LARGE", "Knowledge export exceeds the configured budget") from exc
    def stream():
        try:
            archive.seek(0)
            while True:
                chunk = archive.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            archive.close()
    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="knowledge-{topic.kb_uid}.zip"'},
    )
