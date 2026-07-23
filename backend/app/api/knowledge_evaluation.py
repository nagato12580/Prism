import json
from copy import deepcopy
from hashlib import sha256
from math import isfinite
import redis

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import EvaluationDataset, EvaluationDatasetItem, EvaluationRun, EvaluationRunItem, KnowledgeJob, KnowledgeTopic
from backend.app.schemas.knowledge_evaluation import (
    MAX_EVALUATION_ITEMS,
    MAX_JSONL_LINE_LENGTH,
    EvaluationDatasetGenerate,
    EvaluationDatasetImport,
    EvaluationItemInput,
    EvaluationRunCreate,
)
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy, KnowledgeNotFound
from backend.app.services.knowledge_job_queue import new_evaluation_job, publish_evaluation_job
from backend.app.config import settings
from backend.app.utils.time import local_now


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-evaluation"])
ACTIVE_RUN_STATUSES = {"queued", "claimed", "running", "cancel_requested"}
ACTIVE_JOB_STATUSES = {"queued", "claimed", "running"}
SNAPSHOT_ALLOWLISTS = {
    "retrieval": frozenset({"mode", "top_k", "graph_hops", "rrf_k", "rerank_top_k", "dense_weight", "bm25_weight", "graph_weight"}),
    "embedding": frozenset({"model", "dimension", "dimensions", "normalize", "version"}),
    "graph": frozenset({"mode", "graph_hops", "max_hops", "enabled", "version"}),
}


