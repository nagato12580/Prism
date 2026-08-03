# backend/tests/test_team_admin_api.py
import pytest

from backend.app.models import KnowledgeAccessAuditLog, TeamMember, TeamRole
from backend.app.security.actor import ActorContext
from backend.app.services.team_members import (
    TeamMemberConflict,
    TeamMemberLastAdminDenied,
    TeamMemberNotFound,
    TeamMemberSelfOperationDenied,
    add_team_member,
    list_team_members,
    remove_team_member,
    update_team_member,
)


def actor(user_id: str, tenant_id: str = "tenant-a") -> ActorContext:
    return ActorContext(actor_id=user_id, tenant_id=tenant_id, roles=())


def seed_member(db_session, user_id: str, role: str = TeamRole.MEMBER.value, status: str = "active") -> TeamMember:
    row = TeamMember(tenant_id="tenant-a", user_id=user_id, role=role, status=status)
    db_session.add(row)
    db_session.commit()
    return row


def test_list_returns_tenant_scoped_members(db_session):
    seed_member(db_session, "alice", TeamRole.ADMIN.value)
    seed_member(db_session, "bob")
    other = TeamMember(tenant_id="tenant-b", user_id="carol", role=TeamRole.MEMBER.value, status="active")
    db_session.add(other)
    db_session.commit()

    result = list_team_members(db_session, tenant_id="tenant-a")
    assert {m.user_id for m in result} == {"alice", "bob"}


def test_add_member_validates_role_and_status(db_session):
    member = add_team_member(
        db_session,
        actor=actor("admin"),
        user_id="bob",
        role=TeamRole.ADMIN.value,
        status="active",
    )
    assert member.user_id == "bob"
    assert member.role == TeamRole.ADMIN.value
    assert member.status == "active"


def test_add_duplicate_raises_conflict(db_session):
    seed_member(db_session, "bob")
    with pytest.raises(TeamMemberConflict):
        add_team_member(db_session, actor=actor("admin"), user_id="bob", role=TeamRole.MEMBER.value)


def test_update_member_changes_role_and_status(db_session):
    seed_member(db_session, "bob")
    updated = update_team_member(
        db_session,
        actor=actor("admin"),
        user_id="bob",
        role=TeamRole.ADMIN.value,
        status="disabled",
    )
    assert updated.role == TeamRole.ADMIN.value
    assert updated.status == "disabled"


def test_update_self_raises_self_operation_denied(db_session):
    seed_member(db_session, "admin", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberSelfOperationDenied):
        update_team_member(db_session, actor=actor("admin"), user_id="admin", role=TeamRole.MEMBER.value)


def test_demote_last_active_admin_raises_last_admin_denied(db_session):
    # actor "admin" has no TeamMember row, so the self-op guard
    # (user_id == actor.actor_id) does not fire; only "boss" is seeded as the
    # sole active admin, so demoting it genuinely hits the last-admin guard.
    seed_member(db_session, "boss", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberLastAdminDenied):
        update_team_member(db_session, actor=actor("admin"), user_id="boss", role=TeamRole.MEMBER.value)


def test_disable_last_active_admin_raises_last_admin_denied(db_session):
    # Same actor/target split as above: actor "admin" != target "boss", so the
    # self-op guard is bypassed and the disabling-last-admin branch fires.
    seed_member(db_session, "boss", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberLastAdminDenied):
        update_team_member(db_session, actor=actor("admin"), user_id="boss", status="disabled")


def test_remove_member_ok(db_session):
    seed_member(db_session, "admin", TeamRole.ADMIN.value)
    seed_member(db_session, "bob")
    remove_team_member(db_session, actor=actor("admin"), user_id="bob")
    assert [m.user_id for m in list_team_members(db_session, tenant_id="tenant-a")] == ["admin"]


def test_remove_last_admin_raises_last_admin_denied(db_session):
    seed_member(db_session, "boss", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberLastAdminDenied):
        remove_team_member(db_session, actor=actor("admin"), user_id="boss")


def test_remove_self_raises_self_operation_denied(db_session):
    seed_member(db_session, "admin", TeamRole.ADMIN.value)
    seed_member(db_session, "other", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberSelfOperationDenied):
        remove_team_member(db_session, actor=actor("admin"), user_id="admin")


