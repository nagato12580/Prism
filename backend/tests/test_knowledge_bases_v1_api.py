# backend/tests/test_knowledge_bases_v1_api.py
def test_v1_create_and_list_use_actor_scope(client):
    created = client.post(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
        json={"name": "Manuals", "description": "Product manuals"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["owner_user_id"] == "alice"
    assert body["tenant_id"] == "tenant-a"
    assert body["name"] == "Manuals"

    other = client.get(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"},
    )
    assert all(item["owner_user_id"] == "bob" for item in other.json()["items"])
    assert body["kb_uid"] not in {item["kb_uid"] for item in other.json()["items"]}


def test_system_personal_inbox_kb_is_listed_for_fresh_actor(client, db_session):
    from backend.app.models import KnowledgeTopic

    headers = {"X-Prism-Actor": "fresh-user", "X-Prism-Tenant": "fresh-tenant"}
    assert (
        db_session.query(KnowledgeTopic)
        .filter_by(
            tenant_id="fresh-tenant",
            owner_user_id="fresh-user",
            system_type="personal_inbox",
            deleted_at=None,
        )
        .count()
        == 0
    )

    response = client.get("/api/v1/knowledge-bases", headers=headers)

    assert response.status_code == 200
    items = response.json()["items"]
    personal_inbox_items = [
        item for item in items if item["system_type"] == "personal_inbox"
    ]
    assert len(personal_inbox_items) == 1
    item = personal_inbox_items[0]
    assert item["owner_user_id"] == "fresh-user"
    assert item["tenant_id"] == "fresh-tenant"
    assert item["is_system"] is True
    assert item["delete_disabled"] is True


def test_system_personal_inbox_kb_is_persisted_after_fresh_actor_list(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from backend.app.database import Base, get_db
    from backend.app.main import create_app

    monkeypatch.setenv("SKIP_ENGINE", "1")
    engine = create_engine(f"sqlite:///{tmp_path / 'personal-inbox.db'}")
    Base.metadata.create_all(engine)
    committed_sessions = []

    class CountingSession(Session):
        def commit(self):
            committed_sessions.append(self)
            return super().commit()

    TestingSession = sessionmaker(
        bind=engine,
        class_=CountingSession,
        autocommit=False,
        autoflush=False,
    )
    app = create_app()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    headers = {
        "X-Prism-Actor": "persisted-fresh-user",
        "X-Prism-Tenant": "persisted-fresh-tenant",
    }
    try:
        with TestClient(app) as isolated_client:
            listed = isolated_client.get("/api/v1/knowledge-bases", headers=headers)

            assert listed.status_code == 200
            personal_inbox_items = [
                item
                for item in listed.json()["items"]
                if item["system_type"] == "personal_inbox"
            ]
            assert len(personal_inbox_items) == 1
            kb_uid = personal_inbox_items[0]["kb_uid"]
            assert committed_sessions

            fetched = isolated_client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=headers)

            assert fetched.status_code == 200
            assert fetched.json()["kb_uid"] == kb_uid
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_v1_error_envelope_is_structured(client):
    response = client.get("/api/v1/knowledge-bases/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert body["error"]["retryable"] is False
    assert body["error"]["trace_id"]


def test_v1_get_and_update_kb(client):
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "KB"})
    kb_uid = created.json()["kb_uid"]

    kb = client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=headers)
    assert kb.status_code == 200
    assert kb.json()["name"] == "KB"

    updated = client.patch(
        f"/api/v1/knowledge-bases/{kb_uid}",
        headers=headers,
        json={"name": "KB v2", "version": kb.json()["version"]},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "KB v2"


def test_v1_update_conflict_on_wrong_version(client):
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "KB"})
    kb_uid = created.json()["kb_uid"]

    r1 = client.patch(
        f"/api/v1/knowledge-bases/{kb_uid}",
        headers=headers,
        json={"name": "First", "version": 999},
    )
    assert r1.status_code == 409
    assert r1.json()["error"]["code"] == "VERSION_CONFLICT"


def test_v1_forbidden_actor_cannot_access_others_kb(client):
    alice_headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    bob_headers = {"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=alice_headers, json={"name": "Alice KB"})
    kb_uid = created.json()["kb_uid"]

    resp = client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=bob_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "KNOWLEDGE_ACCESS_DENIED"


def test_v1_delete_kb_tombstones_resource(client):
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "Delete Me"})
    kb_uid = created.json()["kb_uid"]

    deleted = client.delete(f"/api/v1/knowledge-bases/{kb_uid}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleting"

    listed = client.get("/api/v1/knowledge-bases", headers=headers)
    uids = [item["kb_uid"] for item in listed.json()["items"]]
    assert kb_uid not in uids

    resp = client.get(f"/api/v1/knowledge-bases/{kb_uid}", headers=headers)
    assert resp.status_code == 404


def test_system_personal_inbox_kb_is_listed_with_flags(client, db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    topic = ensure_personal_inbox_kb(
        db_session,
        tenant_id="default-user",
        owner_user_id="default-user",
    )
    db_session.commit()

    body = client.get("/api/v1/knowledge-bases").json()
    item = next(row for row in body["items"] if row["kb_uid"] == topic.kb_uid)

    assert item["name"] == "个人随手记"
    assert item["system_type"] == "personal_inbox"
    assert item["is_system"] is True
    assert item["delete_disabled"] is True


def test_system_personal_inbox_kb_cannot_be_deleted(client, db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    topic = ensure_personal_inbox_kb(
        db_session,
        tenant_id="default-user",
        owner_user_id="default-user",
    )
    db_session.commit()

    response = client.delete(f"/api/v1/knowledge-bases/{topic.kb_uid}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYSTEM_KB_DELETE_DISABLED"


def test_v1_list_supports_cursor_pagination(client):
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}

    import uuid
    prefix = f"cursor-test-{uuid.uuid4().hex[:8]}"
    for i in range(5):
        client.post("/api/v1/knowledge-bases", headers=headers, json={"name": f"{prefix}-{i}"})

    page1 = client.get("/api/v1/knowledge-bases", headers=headers, params={"limit": 2})
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["items"]) == 2
    assert p1["cursor"] is not None

    page2 = client.get("/api/v1/knowledge-bases", headers=headers, params={"cursor": p1["cursor"], "limit": 2})
    p2 = page2.json()
    assert len(p2["items"]) == 2
    assert p2["cursor"] is not None

    all_uids = {item["kb_uid"] for item in p1["items"]} | {item["kb_uid"] for item in p2["items"]}
    page3 = client.get("/api/v1/knowledge-bases", headers=headers, params={"cursor": p2["cursor"], "limit": 2})
    p3 = page3.json()
    for item in p3["items"]:
        assert item["kb_uid"] not in all_uids


def test_capability_route_is_not_swallowed_by_kb_uid(client):
    """The /capabilities/parsers route must work and not be caught by /{kb_uid}."""
    resp = client.get("/api/v1/knowledge-bases/capabilities/parsers")
    assert resp.status_code == 200
    body = resp.json()
    assert "parsers" in body
    parser_ids = {p["parser_id"] for p in body["parsers"]}
    assert parser_ids >= {"markdown", "text", "pdf", "docx", "xlsx", "pptx"}
    headers = {"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"}
    created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "VB"})
    body = created.json()
    assert body["version"] == 1

    updated = client.patch(
        f"/api/v1/knowledge-bases/{body['kb_uid']}",
        headers=headers,
        json={"name": "VB2", "version": 1},
    )
    assert updated.json()["version"] == 2
