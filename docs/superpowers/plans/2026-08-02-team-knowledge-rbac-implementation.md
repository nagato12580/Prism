# Team Knowledge RBAC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build team knowledge-base RBAC so personal libraries remain owner-controlled, admins accept transfer requests into team governance, and all listing, retrieval, graph, and content operations respect per-library roles.

**Architecture:** Keep authorization in Backend as the single policy boundary, backed by normalized MySQL tables for team membership and knowledge-base memberships. Backend computes readable/editable knowledge scopes and signs `allowed_kb_uids` for Engine; Engine continues to trust only signed scopes and never evaluates team roles itself. Frontend renders capability-driven actions from Backend responses rather than re-deriving permissions.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic migrations, MySQL-compatible schema, pytest, React 18, TypeScript, React Router, Vite.

## Global Constraints

- Follow the design in `docs/superpowers/specs/2026-08-02-team-knowledge-rbac-design.md`.
- Do not copy Yuxi code directly; reuse only the architectural ideas documented in the spec.
- Engine must not directly judge team roles; it only consumes Backend-signed authorization scopes.
- Team roles are exactly `admin` and `member`.
- Knowledge governance states are exactly `personal`, `pending_transfer`, and `managed`.
- Knowledge-base membership roles are exactly `viewer`, `contributor`, `editor`, and `manager`.
- A member-created knowledge base defaults to `personal`; its owner has full control.
- `pending_transfer` libraries can still be edited by the owner, but cannot be deleted by the owner.
- Admin confirmation is required before a personal library becomes a team library.
- When a library enters `managed`, the original owner receives `editor`, not `manager`.
- Team library deletion is admin-only.
- All Backend APIs remain the final authorization boundary; frontend affordances are not security.
- Preserve existing personal inbox system-library protections.
- Preserve signed `AuthorizedKnowledgeScope.allowed_kb_uids` behavior and short TTL.
- Use focused commits after each task.

---

## File Structure

### Backend Models And Migrations

- Modify `backend/app/models/knowledge_types.py`
  - Add string enum classes for team roles, governance states, and library roles.
- Modify `backend/app/models/knowledge_item.py`
  - Add governance columns to `KnowledgeTopic`.
- Create `backend/app/models/knowledge_access.py`
  - Define `TeamMember`, `KnowledgeBaseMembership`, and `KnowledgeAccessAuditLog`.
- Modify `backend/app/models/__init__.py`
  - Export the new models and enums.
- Create `backend/alembic/versions/20260802_01_team_knowledge_rbac.py`
  - Add new tables and columns.

### Backend Authorization

- Modify `backend/app/security/actor.py`
  - Parse team roles from headers during the current auth-adapter phase.
- Rewrite `backend/app/services/knowledge_access.py`
  - Centralize all read/contribute/edit/manage-members/delete decisions.
  - Provide visible-library queries and capability calculation.
- Create `backend/app/services/knowledge_rbac.py`
  - Implement transfer-request and membership mutation service functions with audit logs.

### Backend APIs

- Modify `backend/app/api/knowledge_bases.py`
  - Extend response DTOs with governance and capability fields.
  - Make list/get/create/update/delete use the new policy.
  - Add transfer request and member-management routes.
- Modify `backend/app/api/knowledge_files.py`
  - Replace old manage/read checks with contribute/edit-specific checks.
- Modify `backend/app/api/knowledge_enrichment.py`
  - Use edit checks for graph, mindmap, and sample-question generation/mutation.
- Modify `backend/app/api/knowledge_retrieval.py`
  - Ensure read checks use the new policy and the signed scope stays bounded.
- Modify `backend/app/api/agent_chat_proxy.py`
  - Ensure requested `kb_uids` are authorized by readable set and no admin/member data is forwarded.
- Search and modify other `KnowledgeAccessPolicy(...).require_manage` call sites where role semantics need `require_contribute`, `require_edit`, or `require_delete`.

### Engine Boundary

- Modify `engine/app/agent/tools/knowledge_base.py` only if tests reveal gaps in `allowed_kb_uids` enforcement.
- Modify `engine/app/api/retrieval.py` only if single-KB retrieval scope needs stricter validation parity.
- Add/extend Engine tests to prove scope-outside `kb_uid` is denied.

### Frontend

- Modify `frontend/src/features/knowledge/api/knowledgeBases.ts`
  - Add governance fields, capability fields, transfer APIs, and membership APIs.
- Modify `frontend/src/features/knowledge/pages/KnowledgeIndexPage.tsx`
  - Group libraries into personal, pending, and team sections.
  - Show submit/withdraw transfer actions and capability-driven delete affordances.
- Modify `frontend/src/features/knowledge/components/KnowledgeShell.tsx`
  - Surface current role and disable/hide tabs/actions by capability.
- Modify knowledge subpages as needed:
  - `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeGraphPage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeGovernancePage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeSettingsPage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.tsx`
- Create a small members panel only when Backend membership APIs are in place:
  - `frontend/src/features/knowledge/components/KnowledgeMembersPanel.tsx`

### Tests

- Modify `backend/tests/test_knowledge_access.py`
  - Expand policy unit coverage.
- Create `backend/tests/test_knowledge_rbac_api.py`
  - Cover transfer and membership API behavior.
- Modify existing Backend API tests where current owner-only assumptions change.
- Modify or create frontend source-scanning tests:
  - `frontend/tests/knowledge-rbac-navigation.test.mjs`
  - `frontend/tests/knowledge-deeplink-routes.test.mjs` if route assumptions change.
- Extend Engine tests for signed scope boundaries if not already sufficient.

---

## Task 1: Schema And ORM Foundations

**Files:**
- Modify: `backend/app/models/knowledge_types.py`
- Modify: `backend/app/models/knowledge_item.py`
- Create: `backend/app/models/knowledge_access.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260802_01_team_knowledge_rbac.py`
- Test: `backend/tests/test_knowledge_access.py`

**Interfaces:**
- Produces enum values:
  - `TeamRole.ADMIN.value == "admin"`
  - `TeamRole.MEMBER.value == "member"`
  - `KnowledgeGovernanceStatus.PERSONAL.value == "personal"`
  - `KnowledgeGovernanceStatus.PENDING_TRANSFER.value == "pending_transfer"`
  - `KnowledgeGovernanceStatus.MANAGED.value == "managed"`
  - `KnowledgeBaseRole.VIEWER.value == "viewer"`
  - `KnowledgeBaseRole.CONTRIBUTOR.value == "contributor"`
  - `KnowledgeBaseRole.EDITOR.value == "editor"`
  - `KnowledgeBaseRole.MANAGER.value == "manager"`
