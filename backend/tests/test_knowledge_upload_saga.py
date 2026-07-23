from datetime import timedelta
import os
import pytest

from backend.app.models import KnowledgeFile
from backend.app.models import KnowledgeTopic
from backend.app.security.actor import ActorContext
from backend.app.utils.time import local_now


def test_staging_reaper_removes_only_old_unreferenced_parts(db_session, tmp_path):
    from backend.app.services.knowledge_uploads import StagingReaper
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    storage.staging.mkdir(parents=True)
    old_orphan = storage.staging / "old-orphan.part"
    old_referenced = storage.staging / "old-referenced.part"
    fresh_orphan = storage.staging / "fresh-orphan.part"
    for path in (old_orphan, old_referenced, fresh_orphan):
        path.write_bytes(b"x")
    old_timestamp = (local_now() - timedelta(hours=25)).timestamp()
    os.utime(old_orphan, (old_timestamp, old_timestamp))
    os.utime(old_referenced, (old_timestamp, old_timestamp))

    db_session.add(KnowledgeFile(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        storage_uri="local://.staging/old-referenced.part",
    ))
    db_session.commit()

    removed = StagingReaper(db_session, storage).run()

    assert removed == 1
    assert not old_orphan.exists()
    assert old_referenced.exists()
    assert fresh_orphan.exists()


def test_upload_service_creates_job_then_publishes_only_job_id(db_session, tmp_path):
    from backend.app.services.knowledge_uploads import KnowledgeUploadService, UploadRequest
    from backend.app.storage.files import LocalFileStorage

    topic = KnowledgeTopic(
        tenant_id="tenant-a", owner_user_id="alice", user_id="alice", name="KB"
    )
    db_session.add(topic)
    db_session.commit()
    published = []

    class Publisher:
        def publish(self, job_id):
            published.append(job_id)

    file_row, job = KnowledgeUploadService(
        db_session, LocalFileStorage(tmp_path), Publisher()
    ).register(
        ActorContext(actor_id="alice", tenant_id="tenant-a"),
        UploadRequest(
            kb_uid=topic.kb_uid,
            filename="a.md",
            relative_path="a.md",
            media_type="document",
            mime_type="text/markdown",
            content=b"# A",
            auto_index=True,
        ),
    )

    assert job.file_uid == file_row.file_uid
    assert job.status == "queued"
    assert job.payload == {"auto_index": True}
    assert published == [job.id]
    db_session.refresh(topic)
    assert topic.mindmap["input_revision"] == 1
    assert topic.sample_questions["input_revision"] == 1


def test_upload_commit_failure_rolls_back_file_job_and_input_revision(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeJob
    from backend.app.services.knowledge_uploads import KnowledgeUploadService, UploadRequest
    from backend.app.storage.files import LocalFileStorage

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        user_id="alice",
        name="Atomic upload",
        mindmap={"status": "ready", "input_revision": 4, "nodes": []},
        sample_questions={"status": "ready", "input_revision": 7, "questions": []},
    )
    db_session.add(topic)
    db_session.commit()
    original_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit crash")))

    with pytest.raises(RuntimeError, match="commit crash"):
        KnowledgeUploadService(db_session, LocalFileStorage(tmp_path)).register(
            ActorContext(actor_id="alice", tenant_id="tenant-a"),
            UploadRequest(
                kb_uid=topic.kb_uid,
                filename="atomic.md",
                relative_path="atomic.md",
                media_type="document",
                mime_type="text/markdown",
                content=b"# Atomic",
            ),
        )

    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()
    db_session.expire_all()
    loaded = db_session.get(KnowledgeTopic, topic.id)
    assert db_session.query(KnowledgeFile).count() == 0
    assert db_session.query(KnowledgeJob).count() == 0
    assert loaded.mindmap["input_revision"] == 4
    assert loaded.sample_questions["input_revision"] == 7


def test_redis_publish_failure_keeps_committed_file_and_queued_job(db_session, tmp_path):
    from backend.app.services.knowledge_uploads import KnowledgeUploadService, UploadRequest
    from backend.app.storage.files import LocalFileStorage

    topic = KnowledgeTopic(
        tenant_id="tenant-a", owner_user_id="alice", user_id="alice", name="KB"
    )
    db_session.add(topic)
    db_session.commit()

    class FailingPublisher:
        def publish(self, job_id):
            raise ConnectionError("redis unavailable")

    file_row, job = KnowledgeUploadService(
        db_session, LocalFileStorage(tmp_path), FailingPublisher()
    ).register(
        ActorContext(actor_id="alice", tenant_id="tenant-a"),
        UploadRequest(
            kb_uid=topic.kb_uid,
            filename="a.md",
            relative_path="a.md",
            media_type="document",
            mime_type="text/markdown",
            content=b"# A",
        ),
    )

    assert db_session.get(KnowledgeFile, file_row.id) is not None
    assert job.status == "queued"
