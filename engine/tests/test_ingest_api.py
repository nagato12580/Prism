from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.app.api import ingest as ingest_api


def test_ingest_api_returns_exception_detail(monkeypatch):
    def fail(item_id):
        raise RuntimeError("Lock wait timeout exceeded; try restarting transaction")

    monkeypatch.setattr(ingest_api, "ingest_item", fail)
    app = FastAPI()
    app.include_router(ingest_api.router)
    client = TestClient(app)

    response = client.post("/ingest", json={"item_id": "item-1"})

    assert response.status_code == 500
    assert response.json()["detail"]["message"] == "Lock wait timeout exceeded; try restarting transaction"