def test_remove_missing_member_raises_not_found(db_session):
    with pytest.raises(TeamMemberNotFound):
        remove_team_member(db_session, actor=actor("admin"), user_id="ghost")


def test_mutations_write_audit_logs(db_session):
    seed_member(db_session, "admin", TeamRole.ADMIN.value)
    add_team_member(db_session, actor=actor("admin"), user_id="bob", role=TeamRole.MEMBER.value)
    update_team_member(db_session, actor=actor("admin"), user_id="bob", role=TeamRole.ADMIN.value)
    remove_team_member(db_session, actor=actor("admin"), user_id="bob")

    actions = [row.action for row in db_session.query(KnowledgeAccessAuditLog).all()]
    assert "team_member.add" in actions
    assert "team_member.update" in actions
    assert "team_member.remove" in actions


# ---------------------------------------------------------------------------
# API tests (Task 2)
# ---------------------------------------------------------------------------

from backend.app.models import TeamMember, TeamRole


def auth_headers(user: str, tenant: str = "tenant-a", roles: str = ""):
    headers = {"X-Prism-Actor": user, "X-Prism-Tenant": tenant}
    if roles:
        headers["X-Prism-Roles"] = roles
    return headers


def test_members_endpoints_require_admin(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="bob", role=TeamRole.MEMBER.value, status="active"))
    db_session.commit()

    for method, path, kwargs in [
        ("get", "/api/v1/team/admin/members", {}),
        ("post", "/api/v1/team/admin/members", {"json": {"user_id": "carol", "role": "member"}}),
        ("put", "/api/v1/team/admin/members/carol", {"json": {"role": "admin"}}),
        ("delete", "/api/v1/team/admin/members/carol", {}),
    ]:
        response = getattr(client, method)(path, headers=auth_headers("bob"), **kwargs)
        assert response.status_code == 403, f"{method.upper()} {path} should be 403 for non-admin"


def test_admin_can_add_list_update_remove_member(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    added = client.post(
        "/api/v1/team/admin/members",
        json={"user_id": "bob", "role": "member", "status": "active"},
        headers=auth_headers("admin"),
    )
    assert added.status_code == 200
    assert added.json()["user_id"] == "bob"
    assert added.json()["role"] == "member"

    listed = client.get("/api/v1/team/admin/members", headers=auth_headers("admin"))
    assert listed.status_code == 200
    assert {m["user_id"] for m in listed.json()["items"]} == {"admin", "bob"}
    assert listed.json()["total"] == 2

    updated = client.put(
        "/api/v1/team/admin/members/bob",
        json={"role": "admin"},
        headers=auth_headers("admin"),
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"

    removed = client.delete("/api/v1/team/admin/members/bob", headers=auth_headers("admin"))
    assert removed.status_code == 200
    assert removed.json()["detail"] == "deleted"


def test_admin_cannot_operate_on_self(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    response = client.put(
        "/api/v1/team/admin/members/admin",
        json={"role": "member"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELF_OPERATION_DENIED"


def test_admin_cannot_remove_last_admin(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    # A distinct admin (via the header roles fast-path) removes the only
    # active admin in the DB. Deleting yourself is always SELF_OPERATION_DENIED
    # (the service checks self-op before the last-admin guard), so a separate
    # actor is required to exercise the LAST_ADMIN guard.
    response = client.delete(
        "/api/v1/team/admin/members/admin",
        headers=auth_headers("boss", roles="admin"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN_OPERATION_DENIED"


def test_post_member_invalid_role_returns_422(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    response = client.post(
        "/api/v1/team/admin/members",
        json={"user_id": "carol", "role": "superadmin"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEMBER_FIELD"


def test_post_member_duplicate_returns_409(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="carol", role=TeamRole.MEMBER.value, status="active"))
    db_session.commit()

    response = client.post(
        "/api/v1/team/admin/members",
        json={"user_id": "carol", "role": "member"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MEMBER_CONFLICT"


def test_put_member_invalid_role_returns_422(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="bob", role=TeamRole.MEMBER.value, status="active"))
    db_session.commit()

    response = client.put(
        "/api/v1/team/admin/members/bob",
        json={"role": "superadmin"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEMBER_FIELD"
