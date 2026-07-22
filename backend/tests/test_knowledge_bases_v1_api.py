# backend/tests/test_knowledge_bases_v1_api.py
from fastapi.testclient import TestClient

from backend.app.main import create_app


def _client():
    app = create_app()
    return TestClient(app)


def test_v1_create_and_list_use_actor_scope():
    client = _client()
    created = client.post(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
        json={"name": "Manuals", "description": "Product manuals"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["owner_user_id"] == "alice"
    assert body["tenant_id"] == "tenant-a"
    assert body["name"] == "Manuals"

    other = client.get(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"},
    )
    assert other.json()["items"] == []


def test_v1_error_envelope_is_structured():
    client = _client()
    response = client.get("/api/v1/knowledge-bases/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert body["error"]["retryable"] is False
    assert body["error"]["trace_id"]


def test_v1_get_and_update_kb():
    client = _client()
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "KB"})
    kb_uid = created.json()["kb_uid"]

    kb = client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=headers)
    assert kb.status_code == 200
    assert kb.json()["name"] == "KB"

    updated = client.patch(
        f"/api/v1/knowledge-bases/{kb_uid}",
        headers=headers,
        json={"name": "KB v2", "version": kb.json()["version"]},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "KB v2"


def test_v1_update_conflict_on_wrong_version():
    client = _client()
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "KB"})
    kb_uid = created.json()["kb_uid"]

    r1 = client.patch(
        f"/api/v1/knowledge-bases/{kb_uid}",
        headers=headers,
        json={"name": "First", "version": 999},
    )
    assert r1.status_code == 409


def test_v1_forbidden_actor_cannot_access_others_kb():
    client = _client()
    alice_headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    bob_headers = {"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=alice_headers, json={"name": "Alice KB"})
    kb_uid = created.json()["kb_uid"]

    resp = client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=bob_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "KNOWLEDGE_ACCESS_DENIED"
