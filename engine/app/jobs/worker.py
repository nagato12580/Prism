import logging
import socket
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

from backend.app.models import EvaluationRun, KnowledgeFile, KnowledgeJob, KnowledgeTopic
from backend.app.services.knowledge_cleanup import KnowledgeCleanupService
from backend.app.services.document_text_quality import assess_document_text
from backend.app.services.knowledge_governance import settle_document_item_to_governance
from backend.app.services.knowledge_jobs import KnowledgeJobService
from backend.app.utils.time import local_now
from engine.app.config import settings
from engine.app.ingestion.pipeline import ingest_item

from . import redis_queue
from .knowledge_handlers import handle_delete, handle_index, handle_parse
from .evaluation_handlers import handle_evaluation
from .enrichment_handlers import JOB_TYPES as ENRICHMENT_JOB_TYPES, handle_enrichment


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)
logger = logging.getLogger("uvicorn.error")

ACTIVE_STATUSES = {"queued", "processing"}
NEEDS_REPUBLISH_STAGES = {"created", "retry", "recovered"}
EVALUATION_REAPER_INTERVAL_SECONDS = 30
_EVALUATION_REAPER_LOCK = threading.Lock()


class _MissingExternalIndex:
    def delete_file(self, tenant_id, kb_uid, file_uid):
        return None


class _CompositeCleanupIndex:
    def __init__(self, indexes):
        self.indexes = indexes

    def delete_file(self, tenant_id, kb_uid, file_uid):
        for index in self.indexes:
            index.delete_file(tenant_id, kb_uid, file_uid)


def _build_cleanup_service(db, job):
    from elasticsearch import Elasticsearch
    from pymilvus import Collection, utility

    from backend.app.storage.files import LocalFileStorage
    from backend.app.services.graph_client import GraphClient
    from engine.app.indexing.es_index import (
        ElasticsearchGenerationIndex,
        V2_INDEX_NAME,
    )
    from engine.app.indexing.milvus_index import MilvusGenerationIndex, _connect

    db.query(KnowledgeTopic).filter_by(
        tenant_id=job.tenant_id, kb_uid=job.kb_uid
    ).one()
    _connect(settings.MILVUS_HOST, settings.MILVUS_PORT)
    milvus_indexes = [
        MilvusGenerationIndex(Collection(name))
        for name in utility.list_collections()
        if name.startswith("prism_kb_")
    ]
    milvus = _CompositeCleanupIndex(milvus_indexes) if milvus_indexes else _MissingExternalIndex()
    es_client = Elasticsearch([settings.ES_HOST], request_timeout=15)
    graph = None
    try:
        es = (
            ElasticsearchGenerationIndex(es_client, V2_INDEX_NAME)
            if es_client.indices.exists(index=V2_INDEX_NAME)
            else _MissingExternalIndex()
        )
        storage = LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))
        graph = GraphClient()
        return KnowledgeCleanupService(
            db, milvus, es, storage, graph_client=graph,
            closers=(es_client.close, graph.close),
        )
    except Exception:
        if graph is not None:
            graph.close()
        es_client.close()
        raise


def dispatch_typed_job(db, job_id, worker_id):
    job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).one_or_none()
    if job is None:
        return None
    if job.job_type == "parse":
        return handle_parse(
            job_id,
            worker_id,
            db,
            KnowledgeJobService(db),
            publisher=_publish_typed_job_id,
        )
    if job.job_type == "delete":
        return handle_delete(
            job_id,
            worker_id,
            db,
            KnowledgeJobService(db),
            _build_cleanup_service(db, job),
        )
    if job.job_type == "index":
        return handle_index(job_id, worker_id, db, KnowledgeJobService(db))
    if job.job_type == "evaluation":
        return handle_evaluation(job_id, worker_id, db, KnowledgeJobService(db))
    if job.job_type in ENRICHMENT_JOB_TYPES:
        return handle_enrichment(job_id, worker_id, db, KnowledgeJobService(db), publisher=_publish_typed_job_id)
    return None


def _publish_typed_job_id(job_id):
    client = redis_queue.redis_client()
    redis_queue.push_job(client, settings.KNOWLEDGE_INGEST_QUEUE, job_id)