- Produces ORM classes:
  - `TeamMember`
  - `KnowledgeBaseMembership`
  - `KnowledgeAccessAuditLog`
- Later tasks consume `KnowledgeTopic.governance_status` and transfer metadata fields.

- [ ] **Step 1: Write failing schema tests**

Add these tests to `backend/tests/test_knowledge_access.py`:

```python
def test_rbac_models_round_trip(db_session):
    from backend.app.models import (
        KnowledgeAccessAuditLog,
        KnowledgeBaseMembership,
        KnowledgeBaseRole,
        KnowledgeGovernanceStatus,
        KnowledgeTopic,
        TeamMember,
        TeamRole,
    )

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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py::test_rbac_models_round_trip -q
```

Expected: FAIL because new models/enums/columns do not exist.

- [ ] **Step 3: Add enums**

In `backend/app/models/knowledge_types.py`, append:

```python
class TeamRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class KnowledgeGovernanceStatus(str, enum.Enum):
    PERSONAL = "personal"
    PENDING_TRANSFER = "pending_transfer"
    MANAGED = "managed"


class KnowledgeBaseRole(str, enum.Enum):
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    EDITOR = "editor"
    MANAGER = "manager"
```

- [ ] **Step 4: Extend KnowledgeTopic**

In `backend/app/models/knowledge_item.py`, import `KnowledgeGovernanceStatus` from `.knowledge_types`.

Add these columns to `KnowledgeTopic` after `delete_disabled`:

```python
    governance_status = Column(
        String(32),
        nullable=False,
        default=KnowledgeGovernanceStatus.PERSONAL.value,
        server_default=KnowledgeGovernanceStatus.PERSONAL.value,
        index=True,
    )
    transfer_requested_by = Column(CHAR(36), nullable=True)
    transfer_requested_at = Column(DateTime, nullable=True)
    transfer_message = Column(Text, nullable=True)
    transfer_reviewed_by = Column(CHAR(36), nullable=True)
    transfer_reviewed_at = Column(DateTime, nullable=True)
    transfer_rejection_reason = Column(Text, nullable=True)
```

- [ ] **Step 5: Add access models**

Create `backend/app/models/knowledge_access.py`:

```python
from sqlalchemy import Column, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import KnowledgeBaseRole, TeamRole, uuid4_str


class TeamMember(Base):
    __tablename__ = "team_member"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_team_member_tenant_user"),
        Index("ix_team_member_tenant_role", "tenant_id", "role"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    user_id = Column(CHAR(36), nullable=False)
    role = Column(String(32), nullable=False, default=TeamRole.MEMBER.value, server_default=TeamRole.MEMBER.value)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class KnowledgeBaseMembership(Base):
    __tablename__ = "knowledge_base_membership"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kb_uid", "user_id", name="uq_kb_membership_scope_user"),
        Index("ix_kb_membership_user", "tenant_id", "user_id"),
        Index("ix_kb_membership_kb", "tenant_id", "kb_uid"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=False)
    user_id = Column(CHAR(36), nullable=False)
    role = Column(String(32), nullable=False, default=KnowledgeBaseRole.VIEWER.value, server_default=KnowledgeBaseRole.VIEWER.value)
    granted_by = Column(CHAR(36), nullable=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class KnowledgeAccessAuditLog(Base):
    __tablename__ = "knowledge_access_audit_log"
    __table_args__ = (
        Index("ix_kb_access_audit_scope_created", "tenant_id", "kb_uid", "created_at"),
        Index("ix_kb_access_audit_actor", "tenant_id", "actor_id", "created_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    tenant_id = Column(CHAR(36), nullable=False)
    kb_uid = Column(CHAR(36), nullable=True)
    actor_id = Column(CHAR(36), nullable=False)
    action = Column(String(64), nullable=False)
    target_user_id = Column(CHAR(36), nullable=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=local_now)
    note = Column(Text, nullable=True)
```

- [ ] **Step 6: Export models**

In `backend/app/models/__init__.py`, import and export:

```python
from .knowledge_access import KnowledgeAccessAuditLog, KnowledgeBaseMembership, TeamMember
from .knowledge_types import KnowledgeBaseRole, KnowledgeGovernanceStatus, TeamRole
```

Add each name to `__all__`.

- [ ] **Step 7: Add Alembic migration**

Create `backend/alembic/versions/20260802_01_team_knowledge_rbac.py`:

```python
"""Add team knowledge RBAC.

revision = "20260802_01"
down_revision = "20260728_01"
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_01"
down_revision = "20260728_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_topic",
        sa.Column("governance_status", sa.String(length=32), nullable=False, server_default="personal"),
    )
    op.add_column("knowledge_topic", sa.Column("transfer_requested_by", sa.CHAR(length=36), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_requested_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_message", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_reviewed_by", sa.CHAR(length=36), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_rejection_reason", sa.Text(), nullable=True))
    op.create_index("ix_knowledge_topic_governance_status", "knowledge_topic", ["governance_status"], unique=False)

    op.create_table(
        "team_member",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", sa.CHAR(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_team_member_tenant_user"),
    )
    op.create_index("ix_team_member_tenant_role", "team_member", ["tenant_id", "role"], unique=False)

    op.create_table(
        "knowledge_base_membership",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", sa.CHAR(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("granted_by", sa.CHAR(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "kb_uid", "user_id", name="uq_kb_membership_scope_user"),
    )
    op.create_index("ix_kb_membership_user", "knowledge_base_membership", ["tenant_id", "user_id"], unique=False)
    op.create_index("ix_kb_membership_kb", "knowledge_base_membership", ["tenant_id", "kb_uid"], unique=False)

    op.create_table(
        "knowledge_access_audit_log",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(length=36), nullable=True),
        sa.Column("actor_id", sa.CHAR(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.CHAR(length=36), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_access_audit_scope_created",
        "knowledge_access_audit_log",
        ["tenant_id", "kb_uid", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_kb_access_audit_actor",
        "knowledge_access_audit_log",
        ["tenant_id", "actor_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_kb_access_audit_actor", table_name="knowledge_access_audit_log")
    op.drop_index("ix_kb_access_audit_scope_created", table_name="knowledge_access_audit_log")
    op.drop_table("knowledge_access_audit_log")
    op.drop_index("ix_kb_membership_kb", table_name="knowledge_base_membership")
    op.drop_index("ix_kb_membership_user", table_name="knowledge_base_membership")
    op.drop_table("knowledge_base_membership")
    op.drop_index("ix_team_member_tenant_role", table_name="team_member")
    op.drop_table("team_member")
    op.drop_index("ix_knowledge_topic_governance_status", table_name="knowledge_topic")
    op.drop_column("knowledge_topic", "transfer_rejection_reason")
    op.drop_column("knowledge_topic", "transfer_reviewed_at")
    op.drop_column("knowledge_topic", "transfer_reviewed_by")
    op.drop_column("knowledge_topic", "transfer_message")
    op.drop_column("knowledge_topic", "transfer_requested_at")
    op.drop_column("knowledge_topic", "transfer_requested_by")
    op.drop_column("knowledge_topic", "governance_status")
```

