from types import SimpleNamespace


def test_refresh_child_ckp_retrieval_artifacts_calls_existing_private_refresh(monkeypatch):
    from backend.app.services import knowledge_governance as kg

    calls = []

    def fake_refresh(db, *, child_ckp, parent_ckp_id):
        calls.append(
            {
                "db": db,
                "child_ckp": child_ckp,
                "parent_ckp_id": parent_ckp_id,
            }
        )

    monkeypatch.setattr(kg, "_refresh_child_ckp_retrieval_meta", fake_refresh)
    db = object()
    child_ckp = SimpleNamespace(id="child-1")

    result = kg.refresh_child_ckp_retrieval_artifacts(
        db,
        child_ckp=child_ckp,
        parent_ckp_id="parent-1",
    )

    assert calls == [
        {
            "db": db,
            "child_ckp": child_ckp,
            "parent_ckp_id": "parent-1",
        }
    ]
    assert result == {
        "child_ckp_id": "child-1",
        "parent_ckp_id": "parent-1",
        "status": "refreshed",
    }


def test_refresh_parent_ckp_aggregate_artifacts_calls_existing_private_refresh(monkeypatch):
    from backend.app.services import knowledge_governance as kg

    calls = []

    def fake_refresh(db, *, parent_ckp):
        calls.append(
            {
                "db": db,
                "parent_ckp": parent_ckp,
            }
        )

    monkeypatch.setattr(kg, "_refresh_parent_ckp_aggregate_terms", fake_refresh)
    db = object()
    parent_ckp = SimpleNamespace(id="parent-1")

    result = kg.refresh_parent_ckp_aggregate_artifacts(db, parent_ckp=parent_ckp)

    assert calls == [
        {
            "db": db,
            "parent_ckp": parent_ckp,
        }
    ]
    assert result == {
        "parent_ckp_id": "parent-1",
        "status": "refreshed",
    }