def run_ingest_queue_job(job_id, *, worker_id):
    db = _Session()
    try:
        job_type = db.query(KnowledgeJob.job_type).filter(KnowledgeJob.id == job_id).scalar()
        if job_type in {"parse", "delete", "index", "evaluation", *ENRICHMENT_JOB_TYPES}:
            return dispatch_typed_job(db, job_id, worker_id)
    finally:
        db.close()
    return run_ingest_job(job_id, worker_id=worker_id)


class HardJobFailure(RuntimeError):
    pass


def _worker_id(prefix):
    host = socket.gethostname()
    return f"{prefix}-{host}-{uuid.uuid4().hex[:8]}"


def _queue_name_for_job(job):
    if job.job_type == "governance":
        return settings.KNOWLEDGE_GOVERNANCE_QUEUE
    return settings.KNOWLEDGE_INGEST_QUEUE


def _publish_job(job):
    client = redis_queue.redis_client()
    redis_queue.push_job(client, _queue_name_for_job(job), job.id)


def _publish_job_and_mark_enqueued(db, job):
    _publish_job(job)
    job.stage = "enqueued"
    db.commit()
    db.refresh(job)
    return job


def claim_job(db, job_id, worker_id):
    now = local_now()
    job = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.id == job_id,
            KnowledgeJob.status == "queued",
            or_(KnowledgeJob.available_at == None, KnowledgeJob.available_at <= now),
        )
        .with_for_update()
        .first()
    )
    if job is None:
        db.rollback()
        return None

    job.status = "processing"
    job.stage = "claimed"
    job.locked_by = worker_id
    job.locked_at = now
    job.started_at = job.started_at or now
    job.attempts = (job.attempts or 0) + 1
    db.commit()
    db.refresh(job)
    return job


def update_job_progress(db, job, *, stage, current=0, total=0):
    job.stage = stage
    job.progress_current = int(current or 0)
    job.progress_total = int(total or 0)
    db.commit()
    db.refresh(job)
    return job


def _record_governance_progress(job_id, resource_id, *, stage, current=0, total=0):
    db = _Session()
    try:
        current = int(current or 0)
        total = int(total or 0)
        job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
        resource = db.query(KnowledgeFile).filter(KnowledgeFile.id == resource_id).first()
        if job is not None:
            job.stage = stage
            job.progress_current = current
            job.progress_total = total
        if resource is not None:
            resource.governance_progress_current = current
            resource.governance_progress_total = total
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception(
            "[knowledge.worker] governance progress update failed job_id=%s resource_id=%s error=%s",
            job_id,
            resource_id,
            exc,
        )
    finally:
        db.close()


def mark_done(db, job):
    now = local_now()
    job.status = "done"
    job.stage = "done"
    job.finished_at = now
    job.locked_by = ""
    job.locked_at = None
    job.error_code = ""
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def _resource_for_job(db, job):
    return db.query(KnowledgeFile).filter(KnowledgeFile.id == job.resource_id).first()


def _record_resource_failure(resource, job, message, final):
    if resource is None:
        return
    if job.job_type == "governance":
        resource.governance_error_message = message
        resource.governance_status = "failed" if final else "queued"
    else:
        resource.error_message = message
        if resource.processing_status != "text_invalid":
            resource.processing_status = "failed" if final else "queued"


def mark_retry_or_failed(db, job, exc, *, retryable):
    message = str(exc) or exc.__class__.__name__
    resource = _resource_for_job(db, job)
    exhausted = not retryable or (job.attempts or 0) >= (job.max_attempts or 1)
    job.error_code = "hard_failure" if not retryable else "retryable_failure"
    job.error_message = message
    job.locked_by = ""
    job.locked_at = None

    if exhausted:
        job.status = "failed"
        job.stage = "failed"
        job.finished_at = local_now()
        _record_resource_failure(resource, job, message, final=True)
    else:
        job.status = "queued"
        job.stage = "retry"
        job.available_at = local_now()
        _record_resource_failure(resource, job, message, final=False)

    db.commit()
    db.refresh(job)
    if not exhausted:
        _publish_job_and_mark_enqueued(db, job)
    return job


