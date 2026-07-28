import pytest

from backend.app.models.asset import PersonalAssetUnit


@pytest.fixture(autouse=True)
def _stub_memory_recall(monkeypatch):
    """避免资产解析测试真实调用向量召回/LLM 实体抽取/向量索引。"""
    monkeypatch.setattr("backend.app.api.assets.recall_preference_context", lambda db, content, **kw: "")
    monkeypatch.setattr("backend.app.api.assets.extract_and_link_entities", lambda *a, **kw: [])
    monkeypatch.setattr("backend.app.api.assets._index_entry_vector", lambda entry: None)


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


def test_create_asset_draft_injects_user_preferences_into_parse(client, monkeypatch):
    captured_prefs = {}

    def fake_parse(**kwargs):
        captured_prefs["user_preferences"] = kwargs.get("user_preferences", "")
        return {
            "title": "Lightweight design",
            "asset_kind": "opinion",
            "summary": "Prefers lightweight.",
            "tags": ["design"],
            "confidence": {"overall": 0.8, "classification": 0.8, "source": 0.7, "extraction": 0.8},
        }

    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", fake_parse)
    monkeypatch.setattr(
        "backend.app.api.assets.recall_preference_context",
        lambda db, content, **kw: "【偏好】用户偏好轻量方案",
    )

    response = client.post(
        "/api/v1/assets/drafts",
        json={"content": "Design a new feature with minimal dependencies."},
    )

    assert response.status_code == 200
    assert captured_prefs["user_preferences"] == "【偏好】用户偏好轻量方案"


def test_create_asset_draft_skips_preferences_when_recall_empty(client, monkeypatch):
    captured_prefs = {}

    def fake_parse(**kwargs):
        captured_prefs["user_preferences"] = kwargs.get("user_preferences", "")
        return {
            "title": "t",
            "asset_kind": "idea",
            "summary": "s",
            "tags": [],
            "confidence": {"overall": 0.5, "classification": 0.5, "source": 0.5, "extraction": 0.5},
        }

    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", fake_parse)
    monkeypatch.setattr("backend.app.api.assets.recall_preference_context", lambda db, content, **kw: "")

    response = client.post("/api/v1/assets/drafts", json={"content": "Some content."})

    assert response.status_code == 200
    assert captured_prefs["user_preferences"] == ""


def test_confirm_asset_with_create_memory_maps_kind_to_memory_type(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)

    draft = client.post(
        "/api/v1/assets/drafts",
        json={"content": "The user wants to ship Prism v2 by August.", "title": "Ship Prism v2"},
    ).json()
    client.put(
        f"/api/v1/assets/drafts/{draft['id']}",
        json={"title": "Ship Prism v2", "asset_kind": "goal", "summary": "User goal: ship Prism v2."},
    )

    response = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={"create_memory": True})

    assert response.status_code == 200
    memories = client.get("/api/v1/memories").json()
    assert len(memories) == 1
    assert memories[0]["title"] == "Ship Prism v2"
    assert memories[0]["memory_type"] == "goal"
    assert memories[0]["source_review_id"] == draft["id"]


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
    assert confirmed["pku_count"] == 0
    assert confirmed["canonical_count"] == 0
    assert confirmed["governance_link_count"] == 0
    assert confirmed["pku_relation_count"] == 0
    items = client.get("/api/v1/knowledge?source_type=asset_synthesis").json()
    assert items == []


def test_confirm_personal_asset_unit_schedules_entity_graph_ingestion(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        id="unit-1",
        user_id="default-user",
        title="GraphRAG retrospective",
        summary="Entity summary",
        content="Entity-driven notes",
        status="pending_review",
    )
    db_session.add(unit)
    db_session.commit()

    calls = {}

    def fake_schedule(unit_id):
        calls["scheduled"] = unit_id

    monkeypatch.setattr("backend.app.api.assets._schedule_asset_unit_entity_graph_ingestion", fake_schedule)

    response = client.post("/api/v1/assets/personal_asset_units/unit-1/confirm", json={})

    assert response.status_code == 200
    assert calls["scheduled"] == "unit-1"


def test_confirm_personal_asset_unit_survives_entity_graph_schedule_failure(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        id="unit-2",
        user_id="default-user",
        title="Failure tolerant unit",
        summary="Entity summary",
        content="Entity-driven notes",
        status="pending_review",
    )
    db_session.add(unit)
    db_session.commit()

    monkeypatch.setattr(
        "backend.app.api.assets._schedule_asset_unit_entity_graph_ingestion",
        lambda unit_id: (_ for _ in ()).throw(RuntimeError("thread start failed")),
    )

    response = client.post("/api/v1/assets/personal_asset_units/unit-2/confirm", json={})

    assert response.status_code == 200
    assert response.json()["unit"]["status"] == "confirmed"


