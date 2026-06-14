# prism/backend/tests/test_knowledge_api.py

from backend.app.utils.media_type import infer_media_type, supported_accept_extensions
from backend.app.models import KnowledgeFile


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
