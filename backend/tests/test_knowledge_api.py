# prism/backend/tests/test_knowledge_api.py
import json
from pathlib import Path

import pytest

from backend.app.utils.media_type import infer_media_type, supported_accept_extensions
from backend.app.models import KnowledgeFile, KnowledgeJob, KnowledgeTopic
from sqlalchemy.exc import IntegrityError


class FakeRedis:
    def __init__(self):
        self.messages = []

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))


def test_create_and_get_item(client):
    resp = client.post("/api/v1/knowledge", json={
        "title": "RAG 笔记",
        "content": "检索增强生成",
        "tags": ["AI", "RAG"],
        "category": "技术/AI",
    })
    assert resp.status_code == 200
    item = resp.json()
    assert item["title"] == "RAG 笔记"
    assert item["tags"] == ["AI", "RAG"]
    assert item["id"]  # UUID 已生成

    # 获取详情
    resp2 = client.get(f"/api/v1/knowledge/{item['id']}")
    assert resp2.status_code == 200
    assert resp2.json()["content"] == "检索增强生成"


def test_list_items_with_tag_filter(client):
    client.post("/api/v1/knowledge", json={"title": "条目1", "tags": ["python"]})
    client.post("/api/v1/knowledge", json={"title": "条目2", "tags": ["java"]})

    resp = client.get("/api/v1/knowledge", params={"tag": "python"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["title"] == "条目1"


def test_update_and_delete_item(client):
    create = client.post("/api/v1/knowledge", json={"title": "原标题"})
    item_id = create.json()["id"]

    resp = client.put(f"/api/v1/knowledge/{item_id}", json={"title": "新标题"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"

    del_resp = client.delete(f"/api/v1/knowledge/{item_id}")
    assert del_resp.status_code == 200

    get_resp = client.get(f"/api/v1/knowledge/{item_id}")
    assert get_resp.status_code == 404


def test_get_nonexistent_item_404(client):
    resp = client.get("/api/v1/knowledge/nonexistent-id")
    assert resp.status_code == 404


def test_delete_item_cleans_derived_artifacts(client, monkeypatch):
    create = client.post("/api/v1/knowledge", json={"title": "Need cleanup"})
    item_id = create.json()["id"]
    cleaned = []

    monkeypatch.setattr(
        "backend.app.api.knowledge.purge_item_derived_artifacts",
        lambda _db, target_item_id: cleaned.append(target_item_id),
    )

    response = client.delete(f"/api/v1/knowledge/{item_id}")

    assert response.status_code == 200
    assert cleaned == [item_id]


def test_infer_media_type_by_extension_and_mime():
    assert infer_media_type("notes.md", "text/markdown") == "document"
    assert infer_media_type("photo.webp", "image/webp") == "image"
    assert infer_media_type("call.m4a", "audio/mp4") == "audio"
    assert infer_media_type("demo.webm", "video/webm") == "video"


def test_unsupported_media_type_rejected():
    try:
        infer_media_type("archive.zip", "application/zip")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("zip files must be rejected")


def test_supported_accept_extensions_contains_all_resource_types():
    extensions = supported_accept_extensions()
    assert ".pdf" in extensions
    assert ".png" in extensions
    assert ".mp3" in extensions
    assert ".mp4" in extensions


def test_unsupported_category_matching_mime_rejected():
    try:
        infer_media_type("file.svg", "image/svg+xml")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("unsupported image MIME types must be rejected")


def test_infer_media_type_accepts_uppercase_extension():
    assert infer_media_type("PHOTO.JPG", None) == "image"


def test_unknown_extension_with_unlisted_video_mime_rejected():
    try:
        infer_media_type("clip.unknown", "video/3gpp")
    except ValueError as exc:
        assert "Unsupported file type" in str(exc)
    else:
        raise AssertionError("unlisted video MIME types must be rejected")


def test_create_list_update_topic(client):
    create = client.post("/api/v1/knowledge/topics", json={
        "name": "Product Docs",
        "description": "Launch docs",
    })
    assert create.status_code == 200
    topic = create.json()
    assert topic["name"] == "Product Docs"
    assert topic["description"] == "Launch docs"
    assert topic["resource_count"] == 0

    listing = client.get("/api/v1/knowledge/topics")
    assert listing.status_code == 200
    assert [item["name"] for item in listing.json()] == ["Product Docs"]

    update = client.put(f"/api/v1/knowledge/topics/{topic['id']}", json={
        "name": "Product Handbook",
        "description": "Updated",
    })
    assert update.status_code == 200
    assert update.json()["name"] == "Product Handbook"


def test_duplicate_topic_name_is_conflict(client):
    first = client.post("/api/v1/knowledge/topics", json={"name": "Research"})
    second = client.post("/api/v1/knowledge/topics", json={"name": "Research"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_topic_name"


def test_delete_empty_topic(client):
    create = client.post("/api/v1/knowledge/topics", json={"name": "Empty"})
    topic_id = create.json()["id"]

    delete = client.delete(f"/api/v1/knowledge/topics/{topic_id}")
    assert delete.status_code == 200
    assert delete.json()["detail"] == "deleted"


def test_create_topic_rejects_whitespace_only_name(client):
    create = client.post("/api/v1/knowledge/topics", json={"name": "   "})

    assert create.status_code == 422


def test_update_topic_rejects_whitespace_only_name(client):
    create = client.post("/api/v1/knowledge/topics", json={"name": "Valid"})
    topic_id = create.json()["id"]

    update = client.put(f"/api/v1/knowledge/topics/{topic_id}", json={"name": "   "})

    assert update.status_code == 422


def test_delete_non_empty_topic_conflict(client, db_session):
    create = client.post("/api/v1/knowledge/topics", json={"name": "Filled"})
    topic_id = create.json()["id"]
    topic = db_session.get(KnowledgeTopic, topic_id)

    db_session.add(KnowledgeFile(
        user_id="default-user",
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        topic_id=topic_id,
        title="Doc",
        original_filename="doc.pdf",
        media_type="document",
        file_ext=".pdf",
        file_size=10,
        md5="abc123",
        storage_path="/tmp/doc.pdf",
    ))
    db_session.commit()

    delete = client.delete(f"/api/v1/knowledge/topics/{topic_id}")

    assert delete.status_code == 409
    assert delete.json()["detail"]["code"] == "topic_not_empty"


def test_create_topic_commit_duplicate_race_is_conflict(client, db_session, monkeypatch):
    def raise_duplicate_commit():
        raise IntegrityError(
            "INSERT INTO knowledge_topic",
            {},
            Exception("UNIQUE constraint failed: knowledge_topic.user_id, knowledge_topic.name"),
        )

    monkeypatch.setattr(db_session, "commit", raise_duplicate_commit)

    create = client.post("/api/v1/knowledge/topics", json={"name": "Race"})

    assert create.status_code == 409
    assert create.json()["detail"]["code"] == "duplicate_topic_name"


def test_update_topic_commit_duplicate_race_is_conflict(client, db_session, monkeypatch):
    create = client.post("/api/v1/knowledge/topics", json={"name": "Original"})
    topic_id = create.json()["id"]

    def raise_duplicate_commit():
        raise IntegrityError(
            "UPDATE knowledge_topic",
            {},
            Exception("Duplicate entry 'default-user-Race' for key 'uq_knowledge_topic_user_name'"),
        )

    monkeypatch.setattr(db_session, "commit", raise_duplicate_commit)

    update = client.put(f"/api/v1/knowledge/topics/{topic_id}", json={"name": "Race"})

    assert update.status_code == 409
    assert update.json()["detail"]["code"] == "duplicate_topic_name"


def _create_topic(client, name="Uploads"):
    response = client.post("/api/v1/knowledge/topics", json={"name": name})
    assert response.status_code == 200
    return response.json()


def test_upload_document_resource_creates_item(client, monkeypatch):
    topic = _create_topic(client)
    called = []
    monkeypatch.setattr("backend.app.api.knowledge._trigger_ingestion", lambda item_id: called.append(item_id))

    response = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
        data={"description": "Greeting", "tags": "intro,hello"},
    )

    assert response.status_code == 200
    resource = response.json()
    assert resource["title"] == "notes"
    assert resource["media_type"] == "document"
    assert resource["processing_status"] == "completed"
    assert resource["description"] == "Greeting"
    assert resource["tags"] == ["intro", "hello"]
    assert resource["content_text"] == "hello document"
    assert resource["item_id"]
    assert called == []


def test_upload_document_marks_abnormal_text_invalid(db_session, monkeypatch):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from backend.app.api.knowledge import router as knowledge_router
    from backend.app.database import get_db

    app = FastAPI()
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    app.include_router(api_prefix)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    topic = _create_topic(client)
    monkeypatch.setattr("backend.app.api.knowledge.extract_text", lambda path: "x" * 300001)
    monkeypatch.setattr("backend.app.api.knowledge.count_pages", lambda path: 10)

    response = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("huge.txt", b"placeholder", "text/plain")},
    )

    assert response.status_code == 200
    resource = response.json()
    assert resource["processing_status"] == "text_invalid"
    assert "too large" in resource["error_message"]
    assert resource["item_id"] is None


def test_duplicate_resource_in_same_topic_is_conflict(client):
    topic = _create_topic(client)
    files = {"file": ("same.txt", b"same", "text/plain")}

    first = client.post(f"/api/v1/knowledge/topics/{topic['id']}/resources", files=files)
    second = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("same-copy.txt", b"same", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_resource_in_topic"


def test_duplicate_resource_does_not_delete_existing_file(client, db_session):
    topic = _create_topic(client)
    first = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("same.txt", b"same", "text/plain")},
    )
    resource = db_session.query(KnowledgeFile).filter_by(id=first.json()["id"]).one()
    stored_path = Path(resource.storage_path)

    second = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("same.txt", b"same", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert stored_path.exists()


def test_upload_image_audio_video_as_metadata_only(client):
    topic = _create_topic(client)
    samples = [
        ("photo.png", b"png bytes", "image/png", "image"),
        ("voice.mp3", b"mp3 bytes", "audio/mpeg", "audio"),
        ("clip.mp4", b"mp4 bytes", "video/mp4", "video"),
    ]

    for filename, content, mime, expected_type in samples:
        response = client.post(
            f"/api/v1/knowledge/topics/{topic['id']}/resources",
            files={"file": (filename, content, mime)},
        )
        assert response.status_code == 200
        resource = response.json()
        assert resource["media_type"] == expected_type
        assert resource["processing_status"] == "metadata_only"
        assert resource["item_id"] is None


def test_ingest_resource_enqueues_parse_job_for_legacy_resource(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    fake_redis = FakeRedis()

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)
    monkeypatch.setattr(
        "backend.app.api.knowledge._trigger_resource_ingestion",
        lambda resource_id, item_id: (_ for _ in ()).throw(AssertionError("Engine thread must not be used")),
    )

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 200
    ingested = response.json()
    assert ingested["processing_status"] == "queued"
    assert ingested["error_message"] is None
    job = db_session.query(KnowledgeJob).filter_by(resource_id=resource["id"], job_type="parse").one()
    assert job.status == "queued"
    assert job.stage == "enqueued"
    assert job.file_uid
    assert job.item_id is None
    assert job.payload == {"auto_index": True}
    assert fake_redis.messages == [("prism:queue:ingest", json.dumps({"job_id": job.id}))]


def test_ingest_resource_reuses_active_parse_job_without_duplicate_redis_message(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    fake_redis = FakeRedis()

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    first = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")
    second = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["processing_status"] == "queued"
    assert db_session.query(KnowledgeJob).filter_by(resource_id=resource["id"], job_type="parse").count() == 1
    assert len(fake_redis.messages) == 1


def test_ingest_resource_maps_enqueue_value_error_to_conflict(client, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    fake_redis = FakeRedis()

    def raise_not_ingestable(*args, **kwargs):
        raise ValueError("resource_not_ingestable")

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)
    monkeypatch.setattr("backend.app.api.knowledge._enqueue_legacy_parse_job", raise_not_ingestable)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "resource_not_ingestable",
        "message": "resource_not_ingestable",
    }
    assert fake_redis.messages == []


def test_ingest_resource_rejects_text_invalid(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "text_invalid"
    saved.error_message = "Document text is too large"
    db_session.commit()
    fake_redis = FakeRedis()

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "text_invalid",
        "message": "Document text is too large",
    }
    assert fake_redis.messages == []


def test_ingest_resource_rejects_no_item(client, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("photo.png", b"image", "image/png")},
    )
    resource = upload.json()
    fake_redis = FakeRedis()

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "no_item"
    assert fake_redis.messages == []


def test_ingest_resource_missing_returns_404(client):
    response = client.post("/api/v1/knowledge/resources/missing-resource/ingest")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


def test_retry_governance_enqueues_governance_job(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "done"
    saved.governance_status = "failed"
    db_session.commit()
    fake_redis = FakeRedis()
    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/governance/retry")

    assert response.status_code == 200
    assert response.json()["governance_status"] == "queued"
    assert fake_redis.messages


def test_retry_governance_rejects_resource_that_is_not_vectorized(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "completed"
    saved.governance_status = "failed"
    db_session.commit()
    fake_redis = FakeRedis()
    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/governance/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_vectorized"
    assert fake_redis.messages == []


@pytest.mark.parametrize("governance_status", ["done", "not_started"])
def test_retry_governance_rejects_resource_when_governance_is_not_failed(
    client,
    db_session,
    monkeypatch,
    governance_status,
):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "done"
    saved.governance_status = governance_status
    db_session.commit()
    fake_redis = FakeRedis()
    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/governance/retry")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "governance_not_failed"
    assert fake_redis.messages == []


def test_retry_governance_maps_enqueue_value_error_to_conflict(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "done"
    saved.governance_status = "failed"
    db_session.commit()
    fake_redis = FakeRedis()

    def raise_not_ingestable(*args, **kwargs):
        raise ValueError("resource_not_ingestable")

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)
    monkeypatch.setattr("backend.app.api.knowledge.enqueue_governance_job", raise_not_ingestable)

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/governance/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "resource_not_ingestable",
        "message": "resource_not_ingestable",
    }
    assert fake_redis.messages == []


def test_topic_ingest_enqueues_all_eligible_documents(client, db_session, monkeypatch):
    topic = _create_topic(client)
    first = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("first.txt", b"first document", "text/plain")},
    ).json()
    second = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("second.txt", b"second document", "text/plain")},
    ).json()
    skipped_image = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("photo.png", b"image", "image/png")},
    ).json()
    saved_second = db_session.query(KnowledgeFile).filter_by(id=second["id"]).one()
    saved_second.processing_status = "failed"
    db_session.commit()
    fake_redis = FakeRedis()

    monkeypatch.setattr("backend.app.api.knowledge._redis_client", lambda: fake_redis)

    response = client.post(f"/api/v1/knowledge/topics/{topic['id']}/ingest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["queued"] == 2
    assert payload["skipped"] == 0
    assert payload["failed"] == 0
    assert payload["messages"] == []
    assert len(payload["job_ids"]) == 2
    jobs = db_session.query(KnowledgeJob).filter(KnowledgeJob.resource_id.in_([first["id"], second["id"]])).all()
    assert {job.id for job in jobs} == set(payload["job_ids"])
    assert {job.stage for job in jobs} == {"enqueued"}
    assert {json.loads(message)["job_id"] for _queue, message in fake_redis.messages} == set(payload["job_ids"])
    assert [queue for queue, _message in fake_redis.messages] == ["prism:queue:ingest", "prism:queue:ingest"]
    assert db_session.query(KnowledgeJob).filter_by(resource_id=skipped_image["id"]).count() == 0


def test_update_resource_title_updates_linked_item(client, monkeypatch):
    topic = _create_topic(client)
    monkeypatch.setattr("backend.app.api.knowledge._trigger_ingestion", lambda item_id: None)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()

    response = client.put(
        f"/api/v1/knowledge/resources/{resource['id']}",
        json={"title": "Renamed notes"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed notes"
    item = client.get(f"/api/v1/knowledge/{resource['item_id']}")
    assert item.status_code == 200
    assert item.json()["title"] == "Renamed notes"


def test_update_resource_title_rejects_blank(client):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("photo.png", b"image", "image/png")},
    )
    resource = upload.json()

    response = client.put(
        f"/api/v1/knowledge/resources/{resource['id']}",
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_resource_title"


def test_list_resources_filter_by_media_type(client):
    topic = _create_topic(client)
    client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"text", "text/plain")},
    )
    client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("photo.png", b"image", "image/png")},
    )

    response = client.get(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        params={"media_type": "image"},
    )

    assert response.status_code == 200
    resources = response.json()
    assert len(resources) == 1
    assert resources[0]["media_type"] == "image"


