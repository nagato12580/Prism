# 团队管理控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a「团队管理」admin console (route `/team/admin`) with three tabs — 待接收审核 (review/accept/reject pending transfers), 团队库授权 (grant KB members on managed libraries), and 成员管理 (CRUD team members admin/member with self-protection) — plus the backend `/team/admin/members` CRUD API that backs the members tab.

**Architecture:** Keep authorization in Backend. All `/team/admin/*` routes are guarded by the existing `KnowledgeAccessPolicy.is_team_admin(actor)`. Member CRUD business logic (validation, self-protection, last-admin guard, audit logging) lives in a new service `backend/app/services/team_members.py`; a new router `backend/app/api/team_admin.py` maps service exceptions to `ApiProblem` responses. The frontend adds `teamAdminApi`, a `TeamAdminPage` shell with three tab components, a「管理」nav group, and a `/team/admin` route. The transfers-review and team-KB tabs reuse existing `knowledgeBasesApi` methods; the team-KB tab reuses the existing `KnowledgeMembersPanel`.

**Tech Stack:** FastAPI, SQLAlchemy ORM, pytest, React 18, TypeScript, React Router, Vite, Node test runner.

## Global Constraints

- Team roles are exactly `admin` and `member` (`TeamRole` enum values `"admin"` / `"member"`).
- Knowledge governance states are exactly `personal`, `pending_transfer`, `managed`.
- Knowledge-base membership roles are exactly `viewer`, `contributor`, `editor`, `manager`.
- Team member status values are exactly `active` / `disabled`.
- All `/team/admin/*` endpoints require `is_team_admin(actor)`; non-admin gets `ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Admin access required")`.
- Cannot operate on self (PUT/DELETE targeting `actor.actor_id` → 409 `SELF_OPERATION_DENIED`).
- Cannot remove/demote/disable the last `status=active` admin in the tenant (→ 409 `LAST_ADMIN_OPERATION_DENIED`).
- Every team-member mutation writes a `KnowledgeAccessAuditLog` row (`action` like `team_member.add` / `team_member.update` / `team_member.remove`).
- Do NOT copy Yuxi code; reuse only the architectural ideas already implemented in this repo.
- Preserve all existing RBAC behavior (do not weaken policy; do not re-derive permissions in the frontend).
- Do NOT commit regenerated `frontend/pnpm-lock.yaml` or `frontend/tsconfig.tsbuildinfo` — restore them after any `pnpm build`.
- Use focused commits after each task.

---

## File Structure

### Backend
- Create: `backend/app/services/team_members.py` — team-member CRUD service (list/add/update/remove) with validation, self-protection, last-admin guard, audit logging.
- Create: `backend/app/api/team_admin.py` — router `prefix="/team/admin"`; `GET/POST/PUT/DELETE /members[/{user_id}]`; maps service exceptions to `ApiProblem`.
- Modify: `backend/app/api/__init__.py` — import and register `team_admin_router`.
- Create: `backend/tests/test_team_admin_api.py` — service + API tests.

### Frontend
- Create: `frontend/src/features/team/api/teamAdmin.ts` — `teamAdminApi` + `TeamMember`/`TeamRole`/`TeamMemberStatus` types.
- Create: `frontend/src/features/team/pages/TeamAdminPage.tsx` — three-tab shell with admin probe + 403 fallback.
- Create: `frontend/src/features/team/pages/TransfersReviewTab.tsx` — pending-transfer review (accept/reject).
- Create: `frontend/src/features/team/pages/TeamKbsTab.tsx` — managed-KB list with member panel.
- Create: `frontend/src/features/team/pages/TeamMembersTab.tsx` — team-member CRUD.
- Modify: `frontend/src/layouts/MainLayout.tsx` — add「管理」nav group with「团队管理」entry (both `navSections` and `NavList`).
- Modify: `frontend/src/app/routes.tsx` — add `team/admin` route.
- Create: `frontend/tests/team-admin-console.test.mjs` — source-scanning assertions.

---

## Task 1: Team Member Service

**Files:**
- Create: `backend/app/services/team_members.py`
- Test: `backend/tests/test_team_admin_api.py`

