# prism/backend/tests/test_models.py
import uuid

from sqlalchemy import CheckConstraint, Enum, String, inspect
from sqlalchemy.dialects import mysql

from backend.app.database import Base
from backend.app.models import (
    AgentTrace,
    AgentTraceStep,
    ChatMessage,
    ChatSession,
    JobStatus,
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeJob,
    KnowledgeTopic,
    ResourceStatus,
    StageStatus,
)
from backend.app.utils import auto_migrate as auto_migrate_module


TENANT_ID = "tenant-1"
OWNER_USER_ID = "owner-1"
KB_UID = "11111111-1111-4111-8111-111111111111"
FILE_UID = "22222222-2222-4222-8222-222222222222"


def test_create_knowledge_item_with_chunk(db_session):
    item = KnowledgeItem(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        title="测试条目",
        content="内容",
        source_type="manual",
        tags=["test"],
    )
    db_session.add(item)
    db_session.commit()

    chunk = KnowledgeChunk(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        file_uid=FILE_UID,
        item_id=item.id,
        generation="generation-1",
        chunk_text="分块文本",
        chunk_index=0,
    )
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
    topic = KnowledgeTopic(
        user_id="default-user",
        tenant_id=TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        name="Product Docs",
        description="Launch files",
    )
    db_session.add(topic)
    db_session.commit()

    resource = KnowledgeFile(
        user_id="default-user",
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        title="Roadmap",
        original_filename="roadmap.md",
        media_type="document",
        mime_type="text/markdown",
        file_ext=".md",
        file_size=18,
        md5="md5-roadmap",
        storage_path="uploads/default-user/topic/roadmap.md",
        processing_status="succeeded",
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


def test_knowledge_topic_system_flags(db_session):
    from backend.app.models import KnowledgeTopic

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="user-a",
        name="个人随手记",
        system_type="personal_inbox",
        is_system=True,
        delete_disabled=True,
    )
    db_session.add(topic)
    db_session.commit()

    saved = db_session.query(KnowledgeTopic).filter_by(kb_uid=topic.kb_uid).one()
    assert saved.system_type == "personal_inbox"
    assert saved.is_system is True
    assert saved.delete_disabled is True


def test_knowledge_file_source_markers(db_session):
    from backend.app.models import KnowledgeFile

    file_row = KnowledgeFile(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        file_uid="file-a",
        original_filename="unit.md",
        source_kind="personal_asset_unit",
        source_id="unit-a",
        system_type="personal_inbox",
    )
    db_session.add(file_row)
    db_session.commit()

    saved = db_session.query(KnowledgeFile).filter_by(file_uid="file-a").one()
    assert saved.source_kind == "personal_asset_unit"
    assert saved.source_id == "unit-a"
    assert saved.system_type == "personal_inbox"


def test_legacy_md5_does_not_replace_public_file_identity(db_session):
    topic = KnowledgeTopic(
        user_id="default-user",
        tenant_id=TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        name="Research",
    )
    db_session.add(topic)
    db_session.commit()

    first = KnowledgeFile(
        user_id="default-user",
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        title="A",
        original_filename="a.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a.txt",
        processing_status="succeeded",
    )
    second = KnowledgeFile(
        user_id="default-user",
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        title="A Copy",
        original_filename="a-copy.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a-copy.txt",
        processing_status="succeeded",
    )
    db_session.add_all([first, second])
    db_session.commit()

    assert first.md5 == second.md5 == "same-md5"
    assert first.file_uid != second.file_uid


def test_knowledge_file_legacy_attrs_map_to_new_attrs(db_session):
    resource = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        title="Legacy Upload",
        original_name="legacy.txt",
        file_path="uploads/legacy.txt",
        file_type=".txt",
        file_size=6,
        md5="legacy-md5",
        parse_status="succeeded",
    )
    db_session.add(resource)
    db_session.commit()

    loaded = db_session.query(KnowledgeFile).filter_by(md5="legacy-md5").one()
    assert loaded.original_filename == "legacy.txt"
    assert loaded.storage_path == "uploads/legacy.txt"
    assert loaded.file_ext == ".txt"
    assert loaded.processing_status == "succeeded"
    assert loaded.original_name == "legacy.txt"
    assert loaded.file_path == "uploads/legacy.txt"
    assert loaded.file_type == ".txt"
    assert loaded.parse_status == "succeeded"


