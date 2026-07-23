import json

import pytest
from sqlalchemy.orm import Query

from backend.app.utils.time import local_now
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeJob, KnowledgeTopic
from backend.app.services.knowledge_job_queue import (
    enqueue_governance_job,
    enqueue_ingest_job,
    enqueue_topic_ingest_jobs,
)


class FakeRedis:
    def __init__(self):
        self.messages = []

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))


class FailingOnceRedis(FakeRedis):
    def __init__(self):
        super().__init__()
        self.failures_remaining = 1

    def lpush(self, queue_name, payload):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("redis unavailable")
        super().lpush(queue_name, payload)


def _topic(db_session, name="Queue Topic"):
    topic = KnowledgeTopic(
        user_id="default-user",
        tenant_id="tenant-test",
        owner_user_id="default-user",
        name=name,
    )
    db_session.add(topic)
    db_session.flush()
    return topic


def _item(db_session, title, topic=None):
    item = KnowledgeItem(
        tenant_id=topic.tenant_id if topic else "tenant-test",
        kb_uid=topic.kb_uid if topic else "kb-test",
        title=title,
        content=f"{title} content",
        source_type="upload",
    )
    db_session.add(item)
    db_session.flush()
    return item


def _resource(db_session, topic, title, status="completed", media_type="document", item=None):
    item = item or _item(db_session, title, topic)
    resource = KnowledgeFile(
        user_id="default-user",
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        file_uid=f"file-{title}",
        topic_id=topic.id,
        item_id=item.id,
        title=title,
        original_filename=f"{title}.txt",
        media_type=media_type,
        file_ext=".txt",
        file_size=10,
        md5=f"md5-{title}",
        storage_path=f"/tmp/{title}.txt",
        processing_status=status,
        error_message="old parse error",
    )
    db_session.add(resource)
    db_session.flush()
    return resource


def test_enqueue_ingest_job_creates_then_reuses_active_job_without_duplicate_redis_message(db_session):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Active Paper")
    db_session.commit()

    redis = FakeRedis()

    first = enqueue_ingest_job(db_session, redis, resource.id, queue_name="knowledge:jobs")
    second = enqueue_ingest_job(db_session, redis, resource.id, queue_name="knowledge:jobs")

    assert first.id == second.id
    assert len(redis.messages) == 1
    assert json.loads(redis.messages[0][1]) == {"job_id": first.id}
    assert first.stage == "enqueued"
    assert db_session.query(KnowledgeJob).filter_by(resource_id=resource.id, job_type="ingest").count() == 1
    db_session.refresh(resource)
    assert resource.processing_status == "queued"
    assert resource.error_message is None


def test_enqueue_ingest_job_retries_redis_push_for_created_active_job(db_session):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Retry Paper")
    db_session.commit()
    redis = FailingOnceRedis()

    with pytest.raises(RuntimeError, match="redis unavailable"):
        enqueue_ingest_job(db_session, redis, resource.id, queue_name="knowledge:jobs")

    job = db_session.query(KnowledgeJob).filter_by(resource_id=resource.id, job_type="ingest").one()
    assert job.stage == "created"
    assert redis.messages == []

    retried = enqueue_ingest_job(db_session, redis, resource.id, queue_name="knowledge:jobs")

    assert retried.id == job.id
    assert retried.stage == "enqueued"
    assert len(redis.messages) == 1
    assert json.loads(redis.messages[0][1]) == {"job_id": job.id}


def test_enqueue_governance_job_creates_then_reuses_without_duplicate_redis_message(db_session):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Governed")
    resource.governance_status = "failed"
    resource.governance_error_message = "old governance error"
    db_session.commit()
    redis = FakeRedis()

    first = enqueue_governance_job(db_session, redis, resource.id, queue_name="knowledge:jobs")
    second = enqueue_governance_job(db_session, redis, resource.id, queue_name="knowledge:jobs")

    assert first.id == second.id
    assert first.job_type == "governance"
    assert first.stage == "enqueued"
    assert len(redis.messages) == 1
    assert json.loads(redis.messages[0][1]) == {"job_id": first.id}
    db_session.refresh(resource)
    assert resource.governance_status == "queued"
    assert resource.governance_error_message is None


def test_enqueue_governance_job_recovers_created_active_job_and_resets_resource_status(db_session):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Governance Retry")
    resource.governance_status = "failed"
    resource.governance_error_message = "old governance error"
    resource.governance_finished_at = local_now()
    job = KnowledgeJob(
        tenant_id=resource.tenant_id,
        kb_uid=resource.kb_uid,
        file_uid=resource.file_uid,
        idempotency_key="governance-retry-created",
        job_type="governance",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        stage="created",
        max_attempts=3,
        available_at=local_now(),
    )
    db_session.add(job)
    db_session.commit()
    redis = FakeRedis()

    retried = enqueue_governance_job(db_session, redis, resource.id, queue_name="knowledge:governance")

    assert retried.id == job.id
    assert retried.stage == "enqueued"
    assert len(redis.messages) == 1
    assert redis.messages[0][0] == "knowledge:governance"
    assert json.loads(redis.messages[0][1]) == {"job_id": job.id}
    db_session.refresh(resource)
    assert resource.governance_status == "queued"
    assert resource.governance_error_message is None
    assert resource.governance_finished_at is None


