# backend/tests/test_knowledge_files_v1_api.py
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta


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


def test_list_files_returns_recently_updated_files_first(db_session):
    from backend.app.api.knowledge_files import list_files
    from backend.app.models import KnowledgeFile, KnowledgeTopic
    from backend.app.security.actor import ActorContext

    now = datetime(2026, 8, 17, 12, 0, 0)
    topic = KnowledgeTopic(
        kb_uid="target-kb",
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="Target KB",
    )
    older_a = KnowledgeFile(
        file_uid="00000000-0000-4000-8000-000000000001",
        tenant_id="tenant-a",
        user_id="alice",
        kb_uid=topic.kb_uid,
        original_filename="older-a.md",
        media_type="document",
        mime_type="text/markdown",
        content_sha256="a" * 64,
        size_bytes=12,
        updated_at=now - timedelta(days=2),
    )
    older_b = KnowledgeFile(
        file_uid="00000000-0000-4000-8000-000000000002",
        tenant_id="tenant-a",
        user_id="alice",
        kb_uid=topic.kb_uid,
        original_filename="older-b.md",
        media_type="document",
        mime_type="text/markdown",
        content_sha256="b" * 64,
        size_bytes=12,
        updated_at=now - timedelta(days=1),
    )
    moved = KnowledgeFile(
        file_uid="ffffffff-ffff-4fff-8fff-ffffffffffff",
        tenant_id="tenant-a",
        user_id="alice",
        kb_uid=topic.kb_uid,
        original_filename="recently-moved.md",
        media_type="document",
        mime_type="text/markdown",
        content_sha256="c" * 64,
        size_bytes=12,
        updated_at=now,
    )
    db_session.add_all([topic, older_a, older_b, moved])
    db_session.commit()

    body = list_files(
        topic.kb_uid,
        actor=ActorContext(actor_id="alice", tenant_id="tenant-a"),
        db=db_session,
        limit=2,
    )

    assert [item["original_filename"] for item in body["items"]] == [
        "recently-moved.md",
        "older-b.md",
    ]


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


def test_download_handles_non_ascii_filename(client, file_headers):
    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Unicode KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("季度评审准备.md", "# 季度评审\n\n内容".encode("utf-8"), "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]

    download = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/download",
        headers=file_headers,
    )
    assert download.status_code == 200
    assert download.content.decode("utf-8") == "# 季度评审\n\n内容"
    disposition = download.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition


def test_preview_prefers_parsed_text_for_binary_documents(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "PDF Preview KB"}
    )
    kb_uid = created.json()["kb_uid"]
    raw_pdf_fragment = b"<< /Filter /FlateDecode /Length 900 >>\nstream\nx\x9cmUMo"
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("paper.pdf", raw_pdf_fragment, "application/pdf")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.content_text = "[[PAGE:1]]\nAlignment-free sequence analysis uses graph embeddings."
    file_row.parse_status = "succeeded"
    db_session.commit()

    preview = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/preview",
        headers=file_headers,
    )

    assert preview.status_code == 200
    assert preview.json()["content"] == file_row.content_text
    assert "FlateDecode" not in preview.json()["content"]


def test_file_projection_includes_stage_error_details(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Stage Error KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("stage-error.md", b"# Error", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.index_status = "failed"
    file_row.index_error = {"code": "INDEX_ERROR", "message": "Milvus flush deadline exceeded"}
    file_row.graph_status = "failed"
    file_row.graph_error = {"code": "GRAPH_ERROR", "message": "Neo4j projection failed"}
    file_row.last_job_id = "job-failed"
    db_session.commit()

    response = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}",
        headers=file_headers,
    )

    assert response.status_code == 200
    assert response.json()["last_job_id"] == "job-failed"
    assert response.json()["index_error"] == {
        "code": "INDEX_ERROR",
        "message": "Milvus flush deadline exceeded",
    }
    assert response.json()["graph_error"] == {
        "code": "GRAPH_ERROR",
        "message": "Neo4j projection failed",
    }


@pytest.mark.parametrize("command,job_type", [("parse", "parse"), ("index", "index"), ("graph", "graph")])
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


