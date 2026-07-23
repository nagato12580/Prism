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
    assert "storage_uri" not in body["file"]
    assert body["file"]["preview_url"] == (
        f"/api/v1/knowledge-bases/{kb_uid}/files/{body['file']['file_uid']}/preview"
    )
    assert body["file"]["download_url"] == (
        f"/api/v1/knowledge-bases/{kb_uid}/files/{body['file']['file_uid']}/download"
    )


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
    assert "storage_uri" not in body
    assert body["preview_url"].endswith(f"/{file_uid}/preview")
    assert body["download_url"].endswith(f"/{file_uid}/download")


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


def test_preview_and_download_use_public_file_routes(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Read KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("read.md", b"# Public preview", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]

    preview = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/preview",
        headers=file_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["content"] == "# Public preview"
    assert "storage_uri" not in preview.json()

    download = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/download",
        headers=file_headers,
    )
    assert download.status_code == 200
    assert download.content == b"# Public preview"
    assert "attachment" in download.headers["content-disposition"]


@pytest.mark.parametrize("command,job_type", [("parse", "parse"), ("index", "index")])
def test_file_command_returns_durable_job(client, file_headers, command, job_type):
    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Command KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("command.md", b"command", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/{command}",
        headers=file_headers,
    )
    assert response.status_code == 202
    assert response.json()["job_type"] == job_type
    assert response.json()["status"] == "queued"


def test_list_files_supports_filters_and_limit(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Filter KB"}
    )
    kb_uid = created.json()["kb_uid"]
    for path, filename in [("docs/a.md", "a.md"), ("notes/b.txt", "b.txt")]:
        response = client.post(
            f"/api/v1/knowledge-bases/{kb_uid}/files",
            headers=file_headers,
            files={"file": (filename, filename.encode(), "text/plain")},
            data={"relative_path": path},
        )
        assert response.status_code == 202

    response = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        params={
            "relative_path": "docs/",
            "media_type": "document",
            "parse_status": "pending",
            "limit": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["relative_path"] == "docs/a.md"
    assert body["items"][0]["media_type"] == "document"


def test_delete_file_tombstones_and_returns_cleanup_job(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Delete KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("delete.md", b"delete", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]

    response = client.delete(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}", headers=file_headers
    )
    assert response.status_code == 202
    assert response.json()["job_type"] == "delete"
    assert client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}", headers=file_headers
    ).status_code == 404


def test_job_snapshot_is_scoped_to_requested_kb(client, file_headers):
    first = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "First"}
    ).json()["kb_uid"]
    second = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Second"}
    ).json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{first}/files",
        headers=file_headers,
        files={"file": ("scoped.md", b"scoped", "text/markdown")},
    )
    job_id = upload.json()["job"]["id"]

    response = client.get(
        f"/api/v1/knowledge-bases/{second}/files/jobs/{job_id}", headers=file_headers
    )
    assert response.status_code == 404