def test_enqueue_governance_job_resets_resource_when_active_job_already_enqueued(db_session):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Governance Already Enqueued", status="done")
    resource.governance_status = "failed"
    resource.governance_error_message = "old"
    resource.governance_finished_at = local_now()
    job = KnowledgeJob(
        tenant_id=resource.tenant_id,
        kb_uid=resource.kb_uid,
        file_uid=resource.file_uid,
        idempotency_key="governance-already-enqueued",
        job_type="governance",
        resource_id=resource.id,
        item_id=resource.item_id,
        topic_id=resource.topic_id,
        status="queued",
        stage="enqueued",
        max_attempts=3,
        available_at=local_now(),
    )
    db_session.add(job)
    db_session.commit()
    redis = FakeRedis()

    retried = enqueue_governance_job(db_session, redis, resource.id, queue_name="knowledge:governance")

    assert retried.id == job.id
    assert retried.stage == "enqueued"
    assert redis.messages == []
    db_session.rollback()
    db_session.refresh(resource)
    assert resource.governance_status == "queued"
    assert resource.governance_error_message is None
    assert resource.governance_finished_at is None


def test_enqueue_governance_job_rejects_dangling_item_id_as_not_ingestable(db_session):
    topic = _topic(db_session)
    resource = KnowledgeFile(
        user_id="default-user",
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        file_uid="file-dangling-governance",
        topic_id=topic.id,
        item_id="missing-item",
        title="Dangling Governance",
        original_filename="dangling-governance.txt",
        media_type="document",
        file_ext=".txt",
        file_size=10,
        md5="md5-dangling-governance",
        storage_path="/tmp/dangling-governance.txt",
        processing_status="completed",
    )
    db_session.add(resource)
    db_session.commit()

    with pytest.raises(ValueError, match="resource_not_ingestable"):
        enqueue_governance_job(db_session, FakeRedis(), resource.id, queue_name="knowledge:jobs")


def test_enqueue_ingest_job_rejects_dangling_item_id(db_session):
    topic = _topic(db_session)
    resource = KnowledgeFile(
        user_id="default-user",
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        file_uid="file-dangling-ingest",
        topic_id=topic.id,
        item_id="missing-item",
        title="Dangling",
        original_filename="dangling.txt",
        media_type="document",
        file_ext=".txt",
        file_size=10,
        md5="md5-dangling",
        storage_path="/tmp/dangling.txt",
        processing_status="completed",
    )
    db_session.add(resource)
    db_session.commit()

    with pytest.raises(ValueError, match="resource_not_ingestable"):
        enqueue_ingest_job(db_session, FakeRedis(), resource.id, queue_name="knowledge:jobs")


def test_enqueue_topic_ingest_jobs_skips_ineligible_resources(db_session):
    topic = _topic(db_session)
    completed = _resource(db_session, topic, "Completed", status="completed")
    failed = _resource(db_session, topic, "Failed", status="failed")
    _resource(db_session, topic, "Done", status="done")
    _resource(db_session, topic, "Invalid", status="text_invalid")
    db_session.commit()

    redis = FakeRedis()

    result = enqueue_topic_ingest_jobs(db_session, redis, topic.id, queue_name="knowledge:jobs")

    assert result.queued == 2
    assert result.skipped == 2
    assert result.failed == 0
    assert set(result.job_ids) == {
        db_session.query(KnowledgeJob).filter_by(resource_id=completed.id).one().id,
        db_session.query(KnowledgeJob).filter_by(resource_id=failed.id).one().id,
    }
    assert result.messages == []
    assert len(redis.messages) == 2
    assert [queue for queue, _payload in redis.messages] == ["knowledge:jobs", "knowledge:jobs"]
    assert {json.loads(payload)["job_id"] for _queue, payload in redis.messages} == set(result.job_ids)


def test_enqueue_topic_ingest_jobs_continues_after_redis_failure_and_retry_recovers_created_job(db_session):
    topic = _topic(db_session)
    first = _resource(db_session, topic, "First", status="completed")
    second = _resource(db_session, topic, "Second", status="completed")
    db_session.commit()
    redis = FailingOnceRedis()

    result = enqueue_topic_ingest_jobs(db_session, redis, topic.id, queue_name="knowledge:jobs")

    assert result.queued == 1
    assert result.failed == 1
    assert result.skipped == 0
    assert len(result.job_ids) == 1
    assert len(result.messages) == 1
    assert result.messages[0].startswith("First: redis unavailable")
    first_job = db_session.query(KnowledgeJob).filter_by(resource_id=first.id, job_type="ingest").one()
    second_job = db_session.query(KnowledgeJob).filter_by(resource_id=second.id, job_type="ingest").one()
    assert first_job.stage == "created"
    assert second_job.stage == "enqueued"
    assert json.loads(redis.messages[0][1]) == {"job_id": second_job.id}

    retry_result = enqueue_topic_ingest_jobs(db_session, redis, topic.id, queue_name="knowledge:jobs")

    assert retry_result.queued == 1
    assert retry_result.failed == 0
    assert retry_result.skipped == 1
    assert retry_result.job_ids == [first_job.id]
    assert len(redis.messages) == 2
    assert json.loads(redis.messages[1][1]) == {"job_id": first_job.id}
    db_session.refresh(first_job)
    db_session.refresh(second_job)
    assert first_job.stage == "enqueued"
    assert second_job.stage == "enqueued"


def test_enqueue_ingest_job_uses_for_update_when_loading_resource(db_session, monkeypatch):
    topic = _topic(db_session)
    resource = _resource(db_session, topic, "Locked")
    db_session.commit()
    calls = []
    original = Query.with_for_update

    def spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", spy)

    enqueue_ingest_job(db_session, FakeRedis(), resource.id, queue_name="knowledge:jobs")

    assert calls
