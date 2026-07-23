import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeJob, KnowledgeTopic
from backend.app.utils.time import local_now


class FakeRedis:
    def __init__(self, messages=None):
        self.messages = list(messages or [])

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))

    def brpop(self, queue_name, timeout=0):
        if not self.messages:
            return None
        queued_name, payload = self.messages.pop()
        return queued_name, payload


@pytest.fixture()
def worker_session(monkeypatch):
    import engine.app.jobs.worker as worker

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "_Session", Session)
    return Session


def _topic(db, name="Worker Topic"):
    topic = KnowledgeTopic(
        tenant_id="tenant-test",
        owner_user_id="default-user",
        user_id="default-user",
        name=name,
    )
    db.add(topic)
    db.flush()
    return topic


def _item(db, topic, title="Worker Item", content="Useful extracted text for vectorization."):
    item = KnowledgeItem(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        title=title,
        content=content,
        source_type="upload",
        user_id="default-user",
    )
    db.add(item)
    db.flush()
    return item


def _resource(db, topic, item=None, **kwargs):
    item = item or _item(db, topic)
    fields = {
        "tenant_id": topic.tenant_id,
        "kb_uid": topic.kb_uid,
        "user_id": "default-user",
        "topic_id": topic.id,
        "item_id": item.id,
        "title": item.title,
        "original_filename": f"{item.title}.txt",
        "media_type": "document",
        "file_ext": ".txt",
        "file_size": 10,
        "md5": f"md5-{item.id}",
        "storage_path": f"/tmp/{item.id}.txt",
        "processing_status": "queued",
        "content_text": item.content,
        "page_count": 1,
        "error_message": "old error",
        "governance_status": "not_started",
        "governance_error_message": "old governance error",
    }
    fields.update(kwargs)
    resource = KnowledgeFile(**fields)
    db.add(resource)
    db.flush()
    return resource


def _job(db, resource, job_type="ingest", status="queued", **kwargs):
    fields = {
        "tenant_id": resource.tenant_id,
        "kb_uid": resource.kb_uid,
        "file_uid": resource.file_uid,
        "idempotency_key": f"{resource.id}:{job_type}:{status}:{uuid4()}",
        "job_type": job_type,
        "resource_id": resource.id,
        "item_id": resource.item_id,
        "topic_id": resource.topic_id,
        "status": status,
        "stage": "enqueued",
        "max_attempts": 3,
        "available_at": local_now(),
    }
    fields.update(kwargs)
    job = KnowledgeJob(**fields)
    db.add(job)
    db.flush()
    return job


def test_claim_job_claims_queued_job(worker_session):
    from engine.app.jobs.worker import claim_job

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    job = _job(db, resource)
    db.commit()

    claimed = claim_job(db, job.id, "worker-1")

    assert claimed is not None
    assert claimed.status == "processing"
    assert claimed.locked_by == "worker-1"
    assert claimed.locked_at is not None
    assert claimed.started_at is not None
    assert claimed.attempts == 1
    assert claimed.stage == "claimed"


def test_claim_job_does_not_claim_delayed_queued_job(worker_session):
    from engine.app.jobs.worker import claim_job

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    job = _job(db, resource, attempts=0, available_at=local_now() + timedelta(minutes=10))
    db.commit()

    claimed = claim_job(db, job.id, "worker-1")

    assert claimed is None
    db.refresh(job)
    assert job.status == "queued"
    assert job.locked_by is None
    assert job.locked_at is None
    assert job.attempts == 0


