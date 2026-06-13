# prism/backend/tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import Base, get_db
from backend.app.models import *  # noqa: 确保所有模型注册到 Base.metadata


@pytest.fixture()
def db_session():
    """内存 SQLite 数据库，每个测试独立。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    """FastAPI 测试客户端，db 依赖注入替换为内存 session。"""
    # create_app will be available after Task 8; import lazily
    from backend.app.main import create_app
    app = create_app()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