- [ ] **Step 8: Run schema test**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py::test_rbac_models_round_trip -q
```

Expected: PASS.

- [ ] **Step 9: Run migration syntax check**

Run:

```bash
python -m py_compile backend/alembic/versions/20260802_01_team_knowledge_rbac.py
```

Expected: exit 0.

- [ ] **Step 10: Commit**

```bash
git add backend/app/models/knowledge_types.py backend/app/models/knowledge_item.py backend/app/models/knowledge_access.py backend/app/models/__init__.py backend/alembic/versions/20260802_01_team_knowledge_rbac.py backend/tests/test_knowledge_access.py
git commit -m "feat: add knowledge RBAC schema"
```

---

## Task 2: Actor Context And Policy Semantics

**Files:**
- Modify: `backend/app/security/actor.py`
- Rewrite: `backend/app/services/knowledge_access.py`
- Test: `backend/tests/test_knowledge_access.py`

**Interfaces:**
- Produces policy methods:
  - `is_team_admin(actor: ActorContext) -> bool`
  - `get_team_role(actor: ActorContext) -> str`
  - `get_membership_role(actor: ActorContext, kb_uid: str) -> str | None`
  - `list_visible_topics(actor: ActorContext) -> list[KnowledgeTopic]`
  - `visible_kb_uids(actor: ActorContext) -> list[str]`
  - `capabilities(actor: ActorContext, topic: KnowledgeTopic) -> dict[str, bool | str | None]`
  - `require_read(actor, kb_uid) -> KnowledgeTopic`
  - `require_contribute(actor, kb_uid) -> KnowledgeTopic`
  - `require_edit(actor, kb_uid) -> KnowledgeTopic`
  - `require_manage_members(actor, kb_uid) -> KnowledgeTopic`
  - `require_delete(actor, kb_uid) -> KnowledgeTopic`
- Later API tasks consume these methods.

- [ ] **Step 1: Replace old policy tests with RBAC tests**

In `backend/tests/test_knowledge_access.py`, keep the missing/deleted tests and add helpers:

```python
from backend.app.models import (
    KnowledgeBaseMembership,
    KnowledgeBaseRole,
    KnowledgeGovernanceStatus,
    KnowledgeTopic,
    TeamMember,
    TeamRole,
)


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
```

Add these tests:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py -q
```

Expected: FAIL because policy methods are not implemented.

- [ ] **Step 3: Extend ActorContext header adapter**

Modify `backend/app/security/actor.py` so `get_actor_context` accepts optional role header:

```python
def get_actor_context(
    x_prism_actor: Annotated[str | None, Header()] = None,
    x_prism_tenant: Annotated[str | None, Header()] = None,
    x_prism_roles: Annotated[str | None, Header()] = None,
) -> ActorContext:
    actor_id = x_prism_actor or "default-user"
    roles = tuple(
        role.strip()
        for role in (x_prism_roles or "").split(",")
        if role.strip()
    )
    return ActorContext(actor_id=actor_id, tenant_id=x_prism_tenant or actor_id, roles=roles)
```

This is not final auth. It is a compatibility adapter for tests and local development.

- [ ] **Step 4: Implement policy helpers**

Replace `backend/app/services/knowledge_access.py` with a role-aware implementation.

Required constants:

```python
ROLE_RANK = {
    KnowledgeBaseRole.VIEWER.value: 10,
    KnowledgeBaseRole.CONTRIBUTOR.value: 20,
    KnowledgeBaseRole.EDITOR.value: 30,
    KnowledgeBaseRole.MANAGER.value: 40,
}
```

Required behavior:

```python
def is_team_admin(self, actor: ActorContext) -> bool:
    if TeamRole.ADMIN.value in actor.roles:
        return True
    row = self.db.query(TeamMember).filter_by(
        tenant_id=actor.tenant_id,
        user_id=actor.actor_id,
        status="active",
    ).one_or_none()
    return bool(row and row.role == TeamRole.ADMIN.value)
```

`get_team_role` returns `admin` when `is_team_admin` is true, otherwise `member`.

`_load_topic(kb_uid)` filters `deleted_at=None` and raises `KnowledgeNotFound` when absent.

`_ensure_same_tenant(topic, actor)` raises `KnowledgeAccessDenied` when tenant differs.

`_membership_role(actor, kb_uid)` loads `KnowledgeBaseMembership` for `(tenant_id, kb_uid, actor_id)`.

`_has_role(actor, topic, minimum_role)` implements:

- admin always true.
- personal: owner true for every role including delete and member management.
- pending_transfer: owner true for read/contribute/edit/manage_members, false for delete.
- managed: membership role rank must meet minimum.

`require_delete` implements:

- personal: owner true.
- pending_transfer: always false for non-admin; admin true.
- managed: admin true only.

`list_visible_topics` returns active, non-deleted topics in actor tenant:

- admin: all.
- member: owner personal/pending plus managed libraries with membership.

Use `or_` and `KnowledgeTopic.kb_uid.in_(subquery)` or a simple two-query approach. Prefer correctness over query cleverness.

`capabilities(actor, topic)` returns:

```python
{
    "my_role": "admin" | "owner" | "viewer" | "contributor" | "editor" | "manager" | None,
    "can_read": bool,
    "can_contribute": bool,
    "can_edit": bool,
    "can_manage_members": bool,
    "can_delete": bool,
}
```

