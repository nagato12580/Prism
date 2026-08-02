# backend/tests/test_knowledge_access.py
import pytest

from backend.app.models import (
    KnowledgeAccessAuditLog,
    KnowledgeBaseMembership,
    KnowledgeBaseRole,
    KnowledgeGovernanceStatus,
    KnowledgeTopic,
    TeamMember,
    TeamRole,
)
from backend.app.security.actor import ActorContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def actor(user_id: str, tenant_id: str = "tenant-a", roles: tuple[str, ...] = ()) -> ActorContext:
    return ActorContext(actor_id=user_id, tenant_id=tenant_id, roles=roles)


def team_member(db_session, user_id: str, role: str = TeamRole.MEMBER.value):
    row = TeamMember(tenant_id="tenant-a", user_id=user_id, role=role, status="active")
    db_session.add(row)
    db_session.commit()
    return row


def kb(db_session, owner: str, status: str = KnowledgeGovernanceStatus.PERSONAL.value, name: str = "KB"):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id=owner,
        name=name,
        governance_status=status,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def grant(db_session, topic, user_id: str, role: str):
    row = KnowledgeBaseMembership(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        user_id=user_id,
        role=role,
        granted_by="admin",
    )
    db_session.add(row)
    db_session.commit()
    return row


# ---------------------------------------------------------------------------
# Existing tests (kept from phase one)
# ---------------------------------------------------------------------------

def test_policy_allows_owner_read(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Shared",
    )
    db_session.add(topic)
    db_session.commit()

    actor_ctx = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    result = KnowledgeAccessPolicy(db_session).require_read(actor_ctx, topic.kb_uid)
    assert result.kb_uid == topic.kb_uid


def test_policy_rejects_non_owner(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Private",
    )
    db_session.add(topic)
    db_session.commit()

    actor_ctx = ActorContext(actor_id="other", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeAccessDenied):
        KnowledgeAccessPolicy(db_session).require_read(actor_ctx, topic.kb_uid)


def test_policy_rejects_wrong_tenant(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Tenant-isolated",
    )
    db_session.add(topic)
    db_session.commit()

    actor_ctx = ActorContext(actor_id="owner", tenant_id="tenant-b", roles=())
    with pytest.raises(KnowledgeAccessDenied):
        KnowledgeAccessPolicy(db_session).require_read(actor_ctx, topic.kb_uid)


def test_policy_raises_not_found_for_missing_kb(db_session):
    from backend.app.services.knowledge_access import KnowledgeNotFound, KnowledgeAccessPolicy

    actor_ctx = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeNotFound):
        KnowledgeAccessPolicy(db_session).require_read(actor_ctx, "nonexistent")


def test_policy_excludes_deleted_topic(db_session):
    from backend.app.services.knowledge_access import KnowledgeNotFound, KnowledgeAccessPolicy
    from backend.app.utils.time import local_now

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Deleted KB",
        deleted_at=local_now(),
    )
    db_session.add(topic)
    db_session.commit()

    actor_ctx = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeNotFound):
        KnowledgeAccessPolicy(db_session).require_read(actor_ctx, topic.kb_uid)


def test_rbac_models_round_trip(db_session):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Private KB",
    )
    member = TeamMember(
        tenant_id="tenant-a",
        user_id="owner",
        role=TeamRole.MEMBER.value,
        status="active",
    )
    db_session.add_all([topic, member])
    db_session.commit()

    assert topic.governance_status == KnowledgeGovernanceStatus.PERSONAL.value

    membership = KnowledgeBaseMembership(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="owner",
        role=KnowledgeBaseRole.EDITOR.value,
        granted_by="admin",
    )
    audit = KnowledgeAccessAuditLog(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        actor_id="admin",
        action="membership.grant",
        target_user_id="owner",
        before=None,
        after={"role": KnowledgeBaseRole.EDITOR.value},
    )
    db_session.add_all([membership, audit])
    db_session.commit()

    stored = db_session.query(KnowledgeBaseMembership).filter_by(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="owner",
    ).one()
    assert stored.role == "editor"


# ---------------------------------------------------------------------------
# New RBAC tests (Task 2)
# ---------------------------------------------------------------------------