def recover_stale_jobs(stale_seconds=None):
    stale_seconds = stale_seconds or settings.KNOWLEDGE_JOB_STALE_SECONDS
    cutoff = local_now() - timedelta(seconds=stale_seconds)
    db = _Session()
    try:
        jobs = (
            db.query(KnowledgeJob)
            .filter(KnowledgeJob.status == "processing", KnowledgeJob.locked_at < cutoff)
            .all()
        )
        now = local_now()
        for job in jobs:
            job.status = "queued"
            job.stage = "recovered"
            job.locked_by = ""
            job.locked_at = None
            job.available_at = now
        db.commit()
        for job in jobs:
            _publish_job_and_mark_enqueued(db, job)
        return len(jobs)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def recover_expired_evaluation_jobs():
    if not _EVALUATION_REAPER_LOCK.acquire(blocking=False):
        return 0
    try:
        return _recover_expired_evaluation_jobs()
    finally:
        _EVALUATION_REAPER_LOCK.release()


def _lock_reaper_topic(db, candidate):
    return (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=candidate.tenant_id, kb_uid=candidate.kb_uid)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )


def _lock_expired_job(db, job_id: str, now):
    return (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.id == job_id,
            KnowledgeJob.job_type.in_({"evaluation", *ENRICHMENT_JOB_TYPES}),
            KnowledgeJob.status.in_({"claimed", "running"}),
            KnowledgeJob.lease_expires_at.is_not(None),
            KnowledgeJob.lease_expires_at <= now,
        )
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )


def _recover_expired_evaluation_jobs():
    """Requeue typed evaluation jobs whose worker lease expired."""
    now = local_now()
    db = _Session()
    recovered_ids = []
    try:
        candidates = (
            db.query(
                KnowledgeJob.id,
                KnowledgeJob.job_type,
                KnowledgeJob.tenant_id,
                KnowledgeJob.kb_uid,
            )
            .filter(
                KnowledgeJob.job_type.in_({"evaluation", *ENRICHMENT_JOB_TYPES}),
                KnowledgeJob.status.in_({"claimed", "running"}),
                KnowledgeJob.lease_expires_at.is_not(None),
                KnowledgeJob.lease_expires_at <= now,
            )
            .order_by(
                KnowledgeJob.tenant_id,
                KnowledgeJob.kb_uid,
                KnowledgeJob.id,
            )
            .all()
        )
        for candidate in candidates:
            topic = None
            if candidate.job_type in ENRICHMENT_JOB_TYPES:
                topic = _lock_reaper_topic(db, candidate)
            job = _lock_expired_job(db, candidate.id, now)
            if job is None:
                db.rollback()
                continue
            if job.cancel_requested_at is not None:
                job.status = "canceled"
                job.finished_at = now
                job.lease_owner = None
                job.lease_expires_at = None
                if job.job_type == "evaluation":
                    run = db.get(EvaluationRun, job.resource_id)
                    if run is not None:
                        run.status = "canceled"
                elif job.job_type in ENRICHMENT_JOB_TYPES:
                    from engine.app.knowledge.enrichment import mark_topic_enrichment_stale
                    if topic is not None:
                        mark_topic_enrichment_stale(
                            topic,
                            reason="generation_canceled",
                            increment_input_revision=False,
                        )
                db.commit()
                continue
            if job.status == "running" and job.attempt >= job.max_attempts:
                job.status = "failed"
                job.error_code = "EVALUATION_LEASE_EXHAUSTED"
                job.error_message = "Evaluation worker lease expired"
                job.retryable = False
                job.finished_at = now
                if job.job_type == "evaluation":
                    run = db.get(EvaluationRun, job.resource_id)
                    if run is not None:
                        run.status = "failed"
                        run.error_message = "evaluation run failed"
                elif job.job_type in ENRICHMENT_JOB_TYPES:
                    if topic is not None:
                        attribute = "mindmap" if job.job_type == "mindmap_generation" else "sample_questions"
                        value = dict(getattr(topic, attribute) or {})
                        value.update({"status": "failed", "error": "generation_failed"})
                        setattr(topic, attribute, value)
                db.commit()
                continue
            job.status = "queued"
            job.stage = "recovered"
            job.lease_owner = None
            job.lease_expires_at = None
            job.heartbeat_at = now
            job.available_at = now
            recovered_ids.append(job.id)
            if job.job_type == "evaluation":
                run = db.get(EvaluationRun, job.resource_id)
                if run is not None:
                    run.status = "queued"
            db.commit()
        for job_id in recovered_ids:
            job = db.get(KnowledgeJob, job_id)
            _publish_job_and_mark_enqueued(db, job)
        return len(recovered_ids)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def republish_due_queued_jobs(stale_seconds=None):
    """Republish due jobs that were never published or whose publication is stale.

    This runs at engine startup and also serves as a recovery sweep: if a worker
    popped a job from Redis but failed to claim it (e.g. transient DB error), the
    job stays queued in MySQL but is lost from Redis.  This function republishes
    jobs in a pre-publication/recovery stage immediately.  Already-enqueued jobs
    are republished only after the stale interval to avoid duplicate delivery on
    every startup sweep.
    """
    stale_seconds = stale_seconds or settings.KNOWLEDGE_JOB_STALE_SECONDS
    now = local_now()
    stale_cutoff = now - timedelta(seconds=stale_seconds)
    db = _Session()
    try:
        jobs = (
            db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.status == "queued",
                or_(KnowledgeJob.available_at == None, KnowledgeJob.available_at <= now),
                or_(
                    KnowledgeJob.stage.in_(NEEDS_REPUBLISH_STAGES),
                    and_(
                        KnowledgeJob.stage == "enqueued",
                        KnowledgeJob.created_at < stale_cutoff,
                    ),
                ),
            )
            .order_by(KnowledgeJob.available_at.asc(), KnowledgeJob.created_at.asc(), KnowledgeJob.id.asc())
            .all()
        )
        count = 0
        for job in jobs:
            _publish_job_and_mark_enqueued(db, job)
            count += 1
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _recover_unclaimed_job(db, job_id):
    """If a job was popped from Redis but claim_job returned None, check whether
    the job is still queued and republish it so another worker can retry."""
    try:
        job = db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id).first()
        if job is not None and job.status == "queued":
            _publish_job_and_mark_enqueued(db, job)
    except Exception:
        db.rollback()