def test_knowledge_file_stage_status_synonyms_use_approved_values(db_session):
    legacy_status = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        title="Legacy Succeeded",
        original_filename="legacy-succeeded.txt",
        file_ext=".txt",
        md5="legacy-succeeded-md5",
        storage_path="uploads/legacy-succeeded.txt",
        parse_status="succeeded",
    )
    new_status = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        title="New Running",
        original_filename="new-running.txt",
        file_ext=".txt",
        md5="new-running-md5",
        storage_path="uploads/new-running.txt",
        processing_status="running",
    )
    pending = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
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
    assert loaded["legacy-succeeded-md5"].processing_status == "succeeded"
    assert loaded["legacy-succeeded-md5"].parse_status == "succeeded"
    assert loaded["new-running-md5"].processing_status == "running"
    assert loaded["new-running-md5"].parse_status == "running"
    assert loaded["pending-md5"].processing_status == "pending"


def test_knowledge_file_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeFile.__table__.constraints}
    assert "uq_knowledge_file_file_uid" in constraints
    assert "uq_knowledge_file_user_topic_md5" not in constraints


def test_knowledge_topic_model_has_named_unique_constraint():
    constraints = {constraint.name for constraint in KnowledgeTopic.__table__.constraints}
    assert "uq_knowledge_topic_kb_uid" in constraints
    assert "uq_knowledge_topic_user_name" not in constraints


def test_document_content_columns_use_mysql_mediumtext():
    assert KnowledgeItem.__table__.columns["content"].type.compile(dialect=mysql.dialect()).lower() == "mediumtext"
    assert (
        KnowledgeItem.__table__.columns["normalized_markdown"].type.compile(dialect=mysql.dialect()).lower()
        == "mediumtext"
    )
    assert KnowledgeFile.__table__.columns["content_text"].type.compile(dialect=mysql.dialect()).lower() == "mediumtext"


def test_auto_migrate_does_not_restore_obsolete_legacy_unique_constraints(monkeypatch):
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
        dialect = mysql.dialect()

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(auto_migrate_module, "inspect", lambda engine: FakeInspector())

    auto_migrate_module.auto_migrate(Base, FakeEngine())

    assert not any("uq_knowledge_topic_user_name" in sql for sql in executed_sql)
    assert not any("uq_knowledge_file_user_topic_md5" in sql for sql in executed_sql)


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
    from backend.app.models import AgentTrace
    from backend.app.models.knowledge_item import KnowledgeFile

    description_column = KnowledgeFile.__table__.columns["description"]
    user_query_column = AgentTrace.__table__.columns["user_query"]

    assert auto_migrate_module._infer_default(description_column) == ""
    assert auto_migrate_module._infer_default(user_query_column) == ""


def test_auto_migrate_adds_missing_agent_trace_indexes(monkeypatch):
    executed_sql = []

    class FakeInspector:
        def get_table_names(self):
            return list(Base.metadata.tables)

        def get_columns(self, table_name):
            table = Base.metadata.tables[table_name]
            return [{"name": column.name, "type": column.type} for column in table.columns]

        def get_unique_constraints(self, table_name):
            return []

        def get_indexes(self, table_name):
            if table_name in {"agent_trace", "agent_trace_step"}:
                return []
            table = Base.metadata.tables[table_name]
            return [{"name": index.name} for index in table.indexes if index.name]

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

    expected_index_names = {
        "ix_agent_trace_resume_status",
        "ix_agent_trace_resume_status_started_at",
        "ix_agent_trace_step_dedupe_key",
        "ix_agent_trace_step_dedupe",
    }
    index_sql = [sql for sql in executed_sql if " ADD INDEX " in sql]
    for index_name in expected_index_names:
        assert any(f"ADD INDEX `{index_name}`" in sql for sql in index_sql)


def test_auto_migrate_reports_skipped_index_creation(monkeypatch, caplog, capsys):
    class FakeInspector:
        def get_table_names(self):
            return list(Base.metadata.tables)

        def get_columns(self, table_name):
            table = Base.metadata.tables[table_name]
            return [{"name": column.name, "type": column.type} for column in table.columns]

        def get_unique_constraints(self, table_name):
            return []

        def get_indexes(self, table_name):
            if table_name in {"agent_trace", "agent_trace_step"}:
                return []
            table = Base.metadata.tables[table_name]
            return [{"name": index.name} for index in table.indexes if index.name]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement):
            sql = str(statement)
            if " ADD INDEX " in sql:
                raise RuntimeError("index failed")

        def commit(self):
            pass

    class FakeEngine:
        dialect = mysql.dialect()

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(auto_migrate_module, "inspect", lambda engine: FakeInspector())

    caplog.set_level("WARNING", logger=auto_migrate_module.logger.name)
    auto_migrate_module.auto_migrate(Base, FakeEngine())

    output = capsys.readouterr().out
    assert "Skipped indexes:" in output
    assert "agent_trace.ix_agent_trace_resume_status" in output
    assert "agent_trace.ix_agent_trace_resume_status" in caplog.text
    assert "index failed" in caplog.text


