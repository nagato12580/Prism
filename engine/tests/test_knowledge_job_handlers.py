# engine/tests/test_knowledge_job_handlers.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import Base
from backend.app.models import KnowledgeChunk, KnowledgeItem, KnowledgeTopic, KnowledgeFile
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService


@pytest.fixture()
def handler_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()


def test_handle_parse_creates_item_and_chunks(handler_db, tmp_path):
    from engine.app.jobs.knowledge_handlers import handle_parse
    import os

    # Setup storage
    root = tmp_path / "storage"
    root.mkdir()
    (root / "t1" / "kb-a" / "file-1").mkdir(parents=True)
    test_file = root / "t1" / "kb-a" / "file-1" / "test.md"
    test_file.write_text("# Title\nBody text", encoding="utf-8")
    os.environ["KNOWLEDGE_STORAGE_ROOT"] = str(root)

    # Setup topic
    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Handler KB")
    handler_db.add(topic)
    handler_db.flush()

    # Setup file
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-1",
        original_filename="test.md",
        storage_uri=f"local://t1/kb-a/file-1/test.md",
        content_sha256="abc",
        size_bytes=20,
    )
    file_row.resource_id = file_row.id
    handler_db.add(file_row)
    handler_db.flush()

    # Setup job
    job_svc = KnowledgeJobService(handler_db)
    command = JobCommand("parse", "t1", topic.kb_uid, "file-1", {"auto_index": False})
    job = job_svc.create(command, "handler-parse-1")
    handler_db.commit()

    result = handle_parse(job.id, "w1", handler_db, job_svc)
    assert result["status"] == "completed"
    assert "item_id" in result
    chunks = handler_db.query(KnowledgeChunk).filter_by(file_uid="file-1").all()
    assert chunks
    assert all(chunk.item_id == result["item_id"] for chunk in chunks)
    assert {chunk.chunk_type for chunk in chunks} == {"parent", "child"}

    repeated = handle_parse(job.id, "w1", handler_db, job_svc)
    assert repeated["status"] == "skipped"
    assert handler_db.query(KnowledgeItem).count() == 1

    del os.environ["KNOWLEDGE_STORAGE_ROOT"]


def test_worker_dispatches_typed_parse_job_to_parse_handler(handler_db, monkeypatch):
    from engine.app.jobs import worker

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Dispatch KB")
    handler_db.add(topic)
    handler_db.commit()
    job = KnowledgeJobService(handler_db).create(
        JobCommand("parse", "t1", topic.kb_uid, "file-1", {}),
        "dispatch-parse-1",
    )
    called = []

    def fake_handle(job_id, worker_id, db_session, job_svc, publisher=None):
        called.append((job_id, worker_id, db_session))
        return {"status": "completed"}

    monkeypatch.setattr(worker, "handle_parse", fake_handle, raising=False)

    result = worker.dispatch_typed_job(handler_db, job.id, "worker-1")

    assert result == {"status": "completed"}
    assert called == [(job.id, "worker-1", handler_db)]


def test_parse_auto_index_creates_and_publishes_index_job(handler_db, tmp_path):
    from engine.app.jobs.knowledge_handlers import handle_parse
    import os

    root = tmp_path / "storage"
    path = root / "t1" / "kb-a" / "file-auto" / "auto.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Auto index", encoding="utf-8")
    os.environ["KNOWLEDGE_STORAGE_ROOT"] = str(root)
    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Auto KB")
    handler_db.add(topic)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-auto",
        original_filename="auto.md",
        storage_uri="local://t1/kb-a/file-auto/auto.md",
    )
    handler_db.add(file_row)
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    parse_job = jobs.create(
        JobCommand("parse", "t1", topic.kb_uid, file_row.file_uid, {"auto_index": True}),
        "parse-auto-index",
    )
    published = []

    result = handle_parse(parse_job.id, "w1", handler_db, jobs, publisher=published.append)

    index_job = handler_db.query(type(parse_job)).filter_by(job_type="index").one()
    assert result["status"] == "completed"
    assert index_job.file_uid == file_row.file_uid
    assert published == [index_job.id]
    del os.environ["KNOWLEDGE_STORAGE_ROOT"]


def test_parse_honors_cancel_request_before_parsing(handler_db, tmp_path):
    from engine.app.jobs.knowledge_handlers import handle_parse
    import os

    root = tmp_path / "storage"
    path = root / "t1" / "kb-a" / "file-cancel" / "cancel.md"
    path.parent.mkdir(parents=True)
    path.write_text("cancel me", encoding="utf-8")
    os.environ["KNOWLEDGE_STORAGE_ROOT"] = str(root)
    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Cancel KB")
    handler_db.add(topic)
    handler_db.flush()
    handler_db.add(KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-cancel",
        original_filename="cancel.md",
        storage_uri="local://t1/kb-a/file-cancel/cancel.md",
    ))
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("parse", "t1", topic.kb_uid, "file-cancel", {}), "parse-cancel"
    )
    jobs.request_cancel(job.id, "alice")

    result = handle_parse(job.id, "w1", handler_db, jobs)

    assert result == {"status": "canceled"}
    assert handler_db.get(type(job), job.id).status == "canceled"
    assert handler_db.query(KnowledgeItem).count() == 0
    del os.environ["KNOWLEDGE_STORAGE_ROOT"]
