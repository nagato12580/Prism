from backend.app.models import AuthSession, User


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