- [ ] **Step 5: Run policy tests**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/security/actor.py backend/app/services/knowledge_access.py backend/tests/test_knowledge_access.py
git commit -m "feat: enforce knowledge RBAC policy"
```

---

## Task 3: Transfer Request And Membership Services

**Files:**
- Create: `backend/app/services/knowledge_rbac.py`
- Test: `backend/tests/test_knowledge_access.py`

**Interfaces:**
- Produces:
  - `request_transfer(db, actor, kb_uid, message: str | None) -> KnowledgeTopic`
  - `withdraw_transfer(db, actor, kb_uid) -> KnowledgeTopic`
  - `accept_transfer(db, actor, kb_uid) -> KnowledgeTopic`
  - `reject_transfer(db, actor, kb_uid, reason: str | None) -> KnowledgeTopic`
  - `upsert_membership(db, actor, kb_uid, user_id: str, role: str) -> KnowledgeBaseMembership`
  - `remove_membership(db, actor, kb_uid, user_id: str) -> None`
  - `list_memberships(db, actor, kb_uid) -> list[KnowledgeBaseMembership]`

- [ ] **Step 1: Add service tests**

Append to `backend/tests/test_knowledge_access.py`:

```python
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
```

- [ ] **Step 2: Run service tests to verify failure**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py::test_transfer_request_accept_grants_original_owner_editor tests/test_knowledge_access.py::test_owner_can_withdraw_pending_transfer tests/test_knowledge_access.py::test_admin_reject_returns_to_personal_with_reason tests/test_knowledge_access.py::test_manager_can_grant_editor_but_not_manager -q
```

Expected: FAIL because service module does not exist.

- [ ] **Step 3: Implement `knowledge_rbac.py`**

Create `backend/app/services/knowledge_rbac.py`.

Implementation requirements:

- Use `KnowledgeAccessPolicy` for all permission checks.
- Use `with_for_update()` when loading a topic for state transitions.
- Use `local_now()` for timestamps.
- Use audit logs for every state or membership mutation.
- Validate role values against `KnowledgeBaseRole`.

Important helper:

```python
def _audit(db, *, tenant_id, kb_uid, actor_id, action, target_user_id=None, before=None, after=None, note=None):
    db.add(KnowledgeAccessAuditLog(
        tenant_id=tenant_id,
        kb_uid=kb_uid,
        actor_id=actor_id,
        action=action,
        target_user_id=target_user_id,
        before=before,
        after=after,
        note=note,
    ))
```

`request_transfer`:

- `require_edit(actor, kb_uid)` must pass.
- Topic must be owner-owned by actor.
- Topic must be `personal`.
- Set status `pending_transfer`.
- Set requested fields.
- Clear previous reviewed/rejection fields.
- Commit and refresh.

`withdraw_transfer`:

- Actor must be owner.
- Status must be `pending_transfer`.
- Set status `personal`.
- Clear requested fields.
- Commit and refresh.

`accept_transfer`:

- Actor must be admin.
- Status must be `pending_transfer`.
- Set status `managed`.
- Set reviewed fields.
- Upsert membership for `topic.owner_user_id` as `editor`.
- Commit and refresh.

`reject_transfer`:

- Actor must be admin.
- Status must be `pending_transfer`.
- Set status `personal`.
- Set reviewed fields and rejection reason.
- Commit and refresh.

`upsert_membership`:

- Topic must be `managed`.
- `require_manage_members` must pass.
- If actor is not admin, deny role `manager`.
- Upsert `(tenant_id, kb_uid, user_id)`.
- Commit and refresh.

`remove_membership`:

- Topic must be `managed`.
- `require_manage_members` must pass.
- If actor is not admin and target membership role is `manager`, deny.
- Delete row if present.
- Commit.

- [ ] **Step 4: Run service tests**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/knowledge_rbac.py backend/tests/test_knowledge_access.py
git commit -m "feat: add knowledge transfer and membership services"
```

---

## Task 4: Knowledge Base API RBAC

**Files:**
- Modify: `backend/app/api/knowledge_bases.py`
- Create: `backend/tests/test_knowledge_rbac_api.py`

**Interfaces:**
- Extends `KnowledgeBaseResponse` with:
  - `governance_status: str`
  - `transfer_requested_by: str | None`
  - `transfer_requested_at: datetime | None`
  - `transfer_message: str | None`
  - `transfer_reviewed_by: str | None`
  - `transfer_reviewed_at: datetime | None`
  - `transfer_rejection_reason: str | None`
  - `my_role: str | None`
  - `can_read: bool`
  - `can_contribute: bool`
  - `can_edit: bool`
  - `can_manage_members: bool`
  - `can_delete: bool`
- Adds DTOs:
  - `TransferRequestCreate(message: str | None = None)`
  - `TransferRejectRequest(reason: str | None = None)`
  - `MembershipUpdate(role: str)`
  - `MembershipResponse(user_id: str, role: str, granted_by: str | None, created_at: datetime | None, updated_at: datetime | None)`
- Adds routes:
  - `POST /knowledge-bases/{kb_uid}/transfer-request`
  - `DELETE /knowledge-bases/{kb_uid}/transfer-request`
  - `GET /knowledge-bases/admin/transfer-requests`
  - `POST /knowledge-bases/admin/transfer-requests/{kb_uid}/accept`
  - `POST /knowledge-bases/admin/transfer-requests/{kb_uid}/reject`
  - `GET /knowledge-bases/{kb_uid}/members`
  - `PUT /knowledge-bases/{kb_uid}/members/{user_id}`
  - `DELETE /knowledge-bases/{kb_uid}/members/{user_id}`

- [ ] **Step 1: Write API tests**

Create `backend/tests/test_knowledge_rbac_api.py`.

Use existing test client fixture names from `backend/tests/conftest.py`. If the fixture is `client`, use it. If the fixture has another name, inspect `backend/tests/conftest.py` and adjust only the fixture parameter name.

Test code:

```python
from backend.app.models import KnowledgeBaseMembership, KnowledgeBaseRole, KnowledgeGovernanceStatus, KnowledgeTopic, TeamMember, TeamRole


def auth_headers(user: str, tenant: str = "tenant-a", roles: str = ""):
    headers = {"X-Prism-Actor": user, "X-Prism-Tenant": tenant}
    if roles:
        headers["X-Prism-Roles"] = roles
    return headers


def seed_team_admin(db_session, user_id="admin"):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id=user_id, role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()


def seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.PERSONAL.value, name="KB"):
    topic = KnowledgeTopic(tenant_id="tenant-a", owner_user_id=owner, name=name, governance_status=status)
    db_session.add(topic)
    db_session.commit()
    return topic


def test_list_hides_unowned_personal_kb(client, db_session):
    visible = seed_topic(db_session, owner="alice", name="Mine")
    hidden = seed_topic(db_session, owner="bob", name="Hidden")

    response = client.get("/api/v1/knowledge-bases", headers=auth_headers("alice"))
    assert response.status_code == 200
    ids = {item["kb_uid"] for item in response.json()["items"]}
    assert visible.kb_uid in ids
    assert hidden.kb_uid not in ids


