def test_create_inbox_item_classifies_to_review(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.inbox._llm_classify", lambda item: None)

    response = client.post(
        "/api/v1/inbox/items",
        json={"content": "我看到一个关于 RAG 重排技术的教程，感觉很值得整理成知识点。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["item"]["status"] == "classified"
    assert payload["review"]["status"] == "pending"
    assert payload["review"]["kind"] in {"knowledge", "opinion", "idea"}

    reviews = client.get("/api/v1/inbox/reviews").json()
    assert len(reviews) == 1
    assert reviews[0]["raw_item"]["content"].startswith("我看到一个关于 RAG")


def test_approve_opinion_review_creates_note(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.inbox._llm_classify",
        lambda item: {
            "kind": "opinion",
            "title": "问题分解能力",
            "summary": "学习 AI 更重要的是建立问题分解能力。",
            "suggested_action": "save_note",
            "category": "AI 学习",
            "tags": ["AI", "学习方法"],
            "rationale": "这是一条观点，适合保存为零散笔记。",
            "confidence": 0.88,
        },
    )

    created = client.post(
        "/api/v1/inbox/items",
        json={"content": "学习 AI 最重要的不是追模型，而是建立问题分解能力。"},
    ).json()

    review_id = created["review"]["id"]
    response = client.post(f"/api/v1/inbox/reviews/{review_id}/approve")

    assert response.status_code == 200
    settled = response.json()
    assert settled["settled_type"] == "note"

    notes = client.get("/api/v1/inbox/notes").json()
    assert len(notes) == 1
    assert notes[0]["title"] == "问题分解能力"
    assert notes[0]["note_type"] == "opinion"


def test_approve_memory_review_creates_memory_entry(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.inbox._llm_classify",
        lambda item: {
            "kind": "memory",
            "title": "偏好轻量方案",
            "summary": "用户希望 Prism 第一版先轻量实现。",
            "suggested_action": "remember",
            "category": "产品偏好",
            "tags": ["Prism", "轻量实现"],
            "rationale": "这是长期偏好，适合记住。",
            "confidence": 0.92,
        },
    )

    created = client.post(
        "/api/v1/inbox/items",
        json={"content": "我希望 Prism 第一版先轻量实现，不要过早引入太重依赖。"},
    ).json()

    response = client.post(f"/api/v1/inbox/reviews/{created['review']['id']}/approve")

    assert response.status_code == 200
    assert response.json()["settled_type"] == "memory"

    memories = client.get("/api/v1/inbox/memories").json()
    assert len(memories) == 1
    assert memories[0]["title"] == "偏好轻量方案"
