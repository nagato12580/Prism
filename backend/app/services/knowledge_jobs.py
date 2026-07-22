# backend/app/services/knowledge_jobs.py
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import update

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


TRANSITIONS: dict[str, set[str]] = {
    JobStatus.QUEUED.value: {JobStatus.CLAIMED.value, JobStatus.CANCELED.value},
    JobStatus.CLAIMED.value: {JobStatus.RUNNING.value, JobStatus.CANCELED.value},
    JobStatus.RUNNING.value: {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELED.value},
    JobStatus.SUCCEEDED.value: set(),
    JobStatus.FAILED.value: set(),
    JobStatus.CANCELED.value: set(),
}


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
        self.db.commit()
        return job

    def claim(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob | None:
        now = local_now()
        result = self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id, KnowledgeJob.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.CLAIMED.value,
                lease_owner=worker_id,
                heartbeat_at=now,
                lease_expires_at=now + lease,
            )
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id) if result.rowcount == 1 else None

    def _check_worker(self, job: KnowledgeJob, worker_id: str) -> None:
        if job.lease_owner != worker_id:
            raise InvalidJobTransition(
                f"Job {job.id} is owned by {job.lease_owner}, not {worker_id}"
            )

    def _transition(self, job_id: str, from_status: str, to_status: str, values: dict) -> KnowledgeJob:
        result = self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id, KnowledgeJob.status == from_status)
            .values(status=to_status, **values)
        )
        self.db.commit()
        if result.rowcount != 1:
            raise InvalidJobTransition(
                f"Cannot transition job {job_id} from {from_status} to {to_status}"
            )
        return self.db.get(KnowledgeJob, job_id)

    def start(self, job_id: str, worker_id: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        now = local_now()
        return self._transition(
            job_id,
            JobStatus.CLAIMED.value,
            JobStatus.RUNNING.value,
            {
                "heartbeat_at": now,
                "attempt": KnowledgeJob.attempt + 1,
                "attempts": KnowledgeJob.attempts + 1,
                "started_at": now,
            },
        )

    def heartbeat(self, job_id: str, worker_id: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        now = local_now()
        self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id)
            .values(heartbeat_at=now)
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id)

    def progress(self, job_id: str, worker_id: str, current: int, total: int, stage: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id)
            .values(progress_current=current, progress_total=total, stage=stage)
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id)

    def succeed(self, job_id: str, worker_id: str, result: dict[str, Any]) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        now = local_now()
        return self._transition(
            job_id,
            JobStatus.RUNNING.value,
            JobStatus.SUCCEEDED.value,
            {"result": result, "finished_at": now, "heartbeat_at": now},
        )

    def fail(self, job_id: str, worker_id: str, error_code: str, error_message: str, retryable: bool) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        now = local_now()
        return self._transition(
            job_id,
            JobStatus.RUNNING.value,
            JobStatus.FAILED.value,
            {
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
                "finished_at": now,
                "heartbeat_at": now,
            },
        )

    def request_cancel(self, job_id: str, canceled_by: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        now = local_now()
        self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id)
            .values(cancel_requested_at=now, canceled_by=canceled_by)
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id)

    def cancel(self, job_id: str, worker_id: str) -> KnowledgeJob:
        job = self.db.get(KnowledgeJob, job_id)
        if job is None:
            raise InvalidJobTransition(f"Job {job_id} not found")
        self._check_worker(job, worker_id)
        now = local_now()
        self.db.execute(
            update(KnowledgeJob)
            .where(
                KnowledgeJob.id == job_id,
                KnowledgeJob.status.in_({JobStatus.CLAIMED.value, JobStatus.RUNNING.value}),
            )
            .values(status=JobStatus.CANCELED.value, finished_at=now, heartbeat_at=now)
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id)
