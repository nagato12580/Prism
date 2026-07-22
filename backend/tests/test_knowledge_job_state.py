# backend/tests/test_knowledge_job_state.py
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeJob
from backend.app.models.knowledge_types import JobStatus


def test_job_create_populates_scope_status_and_payload(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    command = JobCommand(
        job_type="parse",
        tenant_id="tenant-a",
        kb_uid="kb-a",
        file_uid="file-a",
        payload={"content_version": 1},
    )
    job = service.create(command, "idem-parse-1")
    assert job.tenant_id == "tenant-a"
    assert job.kb_uid == "kb-a"
    assert job.file_uid == "file-a"
    assert job.status == JobStatus.QUEUED
    assert job.job_type == "parse"
    assert job.payload == {"content_version": 1}
    assert job.attempt == 0
    assert job.max_attempts == 3


def test_job_claim_is_single_winner(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(
        JobCommand("parse", "tenant-a", "kb-a", "file-a", {"v": 1}),
        "idem-claim-1",
    )
    assert service.claim(job.id, "worker-1", timedelta(seconds=30)) is not None
    assert service.claim(job.id, "worker-2", timedelta(seconds=30)) is None


def test_duplicate_idempotency_key_returns_existing_job(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    command = JobCommand("index", "tenant-a", "kb-a", "file-a", {})
    first = service.create(command, "same-key-1")
    second = service.create(command, "same-key-1")
    assert first.id == second.id
    assert service.create(command, "same-key-2").id != first.id


def test_job_state_transitions_through_valid_paths(db_session):
    from backend.app.services.knowledge_jobs import InvalidJobTransition, JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    lease = timedelta(seconds=30)
    job = service.create(
        JobCommand("parse", "tenant-a", "kb-a", "file-a", {}),
        "idem-trans-1",
    )
    service.claim(job.id, "worker-1", lease)
    service.heartbeat(job.id, "worker-1", lease)
    service.start(job.id, "worker-1")
    service.progress(job.id, "worker-1", current=5, total=10, stage="chunking")
    service.succeed(job.id, "worker-1", result={"chunks": 3})

    db_session.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert job.result == {"chunks": 3}

    with pytest.raises(InvalidJobTransition):
        service.succeed(job.id, "worker-1", result={"again": True})


def test_job_fail_and_cancel_lifecycle(db_session):
    from backend.app.services.knowledge_jobs import InvalidJobTransition, JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    lease = timedelta(seconds=30)
    job = service.create(
        JobCommand("parse", "tenant-a", "kb-a", None, {}),
        "idem-fail-1",
    )

    service.claim(job.id, "worker-1", lease)
    service.request_cancel(job.id, "user-a")
    db_session.refresh(job)
    assert job.cancel_requested_at is not None
    assert job.canceled_by == "user-a"

    service.cancel(job.id, "worker-1")
    db_session.refresh(job)
    assert job.status == JobStatus.CANCELED
    with pytest.raises(InvalidJobTransition):
        service.start(job.id, "worker-1")


def test_repeated_idempotency_does_not_change_state(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    first = service.create(JobCommand("parse", "t", "k", "f", {}), "many-1")
    second = service.create(JobCommand("parse", "t", "k", "f", {}), "many-1")
    assert first.id == second.id
    assert first.status == second.status


def test_reclaim_expired_works(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(
        JobCommand("parse", "t", "k", "f", {}),
        "reclaim-test",
    )
    service.claim(job.id, "worker-1", timedelta(seconds=-1))
    reclaimed = service.reclaim_expired(job.id, "worker-2", timedelta(seconds=30))
    assert reclaimed is not None
    db_session.refresh(reclaimed)
    assert reclaimed.lease_owner == "worker-2"


def test_heartbeat_extends_lease(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(JobCommand("parse", "t", "k", "f", {}), "hb-test")
    service.claim(job.id, "w1", timedelta(seconds=5))
    service.heartbeat(job.id, "w1", timedelta(seconds=60))
    db_session.refresh(job)
    from backend.app.utils.time import local_now
    assert job.lease_expires_at is not None
    remaining = (job.lease_expires_at - local_now()).total_seconds()
    assert remaining > 30


def test_cannot_start_claimed_job_with_wrong_worker(db_session):
    from backend.app.services.knowledge_jobs import InvalidJobTransition, JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(JobCommand("parse", "t", "k", "f", {}), "wrong-worker")
    service.claim(job.id, "worker-a", timedelta(seconds=30))
    with pytest.raises(InvalidJobTransition):
        service.start(job.id, "worker-b")


def test_cannot_cancel_terminal_job(db_session):
    from backend.app.services.knowledge_jobs import InvalidJobTransition, JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(JobCommand("parse", "t", "k", "f", {}), "terminal-cancel")
    service.claim(job.id, "w1", timedelta(seconds=30))
    service.cancel(job.id, "w1")
    with pytest.raises(InvalidJobTransition):
        service.cancel(job.id, "w1")


def test_reconcile_queued_returns_unclaimed_jobs(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    j1 = service.create(JobCommand("parse", "t", "k", "f", {}), "rq-1")
    j2 = service.create(JobCommand("parse", "t", "k", "f", {}), "rq-2")
    service.claim(j2.id, "w1", timedelta(seconds=30))
    ids = service.reconcile_queued()
    assert j1.id in ids
    assert j2.id not in ids