def test_graph_command_creates_file_scoped_jobs_across_files(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile, KnowledgeJob

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "KB-wide Graph Reuse"}
    )
    kb_uid = created.json()["kb_uid"]
    first = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("first.md", b"# First", "text/markdown")},
    ).json()["file"]["file_uid"]
    second = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("second.md", b"# Second", "text/markdown")},
    ).json()["file"]["file_uid"]
    file_a = db_session.query(KnowledgeFile).filter_by(file_uid=first).one()
    file_b = db_session.query(KnowledgeFile).filter_by(file_uid=second).one()
    file_a.parsed_content_version = 1
    file_b.parsed_content_version = 1
    db_session.commit()

    first_response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_a.file_uid}/graph",
        headers=file_headers,
    )
    second_response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_b.file_uid}/graph",
        headers=file_headers,
    )

    db_session.refresh(file_a)
    db_session.refresh(file_b)
    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["id"] != second_response.json()["id"]
    assert first_response.json()["status"] == "queued"
    assert second_response.json()["status"] == "queued"
    assert file_a.last_job_id == first_response.json()["id"]
    assert file_b.last_job_id == second_response.json()["id"]
    assert file_a.graph_status == "running"
    assert file_b.graph_status == "running"
    assert db_session.query(KnowledgeJob).filter_by(kb_uid=kb_uid, job_type="graph").count() == 2


def test_index_command_requeues_after_failed_same_generation_job(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile, KnowledgeJob

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Retry Index KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("retry.md", b"# Retry", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.parsed_content_version = 1
    failed = KnowledgeJob(
        job_type="index",
        tenant_id=file_row.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_uid,
        idempotency_key=f"{kb_uid}:{file_uid}:index:v1",
        status="failed",
    )
    db_session.add(failed)
    db_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/index",
        headers=file_headers,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["id"] != failed.id


def test_index_command_requeues_after_failed_retry_job(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile, KnowledgeJob

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Retry Retry Index KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("retry-again.md", b"# Retry again", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.parsed_content_version = 1
    base_key = f"{kb_uid}:{file_uid}:index:v1"
    base_failed = KnowledgeJob(
        job_type="index",
        tenant_id=file_row.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_uid,
        idempotency_key=base_key,
        status="failed",
        attempts=1,
    )
    db_session.add(base_failed)
    db_session.flush()
    retry_failed = KnowledgeJob(
        job_type="index",
        tenant_id=file_row.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_uid,
        idempotency_key=f"{base_key}:retry:2:{base_failed.id}",
        status="failed",
    )
    db_session.add(retry_failed)
    db_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/index",
        headers=file_headers,
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["id"] not in {base_failed.id, retry_failed.id}


def test_index_command_records_new_job_on_file(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Last Job KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("last-job.md", b"# Last job", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.parsed_content_version = 1
    db_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/index",
        headers=file_headers,
    )

    db_session.refresh(file_row)
    assert response.status_code == 202
    assert file_row.last_job_id == response.json()["id"]
    assert file_row.index_status == "running"


def test_index_command_records_reused_active_job_on_file(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile, KnowledgeJob

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Active Last Job KB"}
    )
    kb_uid = created.json()["kb_uid"]
    upload = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("active-last-job.md", b"# Active", "text/markdown")},
    )
    file_uid = upload.json()["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    file_row.parsed_content_version = 1
    file_row.index_status = "failed"
    active = KnowledgeJob(
        job_type="index",
        tenant_id=file_row.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_uid,
        idempotency_key=f"{kb_uid}:{file_uid}:index:v1:retry:2:old",
        status="queued",
        stage="enqueued",
        error_code="INDEX_ERROR",
        error_message="previous retry failed",
    )
    db_session.add(active)
    db_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}/index",
        headers=file_headers,
    )

    db_session.refresh(file_row)
    assert response.status_code == 202
    assert response.json()["id"] == active.id
    assert response.json()["status"] == "queued"
    assert response.json()["error_code"] is None
    assert response.json()["error_message"] is None
    assert file_row.last_job_id == active.id
    assert file_row.index_status == "running"


def test_index_command_reuses_active_kb_index_job_across_files(client, db_session, file_headers):
    from backend.app.models import KnowledgeFile, KnowledgeJob

    created = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "KB-wide Index Reuse"}
    )
    kb_uid = created.json()["kb_uid"]
    first = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("first.md", b"# First", "text/markdown")},
    ).json()["file"]["file_uid"]
    second = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("second.md", b"# Second", "text/markdown")},
    ).json()["file"]["file_uid"]
    file_a = db_session.query(KnowledgeFile).filter_by(file_uid=first).one()
    file_b = db_session.query(KnowledgeFile).filter_by(file_uid=second).one()
    file_a.parsed_content_version = 1
    file_b.parsed_content_version = 1
    active = KnowledgeJob(
        job_type="index",
        tenant_id=file_a.tenant_id,
        kb_uid=kb_uid,
        file_uid=file_a.file_uid,
        idempotency_key=f"{kb_uid}:{file_a.file_uid}:index:v1",
        status="queued",
        stage="enqueued",
    )
    db_session.add(active)
    db_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files/{file_b.file_uid}/index",
        headers=file_headers,
    )

    db_session.refresh(file_b)
    assert response.status_code == 202
    assert response.json()["id"] == active.id
    assert response.json()["status"] == "queued"
    assert file_b.last_job_id == active.id
    assert file_b.index_status == "running"
    assert db_session.query(KnowledgeJob).filter_by(kb_uid=kb_uid, job_type="index").count() == 1


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


