import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = ROOT / "alembic.ini"
KNOWLEDGE_TABLES = {
    "knowledge_topic",
    "knowledge_file",
    "knowledge_item",
    "knowledge_chunk",
    "knowledge_job",
}
EXPECTED_COLUMNS = {
    "knowledge_topic": {
        "kb_uid", "tenant_id", "owner_user_id", "name", "description", "status", "deleted_at", "version",
        "embedding_profile", "parser_config", "chunk_config", "retrieval_config", "graph_config",
        "active_index_generation", "active_graph_generation", "mindmap", "mindmap_version",
        "mindmap_generated_at", "sample_questions", "sample_questions_version",
    },
    "knowledge_file": {
        "file_uid", "kb_uid", "tenant_id", "storage_uri", "relative_path", "original_filename", "media_type",
        "content_sha256", "size_bytes", "parser_config_snapshot", "chunk_config_snapshot", "parse_status",
        "index_status", "graph_status", "parsed_content_version", "active_index_generation", "parse_error",
        "index_error", "graph_error", "parse_started_at", "parse_finished_at", "index_started_at",
        "index_finished_at", "graph_started_at", "graph_finished_at", "last_job_id", "deleted_at", "md5",
    },
    "knowledge_item": {"tenant_id", "kb_uid", "normalized_markdown", "summary", "source_type", "content_version"},
    "knowledge_chunk": {
        "chunk_uid", "kb_uid", "file_uid", "generation", "parent_id", "parent_chunk_uid", "page_number",
        "char_start", "char_end", "token_start", "token_end", "title_path",
    },
    "knowledge_job": {
        "tenant_id", "kb_uid", "file_uid", "idempotency_key", "payload", "result", "lease_owner",
        "lease_expires_at", "heartbeat_at", "cancel_requested_at", "canceled_by", "attempt", "max_attempts",
        "next_run_at", "stage", "progress_current", "progress_total", "error_code", "error_message", "retryable",
        "status",
    },
}


