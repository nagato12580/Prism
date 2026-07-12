# prism/backend/tests/test_models.py
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import mysql

from backend.app.database import Base
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic, KnowledgeChunk, ChatSession, ChatMessage
from backend.app.utils import auto_migrate as auto_migrate_module


def test_create_knowledge_item_with_chunk(db_session):
    item = KnowledgeItem(title="测试条目", content="内容", source_type="manual", tags=["test"])
    db_session.add(item)
    db_session.commit()

    chunk = KnowledgeChunk(item_id=item.id, chunk_text="分块文本", chunk_index=0)
    db_session.add(chunk)
    db_session.commit()

    loaded = db_session.query(KnowledgeItem).first()
    assert loaded.title == "测试条目"
    assert loaded.tags == ["test"]
    assert len(loaded.chunks) == 1
    assert loaded.chunks[0].chunk_text == "分块文本"


def test_chat_session_message_cascade(db_session):
    session = ChatSession(title="测试会话")
    db_session.add(session)
    db_session.commit()

    msg = ChatMessage(session_id=session.id, role="user", content="你好")
    db_session.add(msg)
    db_session.commit()

    loaded = db_session.query(ChatSession).first()
    assert loaded.title == "测试会话"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].role == "user"


def test_topic_resource_relationship_and_metadata(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Product Docs", description="Launch files")
    db_session.add(topic)
    db_session.commit()

    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="Roadmap",
        original_filename="roadmap.md",
        media_type="document",
        mime_type="text/markdown",
        file_ext=".md",
        file_size=18,
        md5="md5-roadmap",
        storage_path="uploads/default-user/topic/roadmap.md",
        processing_status="completed",
        description="Q3 notes",
        tags=["roadmap", "q3"],
        source_type="upload",
        page_count=1,
        content_text="# Roadmap",
    )
    db_session.add(resource)
    db_session.commit()

    loaded = db_session.query(KnowledgeTopic).filter_by(name="Product Docs").one()
    assert loaded.resources[0].title == "Roadmap"
    assert loaded.resources[0].tags == ["roadmap", "q3"]
    assert loaded.resources[0].uploaded_at is not None


def test_duplicate_resource_md5_is_rejected_per_user_topic(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Research")
    db_session.add(topic)
    db_session.commit()

    first = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A",
        original_filename="a.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a.txt",
        processing_status="completed",
    )
    second = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A Copy",
        original_filename="a-copy.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a-copy.txt",
        processing_status="completed",
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_knowledge_file_legacy_attrs_map_to_new_attrs(db_session):
    resource = KnowledgeFile(
        title="Legacy Upload",
        original_name="legacy.txt",
        file_path="uploads/legacy.txt",
        file_type=".txt",
        file_size=6,
        md5="legacy-md5",
        parse_status="completed",
    )
    db_session.add(resource)
    db_session.commit()

    loaded = db_session.query(KnowledgeFile).filter_by(md5="legacy-md5").one()
    assert loaded.original_filename == "legacy.txt"
    assert loaded.storage_path == "uploads/legacy.txt"
    assert loaded.file_ext == ".txt"
    assert loaded.processing_status == "completed"
    assert loaded.original_name == "legacy.txt"
    assert loaded.file_path == "uploads/legacy.txt"
    assert loaded.file_type == ".txt"
    assert loaded.parse_status == "completed"


def test_knowledge_file_done_status_normalizes_to_completed(db_session):
    legacy_status = KnowledgeFile(
        title="Legacy Done",
        original_filename="legacy-done.txt",
        file_ext=".txt",
        md5="legacy-done-md5",
        storage_path="uploads/legacy-done.txt",
        parse_status="done",
    )
    new_status = KnowledgeFile(
        title="New Done",
        original_filename="new-done.txt",
        file_ext=".txt",
        md5="new-done-md5",
        storage_path="uploads/new-done.txt",
        processing_status="done",
    )
    pending = KnowledgeFile(
        title="Pending",
        original_filename="pending.txt",
        file_ext=".txt",
        md5="pending-md5",
        storage_path="uploads/pending.txt",
        processing_status="pending",
    )
    db_session.add_all([legacy_status, new_status, pending])
    db_session.commit()

    loaded = {item.md5: item for item in db_session.query(KnowledgeFile).all()}
    assert loaded["legacy-done-md5"].processing_status == "done"
    assert loaded["legacy-done-md5"].parse_status == "done"
    assert loaded["new-done-md5"].processing_status == "done"
    assert loaded["new-done-md5"].parse_status == "done"
    assert loaded["pending-md5"].processing_status == "pending"


def test_knowledge_file_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeFile.__table__.constraints}
    assert "uq_knowledge_file_user_topic_md5" in constraints


def test_knowledge_topic_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeTopic.__table__.constraints}
    assert "uq_knowledge_topic_user_name" in constraints


