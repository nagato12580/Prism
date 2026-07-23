from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.database import get_db
from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic
from engine.app.api import ingest as ingest_api


def _client(db_session):
    app = FastAPI()
    app.include_router(ingest_api.router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_ingest_compatibility_adapter_creates_job_without_running_pipeline(db_session):
    topic = KnowledgeTopic(tenant_id="tenant-a", owner_user_id="alice", name="KB")
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id="tenant-a", kb_uid=topic.kb_uid, title="Item", content="text"
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(KnowledgeFile(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        file_uid="file-1",
        item_id=item.id,
        original_filename="a.md",
    ))
    db_session.commit()

    response = _client(db_session).post("/ingest", json={"item_id": item.id})

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["job_type"] == "index"


def test_ingest_compatibility_adapter_rejects_unknown_item(db_session):
    response = _client(db_session).post("/ingest", json={"item_id": "missing"})

    assert response.status_code == 404
