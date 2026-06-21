# prism/backend/tests/test_knowledge_api.py
from pathlib import Path

from backend.app.utils.media_type import infer_media_type, supported_accept_extensions
from backend.app.models import KnowledgeFile
from sqlalchemy.exc import IntegrityError


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

    db_session.add(KnowledgeFile(
        user_id="default-user",
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


def test_ingest_resource_returns_processing_and_triggers_background(client, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    triggered = []

    monkeypatch.setattr(
        "backend.app.api.knowledge._trigger_resource_ingestion",
        lambda resource_id, item_id: triggered.append((resource_id, item_id)),
    )

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 200
    ingested = response.json()
    assert ingested["processing_status"] == "processing"
    assert ingested["error_message"] is None
    assert triggered == [(resource["id"], resource["item_id"])]


def test_ingest_resource_does_not_retrigger_while_processing(client, db_session, monkeypatch):
    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    saved.processing_status = "processing"
    db_session.commit()
    triggered = []

    monkeypatch.setattr(
        "backend.app.api.knowledge._trigger_resource_ingestion",
        lambda resource_id, item_id: triggered.append((resource_id, item_id)),
    )

    response = client.post(f"/api/v1/knowledge/resources/{resource['id']}/ingest")

    assert response.status_code == 200
    assert response.json()["processing_status"] == "processing"
    assert triggered == []


def test_run_resource_ingestion_marks_resource_done(client, db_session, monkeypatch):
    from backend.app.api import knowledge

    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chunks": 3}

    monkeypatch.setattr(knowledge, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(knowledge.httpx, "post", lambda *args, **kwargs: FakeResponse())

    knowledge._run_resource_ingestion(resource["id"], resource["item_id"])

    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    assert saved.processing_status == "done"
    assert saved.error_message is None


def test_run_resource_ingestion_waits_for_long_document_governance(client, db_session, monkeypatch):
    from backend.app.api import knowledge

    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()
    observed = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chunks": 3}

    def fake_post(*args, **kwargs):
        observed.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(knowledge, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(knowledge.httpx, "post", fake_post)

    knowledge._run_resource_ingestion(resource["id"], resource["item_id"])

    assert observed["timeout"] >= 1800


def test_run_resource_ingestion_records_engine_error_body(client, db_session, monkeypatch):
    from backend.app.api import knowledge

    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()

    class FakeResponse:
        status_code = 500
        text = '{"detail":"Lock wait timeout exceeded; try restarting transaction"}'

        def json(self):
            return {"detail": "Lock wait timeout exceeded; try restarting transaction"}

    monkeypatch.setattr(knowledge, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(knowledge.httpx, "post", lambda *args, **kwargs: FakeResponse())

    knowledge._run_resource_ingestion(resource["id"], resource["item_id"])

    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    assert saved.processing_status == "failed"
    assert saved.error_message == "Engine returned 500: Lock wait timeout exceeded; try restarting transaction"


def test_run_resource_ingestion_marks_resource_failed_on_zero_chunks(client, db_session, monkeypatch):
    from backend.app.api import knowledge

    topic = _create_topic(client)
    upload = client.post(
        f"/api/v1/knowledge/topics/{topic['id']}/resources",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
    )
    resource = upload.json()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chunks": 0}

    monkeypatch.setattr(knowledge, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(knowledge.httpx, "post", lambda *args, **kwargs: FakeResponse())

    knowledge._run_resource_ingestion(resource["id"], resource["item_id"])

    saved = db_session.query(KnowledgeFile).filter_by(id=resource["id"]).one()
    assert saved.processing_status == "failed"
    assert saved.error_message == "Ingestion returned 0 chunks (content may be empty)"


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
