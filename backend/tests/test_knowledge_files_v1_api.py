# backend/tests/test_knowledge_files_v1_api.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def file_headers():
    return {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}


def test_upload_file_returns_202_with_file_and_job(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=file_headers,
        json={"name": "Upload KB"},
    )
    kb_uid = created.json()["kb_uid"]

    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("a.md", b"# Title\nBody", "text/markdown")},
        data={"relative_path": "docs/a.md", "auto_index": "true"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "file" in body
    assert "job" in body
    assert body["file"]["parse_status"] == "pending"
    assert body["job"]["job_type"] == "parse"


def test_list_files_returns_empty_for_new_kb(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=file_headers,
        json={"name": "Empty KB"},
    )
    kb_uid = created.json()["kb_uid"]

    resp = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_get_file_after_upload(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases",
        headers=file_headers,
        json={"name": "Get File KB"},
    )
    kb_uid = created.json()["kb_uid"]

    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("doc.md", b"# Doc", "text/markdown")},
        data={"relative_path": "doc.md"},
    )
    file_uid = upload.json()["file"]["file_uid"]

    resp = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}",
        headers=file_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["file_uid"] == file_uid
    assert body["original_filename"] == "doc.md"


def test_forbidden_actor_cannot_upload(client, file_headers):
    alice = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    bob = {"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"}

    created = client.post(
        "/api/v1/knowledge-bases",
        headers=alice,
        json={"name": "Alice KB"},
    )
    kb_uid = created.json()["kb_uid"]

    resp = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=bob,
        files={"file": ("a.md", b"data")},
    )
    assert resp.status_code == 403
