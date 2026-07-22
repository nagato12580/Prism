# backend/app/services/knowledge_jobs.py
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeJob
from backend.app.models.knowledge_types import JobStatus
from backend.app.utils.time import local_now


class InvalidJobTransition(ValueError):
    pass


@dataclass(frozen=True)
class JobCommand:
    job_type: str
    tenant_id: str
    kb_uid: str
    file_uid: str | None
    payload: dict[str, Any]


class KnowledgeJobService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, command: JobCommand, idempotency_key: str) -> KnowledgeJob:
        existing = (
            self.db.query(KnowledgeJob)
            .filter_by(idempotency_key=idempotency_key)
            .one_or_none()
        )
        if existing:
            return existing
        job = KnowledgeJob(
            job_type=command.job_type,
            tenant_id=command.tenant_id,
            kb_uid=command.kb_uid,
            file_uid=command.file_uid,
            payload=command.payload,
            idempotency_key=idempotency_key,
            status=JobStatus.QUEUED.value,
        )
        self.db.add(job)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return (
                self.db.query(KnowledgeJob)
                .filter_by(idempotency_key=idempotency_key)
                .one()
            )
        return job

    def claim(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob | None:
        now = local_now()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status == JobStatus.QUEUED.value,
                or_(
                    KnowledgeJob.available_at.is_(None),
                    KnowledgeJob.available_at <= now,
                ),
            )
            .update(
                {
                    KnowledgeJob.status: JobStatus.CLAIMED.value,
                    KnowledgeJob.lease_owner: worker_id,
                    KnowledgeJob.heartbeat_at: now,
                    KnowledgeJob.lease_expires_at: now + lease,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id) if rowcount == 1 else None

    def reclaim_expired(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob | None:
        now = local_now()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status == JobStatus.CLAIMED.value,
                KnowledgeJob.lease_expires_at.is_not(None),
                KnowledgeJob.lease_expires_at <= now,
            )
            .update(
                {
                    KnowledgeJob.lease_owner: worker_id,
                    KnowledgeJob.heartbeat_at: now,
                    KnowledgeJob.lease_expires_at: now + lease,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id) if rowcount == 1 else None

    def _checked_update(self, job_id: str, worker_id: str, filters: list, values: dict) -> KnowledgeJob:
        q = self.db.query(KnowledgeJob).filter(KnowledgeJob.id == job_id)
        for f in filters:
            q = q.filter(f)
        rowcount = q.update(values, synchronize_session="fetch")
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(
                f"Cannot update job {job_id} as {worker_id}"
            )
        return self.db.get(KnowledgeJob, job_id)

    def start(self, job_id: str, worker_id: str) -> KnowledgeJob:
        now = local_now()
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.status == JobStatus.CLAIMED.value,
                KnowledgeJob.lease_owner == worker_id,
            ],
            {
                KnowledgeJob.status: JobStatus.RUNNING.value,
                KnowledgeJob.heartbeat_at: now,
                KnowledgeJob.attempt: KnowledgeJob.attempt + 1,
                KnowledgeJob.attempts: KnowledgeJob.attempts + 1,
                KnowledgeJob.started_at: now,
            },
        )

    def heartbeat(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob:
        now = local_now()
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            ],
            {
                KnowledgeJob.heartbeat_at: now,
                KnowledgeJob.lease_expires_at: now + lease,
            },
        )

    def progress(self, job_id: str, worker_id: str, current: int, total: int, stage: str) -> KnowledgeJob:
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            ],
            {
                KnowledgeJob.progress_current: current,
                KnowledgeJob.progress_total: total,
                KnowledgeJob.stage: stage,
            },
        )

    def succeed(self, job_id: str, worker_id: str, result: dict[str, Any]) -> KnowledgeJob:
        now = local_now()
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.status == JobStatus.RUNNING.value,
                KnowledgeJob.lease_owner == worker_id,
            ],
            {
                KnowledgeJob.status: JobStatus.SUCCEEDED.value,
                KnowledgeJob.result: result,
                KnowledgeJob.finished_at: now,
                KnowledgeJob.heartbeat_at: now,
            },
        )

    def fail(self, job_id: str, worker_id: str, error_code: str, error_message: str, retryable: bool) -> KnowledgeJob:
        now = local_now()
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.status == JobStatus.RUNNING.value,
                KnowledgeJob.lease_owner == worker_id,
            ],
            {
                KnowledgeJob.status: JobStatus.FAILED.value,
                KnowledgeJob.error_code: error_code,
                KnowledgeJob.error_message: error_message,
                KnowledgeJob.retryable: retryable,
                KnowledgeJob.finished_at: now,
                KnowledgeJob.heartbeat_at: now,
            },
        )

    def request_cancel(self, job_id: str, canceled_by: str) -> KnowledgeJob:
        now = local_now()
        self._checked_update(
            job_id,
            canceled_by,
            [
                KnowledgeJob.status.in_({
                    JobStatus.QUEUED.value,
                    JobStatus.CLAIMED.value,
                    JobStatus.RUNNING.value,
                }),
            ],
            {
                KnowledgeJob.cancel_requested_at: now,
                KnowledgeJob.canceled_by: canceled_by,
            },
        )
        return self.db.get(KnowledgeJob, job_id)

    def cancel(self, job_id: str, worker_id: str) -> KnowledgeJob:
        now = local_now()
        return self._checked_update(
            job_id,
            worker_id,
            [
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            ],
            {
                KnowledgeJob.status: JobStatus.CANCELED.value,
                KnowledgeJob.finished_at: now,
                KnowledgeJob.heartbeat_at: now,
            },
        )

    def reconcile_queued(self, kb_uid: str | None = None) -> list[str]:
        now = local_now()
        query = self.db.query(KnowledgeJob).filter(
            KnowledgeJob.status == JobStatus.QUEUED.value,
            or_(
                KnowledgeJob.available_at.is_(None),
                KnowledgeJob.available_at <= now,
            ),
        )
        if kb_uid:
            query = query.filter(KnowledgeJob.kb_uid == kb_uid)
        jobs = query.order_by(KnowledgeJob.created_at.asc()).limit(1000).all()
        return [job.id for job in jobs]

    def stage_enqueued(self, job_id: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        if job.stage == "enqueued":
            return job
        job.stage = "enqueued"
        self.db.commit()
        return job
