# backend/tests/integration/conftest.py
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.app.database import Base
from backend.app.models import *  # noqa


def _get_mysql_url():
    for key in ("PRISM_TEST_DATABASE_URL", "MYSQL_TEST_DATABASE_URL"):
        url = os.environ.get(key)
        if url:
            if "mysql" in url or "mariadb" in url:
                return url
    return None


@pytest.fixture(scope="session")
def mysql_engine():
    url = _get_mysql_url()
    if not url:
        pytest.skip("No MySQL test database URL configured")
    engine = create_engine(url, pool_size=2, max_overflow=2)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def mysql_session(mysql_engine):
    _truncate_knowledge_tables(mysql_engine)
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def mysql_session_1(mysql_engine):
    _truncate_knowledge_tables(mysql_engine)
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def mysql_session_2(mysql_engine):
    _truncate_knowledge_tables(mysql_engine)
    TestingSession = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    yield session
    session.close()


def _truncate_knowledge_tables(engine):
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        conn.execute(text("TRUNCATE TABLE knowledge_job"))
        conn.execute(text("TRUNCATE TABLE knowledge_chunk"))
        conn.execute(text("TRUNCATE TABLE knowledge_file"))
        conn.execute(text("TRUNCATE TABLE knowledge_item"))
        conn.execute(text("TRUNCATE TABLE knowledge_topic"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
