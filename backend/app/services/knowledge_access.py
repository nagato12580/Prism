# backend/app/services/knowledge_access.py
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.app.models import (
    KnowledgeBaseMembership,
    KnowledgeBaseRole,
    KnowledgeGovernanceStatus,
    KnowledgeTopic,
    TeamMember,
    TeamRole,
)
from backend.app.security.actor import ActorContext


class KnowledgeNotFound(LookupError):
    def __init__(self, kb_uid: str):
        self.kb_uid = kb_uid
        super().__init__(f"Knowledge base {kb_uid} not found")


class KnowledgeAccessDenied(PermissionError):
    def __init__(self, kb_uid: str):
        self.kb_uid = kb_uid
        super().__init__(f"Access denied to knowledge base {kb_uid}")


ROLE_RANK = {
    KnowledgeBaseRole.VIEWER.value: 10,
    KnowledgeBaseRole.CONTRIBUTOR.value: 20,
    KnowledgeBaseRole.EDITOR.value: 30,
    KnowledgeBaseRole.MANAGER.value: 40,
}


class KnowledgeAccessPolicy:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Team helpers
    # ------------------------------------------------------------------

    def is_team_admin(self, actor: ActorContext) -> bool:
        """Return True if *actor* holds the team-admin role.

        Checks the in-memory roles tuple first (fast path for header-based
        auth), then falls back to the ``team_member`` table.
        """
        if TeamRole.ADMIN.value in actor.roles:
            return True
        row = (
            self.db.query(TeamMember)
            .filter_by(
                tenant_id=actor.tenant_id,
                user_id=actor.actor_id,
                status="active",
            )
            .one_or_none()
        )
        return bool(row and row.role == TeamRole.ADMIN.value)

    def get_team_role(self, actor: ActorContext) -> str:
        """Return ``"admin"`` or ``"member"``."""
        return "admin" if self.is_team_admin(actor) else "member"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_topic(self, kb_uid: str) -> KnowledgeTopic:
        """Load a non-deleted topic, raising ``KnowledgeNotFound`` otherwise."""
        topic = (
            self.db.query(KnowledgeTopic)
            .filter_by(kb_uid=kb_uid, deleted_at=None)
            .one_or_none()
        )
        if topic is None:
            raise KnowledgeNotFound(kb_uid)
        return topic

    def _ensure_same_tenant(self, topic: KnowledgeTopic, actor: ActorContext) -> None:
        """Raise ``KnowledgeAccessDenied`` when actor and topic tenants differ."""
        if topic.tenant_id != actor.tenant_id:
            raise KnowledgeAccessDenied(topic.kb_uid)

    def _membership_role(self, actor: ActorContext, kb_uid: str) -> str | None:
        """Return the membership role name (str) or None."""
        row = (
            self.db.query(KnowledgeBaseMembership)
            .filter_by(
                tenant_id=actor.tenant_id,
                kb_uid=kb_uid,
                user_id=actor.actor_id,
            )
            .one_or_none()
        )
        return row.role if row else None

    # ------------------------------------------------------------------
    # Core authorisation check
    # ------------------------------------------------------------------

    def _has_role(self, actor: ActorContext, topic: KnowledgeTopic, minimum_role: str) -> bool:
        """Return True when *actor* holds at least *minimum_role* on *topic*.

        ``minimum_role`` may be one of the ``KnowledgeBaseRole`` values
        (checked against ``ROLE_RANK`` for managed libraries) **or** the
        sentinel ``"delete"`` which maps to the delete capability (managed
        libraries require admin; personal requires owner).
        """
        # Admin bypass
        if self.is_team_admin(actor):
            return True

        is_owner = topic.owner_user_id == actor.actor_id

        if topic.governance_status == KnowledgeGovernanceStatus.MANAGED.value:
            if minimum_role == "delete":
                return False  # only admin may delete managed libraries
            role = self._membership_role(actor, topic.kb_uid)
            if role is None:
                return False
            required_rank = ROLE_RANK.get(minimum_role, 0)
            actual_rank = ROLE_RANK.get(role, 0)
            return actual_rank >= required_rank

        if topic.governance_status == KnowledgeGovernanceStatus.PENDING_TRANSFER.value:
            if is_owner:
                return minimum_role != "delete"
            # Non-owners cannot access pending-transfer libraries at all.
            return False

        # personal
        return is_owner

    # ------------------------------------------------------------------
    # Public guard methods — each returns the topic or raises
    # ------------------------------------------------------------------

    def require_read(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self._load_topic(kb_uid)
        self._ensure_same_tenant(topic, actor)
        if not self._has_role(actor, topic, KnowledgeBaseRole.VIEWER.value):
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    def require_contribute(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self._load_topic(kb_uid)
        self._ensure_same_tenant(topic, actor)
        if not self._has_role(actor, topic, KnowledgeBaseRole.CONTRIBUTOR.value):
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    def require_edit(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self._load_topic(kb_uid)
        self._ensure_same_tenant(topic, actor)
        if not self._has_role(actor, topic, KnowledgeBaseRole.EDITOR.value):
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    def require_manage_members(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self._load_topic(kb_uid)
        self._ensure_same_tenant(topic, actor)
        if not self._has_role(actor, topic, KnowledgeBaseRole.MANAGER.value):
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    def require_delete(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self._load_topic(kb_uid)
        self._ensure_same_tenant(topic, actor)
        if not self._has_role(actor, topic, "delete"):
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_membership_role(self, actor: ActorContext, kb_uid: str) -> str | None:
        """Public introspection: the membership role (or None)."""
        return self._membership_role(actor, kb_uid)

    def list_visible_topics(self, actor: ActorContext) -> list[KnowledgeTopic]:
        """Return every non-deleted topic in the actor's tenant that they may see.

        - Admins see every topic in the tenant.
        - Members see topics they own with status *personal* or
          *pending_transfer*, plus *managed* topics for which a
          ``KnowledgeBaseMembership`` row exists.
        """
        base = (
            self.db.query(KnowledgeTopic)
            .filter_by(tenant_id=actor.tenant_id, deleted_at=None)
        )

        if self.is_team_admin(actor):
            return base.all()

        membership_kb_uids = [
            row[0]
            for row in self.db.query(KnowledgeBaseMembership.kb_uid)
            .filter_by(tenant_id=actor.tenant_id, user_id=actor.actor_id)
            .all()
        ]

        conditions = [
            and_(
                KnowledgeTopic.owner_user_id == actor.actor_id,
                KnowledgeTopic.governance_status.in_([
                    KnowledgeGovernanceStatus.PERSONAL.value,
                    KnowledgeGovernanceStatus.PENDING_TRANSFER.value,
                ]),
            ),
        ]

        if membership_kb_uids:
            conditions.append(
                and_(
                    KnowledgeTopic.governance_status == KnowledgeGovernanceStatus.MANAGED.value,
                    KnowledgeTopic.kb_uid.in_(membership_kb_uids),
                ),
            )

        return base.filter(or_(*conditions)).all()

    def visible_kb_uids(self, actor: ActorContext) -> list[str]:
        """Return the ``kb_uid`` of every visible topic."""
        return [t.kb_uid for t in self.list_visible_topics(actor)]

    def capabilities(self, actor: ActorContext, topic: KnowledgeTopic) -> dict[str, bool | str | None]:
        """Return a dictionary of the actor's effective capabilities on *topic*.

        Keys: ``my_role``, ``can_read``, ``can_contribute``, ``can_edit``,
        ``can_manage_members``, ``can_delete``.
        """
        if self.is_team_admin(actor):
            my_role = "admin"
        elif topic.owner_user_id == actor.actor_id and topic.governance_status != KnowledgeGovernanceStatus.MANAGED.value:
            my_role = "owner"
        else:
            my_role = self._membership_role(actor, topic.kb_uid)

        return {
            "my_role": my_role,
            "can_read": self._has_role(actor, topic, KnowledgeBaseRole.VIEWER.value),
            "can_contribute": self._has_role(actor, topic, KnowledgeBaseRole.CONTRIBUTOR.value),
            "can_edit": self._has_role(actor, topic, KnowledgeBaseRole.EDITOR.value),
            "can_manage_members": self._has_role(actor, topic, KnowledgeBaseRole.MANAGER.value),
            "can_delete": self._has_role(actor, topic, "delete"),
        }