**Interfaces:**
- Consumes: `backend.app.models.TeamMember`, `TeamRole` (from `backend.app.models.knowledge_types`), `KnowledgeAccessAuditLog`, `ActorContext`, `local_now`.
- Produces (consumed by Task 2 routes):
  - `list_team_members(db: Session, *, tenant_id: str) -> list[TeamMember]`
  - `add_team_member(db: Session, *, actor: ActorContext, user_id: str, role: str, status: str = "active") -> TeamMember`
  - `update_team_member(db: Session, *, actor: ActorContext, user_id: str, role: str | None = None, status: str | None = None) -> TeamMember`
  - `remove_team_member(db: Session, *, actor: ActorContext, user_id: str) -> None`
  - Exceptions: `TeamMemberNotFound`, `TeamMemberConflict` (duplicate add), `TeamMemberSelfOperationDenied`, `TeamMemberLastAdminDenied`.

- [ ] **Step 1: Write the failing service tests**

Append to `backend/tests/test_team_admin_api.py` (create the file with this content; the file will hold both service and API tests):

```python
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
    assert list_team_members(db_session, tenant_id="tenant-a") == []


def test_remove_last_admin_raises_last_admin_denied(db_session):
    seed_member(db_session, "admin", TeamRole.ADMIN.value)
    with pytest.raises(TeamMemberLastAdminDenied):
        remove_team_member(db_session, actor=actor("admin"), user_id="admin")


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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && python -m pytest tests/test_team_admin_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.app.services.team_members'`.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/team_members.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_team_admin_api.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/team_members.py backend/tests/test_team_admin_api.py
git commit -m "feat: add team member CRUD service"
```

---

## Task 2: Team Admin API Routes

**Files:**
- Create: `backend/app/api/team_admin.py`
- Modify: `backend/app/api/__init__.py`
- Test: `backend/tests/test_team_admin_api.py`

**Interfaces:**
- Consumes: `team_members` service functions + exceptions (Task 1), `KnowledgeAccessPolicy.is_team_admin`, `get_actor_context`, `ApiProblem`.
- Produces (consumed by Task 3 frontend):
  - `GET /api/v1/team/admin/members` → `{items: TeamMemberDto[], total: int}`
  - `POST /api/v1/team/admin/members` body `{user_id, role, status?}` → `TeamMemberDto`
  - `PUT /api/v1/team/admin/members/{user_id}` body `{role?, status?}` → `TeamMemberDto`
  - `DELETE /api/v1/team/admin/members/{user_id}` → `{"detail": "deleted"}`
  - `TeamMemberDto` fields: `user_id`, `role`, `status`, `created_at`, `updated_at`.

- [ ] **Step 1: Write the failing API tests**

Append to `backend/tests/test_team_admin_api.py`:

```python
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
    assert response.json()["code"] == "SELF_OPERATION_DENIED"