def test_personal_kb_owner_has_full_control(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    topic = kb(db_session, owner="alice")
    policy = KnowledgeAccessPolicy(db_session)
    for method_name in ("require_read", "require_contribute", "require_edit", "require_manage_members", "require_delete"):
        assert getattr(policy, method_name)(actor("alice"), topic.kb_uid).kb_uid == topic.kb_uid


def test_personal_kb_non_owner_is_denied(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = kb(db_session, owner="alice")
    policy = KnowledgeAccessPolicy(db_session)
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_read(actor("bob"), topic.kb_uid)


def test_pending_transfer_owner_can_edit_but_not_delete(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.PENDING_TRANSFER.value)
    policy = KnowledgeAccessPolicy(db_session)
    assert policy.require_edit(actor("alice"), topic.kb_uid).kb_uid == topic.kb_uid
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_delete(actor("alice"), topic.kb_uid)


def test_admin_can_read_and_delete_managed_kb(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    team_member(db_session, "admin", TeamRole.ADMIN.value)
    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)
    policy = KnowledgeAccessPolicy(db_session)
    assert policy.require_read(actor("admin"), topic.kb_uid).kb_uid == topic.kb_uid
    assert policy.require_delete(actor("admin"), topic.kb_uid).kb_uid == topic.kb_uid


def test_membership_roles_are_hierarchical(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)
    grant(db_session, topic, "viewer", KnowledgeBaseRole.VIEWER.value)
    grant(db_session, topic, "contributor", KnowledgeBaseRole.CONTRIBUTOR.value)
    grant(db_session, topic, "editor", KnowledgeBaseRole.EDITOR.value)
    grant(db_session, topic, "manager", KnowledgeBaseRole.MANAGER.value)
    policy = KnowledgeAccessPolicy(db_session)

    assert policy.require_read(actor("viewer"), topic.kb_uid)
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_contribute(actor("viewer"), topic.kb_uid)

    assert policy.require_contribute(actor("contributor"), topic.kb_uid)
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_edit(actor("contributor"), topic.kb_uid)

    assert policy.require_edit(actor("editor"), topic.kb_uid)
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_manage_members(actor("editor"), topic.kb_uid)

    assert policy.require_manage_members(actor("manager"), topic.kb_uid)
    with pytest.raises(KnowledgeAccessDenied):
        policy.require_delete(actor("manager"), topic.kb_uid)


def test_visible_kb_uids_includes_owned_pending_and_authorized_managed(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    owned = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.PERSONAL.value, name="Owned")
    pending = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.PENDING_TRANSFER.value, name="Pending")
    managed_visible = kb(db_session, owner="other", status=KnowledgeGovernanceStatus.MANAGED.value, name="Managed visible")
    managed_hidden = kb(db_session, owner="other", status=KnowledgeGovernanceStatus.MANAGED.value, name="Managed hidden")
    grant(db_session, managed_visible, "alice", KnowledgeBaseRole.VIEWER.value)

    visible = set(KnowledgeAccessPolicy(db_session).visible_kb_uids(actor("alice")))
    assert owned.kb_uid in visible
    assert pending.kb_uid in visible
    assert managed_visible.kb_uid in visible
    assert managed_hidden.kb_uid not in visible


# ---------------------------------------------------------------------------
# Service tests (Task 3)
# ---------------------------------------------------------------------------

def test_transfer_request_accept_grants_original_owner_editor(db_session):
    from backend.app.models import KnowledgeAccessAuditLog, KnowledgeBaseMembership
    from backend.app.services.knowledge_rbac import accept_transfer, request_transfer

    team_member(db_session, "admin", TeamRole.ADMIN.value)
    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.PERSONAL.value)

    requested = request_transfer(db_session, actor("alice"), topic.kb_uid, "ready for team")
    assert requested.governance_status == KnowledgeGovernanceStatus.PENDING_TRANSFER.value
    assert requested.transfer_requested_by == "alice"

    accepted = accept_transfer(db_session, actor("admin"), topic.kb_uid)
    assert accepted.governance_status == KnowledgeGovernanceStatus.MANAGED.value

    membership = db_session.query(KnowledgeBaseMembership).filter_by(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="alice",
    ).one()
    assert membership.role == KnowledgeBaseRole.EDITOR.value

    actions = [row.action for row in db_session.query(KnowledgeAccessAuditLog).all()]
    assert "transfer.request" in actions
    assert "transfer.accept" in actions