def test_mark_retry_or_failed_retries_then_exhausts(worker_session):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    retry_resource = _resource(db, topic, item=_item(db, topic, "Retry Item"))
    retry_job = _job(db, retry_resource, status="processing", attempts=1, locked_by="worker-1")
    failed_resource = _resource(db, topic, item=_item(db, topic, "Failed Item"))
    failed_job = _job(
        db,
        failed_resource,
        status="processing",
        attempts=3,
        max_attempts=3,
        locked_by="worker-1",
    )
    db.commit()
    pushed = []
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    try:
        worker.mark_retry_or_failed(db, retry_job, RuntimeError("temporary outage"), retryable=True)
        worker.mark_retry_or_failed(db, failed_job, RuntimeError("permanent outage"), retryable=True)
    finally:
        monkeypatch.undo()

    db.refresh(retry_job)
    db.refresh(retry_resource)
    assert retry_job.status == "queued"
    assert retry_job.stage == "enqueued"
    assert retry_job.error_message == "temporary outage"
    assert retry_job.locked_by == ""
    assert retry_job.locked_at is None
    assert retry_job.available_at <= local_now()
    assert pushed == [("prism:queue:ingest", retry_job.id)]
    assert retry_resource.processing_status == "queued"
    assert retry_resource.error_message == "temporary outage"
    claimed = worker.claim_job(db, retry_job.id, "retry-worker")
    assert claimed is not None
    assert claimed.status == "processing"

    db.refresh(failed_job)
    db.refresh(failed_resource)
    assert failed_job.status == "failed"
    assert failed_job.stage == "failed"
    assert failed_job.error_message == "permanent outage"
    assert failed_job.finished_at is not None
    assert failed_resource.processing_status == "failed"
    assert failed_resource.error_message == "permanent outage"


def test_retry_publish_failure_is_republished_by_recovery_helper(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    job = _job(db, resource, status="processing", attempts=1, locked_by="worker-1")
    db.commit()

    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: (_ for _ in ()).throw(RuntimeError("redis down")),
    )

    with pytest.raises(RuntimeError, match="redis down"):
        worker.mark_retry_or_failed(db, job, RuntimeError("temporary outage"), retryable=True)

    db.refresh(job)
    assert job.status == "queued"
    assert job.stage == "retry"
    assert job.available_at <= local_now()

    pushed = []
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    assert worker.republish_due_queued_jobs() == 1

    db.refresh(job)
    assert pushed == [(worker.settings.KNOWLEDGE_INGEST_QUEUE, job.id)]
    assert job.stage == "enqueued"


def test_recover_stale_jobs_requeues_processing_jobs(worker_session):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    stale = _job(
        db,
        resource,
        status="processing",
        locked_by="dead-worker",
        locked_at=local_now() - timedelta(seconds=120),
        stage="embedding",
    )
    fresh = _job(
        db,
        resource,
        status="processing",
        locked_by="live-worker",
        locked_at=local_now(),
        stage="embedding",
    )
    db.commit()
    stale_id = stale.id
    fresh_id = fresh.id
    db.close()
    pushed = []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    try:
        recovered = worker.recover_stale_jobs(stale_seconds=60)
    finally:
        monkeypatch.undo()

    db = worker_session()
    try:
        stale = db.query(KnowledgeJob).filter_by(id=stale_id).one()
        fresh = db.query(KnowledgeJob).filter_by(id=fresh_id).one()
        assert recovered == 1
        assert stale.status == "queued"
        assert stale.stage == "enqueued"
        assert stale.locked_by == ""
        assert stale.locked_at is None
        assert stale.available_at <= local_now()
        assert pushed == [("prism:queue:ingest", stale.id)]
        claimed = worker.claim_job(db, stale.id, "recovery-worker")
        assert claimed is not None
        assert claimed.status == "processing"
        assert fresh.status == "processing"
        assert fresh.locked_by == "live-worker"
    finally:
        db.close()


