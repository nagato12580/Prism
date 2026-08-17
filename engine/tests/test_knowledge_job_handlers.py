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


@pytest.fixture(autouse=True)
def offline_tiktoken(monkeypatch):
    import tiktoken

    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda name: type("Encoder", (), {"encode": lambda self, text: list(text or "")})(),
    )


def test_handle_parse_creates_item_and_chunks(handler_db, tmp_path, monkeypatch):
    from engine.app.jobs import knowledge_handlers
    from engine.app.jobs.knowledge_handlers import handle_parse

    # Setup storage
    root = tmp_path / "storage"
    root.mkdir()
    (root / "t1" / "kb-a" / "file-1").mkdir(parents=True)
    test_file = root / "t1" / "kb-a" / "file-1" / "test.md"
    test_file.write_text("# Title\nBody text", encoding="utf-8")
    monkeypatch.setattr(knowledge_handlers.settings, "KNOWLEDGE_STORAGE_ROOT", str(root))

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

    original_chunk = knowledge_handlers.chunk_with_preset
    original_commit = handler_db.commit
    transaction = {"counting": False, "commits": 0}

    def tracked_chunk(*args, **kwargs):
        result = original_chunk(*args, **kwargs)
        transaction["counting"] = True
        return result

    def tracked_commit():
        if transaction["counting"]:
            transaction["commits"] += 1
        return original_commit()

    monkeypatch.setattr(knowledge_handlers, "chunk_with_preset", tracked_chunk)
    monkeypatch.setattr(handler_db, "commit", tracked_commit)

    result = handle_parse(job.id, "w1", handler_db, job_svc)
    assert result["status"] == "completed"
    assert "item_id" in result
    chunks = handler_db.query(KnowledgeChunk).filter_by(file_uid="file-1").all()
    assert chunks
    assert all(chunk.item_id == result["item_id"] for chunk in chunks)
    assert {chunk.chunk_type for chunk in chunks} == {"parent", "child"}
    handler_db.refresh(file_row)
    assert file_row.content_text == "# Title\nBody text"
    handler_db.refresh(topic)
    assert topic.mindmap["input_revision"] == 1
    assert topic.sample_questions["input_revision"] == 1
    assert transaction["commits"] == 1

    transaction["counting"] = False
    repeated = handle_parse(job.id, "w1", handler_db, job_svc)
    assert repeated["status"] == "skipped"
    assert handler_db.query(KnowledgeItem).count() == 1


def test_handle_parse_records_file_error_when_parse_fails(handler_db, tmp_path, monkeypatch, caplog):
    from backend.app.models.knowledge_types import StageStatus
    from engine.app.jobs import knowledge_handlers
    from engine.app.jobs.knowledge_handlers import handle_parse

    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setattr(knowledge_handlers.settings, "KNOWLEDGE_STORAGE_ROOT", str(root))

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Parse failure KB")
    handler_db.add(topic)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-parse-fails",
        original_filename="missing.md",
        storage_uri="local://t1/kb-a/file-parse-fails/missing.md",
        content_sha256="abc",
        size_bytes=20,
        parse_status=StageStatus.PENDING.value,
    )
    handler_db.add(file_row)
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("parse", "t1", topic.kb_uid, file_row.file_uid, {"auto_index": False}),
        "handle-parse-fails",
    )

    result = handle_parse(job.id, "w1", handler_db, jobs)

    handler_db.refresh(file_row)
    assert result["status"] == "failed"
    assert file_row.parse_status == StageStatus.FAILED.value
    assert file_row.parse_error
    assert file_row.parse_error["code"] == "PARSE_ERROR"
    assert "missing.md" in file_row.parse_error["message"]
    assert "knowledge parse job failed" in caplog.text
    assert job.id in caplog.text
    assert file_row.file_uid in caplog.text
    assert topic.kb_uid in caplog.text


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


def test_worker_dispatches_typed_index_job_to_index_handler(handler_db, monkeypatch):
    from engine.app.jobs import worker

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Index Dispatch KB")
    handler_db.add(topic)
    handler_db.commit()
    job = KnowledgeJobService(handler_db).create(
        JobCommand("index", "t1", topic.kb_uid, "file-1", {}),
        "dispatch-index-1",
    )
    called = []

    def fake_handle(job_id, worker_id, db_session, job_svc):
        called.append((job_id, worker_id, db_session))
        return {"status": "completed"}

    monkeypatch.setattr(worker, "handle_index", fake_handle, raising=False)

    result = worker.dispatch_typed_job(handler_db, job.id, "worker-1")

    assert result == {"status": "completed"}
    assert called == [(job.id, "worker-1", handler_db)]