def test_transfer_accept_flow(client, db_session):
    seed_team_admin(db_session)
    topic = seed_topic(db_session, owner="alice")

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/transfer-request",
        json={"message": "please share"},
        headers=auth_headers("alice"),
    )
    assert response.status_code == 200
    assert response.json()["governance_status"] == "pending_transfer"
    assert response.json()["can_delete"] is False

    pending = client.get(
        "/api/v1/knowledge-bases/admin/transfer-requests",
        headers=auth_headers("admin"),
    )
    assert pending.status_code == 200
    assert topic.kb_uid in {item["kb_uid"] for item in pending.json()["items"]}

    accepted = client.post(
        f"/api/v1/knowledge-bases/admin/transfer-requests/{topic.kb_uid}/accept",
        headers=auth_headers("admin"),
    )
    assert accepted.status_code == 200
    assert accepted.json()["governance_status"] == "managed"

    membership = db_session.query(KnowledgeBaseMembership).filter_by(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="alice",
    ).one()
    assert membership.role == KnowledgeBaseRole.EDITOR.value


def test_managed_kb_requires_membership_for_member_visibility(client, db_session):
    topic = seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)

    hidden = client.get("/api/v1/knowledge-bases", headers=auth_headers("bob"))
    assert hidden.status_code == 200
    assert topic.kb_uid not in {item["kb_uid"] for item in hidden.json()["items"]}

    db_session.add(KnowledgeBaseMembership(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="bob",
        role=KnowledgeBaseRole.VIEWER.value,
        granted_by="admin",
    ))
    db_session.commit()

    visible = client.get("/api/v1/knowledge-bases", headers=auth_headers("bob"))
    assert visible.status_code == 200
    item = next(item for item in visible.json()["items"] if item["kb_uid"] == topic.kb_uid)
    assert item["my_role"] == "viewer"
    assert item["can_read"] is True
    assert item["can_contribute"] is False


def test_admin_can_grant_membership(client, db_session):
    seed_team_admin(db_session)
    topic = seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)

    response = client.put(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/members/bob",
        json={"role": "contributor"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 200
    assert response.json()["role"] == "contributor"
```

- [ ] **Step 2: Run API tests to verify failure**

Run:

```bash
cd backend
pytest tests/test_knowledge_rbac_api.py -q
```

Expected: FAIL because routes/response fields are missing.

- [ ] **Step 3: Extend response serialization**

In `backend/app/api/knowledge_bases.py`:

- Import new services and models.
- Add fields to `KnowledgeBaseResponse`.
- Replace `return topic` with a helper:

```python
def _kb_response(topic: KnowledgeTopic, actor: ActorContext, policy: KnowledgeAccessPolicy) -> dict:
    payload = KnowledgeBaseResponse.model_validate(topic).model_dump()
    payload.update(policy.capabilities(actor, topic))
    return payload
```

If Pydantic validation complains because `KnowledgeBaseResponse` includes capability fields not on ORM, set defaults on the model:

```python
my_role: str | None = None
can_read: bool = False
can_contribute: bool = False
can_edit: bool = False
can_manage_members: bool = False
can_delete: bool = False
```

- [ ] **Step 4: Update create/list/get/update/delete**

Required route behavior:

- `create_knowledge_base` still creates personal library with `owner_user_id=actor.actor_id` and `governance_status="personal"`.
- `list_knowledge_bases` must use `KnowledgeAccessPolicy(db).list_visible_topics(actor)` and preserve cursor/limit behavior.
- `get_knowledge_base` must use `require_read`.
- `update_knowledge_base` must use `require_edit`.
- `delete_knowledge_base` must use `require_delete`.
- Existing system KB delete guards remain in place.

- [ ] **Step 5: Add transfer routes**

Use functions from `backend.app.services.knowledge_rbac`.

Place `/admin/transfer-requests` routes before `/{kb_uid}` routes so route matching does not treat `admin` as `kb_uid`.

`GET /admin/transfer-requests`:

- Require admin via `policy.is_team_admin(actor)`.
- Return `{items, total}` for topics in same tenant where `governance_status == "pending_transfer"` and `deleted_at is None`.

- [ ] **Step 6: Add membership routes**

`GET /{kb_uid}/members`:

- Call `list_memberships`.
- Return `{items: [...], total: len(items)}`.

`PUT /{kb_uid}/members/{user_id}`:

- Validate `role` in service.
- Return membership DTO.

`DELETE /{kb_uid}/members/{user_id}`:

- Return `{"detail": "deleted"}`.

- [ ] **Step 7: Run API tests**

Run:

```bash
cd backend
pytest tests/test_knowledge_rbac_api.py tests/test_knowledge_access.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/knowledge_bases.py backend/tests/test_knowledge_rbac_api.py
git commit -m "feat: expose knowledge RBAC APIs"
```

---

## Task 5: Apply Fine-Grained Policy To Files, Enrichment, Retrieval, And Chat

**Files:**
- Modify: `backend/app/api/knowledge_files.py`
- Modify: `backend/app/api/knowledge_enrichment.py`
- Modify: `backend/app/api/knowledge_retrieval.py`
- Modify: `backend/app/api/agent_chat_proxy.py`
- Modify tests:
  - `backend/tests/test_knowledge_files_v1_api.py`
  - `backend/tests/test_knowledge_retrieval_api.py`
  - `backend/tests/test_agent_chat_proxy.py`
  - Create `backend/tests/test_knowledge_rbac_operations.py` if existing test files are too broad.

**Interfaces:**
- Consumes policy methods from Task 2.
- No public response shape changes except more accurate 403s.

- [ ] **Step 1: Write operation-level tests**

Create `backend/tests/test_knowledge_rbac_operations.py`:

```python
from backend.app.models import KnowledgeBaseMembership, KnowledgeBaseRole, KnowledgeGovernanceStatus, KnowledgeTopic


def auth_headers(user: str, tenant: str = "tenant-a"):
    return {"X-Prism-Actor": user, "X-Prism-Tenant": tenant}


def seed_managed(db_session, owner="alice"):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id=owner,
        name="Managed",
        governance_status=KnowledgeGovernanceStatus.MANAGED.value,
        active_index_generation="idx-1",
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def grant(db_session, topic, user_id, role):
    db_session.add(KnowledgeBaseMembership(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        user_id=user_id,
        role=role,
        granted_by="admin",
    ))
    db_session.commit()


def test_viewer_cannot_upload_file(client, db_session):
    topic = seed_managed(db_session)
    grant(db_session, topic, "viewer", KnowledgeBaseRole.VIEWER.value)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/files",
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_headers("viewer"),
    )
    assert response.status_code == 403


def test_contributor_cannot_generate_mindmap(client, db_session):
    topic = seed_managed(db_session)
    grant(db_session, topic, "contributor", KnowledgeBaseRole.CONTRIBUTOR.value)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        json={"idempotency_key": "mindmap-1"},
        headers=auth_headers("contributor"),
    )
    assert response.status_code == 403