def test_auto_migrate_uses_explicit_string_default_for_resume_status():
    resume_status_column = AgentTrace.__table__.columns["resume_status"]
    generic_string_column = AgentTraceStep.__table__.columns["tool_name"]

    assert auto_migrate_module._infer_default(resume_status_column) == " DEFAULT 'none'"
    assert auto_migrate_module._infer_default(generic_string_column) == " DEFAULT ''"


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
                    if row["name"] in {"content", "normalized_markdown"}:
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
    assert any("MODIFY COLUMN `normalized_markdown` MEDIUMTEXT" in sql for sql in executed_sql)
    assert any("MODIFY COLUMN `content_text` MEDIUMTEXT" in sql for sql in executed_sql)


def test_knowledge_job_and_resource_governance_fields(db_session):
    topic = KnowledgeTopic(
        user_id="default-user",
        tenant_id=TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        name="Queue",
    )
    db_session.add(topic)
    db_session.flush()

    resource = KnowledgeFile(
        user_id="default-user",
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        title="Paper",
        original_filename="paper.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=123,
        md5="abc123",
        storage_path="/tmp/paper.pdf",
        processing_status="pending",
        governance_status="queued",
        governance_progress_current=1,
        governance_progress_total=10,
    )
    db_session.add(resource)
    db_session.flush()

    job = KnowledgeJob(
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        file_uid=resource.file_uid,
        idempotency_key="ingest:paper",
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


def test_knowledge_topic_has_explicit_scope_and_public_uuid4(db_session):
    topic = KnowledgeTopic(
        tenant_id=TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        name="Scoped knowledge base",
    )
    db_session.add(topic)
    db_session.commit()

    assert uuid.UUID(topic.kb_uid).version == 4
    assert topic.status == ResourceStatus.ACTIVE
    assert topic.version == 1
    assert topic.active_index_generation is None
    assert topic.active_graph_generation is None


def test_file_item_and_chunk_use_public_scope_and_stage_defaults(db_session):
    topic = KnowledgeTopic(
        tenant_id=TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        name="Scoped files",
    )
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(tenant_id=TENANT_ID, kb_uid=topic.kb_uid, title="Document")
    db_session.add(item)
    db_session.flush()
    resource = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        item_id=item.id,
        storage_uri="knowledge/document.md",
        original_filename="document.md",
    )
    db_session.add(resource)
    db_session.flush()
    parent = KnowledgeChunk(
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        file_uid=resource.file_uid,
        item_id=item.id,
        generation="generation-1",
        chunk_text="Parent",
    )
    db_session.add(parent)
    db_session.flush()
    child = KnowledgeChunk(
        tenant_id=TENANT_ID,
        kb_uid=topic.kb_uid,
        file_uid=resource.file_uid,
        item_id=item.id,
        generation="generation-1",
        chunk_text="Child",
        parent_id=parent.id,
        parent_chunk_uid=parent.chunk_uid,
        page_number=2,
        char_start=10,
        char_end=20,
        token_start=3,
        token_end=7,
        title_path=["Section"],
    )
    db_session.add(child)
    db_session.commit()

    assert uuid.UUID(resource.file_uid).version == 4
    assert uuid.UUID(parent.chunk_uid).version == 4
    assert resource.tenant_id == item.tenant_id == TENANT_ID
    assert resource.kb_uid == item.kb_uid == child.kb_uid == topic.kb_uid
    assert resource.parse_status == StageStatus.PENDING
    assert resource.index_status == StageStatus.PENDING
    assert resource.graph_status == StageStatus.PENDING
    assert child.generation == "generation-1"
    assert child.parent_id == parent.id
    assert child.page_number == 2
    assert child.char_start == 10
    assert child.token_end == 7


