# backend/app/services/knowledge_rbac.py
"""Knowledge-base transfer-request and membership-mutation services.

All functions follow the same pattern:
1. Load and lock the topic (with_for_update for state transitions).
2. Authorise via ``KnowledgeAccessPolicy``.
3. Validate business-rule preconditions.
4. Mutate, audit, commit, refresh.
"""

from sqlalchemy.orm import Session

from backend.app.models import (
    KnowledgeAccessAuditLog,
    KnowledgeBaseMembership,
    KnowledgeBaseRole,
    KnowledgeGovernanceStatus,
    KnowledgeTopic,
)
from backend.app.security.actor import ActorContext
from backend.app.services.knowledge_access import (
    KnowledgeAccessDenied,
    KnowledgeAccessPolicy,
    KnowledgeNotFound,
)
from backend.app.utils.time import local_now


def _audit(
    db: Session,
    *,
    tenant_id: str,
    kb_uid: str,
    actor_id: str,
    action: str,
    target_user_id: str | None = None,
    before=None,
    after=None,
    note: str | None = None,
) -> None:
    db.add(
        KnowledgeAccessAuditLog(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            actor_id=actor_id,
            action=action,
            target_user_id=target_user_id,
            before=before,
            after=after,
            note=note,
        )
    )


def _load_topic_for_update(db: Session, kb_uid: str) -> KnowledgeTopic:
    """Load a non-deleted topic with a row-level lock for state transitions."""
    topic = (
        db.query(KnowledgeTopic)
        .with_for_update()
        .filter_by(kb_uid=kb_uid, deleted_at=None)
        .one_or_none()
    )
    if topic is None:
        raise KnowledgeNotFound(kb_uid)
    return topic


_VALID_ROLES = frozenset(
    [
        KnowledgeBaseRole.VIEWER.value,
        KnowledgeBaseRole.CONTRIBUTOR.value,
        KnowledgeBaseRole.EDITOR.value,
        KnowledgeBaseRole.MANAGER.value,
    ]
)


# ---------------------------------------------------------------------------
# Transfer lifecycle
# ---------------------------------------------------------------------------


def request_transfer(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
    message: str | None = None,
) -> KnowledgeTopic:
    """Request that a personal knowledge base be transferred to team governance.

    Only the owner may request a transfer, and the topic must currently be
    in ``personal`` status.  The admin bypass is explicitly blocked.
    """
    policy = KnowledgeAccessPolicy(db)
    policy.require_edit(actor, kb_uid)  # authorisation + existence + tenant

    # Lock for mutation
    topic = _load_topic_for_update(db, kb_uid)

    # Block admin bypass -- only the owner may request
    if topic.owner_user_id != actor.actor_id:
        raise KnowledgeAccessDenied(kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.PERSONAL.value:
        raise KnowledgeAccessDenied(kb_uid)

    now = local_now()
    topic.governance_status = KnowledgeGovernanceStatus.PENDING_TRANSFER.value
    topic.transfer_requested_by = actor.actor_id
    topic.transfer_requested_at = now
    topic.transfer_message = message
    # Clear any previous review fields
    topic.transfer_reviewed_by = None
    topic.transfer_reviewed_at = None
    topic.transfer_rejection_reason = None

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="transfer.request",
        note=message,
    )

    db.commit()
    db.refresh(topic)
    return topic


def withdraw_transfer(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
) -> KnowledgeTopic:
    """Withdraw a pending transfer request, returning the topic to personal.

    Only the owner may withdraw.
    """
    topic = _load_topic_for_update(db, kb_uid)

    if topic.owner_user_id != actor.actor_id:
        raise KnowledgeAccessDenied(kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.PENDING_TRANSFER.value:
        raise KnowledgeAccessDenied(kb_uid)

    topic.governance_status = KnowledgeGovernanceStatus.PERSONAL.value
    topic.transfer_requested_by = None
    topic.transfer_requested_at = None
    topic.transfer_message = None

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="transfer.withdraw",
    )

    db.commit()
    db.refresh(topic)
    return topic


def accept_transfer(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
) -> KnowledgeTopic:
    """Accept a pending transfer -- admin-only.

    The topic enters ``managed`` and the original owner is granted the
    ``editor`` membership role.
    """
    policy = KnowledgeAccessPolicy(db)
    if not policy.is_team_admin(actor):
        raise KnowledgeAccessDenied(kb_uid)

    topic = _load_topic_for_update(db, kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.PENDING_TRANSFER.value:
        raise KnowledgeAccessDenied(kb_uid)

    now = local_now()
    topic.governance_status = KnowledgeGovernanceStatus.MANAGED.value
    topic.transfer_reviewed_by = actor.actor_id
    topic.transfer_reviewed_at = now

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="transfer.accept",
    )

    # Grant the original owner editor role
    _upsert_membership_row(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        user_id=topic.owner_user_id,
        role=KnowledgeBaseRole.EDITOR.value,
        granted_by=actor.actor_id,
    )

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="membership.grant",
        target_user_id=topic.owner_user_id,
        after={"role": KnowledgeBaseRole.EDITOR.value},
    )

    db.commit()
    db.refresh(topic)
    return topic


