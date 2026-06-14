# prism/backend/tests/test_knowledge_api.py

from backend.app.utils.media_type import infer_media_type, supported_accept_extensions


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
