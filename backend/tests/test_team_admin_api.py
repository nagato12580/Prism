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