def test_knowledge_job_supports_kb_wide_payload_and_defaults(db_session):
    job = KnowledgeJob(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        file_uid=None,
        idempotency_key="graph:kb-wide:1",
        payload={"generation": "generation-1"},
        result={"accepted": True},
    )
    db_session.add(job)
    db_session.commit()

    assert job.file_uid is None
    assert job.status == JobStatus.QUEUED
    assert job.attempt == 0
    assert job.attempts == 0
    assert job.payload == {"generation": "generation-1"}
    assert job.result == {"accepted": True}


def test_knowledge_foundation_metadata_and_database_contract(db_session):
    inspector = inspect(db_session.get_bind())
    metadata_contract = {
        "knowledge_topic": {
            "required": {"kb_uid", "tenant_id", "owner_user_id", "status", "version"},
            "unique": "uq_knowledge_topic_kb_uid",
        },
        "knowledge_file": {
            "required": {"file_uid", "kb_uid", "tenant_id", "parse_status", "index_status", "graph_status"},
            "unique": "uq_knowledge_file_file_uid",
        },
        "knowledge_chunk": {
            "required": {"chunk_uid", "tenant_id", "kb_uid", "file_uid", "generation"},
            "unique": "uq_knowledge_chunk_uid_generation",
        },
        "knowledge_job": {
            "required": {"tenant_id", "kb_uid", "idempotency_key", "status", "attempt", "attempts"},
            "unique": "uq_knowledge_job_idempotency_key",
        },
    }

    for table_name, contract in metadata_contract.items():
        table = Base.metadata.tables[table_name]
        assert all(not table.columns[name].nullable for name in contract["required"])
        assert contract["unique"] in {constraint.name for constraint in table.constraints}
        inspected_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert all(not inspected_columns[name]["nullable"] for name in contract["required"])
        assert contract["unique"] in {
            constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
        }

    parent_foreign_keys = list(KnowledgeChunk.__table__.columns["parent_id"].foreign_keys)
    assert len(parent_foreign_keys) == 1
    assert parent_foreign_keys[0].target_fullname == "knowledge_chunk.id"
    assert parent_foreign_keys[0].ondelete == "SET NULL"


def test_knowledge_status_enums_have_only_approved_values():
    assert {status.value for status in ResourceStatus} == {"active", "deleting"}
    assert {status.value for status in StageStatus} == {
        "pending",
        "running",
        "succeeded",
        "failed",
        "stale",
        "skipped",
    }
    assert {status.value for status in JobStatus} == {
        "queued",
        "claimed",
        "running",
        "succeeded",
        "failed",
        "canceled",
    }


def test_original_filename_uses_legacy_database_column_as_bidirectional_alias(db_session):
    legacy = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        original_name="legacy.md",
    )
    canonical = KnowledgeFile(
        tenant_id=TENANT_ID,
        kb_uid=KB_UID,
        original_filename="canonical.md",
    )
    db_session.add_all([legacy, canonical])
    db_session.commit()

    assert legacy.original_filename == legacy.original_name == "legacy.md"
    assert canonical.original_name == canonical.original_filename == "canonical.md"
    column_names = set(KnowledgeFile.__table__.columns.keys())
    assert "original_name" in column_names
    assert "original_filename" not in column_names


def test_legacy_user_id_columns_have_no_client_or_server_defaults():
    model_columns = [
        (KnowledgeTopic, "user_id"),
        (KnowledgeItem, "user_id"),
        (KnowledgeFile, "user_id"),
    ]
    for model, column_name in model_columns:
        column = model.__table__.columns[column_name]
        assert column.default is None, f"{model.__name__}.{column_name} has a Python/client default"
        assert column.server_default is None, f"{model.__name__}.{column_name} has a server default"
        assert column.nullable, f"{model.__name__}.{column_name} is not nullable"


def test_status_columns_use_plain_strings_without_database_check_constraints():
    status_columns = [
        KnowledgeTopic.__table__.columns["status"],
        KnowledgeFile.__table__.columns["parse_status"],
        KnowledgeFile.__table__.columns["index_status"],
        KnowledgeFile.__table__.columns["graph_status"],
        KnowledgeJob.__table__.columns["status"],
    ]

    assert all(isinstance(column.type, String) for column in status_columns)
    assert all(not isinstance(column.type, Enum) for column in status_columns)
    for table in {column.table for column in status_columns}:
        assert not any(isinstance(constraint, CheckConstraint) for constraint in table.constraints)