def test_topic_delete_blocked_when_resources_exist(client):
    topic = _create_topic(client, "Blocked")
    client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"text", "text/plain")},
    )

    response = client.delete(f"/api/v1/knowledge/topics/{topic['id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "topic_not_empty"


def test_delete_document_resource_cleans_derived_artifacts(client, monkeypatch):
    topic = _create_topic(client, "Cleanup resource")
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    cleaned = []

    monkeypatch.setattr(
        "backend.app.api.knowledge.purge_item_derived_artifacts",
        lambda _db, item_id: cleaned.append(item_id),
    )

    response = client.delete(f"/api/v1/knowledge/resources/{resource['id']}")

    assert response.status_code == 200
    assert cleaned == [resource["item_id"]]


def test_delete_metadata_only_resource_skips_derived_cleanup(client, monkeypatch):
    topic = _create_topic(client, "Metadata only")
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("photo.png", b"image", "image/png")},
    )
    resource = upload.json()
    cleaned = []

    monkeypatch.setattr(
        "backend.app.api.knowledge.purge_item_derived_artifacts",
        lambda _db, item_id: cleaned.append(item_id),
    )

    response = client.delete(f"/api/v1/knowledge/resources/{resource['id']}")

    assert response.status_code == 200
    assert cleaned == []


