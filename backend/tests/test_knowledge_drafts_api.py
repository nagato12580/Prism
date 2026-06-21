def test_personal_asset_units_can_be_listed_and_retrieved(client, monkeypatch):
    monkeypatch.setattr("backend.app.api.assets._ai_parse_asset", lambda **kwargs: None)
    monkeypatch.setattr("backend.app.api.assets._ai_synthesize_knowledge", lambda assets, title="", instruction="": None)

    draft = client.post(
        "/api/v1/assets/drafts",
        json={"content": "Asset fragments should be confirmed before synthesis."},
    ).json()
    confirmed = client.post(f"/api/v1/assets/drafts/{draft['id']}/confirm", json={}).json()

    asset_unit = client.post(
        "/api/v1/assets/personal_asset_units",
        json={"asset_ids": [confirmed["asset"]["id"]], "title": "Knowledge loop"},
    ).json()

    pending = client.get("/api/v1/assets/personal_asset_units?status=pending_review").json()
    assert [item["id"] for item in pending] == [asset_unit["id"]]

    detail = client.get(f"/api/v1/assets/personal_asset_units/{asset_unit['id']}").json()
    assert detail["title"] == "Knowledge loop"
    assert detail["source_asset_ids"] == [confirmed["asset"]["id"]]