def test_handle_index_publishes_generation_and_marks_file(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Index KB",
        active_index_generation=None,
    )
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-index",
        original_filename="doc.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        parsed_content_version=3,
    )
    handler_db.add(file_row)
    handler_db.add(
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="3",
            chunk_uid="parent-index",
            chunk_text="parent",
            chunk_type="parent",
        )
    )
    handler_db.add(
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="3",
            chunk_uid="child-index",
            chunk_text="child",
            chunk_type="child",
        )
    )
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-1",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "index-generation")

    class FakePublisher:
        calls = []

        def build(self, kb_uid, generation, *, expected_old):
            self.calls.append((kb_uid, generation, expected_old))
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 1, "error": None})()

    fake = FakePublisher()
    result = handlers.handle_index(job.id, "w1", handler_db, jobs, publisher_factory=lambda db: fake)

    handler_db.refresh(file_row)
    handler_db.refresh(topic)
    assert result == {"status": "completed", "generation": "index-generation", "row_count": 1}
    assert fake.calls == [(topic.kb_uid, "index-generation", None)]
    assert file_row.index_status == StageStatus.SUCCEEDED.value
    assert file_row.active_index_generation == "index-generation"
    assert topic.active_index_generation == "index-generation"
    assert handler_db.get(type(job), job.id).status == "succeeded"


def test_handle_index_builds_scoped_graph_generation_and_outbox(handler_db, monkeypatch):
    from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt, KnowledgeEntity
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Graph KB",
        active_index_generation=None,
        active_graph_generation=None,
    )
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-graph",
        original_filename="graph.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=3,
    )
    handler_db.add(file_row)
    handler_db.add(
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="3",
            chunk_uid="child-graph",
            chunk_text="Paper: Graph Systems\nAlice Smith\nExample University",
            chunk_type="child",
        )
    )
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-graph",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "index-generation")

    class FakePublisher:
        def build(self, kb_uid, generation, *, expected_old):
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 1, "error": None})()

    result = handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: FakePublisher(),
    )

    handler_db.refresh(file_row)
    handler_db.refresh(topic)
    assert result["status"] == "completed"
    assert topic.active_graph_generation == "index-generation"
    assert file_row.graph_status == StageStatus.SUCCEEDED.value
    assert handler_db.query(KnowledgeEntity).filter_by(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation="index-generation",
    ).count() > 0
    event_count = handler_db.query(GraphOutboxEvent).filter_by(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation="index-generation",
    ).count()
    assert event_count > 0
    assert handler_db.query(GraphProjectionReceipt).count() == event_count * 2


def test_handle_index_does_not_poison_graph_errors_when_job_finalization_loses_lease(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    from backend.app.services.knowledge_jobs import InvalidJobTransition
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Finalization Race KB",
        active_index_generation=None,
        active_graph_generation=None,
    )
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-finalization-race",
        original_filename="race.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    handler_db.add(file_row)
    handler_db.add(
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="1",
            chunk_uid="child-finalization-race",
            chunk_text="Alice studies graph retrieval at Example University.",
            chunk_type="child",
        )
    )
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-finalization-race",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "race-generation")

    class FakePublisher:
        def build(self, kb_uid, generation, *, expected_old):
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 1, "error": None})()

    original_succeed = jobs.succeed

    def fail_succeed(*args, **kwargs):
        original_succeed(*args, **kwargs)
        raise InvalidJobTransition("Cannot update job after side effects committed")

    monkeypatch.setattr(jobs, "succeed", fail_succeed)

    result = handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: FakePublisher(),
    )

    handler_db.refresh(file_row)
    assert result["status"] == "completed"
    assert file_row.index_status == StageStatus.SUCCEEDED.value
    assert file_row.index_error is None
    assert file_row.graph_status == StageStatus.SUCCEEDED.value
    assert file_row.graph_error is None