def test_legacy_endpoints_cannot_access_other_tenant_rows(client, db_session):
    from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic
    other_item = KnowledgeItem(tenant_id="other", kb_uid="other-kb", title="Foreign", content="x")
    other_topic = KnowledgeTopic(tenant_id="other", owner_user_id="default-user", user_id="default-user", name="Shared Name")
    db_session.add_all([other_item, other_topic]); db_session.flush()
    other_file = KnowledgeFile(user_id="default-user", tenant_id="other", kb_uid=other_topic.kb_uid,
                               topic_id=other_topic.id, file_uid="foreign-file", title="Foreign",
                               original_filename="foreign.txt", storage_path="missing.txt")
    db_session.add(other_file); db_session.commit()

    for method, path, kwargs in (
        (client.get, f"/api/v1/knowledge/{other_item.id}", {}),
        (client.put, f"/api/v1/knowledge/{other_item.id}", {"json": {"title": "Changed"}}),
        (client.delete, f"/api/v1/knowledge/{other_item.id}", {}),
        (client.get, f"/api/v1/knowledge/topics/{other_topic.id}", {}),
        (client.put, f"/api/v1/knowledge/topics/{other_topic.id}", {"json": {"name": "Changed"}}),
        (client.delete, f"/api/v1/knowledge/topics/{other_topic.id}", {}),
        (client.get, f"/api/v1/knowledge/resources/{other_file.id}", {}),
        (client.delete, f"/api/v1/knowledge/resources/{other_file.id}", {}),
    ):
        assert method(path, **kwargs).status_code == 404
    assert client.post("/api/v1/knowledge/topics", json={"name": "Shared Name"}).status_code == 200
    db_session.refresh(other_item); db_session.refresh(other_topic); db_session.refresh(other_file)
    assert other_item.title == "Foreign" and other_topic.name == "Shared Name"
