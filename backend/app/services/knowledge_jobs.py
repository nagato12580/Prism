# backend/app/services/knowledge_jobs.py
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

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


class RedisPublisher(Protocol):
    def publish(self, job_id: str) -> None: ...


class KnowledgeJobService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, command: JobCommand, idempotency_key: str, *, commit: bool = True) -> KnowledgeJob:
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
        if not commit:
            try:
                with self.db.begin_nested():
                    self.db.add(job)
                    self.db.flush()
            except IntegrityError:
                return (
                    self.db.query(KnowledgeJob)
                    .filter_by(idempotency_key=idempotency_key)
                    .with_for_update()
                    .one()
                )
            return job
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
        self.db.expire_all()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status == JobStatus.QUEUED.value,
                or_(
                    KnowledgeJob.available_at.is_(None),
                    KnowledgeJob.available_at <= now + timedelta(seconds=5),
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
        now = local_now()
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

    def _lease_not_expired(self, now=None):
        if now is None:
            now = local_now()
        return KnowledgeJob.lease_expires_at.is_not(None) & (
            KnowledgeJob.lease_expires_at > now
        )

    def start(self, job_id: str, worker_id: str) -> KnowledgeJob:
        now = local_now()
        values = {
            KnowledgeJob.status: JobStatus.RUNNING.value,
            KnowledgeJob.heartbeat_at: now,
            KnowledgeJob.attempt: KnowledgeJob.attempt + 1,
            KnowledgeJob.attempts: KnowledgeJob.attempts + 1,
            KnowledgeJob.started_at: now,
        }
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status == JobStatus.CLAIMED.value,
                KnowledgeJob.lease_owner == worker_id,
            )
            .update(values, synchronize_session="fetch")
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot start job {job_id} as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def heartbeat(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob:
        now = local_now()
        values = {
            KnowledgeJob.heartbeat_at: now,
            KnowledgeJob.lease_expires_at: now + lease,
        }
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            )
            .update(values, synchronize_session="fetch")
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot heartbeat job {job_id} as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def progress(self, job_id: str, worker_id: str, current: int, total: int, stage: str) -> KnowledgeJob:
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status == JobStatus.RUNNING.value,
            )
            .update(
                {
                    KnowledgeJob.progress_current: current,
                    KnowledgeJob.progress_total: total,
                    KnowledgeJob.stage: stage,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot set progress for job {job_id} as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def succeed(self, job_id: str, worker_id: str, result: dict[str, Any]) -> KnowledgeJob:
        now = local_now()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status == JobStatus.RUNNING.value,
                KnowledgeJob.lease_owner == worker_id,
            )
            .update(
                {
                    KnowledgeJob.status: JobStatus.SUCCEEDED.value,
                    KnowledgeJob.result: result,
                    KnowledgeJob.finished_at: now,
                    KnowledgeJob.heartbeat_at: now,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot mark job {job_id} succeeded as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def fail(self, job_id: str, worker_id: str, error_code: str, error_message: str, retryable: bool) -> KnowledgeJob:
        now = local_now()
        current = self.db.get(KnowledgeJob, job_id)
        if current is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        exhausted = current.attempt >= current.max_attempts
        if retryable and not exhausted:
            rowcount = (
                self.db.query(KnowledgeJob)
                .filter(
                    KnowledgeJob.id == job_id,
                    KnowledgeJob.status == JobStatus.RUNNING.value,
                    KnowledgeJob.lease_owner == worker_id,
                )
                .update(
                    {
                        KnowledgeJob.status: JobStatus.QUEUED.value,
                        KnowledgeJob.error_code: error_code,
                        KnowledgeJob.error_message: error_message,
                        KnowledgeJob.retryable: True,
                        KnowledgeJob.lease_owner: None,
                        KnowledgeJob.lease_expires_at: None,
                        KnowledgeJob.heartbeat_at: now,
                    },
                    synchronize_session="fetch",
                )
            )
        else:
            rowcount = (
                self.db.query(KnowledgeJob)
                .filter(
                    KnowledgeJob.id == job_id,
                    KnowledgeJob.status == JobStatus.RUNNING.value,
                    KnowledgeJob.lease_owner == worker_id,
                )
                .update(
                    {
                        KnowledgeJob.status: JobStatus.FAILED.value,
                        KnowledgeJob.error_code: error_code,
                        KnowledgeJob.error_message: error_message,
                        KnowledgeJob.retryable: False,
                        KnowledgeJob.finished_at: now,
                        KnowledgeJob.heartbeat_at: now,
                    },
                    synchronize_session="fetch",
                )
            )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot fail job {job_id} as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def request_cancel(self, job_id: str, canceled_by: str) -> KnowledgeJob:
        now = local_now()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status.in_({
                    JobStatus.QUEUED.value,
                    JobStatus.CLAIMED.value,
                    JobStatus.RUNNING.value,
                }),
            )
            .update(
                {
                    KnowledgeJob.cancel_requested_at: now,
                    KnowledgeJob.canceled_by: canceled_by,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot request cancel for job {job_id}")
        return self.db.get(KnowledgeJob, job_id)

    def cancel(self, job_id: str, worker_id: str) -> KnowledgeJob:
        now = local_now()
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.lease_owner == worker_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            )
            .update(
                {
                    KnowledgeJob.status: JobStatus.CANCELED.value,
                    KnowledgeJob.finished_at: now,
                    KnowledgeJob.heartbeat_at: now,
                },
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot cancel job {job_id} as {worker_id}")
        return self.db.get(KnowledgeJob, job_id)

    def reconcile_queued(self, kb_uid: str | None = None, publisher: RedisPublisher | None = None) -> list[str]:
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
        ids = [job.id for job in jobs]
        if publisher:
            for job_id in ids:
                publisher.publish(job_id)
        return ids

    def stage_enqueued(self, job_id: str) -> KnowledgeJob:
        rowcount = (
            self.db.query(KnowledgeJob)
            .filter(
                KnowledgeJob.id == job_id,
                KnowledgeJob.stage != "enqueued",
            )
            .update(
                {KnowledgeJob.stage: "enqueued"},
                synchronize_session="fetch",
            )
        )
        self.db.commit()
        if rowcount != 1:
            raise InvalidJobTransition(f"Cannot stage-enqueue job {job_id}")
        return self.db.get(KnowledgeJob, job_id)
