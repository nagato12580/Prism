# backend/tests/integration/test_knowledge_job_mysql.py
from datetime import timedelta
import threading

import pytest

from backend.app.models import KnowledgeJob
from backend.app.models.knowledge_types import JobStatus
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService


pytestmark = pytest.mark.mysql


def _claim_results(barrier, svc, job_id, worker_id, lease, output):
    barrier.wait()
    result = svc.claim(job_id, worker_id, lease)
    output.append((worker_id, result))


def test_real_concurrent_claim_single_winner(mysql_session_1, mysql_session_2):
    """Two concurrent sessions claim the same job with a synchronization barrier."""
    svc1 = KnowledgeJobService(mysql_session_1)
    svc2 = KnowledgeJobService(mysql_session_2)
    command = JobCommand("parse", "tenant-a", "kb-a", "file-a", {})

    job = svc1.create(command, "real-cc-key")
    job_id = job.id

    barrier = threading.Barrier(2, timeout=5)
    results = []

    t = threading.Thread(
        target=_claim_results,
        args=(barrier, svc2, job_id, "worker-2", timedelta(seconds=30), results),
    )
    t.start()

    barrier.wait()
    winner1 = svc1.claim(job_id, "worker-1", timedelta(seconds=30))
    results.append(("worker-1", winner1))
    t.join(timeout=5)

    winners = [r for r in results if r[1] is not None]
    assert len(winners) == 1, f"Expected exactly 1 winner, got {winners}"

    loaded = mysql_session_1.get(KnowledgeJob, job_id)
    assert loaded.status == JobStatus.CLAIMED


def test_real_concurrent_create_idempotency(mysql_session_1, mysql_session_2):
    """Two concurrent sessions create with the same idempotency key — only one Job."""
    svc1 = KnowledgeJobService(mysql_session_1)
    svc2 = KnowledgeJobService(mysql_session_2)
    command = JobCommand("parse", "tenant-a", "kb-a", "file-a", {})

    barrier = threading.Barrier(2, timeout=5)
    results = []

    def create_in_s2():
        barrier.wait()
        result = svc2.create(command, "real-cc-create-key")
        results.append(("s2", result))

    t = threading.Thread(target=create_in_s2)
    t.start()

    barrier.wait()
    j1 = svc1.create(command, "real-cc-create-key")
    results.append(("s1", j1))
    t.join(timeout=5)

    assert results[0][1].id == results[1][1].id
    rows = mysql_session_1.query(KnowledgeJob).filter_by(
        idempotency_key="real-cc-create-key"
    ).all()
    assert len(rows) == 1


def test_claim_respects_available_at(mysql_session_1):
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
    from backend.app.services.knowledge_jobs import InvalidJobTransition

    svc = KnowledgeJobService(mysql_session_1)
    lease = timedelta(seconds=30)
    command = JobCommand("parse", "t", "k", "f", {})

    job = svc.create(command, "conc-atomic-trans")

    claimed = svc.claim(job.id, "worker-1", lease)
    assert claimed is not None
    assert claimed.lease_owner == "worker-1"
    assert claimed.status == JobStatus.CLAIMED

    svc.start(job.id, "worker-1")
    svc.progress(job.id, "worker-1", 3, 10, "parsing")
    svc.succeed(job.id, "worker-1", {"ok": True})

    loaded = mysql_session_1.get(KnowledgeJob, job.id)
    assert loaded.status == JobStatus.SUCCEEDED
    assert loaded.result == {"ok": True}

    with pytest.raises(InvalidJobTransition):
        svc.cancel(job.id, "worker-1")


def test_reclaim_expired_lease(mysql_session_1):
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


def test_max_attempts_exhausted_marks_not_retryable(mysql_session_1):
    svc = KnowledgeJobService(mysql_session_1)
    lease = timedelta(seconds=30)
    job = svc.create(JobCommand("parse", "t", "k", "f", {}), "conc-max-attempts")
    job.max_attempts = 2
    mysql_session_1.commit()

    svc.claim(job.id, "w1", lease)
    svc.start(job.id, "w1")
    svc.fail(job.id, "w1", "E1", "first", retryable=True)
    mysql_session_1.refresh(job)
    assert job.attempt == 1
    assert job.retryable is True

    svc.claim(job.id, "w2", lease)
    svc.start(job.id, "w2")
    svc.fail(job.id, "w2", "E2", "second", retryable=True)
    mysql_session_1.refresh(job)
    assert job.attempt == 2
    assert job.retryable is False


def test_progress_rejects_claimed_not_running(mysql_session_1):
    from backend.app.services.knowledge_jobs import InvalidJobTransition

    svc = KnowledgeJobService(mysql_session_1)
    job = svc.create(JobCommand("parse", "t", "k", "f", {}), "conc-prog-claimed")
    svc.claim(job.id, "w1", timedelta(seconds=30))
    with pytest.raises(InvalidJobTransition):
        svc.progress(job.id, "w1", 1, 10, "stage")
