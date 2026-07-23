from datetime import timedelta
import os

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
