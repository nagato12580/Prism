"""Real-MySQL verification for the evaluation Alembic revision."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url


pytestmark = pytest.mark.mysql
ROOT = Path(__file__).resolve().parents[3]


def _test_url() -> str:
    url = os.environ.get("MYSQL_TEST_DATABASE_URL") or os.environ.get("PRISM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("No dedicated MySQL test database URL configured")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "mysql"
    assert parsed.database == "prism_test"
    return url


def _alembic(env: dict[str, str], *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "Alembic command failed (credentials redacted)"


def test_evaluation_revision_creates_scoped_tables_on_real_mysql():
    url = _test_url()
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in inspect(connection).get_table_names():
                connection.execute(text(f"DROP TABLE `{table}`"))
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    _alembic(env, "upgrade", "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        expected = {"evaluation_dataset", "evaluation_dataset_item", "evaluation_run", "evaluation_run_item"}
        assert expected <= set(inspector.get_table_names())
        for table in expected:
            columns = {column["name"] for column in inspector.get_columns(table)}
            assert {"tenant_id", "kb_uid"} <= columns
        run_columns = {column["name"] for column in inspector.get_columns("evaluation_run")}
        assert {"request_idempotency_key", "request_fingerprint"} <= run_columns
        assert "uq_evaluation_run_request_key" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("evaluation_run")
        }
        def foreign_keys(table):
            return {
                (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                for fk in inspector.get_foreign_keys(table)
            }

        assert foreign_keys("evaluation_dataset") == {
            (("kb_uid",), "knowledge_topic", ("kb_uid",)),
        }
        assert all(
            fk.get("options", {}).get("ondelete", "").upper() in {"RESTRICT", "NO ACTION"}
            for table in ("evaluation_dataset", "evaluation_run")
            for fk in inspector.get_foreign_keys(table)
            if fk["referred_table"] == "knowledge_topic"
        )
        assert foreign_keys("evaluation_dataset_item") == {
            (("dataset_id", "tenant_id", "kb_uid"), "evaluation_dataset", ("id", "tenant_id", "kb_uid")),
        }
        assert foreign_keys("evaluation_run") == {
            (("kb_uid",), "knowledge_topic", ("kb_uid",)),
            (("dataset_id", "tenant_id", "kb_uid"), "evaluation_dataset", ("id", "tenant_id", "kb_uid")),
        }
        assert foreign_keys("evaluation_run_item") == {
            (("run_id", "tenant_id", "kb_uid"), "evaluation_run", ("id", "tenant_id", "kb_uid")),
            (("dataset_item_id", "tenant_id", "kb_uid"), "evaluation_dataset_item", ("id", "tenant_id", "kb_uid")),
        }
        assert {index["name"] for index in inspector.get_indexes("evaluation_run")} >= {
            "ix_evaluation_run_scope_created", "ix_evaluation_run_dataset"
        }
        assert "ix_evaluation_run_item_run_status" in {
            index["name"] for index in inspector.get_indexes("evaluation_run_item")
        }
        assert "uq_knowledge_topic_tenant_kb" not in {
            constraint["name"] for constraint in inspector.get_unique_constraints("knowledge_topic")
        }
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO knowledge_topic (id,kb_uid,tenant_id,owner_user_id,name,status,version) "
                "VALUES ('eval-topic','eval-kb','eval-tenant','owner','Evaluation','active',1)"
            ))
            connection.execute(text(
                "INSERT INTO evaluation_dataset "
                "(id,dataset_uid,tenant_id,kb_uid,name,created_by,source,created_at,updated_at) "
                "VALUES ('dataset','dataset-uid','eval-tenant','eval-kb','Gold','owner','generated',NOW(),NOW())"
            ))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM knowledge_topic WHERE kb_uid='eval-kb'"))
    finally:
        engine.dispose()
    _alembic(env, "downgrade", "20260722_01")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert not ({"evaluation_dataset", "evaluation_dataset_item", "evaluation_run", "evaluation_run_item"} & set(inspector.get_table_names()))
        assert "knowledge_topic" in inspector.get_table_names()
        assert "uq_knowledge_topic_tenant_kb" not in {
            constraint["name"] for constraint in inspector.get_unique_constraints("knowledge_topic")
        }
    finally:
        engine.dispose()
    _alembic(env, "upgrade", "head")