def test_editor_can_generate_mindmap(client, db_session, monkeypatch):
    topic = seed_managed(db_session)
    grant(db_session, topic, "editor", KnowledgeBaseRole.EDITOR.value)

    def fake_publish(job_id: str) -> None:
        return None

    monkeypatch.setattr("backend.app.api.knowledge_enrichment._publish_job_id", fake_publish)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        json={"idempotency_key": "mindmap-2"},
        headers=auth_headers("editor"),
    )
    assert response.status_code == 202


def test_chat_proxy_rejects_unreadable_requested_kb(client, db_session):
    topic = seed_managed(db_session)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "hello", "kb_uids": [topic.kb_uid]},
        headers=auth_headers("bob"),
    )
    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd backend
pytest tests/test_knowledge_rbac_operations.py -q
```

Expected: FAIL where current APIs still use owner/manage semantics.

- [ ] **Step 3: Update file API permissions**

In `backend/app/api/knowledge_files.py`:

- Change `_require_file(..., manage: bool)` into `_require_file(..., capability: Literal["read", "edit"])`, or keep helper simple:
  - `read` uses `require_read`
  - `edit` uses `require_edit`
- In `upload_file`, require `KnowledgeAccessPolicy(db).require_contribute(actor, kb_uid)` before registering.
- In `update_file_metadata`, `delete_file`, manual stage/retry routes, use:
  - metadata updates and delete: `require_edit`
  - parse/index enqueue: `require_contribute`
  - graph build enqueue: `require_edit`
- Keep preview/download as `require_read`.

Use `rg "require_manage|_require_file" backend/app/api/knowledge_files.py` to confirm no old manage-only check remains where a finer method is required.

- [ ] **Step 4: Update enrichment API permissions**

In `backend/app/api/knowledge_enrichment.py`:

- `_topic_or_problem(..., manage=True)` currently maps to `require_manage`.
- Replace with `capability: Literal["read", "edit"]`.
- Mindmap/sample-question read endpoints use `read`.
- Mindmap/sample-question generation and mutation use `edit`.
- Export endpoint should use `read` unless it exposes raw export with private storage URIs. If export includes raw files or internal paths, use `edit` and sanitize output. Check `build_knowledge_export` output before deciding.

- [ ] **Step 5: Update retrieval API**

In `backend/app/api/knowledge_retrieval.py`:

- Keep `require_read(actor, kb_uid)`.
- Ensure no response includes inaccessible KB metadata.
- No role fields go to Engine.

- [ ] **Step 6: Update chat proxy**

In `backend/app/api/agent_chat_proxy.py`:

- `_authorize_kbs` already calls `policy.require_read`; keep this behavior.
- Add test coverage that managed ungranted libraries return 403.
- If `req.kb_uids` is empty, do not auto-expand to all visible libraries in this task. Preserve current user-selected behavior.

- [ ] **Step 7: Run operation tests and relevant existing tests**

Run:

```bash
cd backend
pytest tests/test_knowledge_rbac_operations.py tests/test_knowledge_rbac_api.py tests/test_knowledge_access.py tests/test_agent_chat_proxy.py tests/test_knowledge_retrieval_api.py -q
```

Expected: PASS. If existing tests fail because they seed personal libraries and use non-owner actors, update test fixtures to grant membership or use owner actors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/knowledge_files.py backend/app/api/knowledge_enrichment.py backend/app/api/knowledge_retrieval.py backend/app/api/agent_chat_proxy.py backend/tests
git commit -m "feat: enforce RBAC on knowledge operations"
```

---

## Task 6: Engine Scope Regression Tests

**Files:**
- Modify: `engine/tests/test_knowledge_tool_contracts.py` or create `engine/tests/test_knowledge_scope_rbac.py`
- Modify only if needed: `engine/app/agent/tools/knowledge_base.py`
- Modify only if needed: `engine/app/api/retrieval.py`

**Interfaces:**
- Consumes signed `AuthorizedKnowledgeScope.allowed_kb_uids`.
- Produces no new public API.

- [ ] **Step 1: Inspect existing Engine scope tests**

Run:

```bash
rg "allowed_kb_uids|KnowledgeAccess|scope" engine/tests -n
```

Identify existing tests. If they already cover all cases below, extend them instead of creating a new file.

- [ ] **Step 2: Add scope boundary tests**

Create `engine/tests/test_knowledge_scope_rbac.py` if no focused file exists.

Test intent:

```python
def test_tool_rejects_kb_uid_outside_allowed_scope(...):
    # Build a ToolContext with knowledge_scope.allowed_kb_uids=("kb-a",)
    # Call the target resolver with "kb-b"
    # Assert it rejects with a clear access error.
```

Because tool helper signatures may be private, inspect `engine/app/agent/tools/knowledge_base.py` and use the smallest importable helper. The plan requirement is exact behavior:

- `kb_uid="kb-b"` with allowed `("kb-a",)` must not reach DB retrieval.
- missing scope must return/raise an authorization failure.
- multi-KB default list must be exactly `allowed_kb_uids`.

- [ ] **Step 3: Run Engine tests to verify current behavior**

Run:

```bash
cd engine
pytest tests/test_knowledge_scope_rbac.py -q
```

Expected: PASS if current Engine is already strict. If FAIL, continue Step 4.

- [ ] **Step 4: Patch Engine only if a test fails**

In `engine/app/agent/tools/knowledge_base.py`, ensure the resolver uses this logic:

```python
if kb_uid and kb_uid not in scope.allowed_kb_uids:
    raise PermissionError(f"knowledge base is not authorized: {kb_uid}")
```

Do not add team role parsing to Engine.

- [ ] **Step 5: Run relevant Engine tests**

Run:

```bash
cd engine
pytest tests/test_knowledge_scope_rbac.py tests/test_knowledge_tool_contracts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/tests engine/app/agent/tools/knowledge_base.py engine/app/api/retrieval.py
git commit -m "test: cover knowledge scope RBAC boundaries"
```

If no Engine production file changed, commit only the tests.

---

## Task 7: Frontend API Types And Capability-Driven Knowledge Index

