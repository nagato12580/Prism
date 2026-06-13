# prism/backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import Base, get_db
from backend.app.models import *  # noqa: 确保所有模型注册到 Base.metadata


@pytest.fixture()
def db_session():
    """内存 SQLite 数据库，每个测试独立。"""
    _engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(_engine)
    TestingSession = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(_engine)
        _engine.dispose()


@pytest.fixture()
def client(db_session):
    """FastAPI 测试客户端，db 依赖注入替换为内存 session。"""
    import os
    prev_skip_engine = os.environ.get("SKIP_ENGINE")
    os.environ["SKIP_ENGINE"] = "1"
    try:
        from backend.app.main import create_app
        app = create_app()

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()
    finally:
        if prev_skip_engine is None:
            os.environ.pop("SKIP_ENGINE", None)
        else:
            os.environ["SKIP_ENGINE"] = prev_skip_engine