def test_handle_graph_updates_only_requested_file_in_active_generation(handler_db, monkeypatch):
    from backend.app.models import GraphOutboxEvent, KnowledgeEntity
    from backend.app.models.knowledge_types import StageStatus
    import backend.app.services.graph_client as graph_client_module
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Per File Graph KB",
        active_index_generation="index-generation",
        active_graph_generation="global-graph",
    )
    handler_db.add(topic)
    handler_db.flush()
    item_a = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="A", content="a")
    item_b = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="B", content="b")
    handler_db.add_all([item_a, item_b])
    handler_db.flush()
    file_a = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-a",
        original_filename="a.md",
        item_id=item_a.id,
        parse_status=StageStatus.SUCCEEDED.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    file_b = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-b",
        original_filename="b.md",
        item_id=item_b.id,
        parse_status=StageStatus.SUCCEEDED.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    handler_db.add_all([file_a, file_b])
    handler_db.add_all([
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_a.file_uid,
            item_id=item_a.id,
            generation="1",
            chunk_uid="child-a",
            chunk_text="Paper: Graph Systems\nAlice Smith\nExample University",
            chunk_type="child",
        ),
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_b.file_uid,
            item_id=item_b.id,
            generation="1",
            chunk_uid="child-b",
            chunk_text="Paper: Other Systems\nBob Smith\nOther University",
            chunk_type="child",
        ),
    ])
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("graph", "t1", topic.kb_uid, file_a.file_uid, {}),
        "handle-graph-file-a",
    )

    deleted_sources = []

    class FakeGraphClient:
        def delete_item_sources_generation(self, tenant_id, kb_uid, graph_generation, item_id):
            deleted_sources.append((tenant_id, kb_uid, graph_generation, item_id))

        def close(self):
            pass

    monkeypatch.setattr(graph_client_module, "GraphClient", FakeGraphClient)

    result = handlers.handle_graph(job.id, "w1", handler_db, jobs)

    handler_db.refresh(file_a)
    handler_db.refresh(file_b)
    handler_db.refresh(topic)
    assert result["status"] == "completed"
    assert result["generation"] == "global-graph"
    assert result["file_uid"] == file_a.file_uid
    assert file_a.graph_status == StageStatus.SUCCEEDED.value
    assert file_b.graph_status == StageStatus.PENDING.value
    assert topic.active_graph_generation == "global-graph"
    assert deleted_sources == [("t1", topic.kb_uid, "global-graph", item_a.id)]
    assert handler_db.query(KnowledgeEntity).filter_by(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        graph_generation="global-graph",
    ).count() > 0
    assert {
        payload.get("file_uid")
        for (payload,) in handler_db.query(GraphOutboxEvent.payload)
        .filter_by(kb_uid=topic.kb_uid, graph_generation="global-graph")
        .all()
    } == {"file-a"}


def test_handle_index_uses_kb_index_generation_not_file_content_version(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Index KB")
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-index-generation",
        original_filename="doc.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    handler_db.add(file_row)
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-generation",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "kb-index-generation")

    class FakePublisher:
        def __init__(self):
            self.calls = []

        def build(self, kb_uid, generation, *, expected_old):
            self.calls.append((kb_uid, generation, expected_old))
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 1, "error": None})()

    fake = FakePublisher()
    result = handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: fake,
    )

    handler_db.refresh(file_row)
    assert result["generation"] == "kb-index-generation"
    assert fake.calls == [(topic.kb_uid, "kb-index-generation", None)]
    assert file_row.active_index_generation == "kb-index-generation"


def test_handle_index_marks_all_parsed_files_in_published_kb_snapshot(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Index KB")
    handler_db.add(topic)
    handler_db.flush()
    item_a = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="A", content="a")
    item_b = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="B", content="b")
    handler_db.add_all([item_a, item_b])
    handler_db.flush()
    file_a = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-a",
        original_filename="a.pdf",
        item_id=item_a.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    file_b = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-b",
        original_filename="b.pdf",
        item_id=item_b.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.FAILED.value,
        index_error={"code": "INDEX_ERROR", "message": "old failure"},
        parsed_content_version=1,
    )
    handler_db.add_all([file_a, file_b])
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_a.file_uid, {}),
        "handle-index-kb-snapshot",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "kb-index-generation")

    class FakePublisher:
        def build(self, kb_uid, generation, *, expected_old):
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 2, "error": None})()

    handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: FakePublisher(),
    )

    handler_db.refresh(file_a)
    handler_db.refresh(file_b)
    assert file_a.index_status == StageStatus.SUCCEEDED.value
    assert file_b.index_status == StageStatus.SUCCEEDED.value
    assert file_a.active_index_generation == "kb-index-generation"
    assert file_b.active_index_generation == "kb-index-generation"
    assert file_b.index_error is None


def test_handle_index_reads_expected_generation_by_kb_uid_when_file_topic_id_is_missing(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Legacy File KB",
        active_index_generation="already-active",
    )
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-without-topic-id",
        topic_id=None,
        original_filename="doc.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    handler_db.add(file_row)
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-missing-topic-id",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "next-generation")

    class FakePublisher:
        def __init__(self):
            self.calls = []

        def build(self, kb_uid, generation, *, expected_old):
            self.calls.append((kb_uid, generation, expected_old))
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 1, "error": None})()

    fake = FakePublisher()
    handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: fake,
    )

    assert fake.calls == [(topic.kb_uid, "next-generation", "already-active")]


