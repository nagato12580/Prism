from backend.app.models import CanonicalKnowledgePoint, PersonalAssetItem, PKUCanonicalLink, PersonalKnowledgeUnit


def test_fragment_creates_single_personal_asset_item_with_raw_and_ai_fields(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "AI UI testing prompt practice",
            "asset_kind": "opinion",
            "source": {"type": "comment", "platform": "zhihu", "url": "https://example.com/a"},
            "summary": "Use AI prompts to improve UI automation test generation.",
            "rewritten_content": "AI-assisted UI test generation works better when prompts include page state, locator constraints, and assertion intent.",
            "extracts": [{"type": "claim", "content": "Prompt context improves UI automation reliability.", "confidence": 0.9}],
            "tags": ["AI testing", "UI automation"],
            "category": "Testing",
            "suggested_relations": [],
            "suggested_extensions": [{"title": "Prompt template for UI automation", "confidence": 0.7}],
            "confidence": {"overall": 0.86, "classification": 0.9, "source": 0.8, "extraction": 0.88},
            "rationale": "The fragment describes a reusable testing practice.",
        },
    )

    response = client.post(
        "/api/v1/assets/items",
        json={
            "raw_text": "AI can help generate Playwright UI automation tests when prompts include page state.",
            "raw_title": "Saved comment",
            "raw_source_type": "comment",
            "raw_source_platform": "zhihu",
            "raw_source_url": "https://example.com/a",
            "raw_tags": ["testing", "prompt"],
        },
    )

    assert response.status_code == 200
    item = response.json()
    assert item["raw_text"].startswith("AI can help")
    assert "body" not in item
    assert item["raw_tags"] == ["testing", "prompt"]
    assert item["raw_source_platform"] == "zhihu"
    assert item["raw_keywords"]
    assert item["keyword_index_text"]
    assert item["raw_embedding_status"] == "pending"
    assert item["title"] == "AI UI testing prompt practice"
    assert item["asset_kind"] == "opinion"
    assert item["rewritten_content"].startswith("AI-assisted UI test generation")
    assert item["status"] == "pending_review"

    updated = client.put(
        f"/api/v1/assets/items/{item['id']}",
        json={
            "raw_text": "Edited original fragment about AI-assisted UI test prompts.",
            "summary": "Edited summary",
            "rewritten_content": "Edited rewritten content for the asset.",
            "tags": ["AI", "testing"],
            "category": "QA",
        },
    ).json()
    assert updated["raw_text"] == "Edited original fragment about AI-assisted UI test prompts."
    assert updated["summary"] == "Edited summary"
    assert updated["rewritten_content"] == "Edited rewritten content for the asset."
    assert updated["tags"] == ["AI", "testing"]

    confirmed = client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={}).json()
    assert confirmed["item"]["id"] == item["id"]
    assert confirmed["item"]["status"] == "confirmed"
    assert confirmed["asset"]["rewritten_content"] == "Edited rewritten content for the asset."
    assert confirmed["asset"]["id"] == item["id"]
    assert confirmed["pku_count"] == 0
    assert confirmed["canonical_count"] == 0
    assert confirmed["governance_link_count"] == 0

    assets = client.get("/api/v1/assets").json()
    assert [asset["id"] for asset in assets] == [item["id"]]
    assert assets[0]["rewritten_content"] == "Edited rewritten content for the asset."


def test_confirmed_asset_search_matches_rewritten_content(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "Raw title",
            "asset_kind": "idea",
            "source": {"type": "manual", "platform": "", "url": ""},
            "summary": "Short summary",
            "rewritten_content": "Use durable acceptance criteria when refining interview question banks.",
            "extracts": [],
            "tags": ["interview"],
            "category": "Hiring",
            "suggested_relations": [],
            "suggested_extensions": [],
            "confidence": {"overall": 0.8},
            "rationale": "The rewritten content is the searchable knowledge form.",
        },
    )

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "rough notes"},
    ).json()
    client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={})

    results = client.get("/api/v1/assets/search?q=acceptance%20criteria").json()

    assert [result["asset_id"] for result in results] == [item["id"]]


def test_delete_asset_item_hard_deletes_pending_fragment(client, db_session, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "Temporary inbox fragment to discard."},
    ).json()

    response = client.delete(f"/api/v1/assets/items/{item['id']}")

    assert response.status_code == 200
    assert response.json() == {"detail": "deleted"}
    assert client.get("/api/v1/assets/items?status=pending_review").json() == []
    assert db_session.query(PersonalAssetItem).filter_by(id=item["id"]).first() is None
    assert client.put(f"/api/v1/assets/items/{item['id']}", json={"title": "Should not exist"}).status_code == 404


def test_delete_asset_item_rejects_confirmed_asset(client, db_session, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "Confirmed fragment should not be deleted through reject."},
    ).json()
    client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={})

    response = client.delete(f"/api/v1/assets/items/{item['id']}")

    assert response.status_code == 409
    assert db_session.query(PersonalAssetItem).filter_by(id=item["id"]).first() is not None


def test_confirmed_asset_item_does_not_settle_into_pku_and_canonical_layer(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "混合检索经验",
            "asset_kind": "opinion",
            "source": {"type": "comment", "platform": "manual", "url": ""},
            "summary": "个人知识库不能只靠向量检索。",
            "extracts": [{"type": "claim", "content": "个人知识库需要结合关键词和向量的混合检索。", "confidence": 0.88}],
            "tags": ["个人知识库", "混合检索"],
            "category": "知识治理",
            "suggested_relations": [],
            "suggested_extensions": [],
            "confidence": {"overall": 0.86, "extraction": 0.88},
            "rationale": "用户表达了个人知识库检索策略观点。",
        },
    )

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "个人知识库不能只靠向量检索，应该结合关键词和 metadata filter。"},
    ).json()
    response = client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["pku_count"] == 0
    assert payload["canonical_count"] == 0
    assert payload["governance_link_count"] == 0

    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_id=item["id"]).all()
    assert pkus == []

    links = db_session.query(PKUCanonicalLink).all()
    assert len(links) == 0
    assert db_session.query(CanonicalKnowledgePoint).count() == 0


def test_legacy_draft_endpoints_alias_personal_asset_items(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    draft = client.post(
        "/api/v1/assets/drafts",
        json={"content": "A small fragment about AI test prompts.", "source_platform": "manual"},
    ).json()

    assert draft["raw_text"] == "A small fragment about AI test prompts."
    assert draft["status"] == "pending_review"

    confirmed = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={}).json()
    assert confirmed["draft"]["id"] == draft["id"]
    assert confirmed["draft"]["status"] == "confirmed"
    assert confirmed["asset"]["id"] == draft["id"]


def test_confirm_extensions_are_stored_on_personal_asset_item(client, db_session, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "A fragment with a follow-up research direction."},
    ).json()

    response = client.post(
        f"/api/v1/assets/items/{item['id']}/confirm",
        json={
            "confirm_extensions": [
                {
                    "title": "Research retrieval evaluation",
                    "reason": "Useful next topic",
                    "suggested_kind": "knowledge",
                    "confidence": 0.8,
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["extension_count"] == 1
    assert payload["item"]["suggested_extensions"][0]["title"] == "Research retrieval evaluation"
    assert payload["item"]["suggested_extensions"][0]["status"] == "confirmed"