def test_republish_due_queued_jobs_publishes_recovered_job(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    job = _job(
        db,
        resource,
        status="queued",
        stage="recovered",
        locked_by="",
        locked_at=None,
        available_at=local_now(),
    )
    delayed = _job(
        db,
        resource,
        status="queued",
        stage="recovered",
        available_at=local_now() + timedelta(minutes=5),
    )
    enqueued = _job(db, resource, status="queued", stage="enqueued", available_at=local_now())
    db.commit()

    pushed = []
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    assert worker.republish_due_queued_jobs() == 1

    db.refresh(job)
    db.refresh(delayed)
    db.refresh(enqueued)
    assert pushed == [(worker.settings.KNOWLEDGE_INGEST_QUEUE, job.id)]
    assert job.stage == "enqueued"
    assert delayed.stage == "recovered"
    assert enqueued.stage == "enqueued"


def test_republish_due_queued_jobs_republishes_only_stale_enqueued_jobs(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    resource = _resource(db, topic)
    stale = _job(
        db,
        resource,
        status="queued",
        stage="enqueued",
        available_at=local_now() - timedelta(minutes=10),
        created_at=local_now() - timedelta(minutes=10),
    )
    fresh = _job(
        db,
        resource,
        status="queued",
        stage="enqueued",
        available_at=local_now(),
        created_at=local_now(),
    )
    db.commit()

    pushed = []
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    assert worker.republish_due_queued_jobs(stale_seconds=60) == 1

    db.refresh(stale)
    db.refresh(fresh)
    assert pushed == [(worker.settings.KNOWLEDGE_INGEST_QUEUE, stale.id)]
    assert stale.stage == "enqueued"
    assert fresh.stage == "enqueued"


def test_run_ingest_job_success_marks_done_and_enqueues_governance(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(db, topic, item=item, processing_status="queued")
    job = _job(db, resource)
    db.commit()
    job_id = job.id
    item_id = item.id
    resource_id = resource.id
    db.close()

    ingest_calls = []
    progress_callbacks = []
    pushed = []

    def fake_ingest_item(received_item_id, progress=None):
        ingest_calls.append(received_item_id)
        progress_callbacks.append(progress)
        progress(stage="embedding", current=1, total=2)
        progress(stage="store_milvus", current=2, total=2)
        return 2

    monkeypatch.setattr(worker, "ingest_item", fake_ingest_item)
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    result = worker.run_ingest_job(job_id, worker_id="worker-1")

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
        governance_job = db.query(KnowledgeJob).filter_by(resource_id=resource.id, job_type="governance").one()

        assert result == 2
        assert ingest_calls == [item_id]
        assert callable(progress_callbacks[0])
        assert job.status == "done"
        assert job.stage == "done"
        assert job.progress_current == 2
        assert job.progress_total == 2
        assert job.locked_by == ""
        assert resource.processing_status == "done"
        assert resource.error_message is None
        assert resource.governance_status == "queued"
        assert resource.governance_error_message is None
        assert governance_job.status == "queued"
        assert governance_job.stage == "enqueued"
        assert pushed == [("prism:queue:governance", governance_job.id)]
    finally:
        db.close()


def test_run_ingest_job_keeps_ingest_done_when_governance_push_fails(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(db, topic, item=item, processing_status="queued")
    job = _job(db, resource)
    db.commit()
    job_id = job.id
    resource_id = resource.id
    db.close()

    monkeypatch.setattr(worker, "ingest_item", lambda item_id, progress=None: 2)
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())

    def fail_push(client, queue_name, pushed_job_id):
        raise RuntimeError("redis governance down")

    monkeypatch.setattr(worker.redis_queue, "push_job", fail_push)

    result = worker.run_ingest_job(job_id, worker_id="worker-1")

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()
        governance_job = db.query(KnowledgeJob).filter_by(resource_id=resource.id, job_type="governance").one()

        assert result == 2
        assert job.status == "done"
        assert job.stage == "done"
        assert resource.processing_status == "done"
        assert resource.governance_status == "failed"
        assert "redis governance down" in resource.governance_error_message
        assert governance_job.status == "queued"
        assert governance_job.stage == "created"
    finally:
        db.close()


def test_run_ingest_job_text_invalid_blocks_vectorization(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="x" * 20)
    resource = _resource(db, topic, item=item, content_text="x" * 20, page_count=1)
    job = _job(db, resource)
    db.commit()
    job_id = job.id
    resource_id = resource.id
    db.close()

    ingest_calls = []
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_TEXT_MAX_CHARS", 100)
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_TEXT_MAX_CHARS_PER_PAGE", 5)
    monkeypatch.setattr(worker, "ingest_item", lambda *args, **kwargs: ingest_calls.append(args))

    worker.run_ingest_job(job_id, worker_id="worker-1")

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()

        assert ingest_calls == []
        assert job.status == "failed"
        assert job.stage == "failed"
        assert job.error_code == "hard_failure"
        assert "Parsed text density is abnormal" in job.error_message
        assert resource.processing_status == "text_invalid"
        assert "Parsed text density is abnormal" in resource.error_message
    finally:
        db.close()


def test_run_governance_job_success_updates_progress_and_marks_done(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(
        db,
        topic,
        item=item,
        processing_status="done",
        governance_status="queued",
        governance_error_message="old governance error",
    )
    job = _job(db, resource, job_type="governance")
    db.commit()
    job_id = job.id
    item_id = item.id
    resource_id = resource.id
    db.close()

    calls = []

    def fake_settle(db, received_item_id, progress=None):
        calls.append(received_item_id)
        progress(current=1, total=2, stage="governance")
        progress(current=2, total=2, stage="governance")
        return "governed"

    monkeypatch.setattr(worker, "settle_document_item_to_governance", fake_settle, raising=False)

    result = worker.run_governance_job(job_id, worker_id="governance-worker-1")

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()

        assert result == "governed"
        assert calls == [item_id]
        assert job.status == "done"
        assert job.stage == "done"
        assert job.progress_current == 2
        assert job.progress_total == 2
        assert job.locked_by == ""
        assert resource.processing_status == "done"
        assert resource.governance_status == "done"
        assert resource.governance_error_message is None
        assert resource.governance_progress_current == 2
        assert resource.governance_progress_total == 2
        assert resource.governance_started_at is not None
        assert resource.governance_finished_at is not None
    finally:
        db.close()


def test_run_governance_job_progress_failure_does_not_fail_settlement(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(
        db,
        topic,
        item=item,
        processing_status="done",
        governance_status="queued",
    )
    job = _job(db, resource, job_type="governance")
    db.commit()
    job_id = job.id
    item_id = item.id
    resource_id = resource.id
    db.close()

    progress_calls = []

    def fake_record_progress(*args, **kwargs):
        progress_calls.append((args, kwargs))
        raise RuntimeError("progress database outage")

    def fake_settle(db, received_item_id, progress=None):
        assert received_item_id == item_id
        progress(current=1, total=2, stage="governance")
        return "governed"

    monkeypatch.setattr(worker, "_record_governance_progress", fake_record_progress)
    monkeypatch.setattr(worker, "settle_document_item_to_governance", fake_settle, raising=False)

    assert worker.run_governance_job(job_id, worker_id="governance-worker-1") == "governed"

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()

        assert progress_calls == [
            ((job_id, resource_id), {"current": 1, "total": 2, "stage": "governance"})
        ]
        assert job.status == "done"
        assert job.stage == "done"
        assert resource.governance_status == "done"
        assert resource.governance_error_message is None
    finally:
        db.close()


def test_run_governance_job_retry_failure_requeues_and_publishes(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(
        db,
        topic,
        item=item,
        processing_status="done",
        governance_status="queued",
    )
    job = _job(db, resource, job_type="governance", attempts=0, max_attempts=3)
    db.commit()
    job_id = job.id
    resource_id = resource.id
    db.close()

    pushed = []

    def fail_settle(*args, **kwargs):
        raise RuntimeError("governance provider down")

    monkeypatch.setattr(worker, "settle_document_item_to_governance", fail_settle, raising=False)
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        worker.redis_queue,
        "push_job",
        lambda client, queue_name, pushed_job_id: pushed.append((queue_name, pushed_job_id)),
    )

    assert worker.run_governance_job(job_id, worker_id="governance-worker-1") is None

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()

        assert job.status == "queued"
        assert job.stage == "enqueued"
        assert job.error_code == "retryable_failure"
        assert "governance provider down" in job.error_message
        assert resource.processing_status == "done"
        assert resource.governance_status == "queued"
        assert "governance provider down" in resource.governance_error_message
        assert pushed == [(worker.settings.KNOWLEDGE_GOVERNANCE_QUEUE, job.id)]
        assert all(queue_name != worker.settings.KNOWLEDGE_INGEST_QUEUE for queue_name, _ in pushed)
    finally:
        db.close()


def test_run_governance_job_exhausted_failure_keeps_resource_searchable(worker_session, monkeypatch):
    import engine.app.jobs.worker as worker

    db = worker_session()
    topic = _topic(db)
    item = _item(db, topic, content="High quality extracted document text.")
    resource = _resource(
        db,
        topic,
        item=item,
        processing_status="done",
        governance_status="queued",
    )
    job = _job(db, resource, job_type="governance", attempts=2, max_attempts=3)
    db.commit()
    job_id = job.id
    resource_id = resource.id
    db.close()

    def fail_settle(*args, **kwargs):
        raise RuntimeError("governance extraction failed")

    monkeypatch.setattr(worker, "settle_document_item_to_governance", fail_settle, raising=False)

    assert worker.run_governance_job(job_id, worker_id="governance-worker-1") is None

    db = worker_session()
    try:
        job = db.query(KnowledgeJob).filter_by(id=job_id).one()
        resource = db.query(KnowledgeFile).filter_by(id=resource_id).one()

        assert job.status == "failed"
        assert job.stage == "failed"
        assert job.error_code == "retryable_failure"
        assert "governance extraction failed" in job.error_message
        assert resource.processing_status == "done"
        assert resource.governance_status == "failed"
        assert "governance extraction failed" in resource.governance_error_message
    finally:
        db.close()


def test_redis_queue_pushes_and_pops_json_payload():
    from engine.app.jobs.redis_queue import pop_job, push_job

    redis = FakeRedis()

    push_job(redis, "knowledge:ingest", "job-123")

    assert redis.messages == [("knowledge:ingest", json.dumps({"job_id": "job-123"}))]
    assert pop_job(redis, "knowledge:ingest") == "job-123"
    assert pop_job(redis, "knowledge:ingest", timeout_seconds=1) is None


def test_worker_manager_starts_ingest_and_governance_workers(monkeypatch):
    import engine.app.jobs.worker as worker

    recovered = []
    evaluation_recovered = []
    republished = []
    started = []

    class FakeThread:
        def __init__(self, *, target, args, daemon, name):
            self.target = target
            self.args = args
            self.daemon = daemon
            self.name = name
            started.append(self)

        def start(self):
            self.started = True

        def join(self, timeout=None):
            self.join_timeout = timeout

    monkeypatch.setattr(worker, "recover_stale_jobs", lambda: recovered.append(True))
    monkeypatch.setattr(worker, "recover_expired_evaluation_jobs", lambda: evaluation_recovered.append(True))
    monkeypatch.setattr(worker, "republish_due_queued_jobs", lambda: republished.append(True))
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: "redis-client")
    monkeypatch.setattr(worker.threading, "Thread", FakeThread)
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_INGEST_WORKERS", 0)
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_GOVERNANCE_WORKERS", -3)

    manager = worker.KnowledgeWorkerManager()
    manager.start()

    assert recovered == [True]
    assert evaluation_recovered == [True]
    assert republished == [True]
    assert len(started) == 3
    assert [thread.name for thread in started] == [
        "knowledge-evaluation-lease-reaper",
        "knowledge-ingest-worker-0",
        "knowledge-governance-worker-0",
    ]
    assert all(thread.started for thread in started)
    assert started[0].args == ()
    assert started[1].args == (
        worker.settings.KNOWLEDGE_INGEST_QUEUE,
        worker.run_ingest_queue_job,
        started[1].args[2],
    )
    assert started[2].args == (
        worker.settings.KNOWLEDGE_GOVERNANCE_QUEUE,
        worker.run_governance_job,
        started[2].args[2],
    )


def test_worker_manager_periodically_sweeps_expired_evaluations(monkeypatch):
    import time
    import engine.app.jobs.worker as worker
    sweeps = []
    class Redis:
        def brpop(self, *_args, **_kwargs):
            time.sleep(0.005)
            return None
    monkeypatch.setattr(worker, "recover_stale_jobs", lambda: None)
    monkeypatch.setattr(worker, "recover_expired_evaluation_jobs", lambda: sweeps.append(time.monotonic()))
    monkeypatch.setattr(worker, "republish_due_queued_jobs", lambda: None)
    monkeypatch.setattr(worker.redis_queue, "redis_client", lambda: Redis())
    monkeypatch.setattr(worker, "EVALUATION_REAPER_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_INGEST_WORKERS", 0)
    monkeypatch.setattr(worker.settings, "KNOWLEDGE_GOVERNANCE_WORKERS", 0)
    manager = worker.KnowledgeWorkerManager()
    manager.start()
    time.sleep(0.04)
    manager.stop()
    assert len(sweeps) >= 2
    assert manager._threads == []


def test_concurrent_evaluation_reapers_only_run_one_sweep(monkeypatch):
    import threading
    import time
    import engine.app.jobs.worker as worker
    entered = []
    release = threading.Event()
    def sweep():
        entered.append(True)
        release.wait(1)
        return 1
    monkeypatch.setattr(worker, "_recover_expired_evaluation_jobs", sweep)
    results = []
    first = threading.Thread(target=lambda: results.append(worker.recover_expired_evaluation_jobs()))
    first.start()
    while not entered:
        time.sleep(0.001)
    second = threading.Thread(target=lambda: results.append(worker.recover_expired_evaluation_jobs()))
    second.start(); second.join()
    release.set(); first.join()
    assert entered == [True]
    assert sorted(results) == [0, 1]