def test_handle_index_records_file_error_when_publish_fails(handler_db, caplog):
    from backend.app.models.knowledge_types import StageStatus
    from engine.app.jobs.knowledge_handlers import handle_index

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Index failure KB")
    handler_db.add(topic)
    handler_db.flush()
    item = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="Doc", content="body")
    handler_db.add(item)
    handler_db.flush()
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-index-fails",
        original_filename="doc.md",
        item_id=item.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        parsed_content_version=3,
    )
    handler_db.add(file_row)
    handler_db.add(
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="3",
            chunk_uid="child-index-fails",
            chunk_text="child",
            chunk_type="child",
        )
    )
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_row.file_uid, {}),
        "handle-index-fails",
    )

    class FailingPublisher:
        def build(self, kb_uid, generation, *, expected_old):
            return type("Result", (), {
                "status": "failed",
                "row_count": 0,
                "error": "Milvus flush deadline exceeded",
            })()

    result = handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: FailingPublisher(),
    )

    handler_db.refresh(file_row)
    assert result["status"] == "failed"
    assert file_row.index_status == StageStatus.FAILED.value
    assert file_row.index_error == {
        "code": "INDEX_ERROR",
        "message": "Milvus flush deadline exceeded",
    }
    assert "knowledge index job failed" in caplog.text
    assert job.id in caplog.text
    assert file_row.file_uid in caplog.text
    assert topic.kb_uid in caplog.text
    assert "Milvus flush deadline exceeded" in caplog.text


def test_handle_index_marks_graph_stage_failed_when_graph_activation_fails(handler_db, monkeypatch):
    from backend.app.models.knowledge_types import StageStatus
    import engine.app.jobs.knowledge_handlers as handlers

    topic = KnowledgeTopic(
        tenant_id="t1",
        owner_user_id="u1",
        name="Graph Activation Failure KB",
        active_index_generation=None,
        active_graph_generation=None,
    )
    handler_db.add(topic)
    handler_db.flush()
    item_a = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="A", content="a")
    item_b = KnowledgeItem(tenant_id="t1", kb_uid=topic.kb_uid, title="B", content="b")
    handler_db.add_all([item_a, item_b])
    handler_db.flush()
    file_a = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-graph-a",
        original_filename="a.md",
        item_id=item_a.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    file_b = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-graph-b",
        original_filename="b.md",
        item_id=item_b.id,
        parse_status=StageStatus.SUCCEEDED.value,
        index_status=StageStatus.PENDING.value,
        graph_status=StageStatus.PENDING.value,
        parsed_content_version=1,
    )
    handler_db.add_all([file_a, file_b])
    handler_db.add_all([
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_a.file_uid,
            item_id=item_a.id,
            generation="1",
            chunk_uid="child-graph-a",
            chunk_text="Alpha Graph",
            chunk_type="child",
        ),
        KnowledgeChunk(
            tenant_id="t1",
            kb_uid=topic.kb_uid,
            file_uid=file_b.file_uid,
            item_id=item_b.id,
            generation="1",
            chunk_uid="child-graph-b",
            chunk_text="Beta Graph",
            chunk_type="child",
        ),
    ])
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("index", "t1", topic.kb_uid, file_a.file_uid, {}),
        "handle-index-graph-activation-fails",
    )
    monkeypatch.setattr(handlers, "_new_index_generation", lambda: "graph-failure-generation")

    class FakePublisher:
        def build(self, kb_uid, generation, *, expected_old):
            topic.active_index_generation = generation
            handler_db.flush()
            return type("Result", (), {"status": "succeeded", "row_count": 2, "error": None})()

    monkeypatch.setattr(
        handlers,
        "activate_graph_generation",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("graph activation blocked")),
    )

    result = handlers.handle_index(
        job.id,
        "w1",
        handler_db,
        jobs,
        publisher_factory=lambda db: FakePublisher(),
    )

    handler_db.refresh(file_a)
    handler_db.refresh(file_b)
    handler_db.refresh(topic)
    assert result["status"] == "failed"
    assert topic.active_graph_generation is None
    assert file_a.index_status == StageStatus.FAILED.value
    assert file_a.graph_status == StageStatus.FAILED.value
    assert file_b.graph_status == StageStatus.FAILED.value
    assert file_a.graph_error == {
        "code": "GRAPH_ERROR",
        "message": "graph activation blocked",
    }
    assert file_b.graph_error == {
        "code": "GRAPH_ERROR",
        "message": "graph activation blocked",
    }


