# backend/app/services/team_members.py
"""Team-member CRUD service.

Authorization is enforced by the route layer via ``KnowledgeAccessPolicy``.
This service owns validation, self-protection, the last-admin guard, and
audit logging. All mutations write ``KnowledgeAccessAuditLog`` rows.
"""

from sqlalchemy.orm import Session

from backend.app.models import KnowledgeAccessAuditLog, TeamMember
from backend.app.models.knowledge_types import TeamRole
from backend.app.security.actor import ActorContext
from backend.app.utils.time import local_now

_TEAM_ROLES = {r.value for r in TeamRole}
_TEAM_STATUSES = {"active", "disabled"}


class TeamMemberNotFound(LookupError):
    pass


class TeamMemberConflict(ValueError):
    pass


class TeamMemberSelfOperationDenied(PermissionError):
    pass


class TeamMemberLastAdminDenied(PermissionError):
    pass


def _audit(
    db: Session,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    target_user_id: str,
    before=None,
    after=None,
    note: str | None = None,
) -> None:
    db.add(
        KnowledgeAccessAuditLog(
            tenant_id=tenant_id,
            kb_uid=None,
            actor_id=actor_id,
            action=action,
            target_user_id=target_user_id,
            before=before,
            after=after,
            note=note,
        )
    )


def _active_admin_count(db: Session, *, tenant_id: str) -> int:
    return (
        db.query(TeamMember)
        .filter_by(tenant_id=tenant_id, role=TeamRole.ADMIN.value, status="active")
        .count()
    )


def _load_member(db: Session, *, tenant_id: str, user_id: str) -> TeamMember:
    row = (
        db.query(TeamMember)
        .filter_by(tenant_id=tenant_id, user_id=user_id)
        .one_or_none()
    )
    if row is None:
        raise TeamMemberNotFound(f"team member not found: {user_id}")
    return row


def list_team_members(db: Session, *, tenant_id: str) -> list[TeamMember]:
    return (
        db.query(TeamMember)
        .filter_by(tenant_id=tenant_id)
        .order_by(TeamMember.created_at.asc(), TeamMember.user_id.asc())
        .all()
    )


def add_team_member(
    db: Session,
    *,
    actor: ActorContext,
    user_id: str,
    role: str,
    status: str = "active",
) -> TeamMember:
    if role not in _TEAM_ROLES:
        raise TeamMemberConflict(f"invalid team role: {role}")
    if status not in _TEAM_STATUSES:
        raise TeamMemberConflict(f"invalid member status: {status}")

    existing = (
        db.query(TeamMember)
        .filter_by(tenant_id=actor.tenant_id, user_id=user_id)
        .one_or_none()
    )
    if existing is not None:
        raise TeamMemberConflict(f"team member already exists: {user_id}")

    row = TeamMember(
        tenant_id=actor.tenant_id,
        user_id=user_id,
        role=role,
        status=status,
    )
    db.add(row)
    _audit(
        db,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        action="team_member.add",
        target_user_id=user_id,
        after={"role": role, "status": status},
    )
    db.commit()
    db.refresh(row)
    return row


def update_team_member(
    db: Session,
    *,
    actor: ActorContext,
    user_id: str,
    role: str | None = None,
    status: str | None = None,
) -> TeamMember:
    if user_id == actor.actor_id:
        raise TeamMemberSelfOperationDenied("cannot operate on yourself")

    if role is not None and role not in _TEAM_ROLES:
        raise TeamMemberConflict(f"invalid team role: {role}")
    if status is not None and status not in _TEAM_STATUSES:
        raise TeamMemberConflict(f"invalid member status: {status}")

    row = _load_member(db, tenant_id=actor.tenant_id, user_id=user_id)
    before = {"role": row.role, "status": row.status}

    demoting_last_admin = (
        row.role == TeamRole.ADMIN.value
        and role == TeamRole.MEMBER.value
        and row.status == "active"
        and _active_admin_count(db, tenant_id=actor.tenant_id) <= 1
    )
    disabling_last_admin = (
        row.role == TeamRole.ADMIN.value
        and status == "disabled"
        and row.status == "active"
        and _active_admin_count(db, tenant_id=actor.tenant_id) <= 1
    )
    if demoting_last_admin or disabling_last_admin:
        raise TeamMemberLastAdminDenied("at least one active admin is required")

    if role is not None:
        row.role = role
    if status is not None:
        row.status = status
    row.updated_at = local_now()

    _audit(
        db,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        action="team_member.update",
        target_user_id=user_id,
        before=before,
        after={"role": row.role, "status": row.status},
    )
    db.commit()
    db.refresh(row)
    return row


def remove_team_member(
    db: Session,
    *,
    actor: ActorContext,
    user_id: str,
) -> None:
    if user_id == actor.actor_id:
        raise TeamMemberSelfOperationDenied("cannot operate on yourself")

    row = _load_member(db, tenant_id=actor.tenant_id, user_id=user_id)
    if (
        row.role == TeamRole.ADMIN.value
        and row.status == "active"
        and _active_admin_count(db, tenant_id=actor.tenant_id) <= 1
    ):
        raise TeamMemberLastAdminDenied("at least one active admin is required")

    db.delete(row)
    _audit(
        db,
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        action="team_member.remove",
        target_user_id=user_id,
        before={"role": row.role, "status": row.status},
    )
    db.commit()