def _mysql_test_url() -> str:
    __tracebackhide__ = True
    database_url = os.getenv("MYSQL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MYSQL_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        pytest.fail("MYSQL_TEST_DATABASE_URL must use MySQL")
    if url.database != "prism_test":
        pytest.fail("MYSQL_TEST_DATABASE_URL must name the dedicated prism_test database")
    return database_url


def _run_alembic(*arguments: str) -> None:
    __tracebackhide__ = True
    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "Alembic command failed; inspect captured output locally"


def _reset_database(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table_name in inspect(connection).get_table_names():
            connection.execute(text(f"DROP TABLE `{table_name}`"))
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def _assert_uuid4(value: str) -> None:
    parsed = uuid.UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


def _default_value(column: dict) -> str | None:
    default = column["default"]
    return default.strip("'") if isinstance(default, str) else default


def test_configured_migration_database_must_be_mysql(monkeypatch):
    monkeypatch.setenv("MYSQL_TEST_DATABASE_URL", "sqlite:///prism_test")
    with pytest.raises(pytest.fail.Exception, match="must use MySQL"):
        _mysql_test_url()


def test_configured_migration_database_must_be_exact_prism_test(monkeypatch):
    monkeypatch.setenv("MYSQL_TEST_DATABASE_URL", "mysql+pymysql://localhost/latest")
    with pytest.raises(pytest.fail.Exception, match="prism_test"):
        _mysql_test_url()


def test_alembic_configuration_points_to_backend_migrations():
    content = ALEMBIC_INI.read_text(encoding="utf-8")
    assert "script_location = backend/alembic" in content


def test_fresh_mysql_upgrade_creates_knowledge_schema_and_is_repeatable():
    database_url = _mysql_test_url()
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        _run_alembic("upgrade", "head")
        _run_alembic("upgrade", "head")

        inspector = inspect(engine)
        assert KNOWLEDGE_TABLES <= set(inspector.get_table_names())
        for table_name, expected in EXPECTED_COLUMNS.items():
            assert expected <= {column["name"] for column in inspector.get_columns(table_name)}
        topic_columns = {column["name"]: column for column in inspector.get_columns("knowledge_topic")}
        assert topic_columns["kb_uid"]["nullable"] is False
        assert topic_columns["tenant_id"]["nullable"] is False
        assert topic_columns["owner_user_id"]["nullable"] is False
        assert topic_columns["active_index_generation"]["nullable"] is False
        assert topic_columns["active_index_generation"]["type"].length == 36
        assert topic_columns["active_graph_generation"]["type"].length == 36
        file_columns = {column["name"]: column for column in inspector.get_columns("knowledge_file")}
        item_columns = {column["name"]: column for column in inspector.get_columns("knowledge_item")}
        chunk_columns = {column["name"]: column for column in inspector.get_columns("knowledge_chunk")}
        job_columns = {column["name"]: column for column in inspector.get_columns("knowledge_job")}
        for columns, names in [
            (topic_columns, ["kb_uid", "tenant_id", "owner_user_id"]),
            (file_columns, ["file_uid", "kb_uid", "tenant_id"]),
            (item_columns, ["kb_uid", "tenant_id"]),
            (chunk_columns, ["chunk_uid", "kb_uid", "file_uid"]),
            (job_columns, ["kb_uid", "tenant_id", "file_uid"]),
        ]:
            for name in names:
                assert columns[name]["type"].length == 36
                assert columns[name]["nullable"] is False
        assert file_columns["active_index_generation"]["type"].length == 36
        assert chunk_columns["generation"]["type"].length == 36
        assert _default_value(topic_columns["active_index_generation"]) == "0"
        assert _default_value(file_columns["active_index_generation"]) == "0"
        assert _default_value(item_columns["content_version"]) == "1"
        assert _default_value(chunk_columns["generation"]) == "0"
        assert _default_value(job_columns["status"]) == "queued"
        unique_names = {
            table_name: {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}
            for table_name in KNOWLEDGE_TABLES
        }
        assert "uq_knowledge_topic_kb_uid" in unique_names["knowledge_topic"]
        assert "uq_knowledge_file_file_uid" in unique_names["knowledge_file"]
        assert "uq_knowledge_chunk_uid_generation" in unique_names["knowledge_chunk"]
        assert "uq_knowledge_job_idempotency_key" in unique_names["knowledge_job"]

        _run_alembic("downgrade", "base")
        assert KNOWLEDGE_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        _reset_database(engine)
        engine.dispose()


def test_legacy_mysql_upgrade_backfills_all_scope_and_preserves_legacy_shape():
    database_url = _mysql_test_url()
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE knowledge_topic ("
                    "id CHAR(36) NOT NULL PRIMARY KEY, "
                    "user_id CHAR(36) NULL, "
                    "name VARCHAR(255) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_topic (id, user_id, name) "
                    "VALUES ('legacy-topic', NULL, 'Legacy')"
                )
            )
            connection.execute(text("CREATE TABLE knowledge_item (id CHAR(36) NOT NULL PRIMARY KEY, title VARCHAR(255) NOT NULL, user_id CHAR(36) NULL)"))
            connection.execute(text("INSERT INTO knowledge_item (id, title, user_id) VALUES ('legacy-item', 'Item', NULL)"))
            connection.execute(
                text(
                    "CREATE TABLE knowledge_file (id CHAR(36) NOT NULL PRIMARY KEY, user_id CHAR(36) NULL, "
                    "topic_id CHAR(36) NULL, item_id CHAR(36) NULL, md5 VARCHAR(32) NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_file (id, user_id, topic_id, item_id, md5) "
                    "VALUES ('legacy-file', NULL, 'legacy-topic', 'legacy-item', 'legacy-md5')"
                )
            )
            connection.execute(text("CREATE TABLE knowledge_chunk (id CHAR(36) NOT NULL PRIMARY KEY, item_id CHAR(36) NULL, chunk_text TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO knowledge_chunk (id, item_id, chunk_text) VALUES ('legacy-chunk', 'legacy-item', 'Text')"))
            connection.execute(
                text(
                    "CREATE TABLE knowledge_job (id CHAR(36) NOT NULL PRIMARY KEY, job_type VARCHAR(32) NOT NULL, "
                    "resource_id CHAR(36) NOT NULL, item_id CHAR(36) NULL, topic_id CHAR(36) NULL, attempts INT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_job (id, job_type, resource_id, item_id, topic_id, attempts) "
                    "VALUES ('legacy-job', 'ingest', 'legacy-file', 'legacy-item', 'legacy-topic', 0)"
                )
            )

        _run_alembic("upgrade", "head")
        _run_alembic("upgrade", "head")

        with engine.connect() as connection:
            topic = connection.execute(
                text(
                    "SELECT kb_uid, tenant_id, owner_user_id, active_index_generation "
                    "FROM knowledge_topic WHERE id = 'legacy-topic'"
                )
            ).mappings().one()
            file_row = connection.execute(text("SELECT file_uid, kb_uid, tenant_id FROM knowledge_file WHERE id = 'legacy-file'" )).mappings().one()
            item = connection.execute(text("SELECT kb_uid, tenant_id FROM knowledge_item WHERE id = 'legacy-item'" )).mappings().one()
            chunk = connection.execute(text("SELECT chunk_uid, kb_uid, file_uid, generation FROM knowledge_chunk WHERE id = 'legacy-chunk'" )).mappings().one()
            job = connection.execute(text("SELECT kb_uid, tenant_id, file_uid FROM knowledge_job WHERE id = 'legacy-job'" )).mappings().one()
        _assert_uuid4(topic["kb_uid"])
        _assert_uuid4(file_row["file_uid"])
        _assert_uuid4(chunk["chunk_uid"])
        assert topic["tenant_id"] == "default-user"
        assert topic["owner_user_id"] == "default-user"
        assert topic["active_index_generation"] == "0"
        assert file_row["kb_uid"] == topic["kb_uid"]
        assert file_row["tenant_id"] == "default-user"
        assert item == {"kb_uid": topic["kb_uid"], "tenant_id": "default-user"}
        assert chunk["kb_uid"] == topic["kb_uid"]
        assert chunk["file_uid"] == file_row["file_uid"]
        assert chunk["generation"] == "0"
        assert job == {"kb_uid": topic["kb_uid"], "tenant_id": "default-user", "file_uid": file_row["file_uid"]}

        topic_columns = {column["name"]: column for column in inspect(engine).get_columns("knowledge_topic")}
        assert topic_columns["kb_uid"]["nullable"] is False
        assert topic_columns["tenant_id"]["nullable"] is False
        assert topic_columns["owner_user_id"]["nullable"] is False
        assert "user_id" in topic_columns

        _run_alembic("downgrade", "base")
        expected_legacy_columns = {
            "knowledge_topic": {"id", "user_id", "name"},
            "knowledge_item": {"id", "title", "user_id"},
            "knowledge_file": {"id", "user_id", "topic_id", "item_id", "md5"},
            "knowledge_chunk": {"id", "item_id", "chunk_text"},
            "knowledge_job": {"id", "job_type", "resource_id", "item_id", "topic_id", "attempts"},
        }
        for table_name, columns in expected_legacy_columns.items():
            assert {column["name"] for column in inspect(engine).get_columns(table_name)} == columns
        with engine.connect() as connection:
            for table_name in KNOWLEDGE_TABLES:
                assert connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one() == 1
    finally:
        _reset_database(engine)
        engine.dispose()


def test_legacy_upgrade_fails_when_item_scope_cannot_be_derived():
    database_url = _mysql_test_url()
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE knowledge_item (id CHAR(36) NOT NULL PRIMARY KEY, title VARCHAR(255) NOT NULL, user_id CHAR(36) NULL)"))
            connection.execute(text("INSERT INTO knowledge_item (id, title, user_id) VALUES ('orphan-item', 'Orphan', NULL)"))

        env = os.environ.copy()
        env["DATABASE_URL"] = os.environ["MYSQL_TEST_DATABASE_URL"]
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Cannot migrate knowledge_item" in result.stderr
        assert "lack required scope fields" in result.stderr
    finally:
        _reset_database(engine)
        engine.dispose()


def test_partial_legacy_downgrade_preserves_preexisting_column_constraint_and_nullability():
    database_url = _mysql_test_url()
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE knowledge_topic (id CHAR(36) NOT NULL PRIMARY KEY, user_id CHAR(36) NULL, "
                    "name VARCHAR(255) NOT NULL, kb_uid CHAR(36) NULL, "
                    "CONSTRAINT uq_knowledge_topic_kb_uid UNIQUE (kb_uid))"
                )
            )
            connection.execute(
                text("INSERT INTO knowledge_topic (id, user_id, name, kb_uid) VALUES ('partial-topic', 'owner', 'Partial', NULL)")
            )

        _run_alembic("upgrade", "head")
        with engine.connect() as connection:
            migrated_uid = connection.execute(text("SELECT kb_uid FROM knowledge_topic WHERE id = 'partial-topic'")).scalar_one()
        _assert_uuid4(migrated_uid)

        _run_alembic("downgrade", "base")
        inspector = inspect(engine)
        topic_columns = {column["name"]: column for column in inspector.get_columns("knowledge_topic")}
        assert set(topic_columns) == {"id", "user_id", "name", "kb_uid"}
        assert topic_columns["kb_uid"]["nullable"] is True
        assert "uq_knowledge_topic_kb_uid" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("knowledge_topic")
        }
        with engine.connect() as connection:
            assert connection.execute(text("SELECT kb_uid FROM knowledge_topic WHERE id = 'partial-topic'")).scalar_one() == migrated_uid
    finally:
        _reset_database(engine)
        engine.dispose()