def test_job_snapshot_includes_failure_reason(client, db_session, file_headers):
    from backend.app.models import KnowledgeJob

    kb_uid = client.post(
        "/api/v1/knowledge-bases", headers=file_headers, json={"name": "Failure reason"}
    ).json()["kb_uid"]
    uploaded = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/files",
        headers=file_headers,
        files={"file": ("failure.md", b"failure", "text/markdown")},
    ).json()
    job_id = uploaded["job"]["id"]
    job = db_session.get(KnowledgeJob, job_id)
    job.status = "failed"
    job.error_code = "INDEX_ERROR"
    job.error_message = "Milvus flush deadline exceeded"
    db_session.commit()

    response = client.get(
        f"/api/v1/knowledge-bases/{kb_uid}/files/jobs/{job_id}",
        headers=file_headers,
    )

    assert response.status_code == 200
    assert response.json()["error_code"] == "INDEX_ERROR"
    assert response.json()["error_message"] == "Milvus flush deadline exceeded"


def test_delete_tombstone_and_job_are_committed_atomically(client, db_session, monkeypatch):
    from backend.app.api import knowledge_files
    from backend.app.models import KnowledgeFile, KnowledgeJob
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    kb_uid = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "Atomic delete"}).json()["kb_uid"]
    uploaded = client.post(f"/api/v1/knowledge-bases/{kb_uid}/files", headers=headers,
                           files={"file": ("atomic.md", b"body", "text/markdown")}).json()
    file_uid = uploaded["file"]["file_uid"]
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid=file_uid).one()
    commits = []
    original_commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", lambda: (commits.append((file_row.deleted_at, db_session.query(KnowledgeJob).filter_by(file_uid=file_row.file_uid, job_type="delete").count())), original_commit())[1])
    monkeypatch.setattr(knowledge_files, "_get_publisher", lambda: type("P", (), {"publish": lambda self, job_id: None})())
    response = client.delete(f"/api/v1/knowledge-bases/{kb_uid}/files/{file_uid}", headers=headers)
    assert response.status_code == 202
    assert commits[0][0] is not None
    assert commits[0][1] == 1


def test_personal_inbox_file_response_includes_source_markers(client, db_session, monkeypatch, tmp_path):
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)

    item = PersonalAssetItem(
        id="api-marker-item",
        user_id="alice",
        raw_text="raw",
        title="API Marker Item",
        status="confirmed",
    )
    unit = PersonalAssetUnit(
        id="api-marker-unit",
        user_id="alice",
        title="API Marker Unit",
        content="content",
        source_asset_ids=["api-marker-item"],
        status="confirmed",
    )
    db_session.add_all([item, unit])
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="alice",
        publish=False,
    )

    get_response = client.get(
        f"/api/v1/knowledge-bases/{file_row.kb_uid}/files/{file_row.file_uid}",
        headers=headers,
    )
    list_response = client.get(
        f"/api/v1/knowledge-bases/{file_row.kb_uid}/files",
        headers=headers,
    )

    assert get_response.status_code == 200
    assert list_response.status_code == 200
    get_body = get_response.json()
    list_body = next(
        item for item in list_response.json()["items"] if item["file_uid"] == file_row.file_uid
    )
    for body in [get_body, list_body]:
        assert body["source_kind"] == "personal_asset_unit"
        assert body["source_id"] == "api-marker-unit"
        assert body["system_type"] == "personal_inbox"


def test_delete_personal_inbox_file_cascades_asset_unit(client, db_session, monkeypatch, tmp_path):
    from backend.app.api import knowledge_files
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))
    monkeypatch.setattr(
        knowledge_files,
        "_get_publisher",
        lambda: type("P", (), {"publish": lambda self, job_id: None})(),
    )

    item = PersonalAssetItem(
        id="api-orphan-item",
        user_id="alice",
        raw_text="raw",
        title="API Orphan Item",
        status="confirmed",
    )
    unit = PersonalAssetUnit(
        id="api-unit",
        user_id="alice",
        title="API Unit",
        content="content",
        source_asset_ids=["api-orphan-item"],
        status="confirmed",
    )
    db_session.add_all([item, unit])
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="alice",
        publish=False,
    )

    response = client.delete(
        f"/api/v1/knowledge-bases/{file_row.kb_uid}/files/{file_row.file_uid}",
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["job_type"] == "delete"
    assert db_session.get(PersonalAssetUnit, "api-unit") is None
    assert db_session.get(PersonalAssetItem, "api-orphan-item") is None
