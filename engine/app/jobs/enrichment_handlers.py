"""Lease-aware handlers for mindmap and sample-question generation."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from backend.app.models import KnowledgeJob, KnowledgeTopic
from backend.app.services.knowledge_jobs import InvalidJobTransition, KnowledgeJobService
from engine.app.knowledge.enrichment import (
    call_llm,
    generate_mindmap,
    generate_sample_questions,
    store_mindmap,
    store_sample_questions,
)


JOB_TYPES = {"mindmap_generation", "sample_questions_generation"}


def _input_revision(value) -> int:
    if not isinstance(value, dict):
        return 0
    try:
        return max(0, int(value.get("input_revision") or 0))
    except (TypeError, ValueError):
        return 0


def _mark_topic_status(db, topic: KnowledgeTopic | None, job_type: str, status: str, *, reason: str | None = None):
    if topic is None:
        return
    attribute = "mindmap" if job_type == "mindmap_generation" else "sample_questions"
    value = deepcopy(getattr(topic, attribute)) if isinstance(getattr(topic, attribute), dict) else {}
    value["status"] = status
    if reason:
        value["stale_reason" if status == "stale" else "error"] = reason[:128]
    value.setdefault("nodes" if attribute == "mindmap" else "questions", [])
    value.setdefault("input_revision", 0)
    value.setdefault(
        "version",
        int(topic.mindmap_version or 0)
        if attribute == "mindmap"
        else int(topic.sample_questions_version or 0),
    )
    setattr(topic, attribute, value)
    db.flush()


def _locked_topic(db, tenant_id: str, kb_uid: str) -> KnowledgeTopic | None:
    return (
        db.query(KnowledgeTopic)
        .filter_by(tenant_id=tenant_id, kb_uid=kb_uid, deleted_at=None)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )


def _locked_job_after_topic(
    db,
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


def handle_enrichment(job_id: str, worker_id: str, db, jobs: KnowledgeJobService, publisher=None) -> dict:
    lease = timedelta(seconds=120)
    job = jobs.claim(job_id, worker_id, lease)
    if job is None:
        return {"status": "skipped"}
    tenant_id = job.tenant_id
    kb_uid = job.kb_uid
    topic = None
    try:
        jobs.start(job_id, worker_id)
        job = db.get(KnowledgeJob, job_id)
        if job.cancel_requested_at is not None:
            db.expire_all()
            topic = _locked_topic(db, tenant_id, kb_uid)
            job = _locked_job_after_topic(db, job_id, tenant_id, kb_uid)
            if job is None:
                db.rollback()
                return {"status": "skipped"}
            _mark_topic_status(db, topic, job.job_type, "stale", reason="generation_canceled")
            jobs.cancel(job_id, worker_id, commit=False)
            db.commit()
            return {"status": "canceled"}
        topic = db.query(KnowledgeTopic).filter_by(
            tenant_id=job.tenant_id, kb_uid=job.kb_uid, deleted_at=None,
        ).one_or_none()
        if topic is None:
            jobs.fail(job_id, worker_id, "KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found", False)
            return {"status": "failed"}
        payload = dict(job.payload or {})
        snapshot_attribute = "mindmap" if job.job_type == "mindmap_generation" else "sample_questions"
        version_attribute = "mindmap_version" if job.job_type == "mindmap_generation" else "sample_questions_version"
        expected_version = int(payload.get("expected_version", getattr(topic, version_attribute) or 0))
        expected_input_revision = int(
            payload.get("expected_input_revision", _input_revision(getattr(topic, snapshot_attribute)))
        )
        model = str(payload.get("model") or "default")[:255]
        prompt_version = str(payload.get("prompt_version") or "v1")[:128]
        jobs.heartbeat(job_id, worker_id, lease)
        if job.job_type == "mindmap_generation":
            output = generate_mindmap(db, topic, model=model, prompt_version=prompt_version, llm=call_llm)
        elif job.job_type == "sample_questions_generation":
            output = generate_sample_questions(db, topic, model=model, prompt_version=prompt_version, llm=call_llm)
        else:
            jobs.fail(job_id, worker_id, "UNSUPPORTED_JOB_TYPE", "Unsupported enrichment job", False)
            return {"status": "failed"}

        jobs.heartbeat(job_id, worker_id, lease)
        db.expire_all()
        topic = _locked_topic(db, tenant_id, kb_uid)
        job = _locked_job_after_topic(db, job_id, tenant_id, kb_uid)
        if job is None:
            db.rollback()
            return {"status": "skipped"}
        if job.cancel_requested_at is not None:
            _mark_topic_status(db, topic, job.job_type, "stale", reason="generation_canceled")
            jobs.cancel(job_id, worker_id, commit=False)
            db.commit()
            return {"status": "canceled"}
        if topic is None:
            jobs.fail(job_id, worker_id, "KNOWLEDGE_BASE_NOT_FOUND", "Knowledge base not found", False)
            return {"status": "failed"}
        snapshot_matches = topic.active_index_generation == payload.get("index_generation") and topic.active_graph_generation == payload.get("graph_generation")
        version_matches = int(getattr(topic, version_attribute) or 0) == expected_version
        input_revision_matches = _input_revision(getattr(topic, snapshot_attribute)) == expected_input_revision
        if not snapshot_matches or not version_matches or not input_revision_matches:
            _mark_topic_status(
                db, topic, job.job_type, "stale",
                reason=(
                    "generation_changed"
                    if not snapshot_matches
                    else "generation_conflict"
                    if not version_matches
                    else "generation_input_changed"
                ),
            )
            jobs.succeed(
                job_id,
                worker_id,
                {"enrichment_status": "stale", "discarded": True},
                commit=False,
            )
            db.commit()
            return {"status": "completed", "enrichment_status": "stale", "discarded": True}
        status = "ready"
        if job.job_type == "mindmap_generation":
            stored = store_mindmap(
                db, topic, nodes=output,
                index_generation=payload.get("index_generation"),
                graph_generation=payload.get("graph_generation"),
                model=model, prompt_version=prompt_version, status=status,
            )
        else:
            stored = store_sample_questions(
                db, topic, questions=output,
                index_generation=payload.get("index_generation"),
                graph_generation=payload.get("graph_generation"),
                model=model, prompt_version=prompt_version, status=status,
            )
        jobs.succeed(
            job_id,
            worker_id,
            {"version": stored["version"], "enrichment_status": status},
            commit=False,
        )
        db.commit()
        return {"status": "completed", "version": stored["version"], "enrichment_status": status}
    except InvalidJobTransition:
        db.rollback()
        return {"status": "skipped"}
    except Exception as exc:
        db.rollback()
        try:
            db.expire_all()
            topic = _locked_topic(db, tenant_id, kb_uid)
            job = _locked_job_after_topic(db, job_id, tenant_id, kb_uid)
            if job is None:
                db.rollback()
                return {"status": "skipped"}
            if job.cancel_requested_at is not None:
                _mark_topic_status(db, topic, job.job_type, "stale", reason="generation_canceled")
                jobs.cancel(job_id, worker_id, commit=False)
                db.commit()
                return {"status": "canceled"}
            failed_job = jobs.fail(
                job_id,
                worker_id,
                "ENRICHMENT_GENERATION_FAILED",
                "Enrichment generation failed",
                True,
                commit=False,
            )
            if failed_job.status == "queued":
                _mark_topic_status(db, topic, job.job_type, "generating")
                value = deepcopy(getattr(topic, "mindmap" if job.job_type == "mindmap_generation" else "sample_questions") or {})
                value["retry_reason"] = "temporary_generation_failure"
                setattr(topic, "mindmap" if job.job_type == "mindmap_generation" else "sample_questions", value)
                failed_job.stage = "retry"
                db.commit()
                if publisher:
                    try:
                        publisher(failed_job.id)
                        jobs.stage_enqueued(failed_job.id)
                    except Exception:
                        db.rollback()
                return {"status": "retrying"}
            _mark_topic_status(db, topic, job.job_type, "failed", reason="generation_failed")
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed", "error": exc.__class__.__name__}
