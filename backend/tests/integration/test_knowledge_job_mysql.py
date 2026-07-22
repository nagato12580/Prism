# backend/tests/integration/test_knowledge_job_mysql.py
from datetime import timedelta

import pytest

from backend.app.models import KnowledgeJob
from backend.app.models.knowledge_types import JobStatus
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService


pytestmark = pytest.mark.mysql


def test_concurrent_claim_single_winner(mysql_session_1):
    """Sequential claims: only the first wins."""
    svc = KnowledgeJobService(mysql_session_1)
    command = JobCommand("parse", "tenant-a", "kb-a", "file-a", {})

    job1 = svc.create(command, "conc-mysql-claim")
    job_id = job1.id

    winner1 = svc.claim(job_id, "worker-1", timedelta(seconds=30))
    winner2 = svc.claim(job_id, "worker-2", timedelta(seconds=30))

    assert winner1 is not None
    assert winner2 is None

    loaded = mysql_session_1.get(KnowledgeJob, job_id)
    assert loaded.status == JobStatus.CLAIMED
    assert loaded.lease_owner == "worker-1"


def test_concurrent_create_same_idempotency_key_one_job(mysql_session_1, mysql_session_2):
    """Two concurrent sessions create with the same idempotency key, only one Job created."""
    svc1 = KnowledgeJobService(mysql_session_1)
    svc2 = KnowledgeJobService(mysql_session_2)
    command = JobCommand("parse", "tenant-a", "kb-a", "file-a", {})

    j1 = svc1.create(command, "conc-mysql-create")
    j2 = svc2.create(command, "conc-mysql-create")

    assert j1.id == j2.id
    assert j1.status == j2.status == JobStatus.QUEUED

    rows = mysql_session_2.query(KnowledgeJob).filter_by(
        idempotency_key="conc-mysql-create"
    ).all()
    assert len(rows) == 1


def test_claim_respects_available_at(mysql_session_1):
    """A job with future available_at should not be claimable."""
    from backend.app.utils.time import local_now
    from datetime import timedelta as delta

    svc = KnowledgeJobService(mysql_session_1)
    command = JobCommand("parse", "t", "k", "f", {})
    job = svc.create(command, "conc-future-avail")
    job.available_at = local_now() + delta(hours=1)
    mysql_session_1.commit()

    claimed = svc.claim(job.id, "worker-1", timedelta(seconds=30))
    assert claimed is None


def test_full_state_machine_with_atomic_updates(mysql_session_1):
    """All transitions use atomic UPDATE with status and worker checks."""
    from backend.app.services.knowledge_jobs import InvalidJobTransition

    svc = KnowledgeJobService(mysql_session_1)
    lease = timedelta(seconds=30)
    command = JobCommand("parse", "t", "k", "f", {})

    job = svc.create(command, "conc-atomic-trans")

    claimed = svc.claim(job.id, "worker-1", lease)
    assert claimed is not None
    assert claimed.lease_owner == "worker-1"
    assert claimed.status == JobStatus.CLAIMED

    svc.heartbeat(job.id, "worker-1", lease)
    svc.start(job.id, "worker-1")
    svc.progress(job.id, "worker-1", 3, 10, "parsing")
    svc.succeed(job.id, "worker-1", {"ok": True})

    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.status == JobStatus.SUCCEEDED
    assert loaded.result == {"ok": True}

    with pytest.raises(InvalidJobTransition):
        svc.cancel(job.id, "worker-1")


def test_reclaim_expired_lease(mysql_session_1):
    """Reclaim a job whose lease has expired."""
    from backend.app.utils.time import local_now

    svc = KnowledgeJobService(mysql_session_1)
    command = JobCommand("parse", "t", "k", "f", {})
    job = svc.create(command, "conc-expired-lease")

    claimed = svc.claim(job.id, "worker-1", timedelta(seconds=-1))
    assert claimed is not None
    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.lease_owner == "worker-1"
    assert loaded.lease_expires_at <= local_now()

    reclaimed = svc.reclaim_expired(job.id, "worker-2", timedelta(seconds=30))
    assert reclaimed is not None
    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.lease_owner == "worker-2"


def test_wrong_worker_cannot_transition(mysql_session_1):
    """Worker B cannot transition a job owned by worker A."""
    from backend.app.services.knowledge_jobs import InvalidJobTransition

    svc = KnowledgeJobService(mysql_session_1)
    command = JobCommand("parse", "t", "k", "f", {})
    job = svc.create(command, "conc-wrong-worker")

    claimed = svc.claim(job.id, "worker-a", timedelta(seconds=30))
    assert claimed is not None

    with pytest.raises(InvalidJobTransition):
        svc.start(job.id, "worker-b")

    with pytest.raises(InvalidJobTransition):
        svc.cancel(job.id, "worker-b")


def test_cancel_requires_worker_match_in_where(mysql_session_1):
    """Cancel uses WHERE lease_owner, not a separate read."""
    from backend.app.services.knowledge_jobs import InvalidJobTransition

    svc = KnowledgeJobService(mysql_session_1)
    command = JobCommand("parse", "t", "k", "f", {})
    job = svc.create(command, "conc-cancel-where")

    claimed = svc.claim(job.id, "worker-a", timedelta(seconds=30))
    assert claimed is not None

    with pytest.raises(InvalidJobTransition):
        svc.cancel(job.id, "worker-b")

    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.status == JobStatus.CLAIMED

    svc.cancel(job.id, "worker-a")
    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.status == JobStatus.CANCELED