def test_parse_auto_index_creates_and_publishes_index_job(handler_db, tmp_path, monkeypatch):
    from engine.app.jobs import knowledge_handlers
    from engine.app.jobs.knowledge_handlers import handle_parse

    root = tmp_path / "storage"
    path = root / "t1" / "kb-a" / "file-auto" / "auto.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Auto index", encoding="utf-8")
    monkeypatch.setattr(knowledge_handlers.settings, "KNOWLEDGE_STORAGE_ROOT", str(root))
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


def test_parse_honors_cancel_request_before_parsing(handler_db, tmp_path, monkeypatch):
    from engine.app.jobs import knowledge_handlers
    from engine.app.jobs.knowledge_handlers import handle_parse

    root = tmp_path / "storage"
    path = root / "t1" / "kb-a" / "file-cancel" / "cancel.md"
    path.parent.mkdir(parents=True)
    path.write_text("cancel me", encoding="utf-8")
    monkeypatch.setattr(knowledge_handlers.settings, "KNOWLEDGE_STORAGE_ROOT", str(root))
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


def test_delete_handler_completes_checkpointed_cleanup(handler_db):
    from backend.app.models import KnowledgeJob
    from backend.app.services.knowledge_cleanup import CleanupResult
    from engine.app.jobs.knowledge_handlers import handle_delete

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Delete KB")
    handler_db.add(topic)
    handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(
        JobCommand("delete", "t1", topic.kb_uid, "file-delete", {}),
        "delete-handler",
    )

    class FakeCleanup:
        def run(self, file_uid, *, job_id):
            assert file_uid == "file-delete"
            assert job_id == job.id
            return CleanupResult("succeeded", "rows_deleted")

    result = handle_delete(job.id, "worker-1", handler_db, jobs, FakeCleanup())

    assert result == {"status": "completed", "checkpoint": "rows_deleted"}
    assert handler_db.get(KnowledgeJob, job.id).status == "succeeded"


def test_delete_handler_closes_cleanup_on_success(handler_db):
    from backend.app.services.knowledge_cleanup import CleanupResult
    from engine.app.jobs.knowledge_handlers import handle_delete
    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Close cleanup")
    handler_db.add(topic); handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(JobCommand("delete", "t1", topic.kb_uid, "f1", {}), "close-cleanup")
    class Cleanup:
        closed = False
        def run(self, file_uid, *, job_id): return CleanupResult("succeeded", "rows_deleted")
        def close(self): self.closed = True
    cleanup = Cleanup()
    handle_delete(job.id, "w1", handler_db, jobs, cleanup)
    assert cleanup.closed is True


def test_delete_handler_closes_cleanup_on_failure(handler_db):
    from engine.app.jobs.knowledge_handlers import handle_delete
    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Close failed cleanup")
    handler_db.add(topic); handler_db.commit()
    jobs = KnowledgeJobService(handler_db)
    job = jobs.create(JobCommand("delete", "t1", topic.kb_uid, "f2", {}), "close-failed-cleanup")
    class Cleanup:
        closed = False
        def run(self, file_uid, *, job_id): raise RuntimeError("down")
        def close(self): self.closed = True
    cleanup = Cleanup()
    assert handle_delete(job.id, "w1", handler_db, jobs, cleanup)["status"] == "failed"
    assert cleanup.closed is True


def test_delete_handler_closes_cleanup_when_claim_is_skipped(handler_db):
    from engine.app.jobs.knowledge_handlers import handle_delete
    class Jobs:
        def claim(self, *args): return None
    class Cleanup:
        closed = False
        def close(self): self.closed = True
    cleanup = Cleanup()
    assert handle_delete("missing", "w1", handler_db, Jobs(), cleanup) == {"status": "skipped"}
    assert cleanup.closed is True


def test_worker_dispatches_delete_job_to_cleanup_handler(handler_db, monkeypatch):
    from engine.app.jobs import worker

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Delete dispatch")
    handler_db.add(topic)
    handler_db.commit()
    job = KnowledgeJobService(handler_db).create(
        JobCommand("delete", "t1", topic.kb_uid, "file-delete", {}),
        "delete-dispatch",
    )
    cleanup = object()
    called = []
    monkeypatch.setattr(worker, "_build_cleanup_service", lambda db, received: cleanup)
    monkeypatch.setattr(
        worker,
        "handle_delete",
        lambda job_id, worker_id, db, jobs, received_cleanup: called.append(
            (job_id, worker_id, received_cleanup)
        ) or {"status": "completed"},
    )

    result = worker.dispatch_typed_job(handler_db, job.id, "worker-1")

    assert result == {"status": "completed"}
    assert called == [(job.id, "worker-1", cleanup)]
