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
from backend.app.models import KnowledgeTopic, KnowledgeFile
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

    del os.environ["KNOWLEDGE_STORAGE_ROOT"]