def test_admin_cannot_remove_last_admin(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    response = client.delete("/api/v1/team/admin/members/admin", headers=auth_headers("admin"))
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN_OPERATION_DENIED"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && python -m pytest tests/test_team_admin_api.py -q`
Expected: FAIL — `404 Not Found` on `/api/v1/team/admin/*` (router not registered yet).

- [ ] **Step 3: Implement the router**

Create `backend/app/api/team_admin.py`:

```python
# backend/app/api/team_admin.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiProblem
from backend.app.database import get_db
from backend.app.models import TeamMember
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessPolicy
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

router = APIRouter(prefix="/team/admin", tags=["team-admin"])


class TeamMemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=36)
    role: str
    status: str = "active"


class TeamMemberUpdate(BaseModel):
    role: str | None = None
    status: str | None = None


class TeamMemberDto(BaseModel):
    user_id: str
    role: str
    status: str
    created_at: object | None = None
    updated_at: object | None = None

    model_config = {"from_attributes": True}


class TeamMemberListResponse(BaseModel):
    items: list[TeamMemberDto]
    total: int


def _require_admin(policy: KnowledgeAccessPolicy, actor: ActorContext) -> None:
    if not policy.is_team_admin(actor):
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Admin access required")


def _team_member_dto(row: TeamMember) -> dict:
    return {
        "user_id": row.user_id,
        "role": row.role,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/members", response_model=TeamMemberListResponse)
def list_members(
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    items = list_team_members(db, tenant_id=actor.tenant_id)
    return TeamMemberListResponse(
        items=[_team_member_dto(m) for m in items],
        total=len(items),
    )


@router.post("/members", response_model=TeamMemberDto)
def create_member(
    body: TeamMemberCreate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = add_team_member(
            db,
            actor=actor,
            user_id=body.user_id,
            role=body.role,
            status=body.status,
        )
    except TeamMemberConflict as e:
        raise ApiProblem(409, "MEMBER_CONFLICT", str(e))
    return _team_member_dto(row)


@router.put("/members/{user_id}", response_model=TeamMemberDto)
def update_member(
    user_id: str,
    body: TeamMemberUpdate,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        row = update_team_member(
            db,
            actor=actor,
            user_id=user_id,
            role=body.role,
            status=body.status,
        )
    except TeamMemberSelfOperationDenied as e:
        raise ApiProblem(409, "SELF_OPERATION_DENIED", str(e))
    except TeamMemberLastAdminDenied as e:
        raise ApiProblem(409, "LAST_ADMIN_OPERATION_DENIED", str(e))
    except TeamMemberNotFound as e:
        raise ApiProblem(404, "MEMBER_NOT_FOUND", str(e))
    except TeamMemberConflict as e:
        raise ApiProblem(422, "INVALID_MEMBER_FIELD", str(e))
    return _team_member_dto(row)


@router.delete("/members/{user_id}")
def delete_member(
    user_id: str,
    actor: ActorContext = Depends(get_actor_context),
    db: Session = Depends(get_db),
):
    policy = KnowledgeAccessPolicy(db)
    _require_admin(policy, actor)
    try:
        remove_team_member(db, actor=actor, user_id=user_id)
    except TeamMemberSelfOperationDenied as e:
        raise ApiProblem(409, "SELF_OPERATION_DENIED", str(e))
    except TeamMemberLastAdminDenied as e:
        raise ApiProblem(409, "LAST_ADMIN_OPERATION_DENIED", str(e))
    except TeamMemberNotFound as e:
        raise ApiProblem(404, "MEMBER_NOT_FOUND", str(e))
    return {"detail": "deleted"}
```

- [ ] **Step 4: Register the router**

Modify `backend/app/api/__init__.py`: add the import and `include_router` call, following the existing pattern:

```python
from .team_admin import router as team_admin_router
```

and in `register_routers`:

```python
    api_prefix.include_router(team_admin_router)
```

Add `team_admin_router` import line with the other `from .xxx import router` lines (alphabetical placement optional, keep readable).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_team_admin_api.py -q`
Expected: PASS (14 tests total: 10 service + 4 API).

- [ ] **Step 6: Run existing RBAC tests to confirm no regression**

Run: `cd backend && python -m pytest tests/test_knowledge_access.py tests/test_knowledge_rbac_api.py tests/test_knowledge_rbac_operations.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/team_admin.py backend/app/api/__init__.py backend/tests/test_team_admin_api.py
git commit -m "feat: expose team admin member API"
```

---

## Task 3: Frontend Team Admin API

**Files:**
- Create: `frontend/src/features/team/api/teamAdmin.ts`
- Test: `frontend/tests/team-admin-console.test.mjs`

**Interfaces:**
- Consumes: `requestJSON` from `@/features/knowledge/api/client`.
- Produces (consumed by Task 4):
  - `type TeamRole = 'admin' | 'member'`
  - `type TeamMemberStatus = 'active' | 'disabled'`
  - `interface TeamMember { user_id: string; role: TeamRole; status: TeamMemberStatus; created_at: string | null; updated_at: string | null }`
  - `interface TeamMemberListResponse { items: TeamMember[]; total: number }`
  - `teamAdminApi.listMembers() -> Promise<TeamMemberListResponse>`
  - `teamAdminApi.addMember(data: { user_id: string; role: TeamRole; status?: TeamMemberStatus }) -> Promise<TeamMember>`
  - `teamAdminApi.updateMember(userId: string, data: { role?: TeamRole; status?: TeamMemberStatus }) -> Promise<TeamMember>`
  - `teamAdminApi.removeMember(userId: string) -> Promise<{ detail: string }>`

- [ ] **Step 1: Write the failing source-scanning test**

Create `frontend/tests/team-admin-console.test.mjs`:

```javascript
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const teamAdmin = readFileSync(resolve(root, 'src/features/team/api/teamAdmin.ts'), 'utf8')

assert.match(teamAdmin, /TeamRole/, 'teamAdmin should define a TeamRole type.')
assert.match(teamAdmin, /TeamMemberStatus/, 'teamAdmin should define a TeamMemberStatus type.')
assert.match(teamAdmin, /listMembers/, 'teamAdminApi should expose listMembers.')
assert.match(teamAdmin, /addMember/, 'teamAdminApi should expose addMember.')
assert.match(teamAdmin, /updateMember/, 'teamAdminApi should expose updateMember.')
assert.match(teamAdmin, /removeMember/, 'teamAdminApi should expose removeMember.')
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend && node --test tests/team-admin-console.test.mjs`
Expected: FAIL — `ENOENT` reading `teamAdmin.ts`.

- [ ] **Step 3: Implement the API client**

Create `frontend/src/features/team/api/teamAdmin.ts`:

```typescript
// Team admin member CRUD against the Backend `/team/admin/members` routes.

import { requestJSON } from '@/features/knowledge/api/client'

export type TeamRole = 'admin' | 'member'
export type TeamMemberStatus = 'active' | 'disabled'

export interface TeamMember {
  user_id: string
  role: TeamRole
  status: TeamMemberStatus
  created_at: string | null
  updated_at: string | null
}

export interface TeamMemberListResponse {
  items: TeamMember[]
  total: number
}

export interface TeamMemberCreate {
  user_id: string
  role: TeamRole
  status?: TeamMemberStatus
}

export interface TeamMemberUpdate {
  role?: TeamRole
  status?: TeamMemberStatus
}

export const teamAdminApi = {
  listMembers(): Promise<TeamMemberListResponse> {
    return requestJSON<TeamMemberListResponse>('/team/admin/members')
  },

  addMember(data: TeamMemberCreate): Promise<TeamMember> {
    return requestJSON<TeamMember>('/team/admin/members', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateMember(userId: string, data: TeamMemberUpdate): Promise<TeamMember> {
    return requestJSON<TeamMember>(`/team/admin/members/${encodeURIComponent(userId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  removeMember(userId: string): Promise<{ detail: string }> {
    return requestJSON<{ detail: string }>(`/team/admin/members/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    })
  },
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && node --test tests/team-admin-console.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/team/api/teamAdmin.ts frontend/tests/team-admin-console.test.mjs
git commit -m "feat: add team admin API client"
```

---

## Task 4: Team Admin Page, Tabs, Navigation, Route

**Files:**
- Create: `frontend/src/features/team/pages/TeamAdminPage.tsx`
- Create: `frontend/src/features/team/pages/TransfersReviewTab.tsx`
- Create: `frontend/src/features/team/pages/TeamKbsTab.tsx`
- Create: `frontend/src/features/team/pages/TeamMembersTab.tsx`
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/src/app/routes.tsx`
- Test: `frontend/tests/team-admin-console.test.mjs`

**Interfaces:**
- Consumes: `teamAdminApi` (Task 3), `knowledgeBasesApi` (existing), `KnowledgeMembersPanel` (existing `frontend/src/features/knowledge/components/KnowledgeMembersPanel.tsx`), UI components `Dialog`/`Button`/`Badge`/`Input`/`EmptyState`/`ErrorState`/`LoadingState`/`NotFoundState`, `ApiProblem` from `@/features/knowledge/api/client`.
- Produces: `/team/admin` route rendering `TeamAdminPage`; nav「管理」group with「团队管理」entry.

- [ ] **Step 1: Extend the source-scanning test**

Append to `frontend/tests/team-admin-console.test.mjs`:

```javascript
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const layout = readFileSync(resolve(root, 'src/layouts/MainLayout.tsx'), 'utf8')
const page = readFileSync(resolve(root, 'src/features/team/pages/TeamAdminPage.tsx'), 'utf8')
const transfersTab = readFileSync(resolve(root, 'src/features/team/pages/TransfersReviewTab.tsx'), 'utf8')
const kbsTab = readFileSync(resolve(root, 'src/features/team/pages/TeamKbsTab.tsx'), 'utf8')
const membersTab = readFileSync(resolve(root, 'src/features/team/pages/TeamMembersTab.tsx'), 'utf8')

assert.match(routes, /team\/admin/, 'routes should define the team admin route.')
assert.match(layout, /团队管理/, 'MainLayout should show a team management nav entry.')
assert.match(page, /待接收/, 'TeamAdminPage should show the transfers review tab.')
assert.match(page, /团队库授权/, 'TeamAdminPage should show the team KBs tab.')
assert.match(page, /成员管理/, 'TeamAdminPage should show the members tab.')
assert.match(transfersTab, /listTransferRequests/, 'Transfers tab should call listTransferRequests.')
assert.match(transfersTab, /acceptTransfer/, 'Transfers tab should call acceptTransfer.')
assert.match(transfersTab, /rejectTransfer/, 'Transfers tab should call rejectTransfer.')
assert.match(kbsTab, /KnowledgeMembersPanel/, 'Team KBs tab should reuse the members panel.')
assert.match(membersTab, /teamAdminApi\.listMembers/, 'Members tab should list team members.')
assert.match(membersTab, /teamAdminApi\.addMember/, 'Members tab should add members.')
assert.match(membersTab, /teamAdminApi\.updateMember/, 'Members tab should update members.')
assert.match(membersTab, /teamAdminApi\.removeMember/, 'Members tab should remove members.')
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend && node --test tests/team-admin-console.test.mjs`
Expected: FAIL — `ENOENT` reading the new page files.

- [ ] **Step 3: Create the TeamMembersTab**

Create `frontend/src/features/team/pages/TeamMembersTab.tsx` (modeled on `KnowledgeMembersPanel.tsx`, roles `admin/member`, plus status toggle):

```tsx
import { useEffect, useState } from 'react'
import { Loader2, Plus, ShieldCheck, Trash2, Users } from 'lucide-react'
import {
  teamAdminApi,
  type TeamMember,
  type TeamMemberStatus,
  type TeamRole,
} from '@/features/team/api/teamAdmin'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, LoadingState } from '@/components/ui/StateView'

const ROLE_OPTIONS: TeamRole[] = ['admin', 'member']
const ROLE_LABELS: Record<TeamRole, string> = { admin: '管理员', member: '成员' }
const ROLE_TONES: Record<TeamRole, 'blue' | 'green'> = { admin: 'blue', member: 'green' }
const STATUS_OPTIONS: TeamMemberStatus[] = ['active', 'disabled']
const STATUS_LABELS: Record<TeamMemberStatus, string> = { active: '启用', disabled: '停用' }
const STATUS_TONES: Record<TeamMemberStatus, 'green' | 'amber'> = { active: 'green', disabled: 'amber' }

export function TeamMembersTab({ currentUserId }: { currentUserId?: string }) {
  const [members, setMembers] = useState<TeamMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<TeamRole>('member')
  const [busy, setBusy] = useState(false)
  const [forbidden, setForbidden] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    teamAdminApi
      .listMembers()
      .then((res) => setMembers(res.items))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) setForbidden(true)
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const addMember = () => {
    if (!userId.trim()) return
    setBusy(true)
    setError(null)
    teamAdminApi
      .addMember({ user_id: userId.trim(), role })
      .then(() => {
        setUserId('')
        load()
      })
      .catch(setError)
      .finally(() => setBusy(false))
  }

  const updateRole = (member: TeamMember, next: TeamRole) => {
    setError(null)
    teamAdminApi.updateMember(member.user_id, { role: next }).then(load).catch(setError)
  }

  const updateStatus = (member: TeamMember, next: TeamMemberStatus) => {
    setError(null)
    teamAdminApi.updateMember(member.user_id, { status: next }).then(load).catch(setError)
  }

  const removeMember = (member: TeamMember) => {
    setError(null)
    teamAdminApi.removeMember(member.user_id).then(load).catch(setError)
  }

  if (forbidden) return null // handled by parent page 403 fallback

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 rounded-lg border border-[var(--prism-line)] bg-slate-50/60 p-2.5">
        <Input
          aria-label="用户 ID"
          placeholder="输入 user_id 添加成员"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="flex-1"
        />
        <select
          aria-label="角色"
          value={role}
          onChange={(e) => setRole(e.target.value as TeamRole)}
          className="h-9 rounded-lg border border-[var(--prism-line)] bg-white px-2 text-sm text-slate-700 outline-none focus:border-blue-300"
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}（{r}）
            </option>
          ))}
        </select>
        <Button variant="primary" size="sm" onClick={addMember} loading={busy} disabled={!userId.trim()}>
          {busy ? null : <Plus size={14} />} 添加成员
        </Button>
      </div>

      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '操作失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载成员…" />
      ) : members.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="暂无团队成员" description="添加第一个团队成员开始管理" />
      ) : (
        <ul className="flex flex-col gap-2">
          {members.map((m) => {
            const isSelf = m.user_id === currentUserId
            return (
              <li
                key={m.user_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-2.5"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Users size={14} className="shrink-0 text-slate-400" />
                  <span className="truncate font-mono text-xs text-slate-700">{m.user_id}</span>
                  {isSelf ? <Badge tone="violet">我</Badge> : null}
                  <Badge tone={ROLE_TONES[m.role]}>{ROLE_LABELS[m.role]}</Badge>
                  <Badge tone={STATUS_TONES[m.status]}>{STATUS_LABELS[m.status]}</Badge>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <select
                    aria-label={`${m.user_id} 角色`}
                    value={m.role}
                    disabled={isSelf}
                    onChange={(e) => updateRole(m, e.target.value as TeamRole)}
                    className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-1.5 text-xs text-slate-700 outline-none focus:border-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}（{r}）
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`${m.user_id} 状态`}
                    value={m.status}
                    disabled={isSelf}
                    onChange={(e) => updateStatus(m, e.target.value as TeamMemberStatus)}
                    className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-1.5 text-xs text-slate-700 outline-none focus:border-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`移除 ${m.user_id}`}
                    title="移除成员"
                    disabled={isSelf}
                    onClick={() => removeMember(m)}
                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Create the TransfersReviewTab**

Create `frontend/src/features/team/pages/TransfersReviewTab.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import {
  knowledgeBasesApi,
  type KnowledgeBase,
} from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, LoadingState } from '@/components/ui/StateView'

export function TransfersReviewTab({ onForbidden }: { onForbidden?: () => void }) {
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [rejecting, setRejecting] = useState<KnowledgeBase | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .listTransferRequests()
      .then((res) => setItems(res.items))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) onForbidden?.()
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const accept = (kb: KnowledgeBase) => {
    setBusy(true)
    setError(null)
    knowledgeBasesApi
      .acceptTransfer(kb.kb_uid)
      .then(load)
      .catch(setError)
      .finally(() => setBusy(false))
  }

  const confirmReject = () => {
    if (!rejecting) return
    setBusy(true)
    setError(null)
    knowledgeBasesApi
      .rejectTransfer(rejecting.kb_uid, { reason: reason.trim() || null })
      .then(() => {
        setRejecting(null)
        setReason('')
        load()
      })
      .catch(setError)
      .finally(() => setBusy(false))
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '操作失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载待接收…" />
      ) : items.length === 0 ? (
        <EmptyState icon={Check} title="暂无待接收知识库" description="成员提交的知识库会出现在这里等待审核" />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((kb) => (
            <li key={kb.kb_uid} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-900">{kb.name}</span>
                  <Badge tone="amber">待接收</Badge>
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{kb.description || '暂无描述'}</div>
                <div className="mt-1 text-[11px] text-slate-400">
                  提交者：{kb.transfer_requested_by || kb.owner_user_id}
                  {kb.transfer_message ? ` · 说明：${kb.transfer_message}` : ''}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button variant="primary" size="sm" onClick={() => accept(kb)} loading={busy}>
                  <Check size={14} /> 接收
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setRejecting(kb)}>
                  <X size={14} /> 拒绝
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={!!rejecting} onClose={() => setRejecting(null)} title="拒绝提交" width="sm">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600">确认拒绝「{rejecting?.name}」的团队库提交？</p>
          <input
            aria-label="拒绝原因"
            placeholder="拒绝原因（可选）"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="h-9 w-full rounded-md border border-[var(--prism-line)] px-3 text-sm text-slate-700 outline-none focus:border-blue-300"
          />
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmReject} loading={busy}>
              确认拒绝
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
```

- [ ] **Step 5: Create the TeamKbsTab**

Create `frontend/src/features/team/pages/TeamKbsTab.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { ArrowRight, BookOpen, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  knowledgeBasesApi,
  type KnowledgeBase,
} from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, LoadingState } from '@/components/ui/StateView'
import { KnowledgeMembersPanel } from '@/features/knowledge/components/KnowledgeMembersPanel'

export function TeamKbsTab({ onForbidden }: { onForbidden?: () => void }) {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [membersKb, setMembersKb] = useState<KnowledgeBase | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .list({ limit: 200 })
      .then((res) => setItems(res.items.filter((kb) => kb.governance_status === 'managed')))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) onForbidden?.()
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="flex flex-col gap-3">
      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '加载失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载团队库…" />
      ) : items.length === 0 ? (
        <EmptyState icon={BookOpen} title="暂无团队库" description="接收的知识库会出现在这里" />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((kb) => (
            <li key={kb.kb_uid} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-900">{kb.name}</span>
                  <Badge tone="blue">团队库</Badge>
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{kb.description || '暂无描述'}</div>
                <div className="mt-1 text-[11px] text-slate-400">创建者：{kb.owner_user_id}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button variant="ghost" size="sm" onClick={() => setMembersKb(kb)}>
                  <Users size={14} /> 成员
                </Button>
                <Button variant="ghost" size="sm" onClick={() => navigate(`/knowledge/${kb.kb_uid}/files`)}>
                  <ArrowRight size={14} /> 进入
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <KnowledgeMembersPanel
        kbUid={membersKb?.kb_uid ?? ''}
        open={!!membersKb}
        onClose={() => setMembersKb(null)}
      />
    </div>
  )
}
```

- [ ] **Step 6: Create the TeamAdminPage shell**

Create `frontend/src/features/team/pages/TeamAdminPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { ArrowLeft, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { LoadingState, NotFoundState } from '@/components/ui/StateView'
import { TransfersReviewTab } from './TransfersReviewTab'
import { TeamKbsTab } from './TeamKbsTab'
import { TeamMembersTab } from './TeamMembersTab'
import { ApiProblem } from '@/features/knowledge/api/client'
import { knowledgeBasesApi } from '@/features/knowledge/api/knowledgeBases'

type TabKey = 'transfers' | 'kbs' | 'members'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'transfers', label: '待接收' },
  { key: 'kbs', label: '团队库授权' },
  { key: 'members', label: '成员管理' },
]

export function TeamAdminPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabKey>('transfers')
  const [probeLoading, setProbeLoading] = useState(true)
  const [forbidden, setForbidden] = useState(false)

  useEffect(() => {
    let cancelled = false
    knowledgeBasesApi
      .listTransferRequests()
      .then(() => { if (!cancelled) setForbidden(false) })
      .catch((e) => {
        const p = e as ApiProblem
        if (!cancelled && p?.status === 403) setForbidden(true)
      })
      .finally(() => { if (!cancelled) setProbeLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (probeLoading) return <LoadingState label="加载团队管理…" />
  if (forbidden) {
    return (
      <div className="flex flex-col gap-3">
        <NotFoundState title="无权访问" description="仅团队管理员可查看此页面" />
        <button
          type="button"
          onClick={() => navigate('/knowledge')}
          className="mx-auto inline-flex items-center gap-1 text-xs text-[var(--prism-blue)] hover:underline"
        >
          <ArrowLeft size={14} /> 返回知识库列表
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="team-admin-page">
      <header className="mb-4 flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)]/10 text-[var(--prism-blue)]">
          <ShieldCheck size={18} />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">团队管理</h1>
          <p className="text-xs text-slate-500">接收团队库、授权成员、管理团队成员</p>
        </div>
      </header>

      <nav className="mb-3 flex flex-wrap items-center gap-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              'inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
              tab === t.key
                ? 'bg-[var(--prism-blue)] text-white'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-auto">
        {tab === 'transfers' ? <TransfersReviewTab onForbidden={() => setForbidden(true)} /> : null}
        {tab === 'kbs' ? <TeamKbsTab onForbidden={() => setForbidden(true)} /> : null}
        {tab === 'members' ? <TeamMembersTab currentUserId="admin" /> : null}
      </div>
    </div>
  )
}
```

Note: `TeamMembersTab`'s `currentUserId` is passed as `"admin"` as a placeholder for the current actor id. There is no whoami endpoint in the current auth-adapter phase; the members tab disables self-operations based on this prop. If a real identity endpoint is added later, replace the literal.

- [ ] **Step 7: Add navigation entry**

Modify `frontend/src/layouts/MainLayout.tsx`:

1. Add an icon import for the new nav item (add `ShieldCheck` to the existing lucide import list).
2. In `navSections` (used by `CompactNav`), add a new section:

```tsx
  {
    label: '管理',
    items: [{ to: '/team/admin', label: '团队管理', icon: ShieldCheck }],
  },
```

3. In `NavList`, add a matching section (mirroring the existing groups):

```tsx
      <div className="px-2 text-[11px] font-medium text-slate-500">管理</div>
      <div className="space-y-1">
        <NavItem
          to="/team/admin"
          label="团队管理"
          icon={ShieldCheck}
          active={location.pathname === '/team/admin' || location.pathname.startsWith('/team/admin/')}
          isDark={isDark}
          onNavigate={onNavigate}
        />
      </div>
```

- [ ] **Step 8: Add the route**

Modify `frontend/src/app/routes.tsx`:

1. Add the import near the other feature-page imports:

```tsx
import { TeamAdminPage } from '@/features/team/pages/TeamAdminPage'
```

2. Add the route inside `MainLayout`'s children (e.g., after the `knowledge` block):

```tsx
      { path: 'team/admin', element: <TeamAdminPage /> },
```

- [ ] **Step 9: Run frontend test to verify it passes**

Run: `cd frontend && node --test tests/team-admin-console.test.mjs`
Expected: PASS (all assertions).

- [ ] **Step 10: Run frontend build**

Run: `cd frontend && pnpm build`
Expected: PASS (chunk-size warning acceptable). **Then restore generated files:**

```bash
cd .. && git checkout -- frontend/pnpm-lock.yaml frontend/tsconfig.tsbuildinfo
```

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/team frontend/src/layouts/MainLayout.tsx frontend/src/app/routes.tsx frontend/tests/team-admin-console.test.mjs
git commit -m "feat: add team admin console UI"
```

---

## Task 5: Integration And Regression Sweep

**Files:**
- Modify tests only unless failures expose missing implementation:
  - `backend/tests/test_team_admin_api.py`
  - `frontend/tests/team-admin-console.test.mjs`

**Interfaces:**
- Produces a verified branch ready for review.

- [ ] **Step 1: Run Backend targeted tests**

Run: `cd backend && python -m pytest tests/test_team_admin_api.py tests/test_knowledge_access.py tests/test_knowledge_rbac_api.py tests/test_knowledge_rbac_operations.py -q`
Expected: PASS.

- [ ] **Step 2: Run Frontend targeted tests + build**

Run: `cd frontend && node --test tests/team-admin-console.test.mjs tests/knowledge-rbac-navigation.test.mjs && pnpm build`
Expected: PASS (chunk-size warning acceptable). Then restore generated files:

```bash
cd .. && git checkout -- frontend/pnpm-lock.yaml frontend/tsconfig.tsbuildinfo
```

- [ ] **Step 3: Run full backend suite to confirm no new regressions**

Run: `cd backend && python -m pytest -q`
Expected: same failure set as the pre-existing baseline (36 environmental failures — API keys, Milvus gRPC, ASR/LLM). Confirm no NEW failures appear. To verify precisely, compare `grep '^FAILED'` output against the known baseline (`tests/test_knowledge_retrieval_api.py` degraded/public_query were already fixed in the RBAC work; the 36 remaining are environmental).

- [ ] **Step 4: Manual smoke checklist**

Start services per repo conventions (`cd frontend && pnpm dev` and `python -m backend.run`), then verify as admin:
1. Sidebar shows「管理」→「团队管理」.
2. `/team/admin` renders three tabs; default is「待接收」.
3. Empty states render for no pending transfers / no team KBs / no members.
4. With a `pending_transfer` KB,「接收」moves it to team KBs (owner becomes `editor`),「拒绝」returns it to personal with reason.
5. Team KBs tab「成员」opens the members panel; grant a viewer/contributor/editor.
6. Members tab: add a member, change role, toggle status, remove; own row is disabled.
7. A non-admin user sees「无权访问」on `/team/admin`.

If the smoke checklist cannot run (services unavailable), record it as not-run in the final handoff.

- [ ] **Step 5: Commit any test adjustments**

If this task changed tests or small implementation fixes:

```bash
git add backend/tests frontend/tests backend/app frontend/src
git commit -m "test: verify team admin console end to end"
```

If no files changed, do not create an empty commit.

---

## Handoff Notes For Implementer

- Start from a clean worktree or isolated worktree. If there are unrelated user changes, do not revert them.
- Follow tasks in order. Do not begin frontend before the Backend `/team/admin/members` API exists.
- The transfers-review and team-KB tabs reuse `knowledgeBasesApi` methods and the existing `KnowledgeMembersPanel` — do not reimplement them.
- Do NOT give `manager` team-library deletion; do NOT change any existing RBAC semantics.
- Do NOT re-derive permissions in the frontend — consume Backend `can_*` fields and 403 responses.
- Keep the `currentUserId="admin"` literal documented in `TeamAdminPage`; it is a phase-1 placeholder until a whoami endpoint exists.
- `pnpm build` regenerates `frontend/pnpm-lock.yaml` (9→6) and `frontend/tsconfig.tsbuildinfo` — always restore both before committing.