def _validate_ingest_resource(db, job):
    resource = _resource_for_job(db, job)
    if resource is None:
        raise HardJobFailure("resource_not_found")
    if not resource.item_id:
        raise HardJobFailure("resource_not_ingestable")

    quality = assess_document_text(
        resource.content_text,
        page_count=resource.page_count,
        max_chars=settings.KNOWLEDGE_TEXT_MAX_CHARS,
        max_chars_per_page=settings.KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE,
    )
    if not quality.ok:
        resource.processing_status = "text_invalid"
        resource.error_message = quality.message
        db.commit()
        raise HardJobFailure(quality.message)
    return resource


def enqueue_governance_job_from_worker(db, resource):
    job = (
        db.query(KnowledgeJob)
        .filter(
            KnowledgeJob.resource_id == resource.id,
            KnowledgeJob.job_type == "governance",
            KnowledgeJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(KnowledgeJob.created_at.desc(), KnowledgeJob.id.desc())
        .with_for_update()
        .first()
    )
    if job is None:
        job = KnowledgeJob(
            tenant_id=resource.tenant_id,
            kb_uid=resource.kb_uid,
            file_uid=resource.file_uid,
            idempotency_key=(
                f"{resource.tenant_id}:{resource.kb_uid}:"
                f"{resource.file_uid}:governance:{resource.item_id}"
            ),
            job_type="governance",
            resource_id=resource.id,
            item_id=resource.item_id,
            topic_id=resource.topic_id,
            status="queued",
            stage="created",
            max_attempts=3,
            available_at=local_now(),
        )
        db.add(job)
        db.flush()

    resource.governance_status = "queued"
    resource.governance_error_message = None
    db.commit()
    db.refresh(job)

    if job.stage != "enqueued":
        client = redis_queue.redis_client()
        redis_queue.push_job(client, settings.KNOWLEDGE_GOVERNANCE_QUEUE, job.id)
        job.stage = "enqueued"
        db.commit()
        db.refresh(job)
    return job


def run_ingest_job(job_id, *, worker_id):
    db = _Session()
    try:
        job = claim_job(db, job_id, worker_id)
        if job is None:
            _recover_unclaimed_job(db, job_id)
            return None

        try:
            resource = _validate_ingest_resource(db, job)
            resource.processing_status = "processing"
            resource.error_message = None
            db.commit()

            def progress(**kwargs):
                update_job_progress(db, job, **kwargs)

            result = ingest_item(job.item_id, progress=progress)
            db.refresh(resource)
            resource.processing_status = "done"
            resource.error_message = None
            resource.governance_status = "queued"
            resource.governance_error_message = None
            mark_done(db, job)
            try:
                enqueue_governance_job_from_worker(db, resource)
            except Exception as exc:
                logger.exception(
                    "[knowledge.worker] governance enqueue failed after ingest job_id=%s error=%s",
                    job_id,
                    exc,
                )
                db.rollback()
                resource = _resource_for_job(db, job)
                if resource is not None:
                    resource.processing_status = "done"
                    resource.governance_status = "failed"
                    resource.governance_error_message = str(exc) or exc.__class__.__name__
                    db.commit()
            return result
        except HardJobFailure as exc:
            db.rollback()
            mark_retry_or_failed(db, job, exc, retryable=False)
            return None
        except Exception as exc:
            logger.exception("[knowledge.worker] ingest failed job_id=%s error=%s", job_id, exc)
            db.rollback()
            mark_retry_or_failed(db, job, exc, retryable=True)
            return None
    finally:
        db.close()


def run_governance_job(job_id, *, worker_id):
    db = _Session()
    try:
        job = claim_job(db, job_id, worker_id)
        if job is None:
            _recover_unclaimed_job(db, job_id)
            return None

        try:
            resource = _resource_for_job(db, job)
            if resource is None or not resource.item_id or not job.item_id:
                raise HardJobFailure("resource_not_governable")

            now = local_now()
            resource.governance_status = "processing"
            resource.governance_started_at = now
            resource.governance_finished_at = None
            resource.governance_error_message = None
            db.commit()

            def progress(**kwargs):
                current = int(kwargs.get("current") or 0)
                total = int(kwargs.get("total") or 0)
                stage = kwargs.get("stage") or "governance"
                try:
                    _record_governance_progress(
                        job.id,
                        resource.id,
                        stage=stage,
                        current=current,
                        total=total,
                    )
                except Exception as exc:
                    logger.exception(
                        "[knowledge.worker] governance progress callback failed job_id=%s resource_id=%s error=%s",
                        job.id,
                        resource.id,
                        exc,
                    )

            result = settle_document_item_to_governance(db, job.item_id, progress=progress)
            db.refresh(resource)
            resource.processing_status = "done"
            resource.governance_status = "done"
            resource.governance_finished_at = local_now()
            resource.governance_error_message = None
            mark_done(db, job)
            return result
        except HardJobFailure as exc:
            db.rollback()
            mark_retry_or_failed(db, job, exc, retryable=False)
            return None
        except Exception as exc:
            logger.exception("[knowledge.worker] governance failed job_id=%s error=%s", job_id, exc)
            db.rollback()
            mark_retry_or_failed(db, job, exc, retryable=True)
            return None
    finally:
        db.close()


from engine.app.graph.outbox_projector import GraphProjectionReceiptStore, OutboxProjectorLoop


def _build_graph_projector(db):
    """Construct a Neo4jOutboxProjector wired to a real GraphClient.

    Returns None when the projector is disabled or Neo4j is unreachable so the
    worker thread can no-op without crashing ingestion.
    """
    if not settings.GRAPH_PROJECTOR_ENABLED:
        return None
    try:
        from backend.app.services.graph_client import GraphClient
        from engine.app.graph.neo4j_projector import Neo4jOutboxProjector

        graph = GraphClient()
        return Neo4jOutboxProjector(graph, GraphProjectionReceiptStore(db))
    except Exception as exc:
        logger.warning("[knowledge.worker] graph_projector_init_failed error=%s", exc)
        return None


def _drain_graph_projector_batch(db, *, projector, worker_id: str) -> int:
    """Claim + apply one batch of due neo4j receipts. Never raises.

    The projector owns its GraphClient; on transient Neo4j failure each receipt
    is rescheduled via the receipt store (retry/failed), so a single batch error
    does not propagate.
    """
    if projector is None:
        return 0
    loop = OutboxProjectorLoop(projector, projector.receipts, worker_id=worker_id)
    try:
        return loop.run_batch(limit=settings.GRAPH_PROJECTOR_BATCH_LIMIT)
    except Exception as exc:
        logger.exception("[knowledge.worker] graph_projector_batch_failed error=%s", exc)
        return 0


class KnowledgeWorkerManager:
    def __init__(self):
        self._stop = threading.Event()
        self._threads = []
        self._client = None

    def start(self):
        if self._threads:
            return
        recover_stale_jobs()
        recover_expired_evaluation_jobs()
        republish_due_queued_jobs()
        self._client = redis_queue.redis_client()
        reaper = threading.Thread(
            target=self._evaluation_reaper_loop,
            args=(),
            daemon=True,
            name="knowledge-evaluation-lease-reaper",
        )
        self._threads.append(reaper)
        reaper.start()
        for index in range(max(1, settings.KNOWLEDGE_INGEST_WORKERS)):
            worker_id = _worker_id(f"ingest-{index}")
            thread = threading.Thread(
                target=self._loop,
                args=(settings.KNOWLEDGE_INGEST_QUEUE, run_ingest_queue_job, worker_id),
                daemon=True,
                name=f"knowledge-ingest-worker-{index}",
            )
            self._threads.append(thread)
            thread.start()
        for index in range(max(1, settings.KNOWLEDGE_GOVERNANCE_WORKERS)):
            worker_id = _worker_id(f"governance-{index}")
            thread = threading.Thread(
                target=self._loop,
                args=(settings.KNOWLEDGE_GOVERNANCE_QUEUE, run_governance_job, worker_id),
                daemon=True,
                name=f"knowledge-governance-worker-{index}",
            )
            self._threads.append(thread)
            thread.start()

        # Graph outbox projector: drains due neo4j receipts independently of
        # the Redis job queues. Neo4j outage -> receipts retry, never breaks
        # ingestion (failure isolation).
        if settings.GRAPH_PROJECTOR_ENABLED:
            projector_thread = threading.Thread(
                target=self._graph_projector_loop,
                args=(),
                daemon=True,
                name="knowledge-graph-projector",
            )
            self._threads.append(projector_thread)
            projector_thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads = []
        self._client = None

    def _loop(self, queue_name, runner, worker_id):
        while not self._stop.is_set():
            try:
                job_id = redis_queue.pop_job(self._client, queue_name, timeout_seconds=2)
                if not job_id:
                    continue
                runner(job_id, worker_id=worker_id)
            except Exception as exc:
                logger.exception(
                    "[knowledge.worker] loop error queue=%s worker_id=%s error=%s",
                    queue_name,
                    worker_id,
                    exc,
                )
                time.sleep(1)

    def _evaluation_reaper_loop(self):
        while not self._stop.wait(EVALUATION_REAPER_INTERVAL_SECONDS):
            try:
                recover_expired_evaluation_jobs()
                republish_due_queued_jobs()
            except Exception as exc:
                logger.exception("[knowledge.worker] evaluation lease sweep failed error=%s", exc)

    def _graph_projector_loop(self):
        """Periodically drain due graph outbox receipts to Neo4j.

        Builds a fresh GraphClient per batch attempt so a Neo4j restart is
        recovered on the next iteration; a persistent init failure just logs
        and retries next tick.
        """
        interval = settings.GRAPH_PROJECTOR_INTERVAL_SECONDS
        worker_id = _worker_id("graph-projector")
        while not self._stop.wait(interval):
            db = _Session()
            try:
                projector = _build_graph_projector(db)
                try:
                    _drain_graph_projector_batch(db, projector=projector, worker_id=worker_id)
                finally:
                    if projector is not None:
                        try:
                            projector.graph.close()
                        except Exception:
                            pass
            except Exception as exc:
                logger.exception("[knowledge.worker] graph_projector_loop error=%s", exc)
            finally:
                db.close()