def _redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _topic_or_problem(db: Session, actor: ActorContext, kb_uid: str):
    try:
        return KnowledgeAccessPolicy(db).require_manage(actor, kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", f"Knowledge base {kb_uid} not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", f"Access denied to {kb_uid}")


def _dataset_or_problem(db: Session, actor: ActorContext, kb_uid: str, dataset_uid: str) -> EvaluationDataset:
    dataset = db.query(EvaluationDataset).filter_by(dataset_uid=dataset_uid, tenant_id=actor.tenant_id, kb_uid=kb_uid).one_or_none()
    if dataset is None:
        raise ApiProblem(404, "EVALUATION_DATASET_NOT_FOUND", "Evaluation dataset not found")
    return dataset


def _run_or_problem(db: Session, actor: ActorContext, kb_uid: str, run_uid: str) -> EvaluationRun:
    run = db.query(EvaluationRun).filter_by(run_uid=run_uid, tenant_id=actor.tenant_id, kb_uid=kb_uid).one_or_none()
    if run is None:
        raise ApiProblem(404, "EVALUATION_RUN_NOT_FOUND", "Evaluation run not found")
    return run


def _create_dataset(db: Session, actor: ActorContext, kb_uid: str, name: str, source: str, items: list[EvaluationItemInput]) -> EvaluationDataset:
    dataset = EvaluationDataset(tenant_id=actor.tenant_id, kb_uid=kb_uid, name=name, created_by=actor.actor_id, source=source)
    db.add(dataset)
    db.flush()
    for ordinal, item in enumerate(items):
        db.add(EvaluationDatasetItem(dataset_id=dataset.id, tenant_id=actor.tenant_id, kb_uid=kb_uid, ordinal=ordinal,
                                     query=item.query, gold_chunk_uids=item.gold_chunk_uids, gold_answer=item.gold_answer))
    db.commit()
    db.refresh(dataset)
    return dataset


def _safe_snapshot(value: dict | None, kind: str) -> dict:
    source = value if isinstance(value, dict) else {}
    snapshot = {}
    for key in SNAPSHOT_ALLOWLISTS[kind]:
        if key not in source:
            continue
        item = source[key]
        if item is None or isinstance(item, (str, bool, int)) or isinstance(item, float) and isfinite(item):
            snapshot[key] = deepcopy(item)
    return snapshot


def _stream_dataset_export(session_factory, dataset_id: str, tenant_id: str, kb_uid: str):
    last_ordinal = -1
    while True:
        stream_db = session_factory()
        try:
            rows = (
                stream_db.query(EvaluationDatasetItem)
                .filter(
                    EvaluationDatasetItem.dataset_id == dataset_id,
                    EvaluationDatasetItem.tenant_id == tenant_id,
                    EvaluationDatasetItem.kb_uid == kb_uid,
                    EvaluationDatasetItem.ordinal > last_ordinal,
                )
                .order_by(EvaluationDatasetItem.ordinal)
                .limit(100)
                .all()
            )
            payloads = [
                json.dumps({"query": item.query, "gold_chunk_uids": item.gold_chunk_uids, "gold_answer": item.gold_answer}, ensure_ascii=False) + "\n"
                for item in rows
            ]
            if rows:
                last_ordinal = rows[-1].ordinal
        finally:
            stream_db.close()
        if not payloads:
            break
        yield from payloads


@router.post("/{kb_uid}/evaluation-datasets/import", status_code=201)
def import_evaluation_dataset(kb_uid: str, body: EvaluationDatasetImport, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    items: list[EvaluationItemInput] = []
    for line_number, line in enumerate(body.jsonl.splitlines(), 1):
        if not line.strip():
            continue
        if len(line) > MAX_JSONL_LINE_LENGTH:
            raise ApiProblem(422, "INVALID_EVALUATION_JSONL", f"JSONL item at line {line_number} is too long")
        if len(items) >= MAX_EVALUATION_ITEMS:
            raise ApiProblem(422, "INVALID_EVALUATION_JSONL", f"JSONL exceeds {MAX_EVALUATION_ITEMS} items")
        try:
            items.append(EvaluationItemInput.model_validate(json.loads(line)))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ApiProblem(422, "INVALID_EVALUATION_JSONL", f"Invalid JSONL item at line {line_number}") from exc
    if not items:
        raise ApiProblem(422, "INVALID_EVALUATION_JSONL", "JSONL must contain at least one item")
    dataset = _create_dataset(db, actor, kb_uid, body.name, "jsonl", items)
    return {"id": dataset.id, "dataset_uid": dataset.dataset_uid, "name": dataset.name, "item_count": len(items)}


@router.post("/{kb_uid}/evaluation-datasets/generated", status_code=201)
def create_generated_evaluation_dataset(kb_uid: str, body: EvaluationDatasetGenerate, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    dataset = _create_dataset(db, actor, kb_uid, body.name, "generated", body.items)
    return {"id": dataset.id, "dataset_uid": dataset.dataset_uid, "name": dataset.name, "item_count": len(body.items)}


@router.get("/{kb_uid}/evaluation-datasets")
def list_evaluation_datasets(kb_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    counts = (
        db.query(EvaluationDatasetItem.dataset_id, func.count(EvaluationDatasetItem.id).label("item_count"))
        .group_by(EvaluationDatasetItem.dataset_id)
        .subquery()
    )
    rows = (
        db.query(EvaluationDataset, func.coalesce(counts.c.item_count, 0))
        .outerjoin(counts, counts.c.dataset_id == EvaluationDataset.id)
        .filter(EvaluationDataset.tenant_id == actor.tenant_id, EvaluationDataset.kb_uid == kb_uid)
        .order_by(EvaluationDataset.created_at.desc())
        .all()
    )
    return [{"id": row.id, "dataset_uid": row.dataset_uid, "name": row.name, "source": row.source, "item_count": count} for row, count in rows]


@router.get("/{kb_uid}/evaluation-datasets/{dataset_uid}/export", response_class=StreamingResponse)
def export_evaluation_dataset(kb_uid: str, dataset_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    dataset = _dataset_or_problem(db, actor, kb_uid, dataset_uid)
    frozen_dataset_id = dataset.id
    frozen_tenant_id = actor.tenant_id
    stream_sessions = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    def stream():
        yield from _stream_dataset_export(stream_sessions, frozen_dataset_id, frozen_tenant_id, kb_uid)
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/{kb_uid}/evaluation-runs", status_code=201)
def create_evaluation_run(
    kb_uid: str,
    body: EvaluationRunCreate,
    response: Response,
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    _topic_or_problem(db, actor, kb_uid)
    topic = (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=actor.tenant_id, kb_uid=kb_uid)
        .with_for_update()
        .one()
    )
    if topic.deleted_at is not None or topic.status == "deleting":
        raise ApiProblem(409, "KNOWLEDGE_BASE_DELETING", "Knowledge base is being deleted")
    if not topic.active_index_generation:
        raise ApiProblem(409, "EVALUATION_INDEX_UNAVAILABLE", "Knowledge base has no active index")
    key = idempotency_header or body.idempotency_key
    if not key:
        raise ApiProblem(422, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required")
    if idempotency_header and body.idempotency_key and idempotency_header != body.idempotency_key:
        raise ApiProblem(422, "IDEMPOTENCY_KEY_MISMATCH", "Idempotency keys do not match")
    fingerprint_payload = {
        "tenant_id": actor.tenant_id, "kb_uid": kb_uid, "dataset_uid": body.dataset_uid,
        "model": body.model, "config": body.config.model_dump(exclude_none=True),
    }
    fingerprint = sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.query(EvaluationRun).filter_by(
        tenant_id=actor.tenant_id, kb_uid=kb_uid, request_idempotency_key=key,
    ).one_or_none()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request")
        job = db.query(KnowledgeJob).filter_by(job_type="evaluation", resource_id=existing.id).one()
        try:
            publish_evaluation_job(db, _redis_client(), job, queue_name=settings.KNOWLEDGE_INGEST_QUEUE)
            response.status_code = 200
        except Exception:
            db.rollback()
            response.status_code = 202
        return _run_payload(existing)
    dataset = _dataset_or_problem(db, actor, kb_uid, body.dataset_uid)
    item_count = db.query(func.count(EvaluationDatasetItem.id)).filter_by(
        dataset_id=dataset.id, tenant_id=actor.tenant_id, kb_uid=kb_uid,
    ).scalar()
    run = EvaluationRun(dataset_id=dataset.id, tenant_id=actor.tenant_id, kb_uid=kb_uid, created_by=actor.actor_id, model=body.model,
                        request_idempotency_key=key, request_fingerprint=fingerprint,
                        config=body.config.model_dump(exclude_none=True), retrieval_config=_safe_snapshot(topic.retrieval_config, "retrieval"),
                        embedding_profile=_safe_snapshot(topic.embedding_profile, "embedding"), graph_config=_safe_snapshot(topic.graph_config, "graph"),
                        index_generation=topic.active_index_generation, graph_generation=topic.active_graph_generation,
                        progress_total=item_count)
    db.add(run)
    db.flush()
    items = db.query(EvaluationDatasetItem).filter_by(
        dataset_id=dataset.id, tenant_id=actor.tenant_id, kb_uid=kb_uid,
    ).order_by(EvaluationDatasetItem.ordinal).yield_per(100)
    for item in items:
        db.add(EvaluationRunItem(run_id=run.id, dataset_item_id=item.id, tenant_id=actor.tenant_id, kb_uid=kb_uid, ordinal=item.ordinal,
                                 query=item.query, gold_chunk_uids=list(item.gold_chunk_uids or []), gold_answer=item.gold_answer))
    job = new_evaluation_job(run)
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(EvaluationRun).filter_by(
            tenant_id=actor.tenant_id, kb_uid=kb_uid, request_idempotency_key=key,
        ).one()
        if existing.request_fingerprint != fingerprint:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request")
        run = existing
        job = db.query(KnowledgeJob).filter_by(job_type="evaluation", resource_id=run.id).one()
        response.status_code = 200
    try:
        publish_evaluation_job(db, _redis_client(), job, queue_name=settings.KNOWLEDGE_INGEST_QUEUE)
    except Exception:
        db.rollback()
        response.status_code = 202
    db.refresh(run)
    return _run_payload(run)


def _run_payload(run: EvaluationRun) -> dict:
    payload = {"id": run.id, "run_uid": run.run_uid, "dataset_id": run.dataset_id, "model": run.model, "config": run.config,
               "retrieval_config": run.retrieval_config, "embedding_profile": run.embedding_profile, "graph_config": run.graph_config,
               "index_generation": run.index_generation, "graph_generation": run.graph_generation, "status": run.status,
               "progress_current": run.progress_current, "progress_total": run.progress_total, "metrics": run.metrics}
    return payload


@router.get("/{kb_uid}/evaluation-runs")
def list_evaluation_runs(kb_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    return [_run_payload(row) for row in db.query(EvaluationRun).filter_by(tenant_id=actor.tenant_id, kb_uid=kb_uid).order_by(EvaluationRun.created_at.desc()).all()]


@router.get("/{kb_uid}/evaluation-runs/{run_uid}")
def get_evaluation_run(
    kb_uid: str,
    run_uid: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
    cursor: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    _topic_or_problem(db, actor, kb_uid)
    run = _run_or_problem(db, actor, kb_uid, run_uid)
    query = db.query(EvaluationRunItem).filter_by(run_id=run.id, tenant_id=actor.tenant_id, kb_uid=kb_uid)
    total = query.count()
    if cursor is not None:
        query = query.filter(EvaluationRunItem.ordinal > cursor)
    rows = query.order_by(EvaluationRunItem.ordinal).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    payload = _run_payload(run)
    payload["items"] = [{"id": item.id, "ordinal": item.ordinal, "query": item.query, "status": item.status,
                         "evidence": item.evidence, "metrics": item.metrics, "error_message": item.error_message} for item in rows]
    payload["items_total"] = total
    payload["next_cursor"] = str(rows[-1].ordinal) if has_more and rows else None
    return payload


@router.post("/{kb_uid}/evaluation-runs/{run_uid}/cancel")
def cancel_evaluation_run(kb_uid: str, run_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    run = _run_or_problem(db, actor, kb_uid, run_uid)
    run.cancel_requested_at = local_now()
    if run.status in ACTIVE_RUN_STATUSES:
        run.status = "cancel_requested"
    db.query(KnowledgeJob).filter_by(job_type="evaluation", resource_id=run.id).update({KnowledgeJob.cancel_requested_at: run.cancel_requested_at}, synchronize_session=False)
    db.commit()
    return _run_payload(run)


@router.delete("/{kb_uid}/evaluation-runs/{run_uid}", status_code=204)
def delete_evaluation_run(kb_uid: str, run_uid: str, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    _topic_or_problem(db, actor, kb_uid)
    run = (
        db.query(EvaluationRun)
        .filter_by(run_uid=run_uid, tenant_id=actor.tenant_id, kb_uid=kb_uid)
        .with_for_update()
        .one_or_none()
    )
    if run is None:
        raise ApiProblem(404, "EVALUATION_RUN_NOT_FOUND", "Evaluation run not found")
    jobs = (
        db.query(KnowledgeJob)
        .filter_by(job_type="evaluation", resource_id=run.id)
        .with_for_update()
        .all()
    )
    if run.status in ACTIVE_RUN_STATUSES or any(
        job.status in ACTIVE_JOB_STATUSES or job.cancel_requested_at is not None and job.status not in {"canceled", "failed", "succeeded"}
        for job in jobs
    ):
        db.rollback()
        raise ApiProblem(409, "EVALUATION_RUN_ACTIVE", "Active evaluation runs cannot be deleted")
    for job in jobs:
        db.delete(job)
    db.delete(run)
    db.commit()
    return Response(status_code=204)
