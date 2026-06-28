from fastapi import FastAPI
from fastapi.testclient import TestClient
import threading
import time

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


def test_ingest_api_serializes_concurrent_requests(monkeypatch):
    calls = []
    first_started = threading.Event()
    release_first = threading.Event()

    def fake_ingest(item_id):
        calls.append(("start", item_id, time.monotonic()))
        if item_id == "item-1":
            first_started.set()
            assert release_first.wait(timeout=2)
        calls.append(("end", item_id, time.monotonic()))
        return 1

    monkeypatch.setattr(ingest_api, "ingest_item", fake_ingest)
    app = FastAPI()
    app.include_router(ingest_api.router)
    client = TestClient(app)

    first_response = {}

    def post_first():
        first_response["value"] = client.post("/ingest", json={"item_id": "item-1"})

    thread = threading.Thread(target=post_first)
    thread.start()
    assert first_started.wait(timeout=2)

    second_done = threading.Event()
    second_response = {}

    def post_second():
        second_response["value"] = client.post("/ingest", json={"item_id": "item-2"})
        second_done.set()

    second_thread = threading.Thread(target=post_second)
    second_thread.start()
    time.sleep(0.1)

    assert not second_done.is_set()
    release_first.set()
    thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert first_response["value"].status_code == 200
    assert second_response["value"].status_code == 200
    assert [event[:2] for event in calls] == [
        ("start", "item-1"),
        ("end", "item-1"),
        ("start", "item-2"),
        ("end", "item-2"),
    ]
