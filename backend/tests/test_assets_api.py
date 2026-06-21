def test_create_asset_draft_from_fragment_uses_ai_parse(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "Problem decomposition",
            "asset_kind": "opinion",
            "source": {"type": "comment", "platform": "zhihu", "url": ""},
            "summary": "Learning AI depends on problem decomposition.",
            "extracts": [{"type": "claim", "content": "Problem decomposition matters more than chasing models.", "confidence": 0.91}],
            "tags": ["AI", "learning"],
            "category": "AI learning",
            "suggested_relations": [],
            "suggested_extensions": [{"title": "How to train problem decomposition", "confidence": 0.78}],
            "confidence": {"overall": 0.86, "classification": 0.9, "source": 0.7, "extraction": 0.91},
            "rationale": "This is an opinion fragment.",
        },
    )

    response = client.post(
        "/api/v1/assets/drafts",
        json={
            "content": "Learning AI is less about chasing models and more about problem decomposition.",
            "source_type": "comment",
            "source_platform": "zhihu",
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["raw_text"].startswith("Learning AI")
    assert draft["title"] == "Problem decomposition"
    assert draft["asset_kind"] == "opinion"
    assert draft["source_platform"] == "zhihu"
    assert draft["confidence"]["overall"] == 0.86
    assert draft["suggested_extensions"][0]["title"] == "How to train problem decomposition"


def test_asset_draft_can_be_edited_and_confirmed_to_personal_asset(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    draft = client.post(
        "/api/v1/assets/drafts",
        json={"content": "This GitHub project can be used as an agent tool registry reference.", "source_platform": "GitHub"},
    ).json()

    updated = client.put(
        f"/api/v1/assets/drafts/{draft['id']}",
        json={
            "title": "Agent tool registry reference",
            "asset_kind": "resource",
            "category": "Agent architecture",
            "tags": ["Agent", "tools"],
            "summary": "A reference resource for agent tool registries.",
        },
    ).json()

    assert updated["title"] == "Agent tool registry reference"
    assert updated["asset_kind"] == "resource"
    assert updated["tags"] == ["Agent", "tools"]

    response = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["status"] == "confirmed"
    assert payload["asset"]["title"] == "Agent tool registry reference"
    assert payload["asset"]["asset_kind"] == "resource"
    assert payload["asset"]["source_draft_id"] == draft["id"]

    assets = client.get("/api/v1/assets/search?q=Agent").json()
    assert len(assets) == 1
    assert assets[0]["title"] == "Agent tool registry reference"


def test_asset_overview_groups_confirmed_assets(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    for title, category, text in [
        ("Comment A", "AI learning", "Learning AI requires problem decomposition."),
        ("Comment B", "Agent architecture", "Agents need tools and memory."),
    ]:
        draft = client.post("/api/v1/assets/drafts", json={"content": text, "title": title}).json()
        client.put(
            f"/api/v1/assets/drafts/{draft['id']}",
            json={"asset_kind": "opinion", "category": category, "tags": [category]},
        )
        client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={})

    overview = client.get("/api/v1/assets/overview?q=Comment").json()

    assert "2" in overview["summary"]
    assert {item["name"] for item in overview["categories"]} == {"AI learning", "Agent architecture"}
    assert len(overview["representative_assets"]) == 2


def test_assets_synthesize_to_personal_asset_unit_and_governance_without_knowledge_item(client, monkeypatch):
    from backend.app.services.knowledge_governance import GovernanceResult

    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)
    monkeypatch.setattr(
        "backend.app.api.assets._ai_synthesize_knowledge",
        lambda assets, title="", instruction="": {
            "title": title or "Agent tool system",
            "summary": "Combine multiple agent assets into stable knowledge.",
            "content": "# Agent tool system\n\nAgents need tool registries, boundaries, and autonomous selection.",
            "category": "Agent architecture",
            "tags": ["Agent", "tools"],
            "outline": [{"title": "Tool registry", "asset_ids": [asset.id for asset in assets]}],
            "confidence": {"overall": 0.88, "synthesis": 0.86},
            "rationale": "The assets all concern agent tool systems.",
        },
    )
    monkeypatch.setattr(
        "backend.app.api.assets.settle_personal_asset_unit_to_governance",
        lambda db, unit: GovernanceResult(pku_count=2, canonical_count=2, link_count=2, pku_relation_count=1),
    )

    asset_ids = []
    for text in ["Agents need a tool registry.", "Tool boundaries need clear descriptions."]:
        draft = client.post("/api/v1/assets/drafts", json={"content": text}).json()
        confirmed = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={}).json()
        asset_ids.append(confirmed["asset"]["id"])

    assert client.get("/api/v1/knowledge?source_type=asset_synthesis").json() == []

    asset_unit = client.post(
        "/api/v1/assets/personal_asset_units",
        json={"asset_ids": asset_ids, "title": "Agent tool system"},
    ).json()

    assert asset_unit["status"] == "pending_review"
    assert asset_unit["source_asset_ids"] == asset_ids
    assert asset_unit["content"].startswith("# Agent tool system")

    updated = client.put(
        f"/api/v1/assets/personal_asset_units/{asset_unit['id']}",
        json={"title": "Agent system design", "category": "Prism Agent"},
    ).json()
    assert updated["title"] == "Agent system design"

    confirmed = client.post(
        f"/api/v1/assets/personal_asset_units/{asset_unit['id']}/confirm",
        json={},
    ).json()

    assert confirmed["unit"]["status"] == "confirmed"
    assert confirmed["unit"]["title"] == "Agent system design"
    assert confirmed["pku_count"] == 2
    assert confirmed["canonical_count"] == 2
    assert confirmed["governance_link_count"] == 2
    assert confirmed["pku_relation_count"] == 1
    items = client.get("/api/v1/knowledge?source_type=asset_synthesis").json()
    assert items == []
