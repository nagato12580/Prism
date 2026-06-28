import json
from dataclasses import dataclass, field

from backend.app.models import KnowledgeFile, KnowledgeJob
from backend.app.utils.time import local_now


ACTIVE_STATUSES = {"queued", "processing"}
ELIGIBLE_INGEST_STATUSES = {"completed", "failed"}
STAGE_CREATED = "created"
STAGE_ENQUEUED = "enqueued"


@dataclass
class BatchEnqueueResult:
    queued: int = 0
    skipped: int = 0
    failed: int = 0
    job_ids: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _push(redis_client, queue_name, job_id):
    redis_client.lpush(queue_name, json.dumps({"job_id": job_id}))


def _active_job(db, resource_id, job_type, *, for_update=False):
    query = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.resource_id == resource_id,
            KnowledgeJob.job_type == job_type,
            KnowledgeJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(KnowledgeJob.created_at.desc(), KnowledgeJob.id.desc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _locked_resource(db, resource_id):
    return db.query(KnowledgeFile).filter(KnowledgeFile.id == resource_id).with_for_update().first()


def _enqueue_job_message(db, redis_client, queue_name, job):
    if job.stage == STAGE_ENQUEUED:
        return job

    _push(redis_client, queue_name, job.id)
    # Delivery is at-least-once: if this commit fails after Redis accepts the
    # message, a later retry may push again. Workers must claim jobs idempotently.
    job.stage = STAGE_ENQUEUED
    db.commit()
    db.refresh(job)
    return job


def _enqueue_active_job_message(db, redis_client, queue_name, job):
    locked_job = _active_job(db, job.resource_id, job.job_type, for_update=True)
    return _enqueue_job_message(db, redis_client, queue_name, locked_job or job)


def enqueue_ingest_job(db, redis_client, resource_id, *, queue_name):
    resource = _locked_resource(db, resource_id)
    if resource is None:
        raise ValueError("resource_not_found")
    if resource.media_type != "document" or not resource.item_id or resource.item is None:
        raise ValueError("resource_not_ingestable")
    if resource.processing_status == "text_invalid":
        raise ValueError("text_invalid")

    active_job = _active_job(db, resource_id, "ingest", for_update=True)
    if active_job is not None:
        return _enqueue_job_message(db, redis_client, queue_name, active_job)

    job = KnowledgeJob(
        job_type="ingest",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        stage=STAGE_CREATED,
        max_attempts=3,
        available_at=local_now(),
    )
    resource.processing_status = "queued"
    resource.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return _enqueue_active_job_message(db, redis_client, queue_name, job)


def enqueue_governance_job(db, redis_client, resource_id, *, queue_name):
    resource = _locked_resource(db, resource_id)
    if resource is None:
        raise ValueError("resource_not_found")
    if resource.item is None:
        raise ValueError("resource_not_ingestable")

    active_job = _active_job(db, resource_id, "governance", for_update=True)
    if active_job is not None:
        resource.governance_status = "queued"
        resource.governance_error_message = None
        resource.governance_finished_at = None
        if active_job.stage == STAGE_ENQUEUED:
            db.commit()
            db.refresh(active_job)
            return active_job
        return _enqueue_job_message(db, redis_client, queue_name, active_job)

    job = KnowledgeJob(
        job_type="governance",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        stage=STAGE_CREATED,
        max_attempts=3,
        available_at=local_now(),
    )
    resource.governance_status = "queued"
    resource.governance_error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return _enqueue_active_job_message(db, redis_client, queue_name, job)


def enqueue_topic_ingest_jobs(db, redis_client, topic_id, *, queue_name):
    result = BatchEnqueueResult()
    resources = (
        db.query(KnowledgeFile)
        .filter(KnowledgeFile.topic_id == topic_id, KnowledgeFile.media_type == "document")
        .order_by(KnowledgeFile.uploaded_at.asc(), KnowledgeFile.id.asc())
        .all()
    )

    for resource in resources:
        active_job = _active_job(db, resource.id, "ingest")
        needs_enqueue_recovery = active_job is not None and active_job.stage != STAGE_ENQUEUED
        if resource.processing_status not in ELIGIBLE_INGEST_STATUSES and not needs_enqueue_recovery:
            result.skipped += 1
            continue

        try:
            job = enqueue_ingest_job(db, redis_client, resource.id, queue_name=queue_name)
        except ValueError as exc:
            db.rollback()
            result.failed += 1
            result.messages.append(f"{resource.title}: {exc}")
        except Exception as exc:
            db.rollback()
            result.failed += 1
            result.messages.append(f"{resource.title}: {exc}")
        else:
            result.queued += 1
            result.job_ids.append(job.id)

    return result