def test_run_asset_unit_entity_graph_ingestion_executes_with_fresh_session(db_session, monkeypatch):
    unit = PersonalAssetUnit(
        id="unit-bg",
        user_id="default-user",
        title="Background ingest unit",
        summary="Entity summary",
        content="Entity-driven notes",
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()

    calls = {}

    class FakeSession:
        closed = False

        def __init__(self, wrapped):
            self.wrapped = wrapped

        def query(self, *args, **kwargs):
            return self.wrapped.query(*args, **kwargs)

        def commit(self):
            return self.wrapped.commit()

        def rollback(self):
            return self.wrapped.rollback()

        def close(self):
            type(self).closed = True
            self.wrapped.close()

    def fake_session_local():
        return FakeSession(db_session)

    def fake_ingest(db, loaded_unit):
        calls["unit_id"] = loaded_unit.id
        calls["status"] = loaded_unit.status

    monkeypatch.setattr("backend.app.api.assets.SessionLocal", fake_session_local)
    monkeypatch.setattr("backend.app.api.assets._ingest_asset_unit_entity_graph", fake_ingest)

    from backend.app.api import assets as assets_api

    assets_api._run_asset_unit_entity_graph_ingestion("unit-bg")

    assert calls == {"unit_id": "unit-bg", "status": "confirmed"}
    assert FakeSession.closed is True


def test_confirm_personal_asset_unit_does_not_run_governance_settlement(
    client, db_session, monkeypatch
):
    unit = PersonalAssetUnit(
        id="unit-async",
        user_id="default-user",
        title="Async confirm unit",
        summary="Entity summary",
        content="Entity-driven notes",
        status="pending_review",
    )
    db_session.add(unit)
    db_session.commit()

    monkeypatch.setattr(
        "backend.app.api.assets._ingest_asset_unit_entity_graph",
        lambda db, unit: None,
    )

    response = client.post("/api/v1/assets/personal_asset_units/unit-async/confirm", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"]["status"] == "confirmed"
    assert payload["pku_count"] == 0
    assert payload["canonical_count"] == 0
    assert payload["governance_link_count"] == 0
    assert payload["pku_relation_count"] == 0


def test_confirm_personal_asset_unit_syncs_to_personal_inbox(client, db_session, monkeypatch):
    from backend.app.models import KnowledgeFile
    from backend.app.services import personal_inbox

    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)
    monkeypatch.setattr(
        "backend.app.api.assets._ai_synthesize_knowledge",
        lambda assets, title="", instruction="": {
            "title": title or "Unit",
            "summary": "Unit summary",
            "content": "Unit content",
            "tags": [],
            "outline": [],
            "confidence": {},
            "rationale": "",
        },
    )
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)

    item = client.post(
        "/api/v1/assets/items",
        json={"raw_text": "fragment content", "raw_title": "Fragment"},
    ).json()
    client.post(f"/api/v1/assets/items/{item['id']}/confirm", json={})
    unit = client.post(
        "/api/v1/assets/personal_asset_units",
        json={"asset_ids": [item["id"]], "title": "Unit"},
    ).json()

    response = client.post(f"/api/v1/assets/personal_asset_units/{unit['id']}/confirm")

    assert response.status_code == 200
    file_row = (
        db_session.query(KnowledgeFile)
        .filter_by(source_kind="personal_asset_unit", source_id=unit["id"])
        .one()
    )
    assert file_row.tenant_id == "default-user"
    assert file_row.user_id == "default-user"
    assert file_row.original_filename.endswith(".md")
    assert file_row.content_text and "Unit content" in file_row.content_text


def test_update_confirmed_personal_asset_unit_resyncs_existing_file(client, db_session, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox

    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)
    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="default-user",
        title="Old",
        summary="Old summary",
        content="Old content",
        source_asset_ids=[],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()
    personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="default-user",
        owner_user_id="default-user",
        publish=False,
    )
    file_uid = db_session.query(KnowledgeFile).filter_by(source_id="unit-a").one().file_uid

    response = client.put(
        "/api/v1/assets/personal_asset_units/unit-a",
        json={"title": "New", "content": "New content"},
    )

    assert response.status_code == 200
    updated = db_session.query(KnowledgeFile).filter_by(source_id="unit-a").one()
    assert updated.file_uid == file_uid
    assert "New content" in updated.content_text