def test_document_content_columns_use_mysql_mediumtext():
    assert KnowledgeItem.__table__.columns["content"].type.compile(dialect=mysql.dialect()).lower() == "mediumtext"
    assert KnowledgeFile.__table__.columns["content_text"].type.compile(dialect=mysql.dialect()).lower() == "mediumtext"


def test_auto_migrate_adds_missing_topic_resource_unique_constraints(monkeypatch):
    executed_sql = []

    class FakeInspector:
        def get_table_names(self):
            return list(Base.metadata.tables)

        def get_columns(self, table_name):
            table = Base.metadata.tables[table_name]
            return [{"name": column.name} for column in table.columns]

        def get_unique_constraints(self, table_name):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            executed_sql.append(str(statement))

        def commit(self):
            pass

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(auto_migrate_module, "inspect", lambda engine: FakeInspector())

    auto_migrate_module.auto_migrate(Base, FakeEngine())

    assert any("ADD CONSTRAINT `uq_knowledge_topic_user_name`" in sql for sql in executed_sql)
    assert any("ADD CONSTRAINT `uq_knowledge_file_user_topic_md5`" in sql for sql in executed_sql)


def test_auto_migrate_adds_missing_columns_without_string_compile_error(monkeypatch):
    executed_sql = []

    class FakeInspector:
        def get_table_names(self):
            return list(Base.metadata.tables)

        def get_columns(self, table_name):
            table = Base.metadata.tables[table_name]
            if table_name == "knowledge_topic":
                return [{"name": "id"}]
            return [{"name": column.name} for column in table.columns]

        def get_unique_constraints(self, table_name):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            executed_sql.append(str(statement))

        def commit(self):
            pass

    class FakeEngine:
        def connect(self):
            return FakeConnection()

    from sqlalchemy.dialects import mysql

    FakeEngine.dialect = mysql.dialect()
    monkeypatch.setattr(auto_migrate_module, "inspect", lambda engine: FakeInspector())

    auto_migrate_module.auto_migrate(Base, FakeEngine())

    assert any("ADD COLUMN `name`" in sql for sql in executed_sql)


def test_auto_migrate_does_not_add_default_to_text_columns():
    from backend.app.models.knowledge_item import KnowledgeFile
    description_column = KnowledgeFile.__table__.columns["description"]

    assert auto_migrate_module._infer_default(description_column) == ""


def test_auto_migrate_upgrades_existing_text_columns_to_mediumtext(monkeypatch):
    executed_sql = []

    class FakeInspector:
        def get_table_names(self):
            return list(Base.metadata.tables)

        def get_columns(self, table_name):
            table = Base.metadata.tables[table_name]
            rows = [{"name": column.name, "type": column.type} for column in table.columns]
            if table_name == "knowledge_item":
                for row in rows:
                    if row["name"] == "content":
                        row["type"] = mysql.TEXT()
            if table_name == "knowledge_file":
                for row in rows:
                    if row["name"] == "content_text":
                        row["type"] = mysql.TEXT()
            return rows

        def get_unique_constraints(self, table_name):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            executed_sql.append(str(statement))

        def commit(self):
            pass

    class FakeEngine:
        dialect = mysql.dialect()

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(auto_migrate_module, "inspect", lambda engine: FakeInspector())

    auto_migrate_module.auto_migrate(Base, FakeEngine())

    assert any("MODIFY COLUMN `content` MEDIUMTEXT" in sql for sql in executed_sql)
    assert any("MODIFY COLUMN `content_text` MEDIUMTEXT" in sql for sql in executed_sql)


def test_knowledge_job_and_resource_governance_fields(db_session):
    from backend.app.models import KnowledgeFile, KnowledgeJob, KnowledgeTopic

    topic = KnowledgeTopic(user_id="default-user", name="Queue")
    db_session.add(topic)
    db_session.flush()

    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="Paper",
        original_filename="paper.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=123,
        md5="abc123",
        storage_path="/tmp/paper.pdf",
        processing_status="queued",
        governance_status="queued",
        governance_progress_current=1,
        governance_progress_total=10,
    )
    db_session.add(resource)
    db_session.flush()

    job = KnowledgeJob(
        job_type="ingest",
        resource_id=resource.id,
        item_id="item-1",
        topic_id=topic.id,
        status="queued",
        progress_current=0,
        progress_total=10,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.commit()

    loaded = db_session.query(KnowledgeJob).filter_by(resource_id=resource.id).one()
    assert loaded.status == "queued"
    assert loaded.max_attempts == 3
    assert loaded.resource_id == resource.id

    loaded_resource = db_session.query(KnowledgeFile).filter_by(id=resource.id).one()
    assert loaded_resource.governance_status == "queued"
    assert loaded_resource.governance_progress_current == 1
    assert loaded_resource.governance_progress_total == 10