def reject_transfer(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
    reason: str | None = None,
) -> KnowledgeTopic:
    """Reject a pending transfer -- admin-only.

    The topic returns to ``personal`` with a rejection reason recorded.
    """
    policy = KnowledgeAccessPolicy(db)
    if not policy.is_team_admin(actor):
        raise KnowledgeAccessDenied(kb_uid)

    topic = _load_topic_for_update(db, kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.PENDING_TRANSFER.value:
        raise KnowledgeAccessDenied(kb_uid)

    now = local_now()
    topic.governance_status = KnowledgeGovernanceStatus.PERSONAL.value
    topic.transfer_reviewed_by = actor.actor_id
    topic.transfer_reviewed_at = now
    topic.transfer_rejection_reason = reason

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="transfer.reject",
        note=reason,
    )

    db.commit()
    db.refresh(topic)
    return topic


# ---------------------------------------------------------------------------
# Membership CRUD
# ---------------------------------------------------------------------------


def _upsert_membership_row(
    db: Session,
    *,
    tenant_id: str,
    kb_uid: str,
    user_id: str,
    role: str,
    granted_by: str | None = None,
) -> KnowledgeBaseMembership:
    """Insert or update a single membership row (no auth checks)."""
    row = (
        db.query(KnowledgeBaseMembership)
        .filter_by(tenant_id=tenant_id, kb_uid=kb_uid, user_id=user_id)
        .one_or_none()
    )
    if row is None:
        row = KnowledgeBaseMembership(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            user_id=user_id,
            role=role,
            granted_by=granted_by,
        )
        db.add(row)
    else:
        row.role = role
        row.granted_by = granted_by
    return row


def upsert_membership(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
    user_id: str,
    role: str,
) -> KnowledgeBaseMembership:
    """Grant or update a membership role for *user_id* on *kb_uid*.

    Requires the topic to be ``managed`` and the actor must hold the
    ``manage_members`` capability.  Non-admin actors may not assign the
    ``manager`` role.
    """
    if role not in _VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")

    policy = KnowledgeAccessPolicy(db)
    topic = policy.require_manage_members(actor, kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.MANAGED.value:
        raise KnowledgeAccessDenied(kb_uid)

    if not policy.is_team_admin(actor) and role == KnowledgeBaseRole.MANAGER.value:
        raise KnowledgeAccessDenied(kb_uid)

    membership = _upsert_membership_row(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        user_id=user_id,
        role=role,
        granted_by=actor.actor_id,
    )

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="membership.grant",
        target_user_id=user_id,
        after={"role": role},
    )

    db.commit()
    db.refresh(membership)
    return membership


def remove_membership(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
    user_id: str,
) -> None:
    """Remove a user's membership from *kb_uid*.

    Requires the topic to be ``managed`` and the actor must hold the
    ``manage_members`` capability.  Non-admin actors may not remove a
    ``manager``.
    """
    policy = KnowledgeAccessPolicy(db)
    topic = policy.require_manage_members(actor, kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.MANAGED.value:
        raise KnowledgeAccessDenied(kb_uid)

    membership = (
        db.query(KnowledgeBaseMembership)
        .filter_by(tenant_id=actor.tenant_id, kb_uid=kb_uid, user_id=user_id)
        .one_or_none()
    )

    if membership is None:
        db.commit()
        return

    if (
        membership.role == KnowledgeBaseRole.MANAGER.value
        and not policy.is_team_admin(actor)
    ):
        raise KnowledgeAccessDenied(kb_uid)

    before_role = membership.role
    db.delete(membership)

    _audit(
        db,
        tenant_id=actor.tenant_id,
        kb_uid=kb_uid,
        actor_id=actor.actor_id,
        action="membership.revoke",
        target_user_id=user_id,
        before={"role": before_role},
    )

    db.commit()


def list_memberships(
    db: Session,
    actor: ActorContext,
    kb_uid: str,
) -> list[KnowledgeBaseMembership]:
    """List all memberships for *kb_uid*.

    Requires the topic to be ``managed`` and the actor must hold the
    ``manage_members`` capability.
    """
    policy = KnowledgeAccessPolicy(db)
    topic = policy.require_manage_members(actor, kb_uid)

    if topic.governance_status != KnowledgeGovernanceStatus.MANAGED.value:
        raise KnowledgeAccessDenied(kb_uid)

    return (
        db.query(KnowledgeBaseMembership)
        .filter_by(tenant_id=actor.tenant_id, kb_uid=kb_uid)
        .all()
    )
