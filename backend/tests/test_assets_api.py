def test_create_asset_draft_from_raw_item_uses_ai_parse(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "问题分解能力",
            "asset_kind": "opinion",
            "source": {"type": "comment", "platform": "知乎", "url": ""},
            "summary": "学习 AI 的关键是建立问题分解能力。",
            "extracts": [{"type": "claim", "content": "问题分解能力比追模型重要。", "confidence": 0.91}],
            "tags": ["AI", "学习方法"],
            "category": "AI 学习",
            "suggested_relations": [],
            "suggested_extensions": [{"title": "如何训练问题分解能力", "confidence": 0.78}],
            "confidence": {"overall": 0.86, "classification": 0.9, "source": 0.7, "extraction": 0.91},
            "rationale": "这是观点型评论。",
        },
    )

    raw = client.post(
        "/api/v1/inbox/items",
        json={"content": "学习 AI 最重要的不是追模型，而是建立问题分解能力。", "classify": False},
    ).json()["item"]

    response = client.post("/api/v1/assets/drafts", json={"raw_item_id": raw["id"]})

    assert response.status_code == 200
    draft = response.json()
    assert draft["raw_item_id"] == raw["id"]
    assert draft["title"] == "问题分解能力"
    assert draft["asset_kind"] == "opinion"
    assert draft["source_platform"] == "知乎"
    assert draft["confidence"]["overall"] == 0.86
    assert draft["suggested_extensions"][0]["title"] == "如何训练问题分解能力"


def test_asset_draft_can_be_edited_and_confirmed_to_personal_asset(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    draft = client.post(
        "/api/v1/assets/drafts",
        json={"content": "这个 GitHub 项目可以作为 Agent 工具注册表参考。", "source_platform": "GitHub"},
    ).json()

    updated = client.put(
        f"/api/v1/assets/drafts/{draft['id']}",
        json={
            "title": "Agent 工具注册表参考",
            "asset_kind": "resource",
            "category": "Agent 架构",
            "tags": ["Agent", "工具"],
            "summary": "一个可参考的 Agent 工具注册表资源。",
        },
    ).json()

    assert updated["title"] == "Agent 工具注册表参考"
    assert updated["asset_kind"] == "resource"
    assert updated["tags"] == ["Agent", "工具"]

    response = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["status"] == "confirmed"
    assert payload["asset"]["title"] == "Agent 工具注册表参考"
    assert payload["asset"]["asset_kind"] == "resource"
    assert payload["asset"]["source_draft_id"] == draft["id"]

    assets = client.get("/api/v1/assets/search?q=Agent").json()
    assert len(assets) == 1
    assert assets[0]["title"] == "Agent 工具注册表参考"


def test_asset_overview_groups_confirmed_assets(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    for title, category, text in [
        ("评论 A", "AI 学习", "学习 AI 需要问题分解。"),
        ("评论 B", "Agent 架构", "Agent 需要工具和记忆。"),
    ]:
        draft = client.post("/api/v1/assets/drafts", json={"content": text, "title": title}).json()
        client.put(
            f"/api/v1/assets/drafts/{draft['id']}",
            json={"asset_kind": "opinion", "category": category, "tags": [category]},
        )
        client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={})

    overview = client.get("/api/v1/assets/overview?q=评论").json()

    assert "共找到 2 条" in overview["summary"]
    assert {item["name"] for item in overview["categories"]} == {"AI 学习", "Agent 架构"}
    assert len(overview["representative_assets"]) == 2


def test_assets_synthesize_to_knowledge_only_after_knowledge_draft_confirm(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)
    monkeypatch.setattr(
        "backend.app.api.assets._ai_synthesize_knowledge",
        lambda assets, title="", instruction="": {
            "title": title or "Agent 工具体系整理",
            "summary": "把多个 Agent 资产整理成稳定知识。",
            "content": "# Agent 工具体系\n\nAgent 需要工具注册、边界描述和自主选择。",
            "category": "Agent 架构",
            "tags": ["Agent", "工具"],
            "outline": [{"title": "工具注册", "asset_ids": [asset.id for asset in assets]}],
            "confidence": {"overall": 0.88, "synthesis": 0.86},
            "rationale": "资产都围绕 Agent 工具体系。",
        },
    )

    asset_ids = []
    for text in ["Agent 需要工具注册表。", "工具边界需要清晰描述。"]:
        draft = client.post("/api/v1/assets/drafts", json={"content": text}).json()
        confirmed = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={}).json()
        asset_ids.append(confirmed["asset"]["id"])

    assert client.get("/api/v1/knowledge?source_type=asset_synthesis").json() == []

    knowledge_draft = client.post(
        "/api/v1/assets/knowledge-drafts",
        json={"asset_ids": asset_ids, "title": "Agent 工具体系整理"},
    ).json()

    assert knowledge_draft["status"] == "pending"
    assert knowledge_draft["source_asset_ids"] == asset_ids
    assert knowledge_draft["content"].startswith("# Agent 工具体系")

    updated = client.put(
        f"/api/v1/assets/knowledge-drafts/{knowledge_draft['id']}",
        json={"title": "Agent 工具系统设计", "category": "Prism Agent"},
    ).json()
    assert updated["title"] == "Agent 工具系统设计"

    confirmed = client.post(
        f"/api/v1/assets/knowledge-drafts/{knowledge_draft['id']}/confirm",
        json={"ingest": False},
    ).json()

    assert confirmed["knowledge_item_id"]
    items = client.get("/api/v1/knowledge?source_type=asset_synthesis").json()
    assert len(items) == 1
    assert items[0]["title"] == "Agent 工具系统设计"
    assert items[0]["category"] == "Prism Agent"
