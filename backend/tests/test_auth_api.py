from datetime import timedelta

from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now


def test_auth_models_round_trip(db_session):
    user = User(username="alice", display_name="Alice", status="active")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    session = AuthSession(user_id=user.id, created_by_mode="dev_login")
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    assert session.user_id == user.id
    assert session.id
    assert user.username == "alice"


def test_dev_login_sets_cookie_and_returns_me_payload(client):
    response = client.post("/api/v1/auth/login/dev", json={"username": "alice", "display_name": "Alice"})
    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert "prism_session" in response.cookies


def test_me_prefers_session_over_conflicting_header_fallback(client):
    login = client.post("/api/v1/auth/login/dev", json={"username": "alice"})
    assert login.status_code == 200

    response = client.get(
        "/api/v1/auth/me",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-b"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert response.json()["auth_mode"] == "session"


def test_me_uses_header_fallback_when_enabled(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={"X-Prism-Actor": "carol", "X-Prism-Tenant": "tenant-c"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "carol"
    assert response.json()["auth_mode"] == "header-fallback"


def test_logout_clears_current_session(client):
    client.post("/api/v1/auth/login/dev", json={"username": "alice"})
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 401


def test_me_rejects_expired_session(client, db_session):
    user = User(username="expired-user", display_name="Expired", status="active")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    row = AuthSession(user_id=user.id, expires_at=local_now() - timedelta(hours=1), created_by_mode="dev_login")
    db_session.add(row)
    db_session.commit()

    client.cookies.set("prism_session", row.id)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_rejects_disabled_session_user(client, db_session):
    user = User(username="disabled-user", display_name="Disabled", status="disabled")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    row = AuthSession(user_id=user.id, expires_at=local_now() + timedelta(hours=1), created_by_mode="dev_login")
    db_session.add(row)
    db_session.commit()

    client.cookies.set("prism_session", row.id)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 403
