# backend/tests/integration/conftest.py
import os
import re
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.app.database import Base
from backend.app.models import *  # noqa

_REQUIRED_DB_NAME = "prism_test"


def _get_mysql_url():
    for key in ("PRISM_TEST_DATABASE_URL", "MYSQL_TEST_DATABASE_URL"):
        url = os.environ.get(key)
        if url:
            if any(proto in url for proto in ("mysql", "mariadb")):
                return url
    return None


def _resolve_db_name(url: str) -> str:
    match = re.search(r"/([^/?]+)(?:\?|$)", url.split("@")[-1] if "@" in url else url)
    if match:
        return match.group(1)
    return ""


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    url = _get_mysql_url()
    if url:
        db_name = _resolve_db_name(url)
        if db_name != _REQUIRED_DB_NAME:
            pytest.exit(
                f"Refusing to run MySQL integration tests: database name is "
                f"{db_name!r}, must be {_REQUIRED_DB_NAME!r}."
            )
        os.environ["DATABASE_URL"] = url
    else:
        config.option.markexpr = "not mysql"


@pytest.fixture(scope="session")
def mysql_engine():
    url = _get_mysql_url()
    if not url:
        pytest.skip("No MySQL test database URL configured")
    engine = create_engine(url, pool_size=2, max_overflow=2)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


TABLE_NAMES = [
    "evaluation_run_item",
    "evaluation_run",
    "evaluation_dataset_item",
    "evaluation_dataset",
    "knowledge_job",
    "knowledge_chunk",
    "knowledge_file",
    "knowledge_item",
    "knowledge_topic",
]


@pytest.fixture(autouse=True)
def _truncate_before_each_test(request):
    # Migration tests must start before ORM metadata can create any tables.
    if request.node.path.name == "test_knowledge_evaluation_mysql.py":
        yield
        return
    mysql_engine = request.getfixturevalue("mysql_engine")
    with mysql_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for name in TABLE_NAMES:
            conn.execute(text(f"TRUNCATE TABLE {name}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    yield


@pytest.fixture()
def mysql_session(mysql_engine):
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def mysql_session_1(mysql_engine):
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def mysql_session_2(mysql_engine):
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()