**Files:**
- Modify: `frontend/src/features/knowledge/api/knowledgeBases.ts`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeIndexPage.tsx`
- Create: `frontend/tests/knowledge-rbac-navigation.test.mjs`

**Interfaces:**
- Consumes Backend `KnowledgeBase` response fields from Task 4.
- Produces API functions:
  - `requestTransfer(kbUid: string, data: { message?: string | null }): Promise<KnowledgeBase>`
  - `withdrawTransfer(kbUid: string): Promise<KnowledgeBase>`
  - `listTransferRequests(): Promise<KnowledgeBaseListResponse>`
  - `acceptTransfer(kbUid: string): Promise<KnowledgeBase>`
  - `rejectTransfer(kbUid: string, data: { reason?: string | null }): Promise<KnowledgeBase>`
  - `listMembers(kbUid: string): Promise<KnowledgeBaseMembersResponse>`
  - `updateMember(kbUid: string, userId: string, data: { role: KnowledgeBaseMemberRole }): Promise<KnowledgeBaseMember>`
  - `deleteMember(kbUid: string, userId: string): Promise<{ detail: string }>`

- [ ] **Step 1: Write source-scanning tests**

Create `frontend/tests/knowledge-rbac-navigation.test.mjs`:

```javascript
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const api = readFileSync(resolve(root, 'src/features/knowledge/api/knowledgeBases.ts'), 'utf8')
const indexPage = readFileSync(resolve(root, 'src/features/knowledge/pages/KnowledgeIndexPage.tsx'), 'utf8')

assert.match(api, /governance_status:\s*KnowledgeGovernanceStatus/, 'KnowledgeBase should expose governance_status.')
assert.match(api, /can_contribute:\s*boolean/, 'KnowledgeBase should expose can_contribute.')
assert.match(api, /requestTransfer/, 'API should include transfer request action.')
assert.match(api, /acceptTransfer/, 'API should include admin accept transfer action.')
assert.match(api, /updateMember/, 'API should include member role update action.')

assert.match(indexPage, /我的个人库/, 'Knowledge index should show a personal libraries section.')
assert.match(indexPage, /提交中/, 'Knowledge index should show pending transfer libraries.')
assert.match(indexPage, /团队库/, 'Knowledge index should show managed team libraries.')
assert.match(indexPage, /can_delete/, 'Delete affordance should be capability-driven.')
assert.match(indexPage, /requestTransfer/, 'Personal libraries should expose transfer request action.')
assert.match(indexPage, /withdrawTransfer/, 'Pending transfer libraries should expose withdraw action.')
```

- [ ] **Step 2: Run frontend test to verify failure**

Run:

```bash
cd frontend
node --test tests/knowledge-rbac-navigation.test.mjs
```

Expected: FAIL because types/UI are missing.

- [ ] **Step 3: Extend API types**

In `frontend/src/features/knowledge/api/knowledgeBases.ts`:

Add:

```ts
export type KnowledgeGovernanceStatus = 'personal' | 'pending_transfer' | 'managed'
export type KnowledgeBaseMemberRole = 'viewer' | 'contributor' | 'editor' | 'manager'

export interface KnowledgeBaseMember {
  user_id: string
  role: KnowledgeBaseMemberRole
  granted_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface KnowledgeBaseMembersResponse {
  items: KnowledgeBaseMember[]
  total: number
}
```

Extend `KnowledgeBase`:

```ts
governance_status: KnowledgeGovernanceStatus
transfer_requested_by: string | null
transfer_requested_at: string | null
transfer_message: string | null
transfer_reviewed_by: string | null
transfer_reviewed_at: string | null
transfer_rejection_reason: string | null
my_role: 'admin' | 'owner' | KnowledgeBaseMemberRole | null
can_read: boolean
can_contribute: boolean
can_edit: boolean
can_manage_members: boolean
can_delete: boolean
```

Add API methods named in Interfaces.

- [ ] **Step 4: Refactor index grouping**

In `KnowledgeIndexPage.tsx`:

- Compute:

```ts
const personalItems = items.filter((kb) => kb.governance_status === 'personal')
const pendingItems = items.filter((kb) => kb.governance_status === 'pending_transfer')
const managedItems = items.filter((kb) => kb.governance_status === 'managed')
```

- Replace single grid with reusable local render function:

```tsx
function KnowledgeSection({ title, items }: { title: string; items: KnowledgeBase[] }) {
  if (items.length === 0) return null
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold text-slate-500">{title}</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map(renderKnowledgeCard)}
      </div>
    </section>
  )
}
```

- Use visible section names exactly:
  - `我的个人库`
  - `提交中`
  - `团队库`

- Delete action must check `kb.can_delete`, not `isDeleteDisabled(kb)` alone.
- Keep `is_system || delete_disabled` protection too:

```ts
function canDeleteKb(kb: KnowledgeBase) {
  return kb.can_delete && !kb.is_system && !kb.delete_disabled
}
```

- Add transfer actions:
  - personal: `提交为团队库`
  - pending_transfer: `撤回提交`

Use buttons that call `knowledgeBasesApi.requestTransfer(kb.kb_uid, { message: null })` and `knowledgeBasesApi.withdrawTransfer(kb.kb_uid)`, then reload.

- [ ] **Step 5: Run frontend test**

Run:

```bash
cd frontend
node --test tests/knowledge-rbac-navigation.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd frontend
pnpm build
```

Expected: PASS. Existing bundle size warning is acceptable.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/knowledge/api/knowledgeBases.ts frontend/src/features/knowledge/pages/KnowledgeIndexPage.tsx frontend/tests/knowledge-rbac-navigation.test.mjs
git commit -m "feat: show knowledge RBAC states in frontend"
```

---

## Task 8: Frontend Detail Capabilities And Members Panel

**Files:**
- Modify: `frontend/src/features/knowledge/components/KnowledgeShell.tsx`
- Create: `frontend/src/features/knowledge/components/KnowledgeMembersPanel.tsx`
- Modify as needed:
  - `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeGraphPage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeGovernancePage.tsx`
  - `frontend/src/features/knowledge/pages/KnowledgeSettingsPage.tsx`
- Test: `frontend/tests/knowledge-rbac-navigation.test.mjs`

**Interfaces:**
- Consumes `KnowledgeBase.can_*` and `knowledgeBasesApi` methods.
- Produces capability-driven UI for detail pages.

- [ ] **Step 1: Extend frontend source-scanning test**

Append to `frontend/tests/knowledge-rbac-navigation.test.mjs`:

```javascript
const shell = readFileSync(resolve(root, 'src/features/knowledge/components/KnowledgeShell.tsx'), 'utf8')

assert.match(shell, /can_manage_members/, 'Knowledge shell should expose member management by capability.')
assert.match(shell, /KnowledgeMembersPanel/, 'Knowledge shell should render a members panel.')
assert.match(shell, /my_role/, 'Knowledge shell should display or use the current user role.')
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd frontend
node --test tests/knowledge-rbac-navigation.test.mjs
```

