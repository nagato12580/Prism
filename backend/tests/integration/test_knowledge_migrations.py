import os
import subprocess
import sys
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
    database_url = os.getenv("MYSQL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("MYSQL_TEST_DATABASE_URL is not configured")
    url = make_url(database_url)
    if url.get_backend_name() != "mysql":
        pytest.skip("MYSQL_TEST_DATABASE_URL must use MySQL")
    if not url.database or "test" not in url.database.lower():
        pytest.skip("MYSQL_TEST_DATABASE_URL must name a dedicated test database")
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

        _run_alembic("downgrade", "base")
        assert KNOWLEDGE_TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        _reset_database(engine)
        engine.dispose()


def test_legacy_mysql_upgrade_backfills_topic_identity_and_preserves_legacy_shape():
    database_url = _mysql_test_url()
    engine = create_engine(database_url)
    try:
        _reset_database(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE knowledge_topic ("
                    "id CHAR(36) NOT NULL PRIMARY KEY, "
                    "user_id CHAR(36) NOT NULL, "
                    "name VARCHAR(255) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_topic (id, user_id, name) "
                    "VALUES ('legacy-topic', 'legacy-user', 'Legacy')"
                )
            )

        _run_alembic("upgrade", "head")
        _run_alembic("upgrade", "head")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT kb_uid, tenant_id, owner_user_id, active_index_generation "
                    "FROM knowledge_topic WHERE id = 'legacy-topic'"
                )
            ).mappings().one()
        assert row["kb_uid"]
        assert row["tenant_id"] == "legacy-user"
        assert row["owner_user_id"] == "legacy-user"
        assert row["active_index_generation"] == 0

        topic_columns = {column["name"]: column for column in inspect(engine).get_columns("knowledge_topic")}
        assert topic_columns["kb_uid"]["nullable"] is False
        assert topic_columns["tenant_id"]["nullable"] is False
        assert topic_columns["owner_user_id"]["nullable"] is False
        assert "user_id" in topic_columns

        _run_alembic("downgrade", "base")
        assert {column["name"] for column in inspect(engine).get_columns("knowledge_topic")} == {
            "id",
            "user_id",
            "name",
        }
        assert "knowledge_topic" in inspect(engine).get_table_names()
    finally:
        _reset_database(engine)
        engine.dispose()