def test_owner_can_withdraw_pending_transfer(db_session):
    from backend.app.services.knowledge_rbac import request_transfer, withdraw_transfer

    topic = kb(db_session, owner="alice")
    request_transfer(db_session, actor("alice"), topic.kb_uid, None)
    withdrawn = withdraw_transfer(db_session, actor("alice"), topic.kb_uid)
    assert withdrawn.governance_status == KnowledgeGovernanceStatus.PERSONAL.value
    assert withdrawn.transfer_requested_by is None


def test_admin_reject_returns_to_personal_with_reason(db_session):
    from backend.app.services.knowledge_rbac import reject_transfer, request_transfer

    team_member(db_session, "admin", TeamRole.ADMIN.value)
    topic = kb(db_session, owner="alice")
    request_transfer(db_session, actor("alice"), topic.kb_uid, None)
    rejected = reject_transfer(db_session, actor("admin"), topic.kb_uid, "needs cleanup")
    assert rejected.governance_status == KnowledgeGovernanceStatus.PERSONAL.value
    assert rejected.transfer_rejection_reason == "needs cleanup"


def test_manager_can_grant_editor_but_not_manager(db_session):
    from backend.app.services.knowledge_rbac import upsert_membership
    from backend.app.services.knowledge_access import KnowledgeAccessDenied

    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)
    grant(db_session, topic, "manager", KnowledgeBaseRole.MANAGER.value)

    membership = upsert_membership(
        db_session,
        actor("manager"),
        topic.kb_uid,
        "bob",
        KnowledgeBaseRole.EDITOR.value,
    )
    assert membership.role == KnowledgeBaseRole.EDITOR.value

    with pytest.raises(KnowledgeAccessDenied):
        upsert_membership(
            db_session,
            actor("manager"),
            topic.kb_uid,
            "charlie",
            KnowledgeBaseRole.MANAGER.value,
        )


def test_transfer_operations_are_denied_across_tenants(db_session):
    """An actor in a different tenant cannot withdraw/accept/reject a transfer.

    Regression for a tenant-isolation gap where ``accept_transfer`` could
    insert the owner's editor membership under the acting admin's tenant.
    """
    from backend.app.services.knowledge_access import KnowledgeAccessDenied
    from backend.app.services.knowledge_rbac import (
        accept_transfer,
        reject_transfer,
        request_transfer,
        withdraw_transfer,
    )

    topic = kb(db_session, owner="alice")
    request_transfer(db_session, actor("alice"), topic.kb_uid, None)

    # A team-admin role in another tenant must not be able to accept or reject.
    foreign_admin = actor("admin-b", tenant_id="tenant-b", roles=(TeamRole.ADMIN.value,))
    with pytest.raises(KnowledgeAccessDenied):
        accept_transfer(db_session, foreign_admin, topic.kb_uid)
    with pytest.raises(KnowledgeAccessDenied):
        reject_transfer(db_session, foreign_admin, topic.kb_uid, "nope")

    # The same user id in another tenant must not be able to withdraw.
    with pytest.raises(KnowledgeAccessDenied):
        withdraw_transfer(db_session, actor("alice", tenant_id="tenant-b"), topic.kb_uid)

    # The transfer state must be untouched by all denied attempts.
    still_pending = db_session.query(KnowledgeTopic).filter_by(kb_uid=topic.kb_uid).one()
    assert still_pending.governance_status == KnowledgeGovernanceStatus.PENDING_TRANSFER.value


def test_accept_transfer_uses_topic_tenant_for_membership_and_audit(db_session):
    """accept_transfer writes membership and audit rows under the topic tenant."""
    from backend.app.services.knowledge_rbac import accept_transfer, request_transfer

    team_member(db_session, "admin", TeamRole.ADMIN.value)
    topic = kb(db_session, owner="alice", status=KnowledgeGovernanceStatus.PERSONAL.value)

    request_transfer(db_session, actor("alice"), topic.kb_uid, None)
    accept_transfer(db_session, actor("admin"), topic.kb_uid)

    membership = db_session.query(KnowledgeBaseMembership).filter_by(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="alice",
    ).one()
    assert membership.role == KnowledgeBaseRole.EDITOR.value

    audit_tenant_ids = {
        row.tenant_id for row in db_session.query(KnowledgeAccessAuditLog).all()
    }
    assert audit_tenant_ids == {"tenant-a"}
