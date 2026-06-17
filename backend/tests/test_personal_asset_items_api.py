from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink, PersonalKnowledgeUnit


def test_fragment_creates_single_personal_asset_item_with_raw_and_ai_fields(client, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.assets._ai_parse_asset",
        lambda **kwargs: {
            "title": "AI UI testing prompt practice",
            "asset_kind": "opinion",
            "source": {"type": "comment", "platform": "zhihu", "url": "https://example.com/a"},
            "summary": "Use AI prompts to improve UI automation test generation.",
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
    assert item["raw_tags"] == ["testing", "prompt"]
    assert item["raw_source_platform"] == "zhihu"
    assert item["raw_keywords"]
    assert item["keyword_index_text"]
    assert item["raw_embedding_status"] == "pending"
    assert item["title"] == "AI UI testing prompt practice"
    assert item["asset_kind"] == "opinion"
    assert item["status"] == "pending_review"

    updated = client.put(
        f"/api/v1/assets/items/{item['id']}",
        json={"summary": "Edited summary", "tags": ["AI", "testing"], "category": "QA"},
    ).json()
    assert updated["summary"] == "Edited summary"
    assert updated["tags"] == ["AI", "testing"]

    confirmed = client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={}).json()
    assert confirmed["item"]["id"] == item["id"]
    assert confirmed["item"]["status"] == "confirmed"
    assert confirmed["asset"]["id"] == item["id"]
    assert confirmed["pku_count"] >= 1
    assert confirmed["canonical_count"] >= 1
    assert confirmed["governance_link_count"] >= 1

    assets = client.get("/api/v1/assets").json()
    assert [asset["id"] for asset in assets] == [item["id"]]


def test_confirmed_asset_item_settles_into_pku_and_canonical_layer(client, db_session, monkeypatch):
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
    assert payload["pku_count"] == 2
    assert payload["canonical_count"] == 1
    assert payload["governance_link_count"] == 2

    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_id=item["id"]).all()
    assert {pku.source_kind for pku in pkus} == {"personal_asset_item"}
    assert {pku.modality for pku in pkus} == {"opinion"}
    assert any("混合检索" in pku.normalized_statement for pku in pkus)

    links = db_session.query(PKUCanonicalLink).all()
    assert len(links) == 2
    assert {link.role for link in links} == {"personal_claim"}
    assert db_session.query(CanonicalKnowledgePoint).count() == 1


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