Expected: FAIL because shell/member panel does not exist.

- [ ] **Step 3: Inspect KnowledgeShell data loading**

Open `frontend/src/features/knowledge/components/KnowledgeShell.tsx`.

Identify where it loads current KB detail. If it does not load detail directly, trace the current route loader/store and use the existing pattern.

- [ ] **Step 4: Create members panel**

Create `frontend/src/features/knowledge/components/KnowledgeMembersPanel.tsx`.

Requirements:

- Props:

```ts
interface KnowledgeMembersPanelProps {
  kbUid: string
  open: boolean
  onClose: () => void
}
```

- On open, call `knowledgeBasesApi.listMembers(kbUid)`.
- Render current members with role select.
- Role options exactly `viewer`, `contributor`, `editor`, `manager`.
- Updating role calls `knowledgeBasesApi.updateMember`.
- Removing calls `knowledgeBasesApi.deleteMember`.
- Keep UI simple. Do not build user search in this first pass unless an existing user API exists in Prism. Allow a text input for `user_id` plus role select for adding/updating a member.

- [ ] **Step 5: Wire shell actions**

In `KnowledgeShell.tsx`:

- Add a role badge using `kb.my_role`.
- Show a member-management button only when `kb.can_manage_members`.
- Render `KnowledgeMembersPanel` when clicked.
- Hide or disable settings/edit actions when `!kb.can_edit`.

Do not block route rendering client-side only. Backend still enforces actual access.

- [ ] **Step 6: Gate page actions by capability**

Search:

```bash
rg "upload|delete|generate|rebuild|settings|governance|graph" frontend/src/features/knowledge -n
```

For buttons that mutate files/index/graph/config:

- Upload and index actions require `can_contribute`.
- Graph build/rebuild and governance generation require `can_edit`.
- Settings update requires `can_edit`.
- Member panel requires `can_manage_members`.
- Delete knowledge base remains index-page only or admin-only by `can_delete`.

If current subpages cannot easily access KB capabilities, pass capabilities through `KnowledgeShell` context or use the existing workspace store. Keep the implementation local and avoid large state-management rewrites.

- [ ] **Step 7: Run frontend tests/build**

Run:

```bash
cd frontend
node --test tests/knowledge-rbac-navigation.test.mjs
pnpm build
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/knowledge frontend/tests/knowledge-rbac-navigation.test.mjs
git commit -m "feat: gate knowledge UI by RBAC capabilities"
```

---

## Task 9: Integration And Regression Sweep

**Files:**
- Modify tests only unless failures expose missing implementation:
  - `backend/tests/test_knowledge_access.py`
  - `backend/tests/test_knowledge_rbac_api.py`
  - `backend/tests/test_knowledge_rbac_operations.py`
  - `backend/tests/test_agent_chat_proxy.py`
  - `engine/tests/test_knowledge_scope_rbac.py`
  - `frontend/tests/knowledge-rbac-navigation.test.mjs`

**Interfaces:**
- Produces a verified branch ready for review.

- [ ] **Step 1: Run Backend targeted tests**

Run:

```bash
cd backend
pytest tests/test_knowledge_access.py tests/test_knowledge_rbac_api.py tests/test_knowledge_rbac_operations.py tests/test_agent_chat_proxy.py tests/test_knowledge_retrieval_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Engine targeted tests**

Run:

```bash
cd engine
pytest tests/test_knowledge_scope_rbac.py tests/test_knowledge_tool_contracts.py -q
```

Expected: PASS. If `tests/test_knowledge_tool_contracts.py` does not exist, run the closest scope-related test discovered by `rg "allowed_kb_uids|knowledge_scope" engine/tests -n`.

- [ ] **Step 3: Run Frontend targeted tests**

Run:

```bash
cd frontend
node --test tests/knowledge-rbac-navigation.test.mjs tests/knowledge-deeplink-routes.test.mjs
pnpm build
```

Expected: PASS.

- [ ] **Step 4: Run migration upgrade in a disposable database**

If the local Docker database is available, run the project’s normal migration command. If there is no documented command, run:

```bash
alembic upgrade head
```

from repo root with the same environment normally used for Backend tests.

Expected: migration applies cleanly.

If the database is unavailable, record this as not run in the final handoff with the exact connection error.

- [ ] **Step 5: Run full suites only if targeted tests pass**

Run:

```bash
cd backend
pytest -q
```

Run:

```bash
cd engine
pytest -q
```

Run:

```bash
cd frontend
pnpm test
```

Known caveat from 2026-08-02: frontend full `pnpm test` may fail because several existing Node/ESM source-import tests rely on incompatible module loading or `import.meta.dirname`. Do not treat those as RBAC regressions unless the failure mentions files changed in this plan.

- [ ] **Step 6: Manual smoke test**

Start services using the repo’s normal dev commands:

```bash
cd frontend
pnpm dev
```

In another terminal, start Backend as usual:

```bash
python -m backend.run
```

Manual scenarios:

1. As `alice` member, create a knowledge base. It appears in `我的个人库`.
2. As `bob` member, verify Alice’s personal library is absent.
3. As Alice, submit transfer. It appears in `提交中`, delete is disabled, edit/upload remains available.
4. As admin, view pending transfer list and accept.
5. As Alice, verify the library appears as `团队库` with role `editor`.
6. As Bob, verify the library is absent before membership grant.
7. As admin, grant Bob `viewer`.
8. As Bob, verify the library appears, retrieval works, upload/edit buttons are hidden or disabled.
9. As admin, grant Bob `contributor`; verify upload is visible and graph rebuild remains hidden.
10. As admin, grant Bob `editor`; verify graph rebuild/edit controls are visible.
11. As Bob `editor`, verify member management is hidden.
12. As admin, verify delete is available for the team library.

- [ ] **Step 7: Commit final test adjustments**

If this task changed any tests or small implementation fixes:

```bash
git add backend/tests engine/tests frontend/tests backend/app engine/app frontend/src
git commit -m "test: verify team knowledge RBAC end to end"
```

If no files changed, do not create an empty commit.

---

## Handoff Notes For Implementer

- Start from a clean worktree or isolated worktree. If there are unrelated user changes, do not revert them.
- Follow tasks in order. Do not begin frontend before Backend response fields exist.
- Prefer small commits exactly as listed.
- Do not replace the current signed scope model with frontend-side filtering.
- Do not give `manager` team-library deletion.
- Do not make original owner `manager` after admin acceptance; it must be `editor`.
- Do not allow pending-transfer owner deletion.
- Do not introduce departments or share_config JSON in this implementation.
- Keep existing personal inbox system-library protections intact.

