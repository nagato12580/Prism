# Dev Auth Identity Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a development-only login flow, real `users` and `auth_sessions` tables, session-first backend actor resolution, `/auth/me`, and frontend current-user bootstrap so Prism can identify the signed-in user without hardcoded actor assumptions.

**Architecture:** Introduce a small auth slice that is independent from domain-specific team membership. The backend resolves identity from an `HttpOnly` session cookie first and only falls back to `X-Prism-*` headers when compatibility mode is enabled. The frontend adds a tiny auth store, a dev login page, a protected app shell, and routes consumers such as team admin through `/auth/me`.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, pytest, React 18, React Router, Zustand, TypeScript, Node test runner

---

## File Map

### Backend

- Create: `backend/app/models/auth.py`
  - Holds `User` and `AuthSession` ORM models.
- Modify: `backend/app/models/__init__.py`
  - Re-export `User` and `AuthSession`.
- Create: `backend/app/services/auth.py`
  - Session lookup, cookie helpers, dev-login user provisioning, logout helpers, current-user payload serialization.
- Modify: `backend/app/security/actor.py`
  - Resolve `ActorContext` from request/session first, then header fallback.
- Modify: `backend/app/config.py`
  - Add `DEV_AUTH_ENABLED`, `HEADER_AUTH_FALLBACK_ENABLED`, `SESSION_COOKIE_NAME`, `SESSION_TTL_HOURS`, `SESSION_COOKIE_SECURE`.
- Create: `backend/app/api/auth.py`
  - `POST /auth/login/dev`, `POST /auth/logout`, `GET /auth/me`.
- Modify: `backend/app/api/__init__.py`
  - Register `auth_router`.
- Create: `backend/alembic/versions/20260803_01_dev_auth_identity_bootstrap.py`
  - Create `users` and `auth_sessions`.
- Create: `backend/tests/test_auth_api.py`
  - Auth API, session precedence, fallback compatibility tests.
- Modify: `backend/tests/conftest.py`
  - Set auth-related env flags for tests that create the app.
- Modify: `backend/tests/test_team_admin_api.py`
  - Add a session-backed team admin integration test after `/auth/me` exists.

### Frontend

- Create: `frontend/src/features/auth/api/auth.ts`
  - Typed auth API client for `loginDev`, `logout`, `me`.
- Create: `frontend/src/features/auth/store/authStore.ts`
  - Shared auth state and bootstrap helpers.
- Create: `frontend/src/features/auth/pages/LoginPage.tsx`
  - Minimal development login screen.
- Create: `frontend/src/features/auth/components/RequireAuth.tsx`
  - Route guard that waits for bootstrap then redirects to `/login`.
- Modify: `frontend/src/app/routes.tsx`
  - Add `/login`; wrap protected app shell with auth guard.
- Modify: `frontend/src/main.tsx`
  - Trigger auth bootstrap provider/setup.
- Modify: `frontend/src/features/team/pages/TeamAdminPage.tsx`
  - Stop passing `currentUserId="admin"`.
- Modify: `frontend/src/features/team/pages/TeamMembersTab.tsx`
  - Read current user from auth store.
- Create: `frontend/tests/auth-bootstrap.test.mjs`
  - Route/auth store structure assertions.
- Modify: `frontend/tests/team-admin-console.test.mjs`
  - Assert team admin stops hardcoding `"admin"`.

## Task 1: Add auth data model and migration

**Files:**
- Create: `backend/app/models/auth.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/20260803_01_dev_auth_identity_bootstrap.py`
- Test: `backend/tests/test_auth_api.py`

- [ ] **Step 1: Write the failing model smoke test**

Add this test skeleton to `backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_auth_api.py::test_auth_models_round_trip -v`
Expected: FAIL with `ImportError` or `AttributeError` because `User` and `AuthSession` do not exist yet.

- [ ] **Step 3: Add the auth ORM models**

Create `backend/app/models/auth.py` with:

```python
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR

from ..database import Base
from ..utils.time import local_now
from .knowledge_types import uuid4_str


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_status", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    username = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    email = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="active", server_default="active")
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)


class AuthSession(Base):
    __tablename__ = "auth_session"
    __table_args__ = (
        Index("ix_auth_session_user", "user_id"),
        Index("ix_auth_session_expires_at", "expires_at"),
    )

    id = Column(CHAR(36), primary_key=True, default=uuid4_str)
    user_id = Column(CHAR(36), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=local_now)
    last_seen_at = Column(DateTime, default=local_now)
    created_by_mode = Column(String(32), nullable=False, default="dev_login", server_default="dev_login")
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
```

Modify `backend/app/models/__init__.py` imports and `__all__`:

```python
from .auth import User, AuthSession
```

```python
    "User",
    "AuthSession",
```

- [ ] **Step 4: Add the migration**

Create `backend/alembic/versions/20260803_01_dev_auth_identity_bootstrap.py` with upgrade core:

```python
def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", mysql.CHAR(36), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "auth_session",
        sa.Column("id", mysql.CHAR(36), primary_key=True, nullable=False),
        sa.Column("user_id", mysql.CHAR(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_mode", sa.String(length=32), nullable=False, server_default="dev_login"),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_auth_session_user", "auth_session", ["user_id"])
    op.create_index("ix_auth_session_expires_at", "auth_session", ["expires_at"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_auth_api.py::test_auth_models_round_trip -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/auth.py backend/app/models/__init__.py backend/alembic/versions/20260803_01_dev_auth_identity_bootstrap.py backend/tests/test_auth_api.py
git commit -m "feat(auth): add user and auth session models"
```

## Task 2: Implement session-first actor resolution and auth API

**Files:**
- Create: `backend/app/services/auth.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/security/actor.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_auth_api.py`

- [ ] **Step 1: Write failing API tests for dev login, me, logout, and header fallback**

Append these tests to `backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run auth API tests to verify they fail**

Run: `pytest backend/tests/test_auth_api.py -v`
Expected: FAIL with `404` on `/api/v1/auth/...` and missing auth resolver behavior.

- [ ] **Step 3: Add auth configuration**

Extend `backend/app/config.py`:

```python
    DEV_AUTH_ENABLED: bool = os.getenv("DEV_AUTH_ENABLED", "1") == "1"
    HEADER_AUTH_FALLBACK_ENABLED: bool = os.getenv("HEADER_AUTH_FALLBACK_ENABLED", "1") == "1"
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "prism_session")
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "72"))
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
```

- [ ] **Step 4: Implement auth service helpers**

Create `backend/app/services/auth.py` with these units:

```python
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now


@dataclass(frozen=True)
class AuthIdentity:
    user: User
    session: AuthSession


def build_me_payload(*, username: str, display_name: str, status: str, tenant_id: str, auth_mode: str, team_role: str | None, user_id: str | None = None) -> dict:
    return {
        "id": user_id or username,
        "username": username,
        "display_name": display_name,
        "email": None,
        "status": status,
        "tenant_id": tenant_id,
        "auth_mode": auth_mode,
        "team_role": team_role,
    }


def upsert_dev_user(db: Session, *, username: str, display_name: str | None) -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username, display_name=display_name or username, status="active")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        db.commit()
        db.refresh(user)
    return user


def create_dev_session(db: Session, *, user: User, request: Request) -> AuthSession:
    row = AuthSession(
        user_id=user.id,
        expires_at=local_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
```

- [ ] **Step 5: Implement session-first actor resolver**

Replace `backend/app/security/actor.py` with request-aware resolution:

```python
from typing import Annotated

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    request_id: str = ""
    auth_mode: str = "header-fallback"
    user_pk: str | None = None
```

Add core resolution shape:

```python
def _resolve_session_actor(request: Request) -> ActorContext | None:
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        return None
    db: Session = SessionLocal()
    try:
        row = db.query(AuthSession).filter_by(id=session_id).one_or_none()
        if row is None or row.expires_at < local_now():
            return None
        user = db.query(User).filter_by(id=row.user_id).one()
        if user.status != "active":
            raise HTTPException(status_code=403, detail={"code": "AUTH_USER_DISABLED"})
        return ActorContext(
            actor_id=user.username,
            tenant_id=user.username,
            auth_mode="session",
            user_pk=user.id,
            roles=(),
        )
    finally:
        db.close()
```

Then make `get_actor_context` prefer `_resolve_session_actor(request)` and only parse headers when `settings.HEADER_AUTH_FALLBACK_ENABLED` is true.

- [ ] **Step 6: Add auth API router**

Create `backend/app/api/auth.py`:

```python
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import get_db
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.auth import build_me_payload, create_dev_session, upsert_dev_user
from backend.app.services.knowledge_access import KnowledgeAccessPolicy

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)


@router.post("/login/dev")
def login_dev(body: DevLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if not settings.DEV_AUTH_ENABLED:
        return Response(status_code=404)
    username = body.username.strip()
    user = upsert_dev_user(db, username=username, display_name=body.display_name.strip() if body.display_name else None)
    session = create_dev_session(db, user=user, request=request)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session.id,
        httponly=True,
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )
    return build_me_payload(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        status=user.status,
        tenant_id=user.username,
        auth_mode="session",
        team_role="member",
    )
```

Add `/logout` and `/me` in the same file, with `/me` deriving `team_role` via `KnowledgeAccessPolicy(db).get_team_role(actor)`.

- [ ] **Step 7: Register router and set auth-friendly test env**

Modify `backend/app/api/__init__.py`:

```python
from .auth import router as auth_router
```

```python
    api_prefix.include_router(auth_router)
```

Modify `backend/tests/conftest.py` before `create_app()`:

```python
    prev_dev_auth = os.environ.get("DEV_AUTH_ENABLED")
    prev_header_fallback = os.environ.get("HEADER_AUTH_FALLBACK_ENABLED")
    os.environ["DEV_AUTH_ENABLED"] = "1"
    os.environ["HEADER_AUTH_FALLBACK_ENABLED"] = "1"
```

Restore both values in the `finally` block.

- [ ] **Step 8: Run backend auth tests to verify they pass**

Run: `pytest backend/tests/test_auth_api.py -v`
Expected: PASS

- [ ] **Step 9: Run team admin regression tests**

Run: `pytest backend/tests/test_team_admin_api.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/auth.py backend/app/api/auth.py backend/app/security/actor.py backend/app/config.py backend/app/api/__init__.py backend/tests/conftest.py backend/tests/test_auth_api.py backend/tests/test_team_admin_api.py
git commit -m "feat(auth): add dev auth endpoints and session-first actor resolution"
```

## Task 3: Add frontend auth bootstrap and login route

**Files:**
- Create: `frontend/src/features/auth/api/auth.ts`
- Create: `frontend/src/features/auth/store/authStore.ts`
- Create: `frontend/src/features/auth/pages/LoginPage.tsx`
- Create: `frontend/src/features/auth/components/RequireAuth.tsx`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/main.tsx`
- Test: `frontend/tests/auth-bootstrap.test.mjs`

- [ ] **Step 1: Write failing frontend structure tests**

Create `frontend/tests/auth-bootstrap.test.mjs`:

```javascript
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

const root = resolve(import.meta.dirname ?? new URL('..', import.meta.url).pathname)
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const main = readFileSync(resolve(root, 'src/main.tsx'), 'utf8')
const store = readFileSync(resolve(root, 'src/features/auth/store/authStore.ts'), 'utf8')

assert.match(routes, /path:\s*'login'/, 'routes should expose a login page')
assert.match(routes, /RequireAuth/, 'protected app shell should use RequireAuth')
assert.match(main, /refreshMe|bootstrapAuth/, 'main entry should bootstrap auth state')
assert.match(store, /create\(/, 'auth store should be implemented with Zustand')
assert.match(store, /refreshMe/, 'auth store should expose refreshMe')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm.cmd test -- --test-name-pattern auth-bootstrap`
Expected: FAIL because the auth files and login route do not exist yet.

- [ ] **Step 3: Add auth API client**

Create `frontend/src/features/auth/api/auth.ts`:

```ts
import { requestJSON } from '@/features/knowledge/api/client'

export interface MeResponse {
  id: string
  username: string
  display_name: string
  email: string | null
  status: string
  tenant_id: string
  auth_mode: 'session' | 'header-fallback'
  team_role: string | null
}

export const authApi = {
  loginDev(data: { username: string; display_name?: string }) {
    return requestJSON<MeResponse>('/auth/login/dev', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
  logout() {
    return requestJSON<{ detail: string }>('/auth/logout', { method: 'POST' })
  },
  me() {
    return requestJSON<MeResponse>('/auth/me')
  },
}
```

- [ ] **Step 4: Add auth store and route guard**

Create `frontend/src/features/auth/store/authStore.ts`:

```ts
import { create } from 'zustand'
import { ApiProblem } from '@/features/knowledge/api/client'
import { authApi, type MeResponse } from '@/features/auth/api/auth'

interface AuthState {
  me: MeResponse | null
  loading: boolean
  bootstrapped: boolean
  refreshMe: () => Promise<void>
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  me: null,
  loading: false,
  bootstrapped: false,
  async refreshMe() {
    set({ loading: true })
    try {
      const me = await authApi.me()
      set({ me, loading: false, bootstrapped: true })
    } catch (error) {
      const problem = error as ApiProblem
      if (problem.status === 401) {
        set({ me: null, loading: false, bootstrapped: true })
        return
      }
      throw error
    }
  },
  clear() {
    set({ me: null, loading: false, bootstrapped: true })
  },
}))
```

Create `frontend/src/features/auth/components/RequireAuth.tsx`:

```tsx
import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/features/auth/store/authStore'
import { LoadingState } from '@/components/ui/StateView'

export function RequireAuth() {
  const { me, loading, bootstrapped, refreshMe } = useAuthStore()

  useEffect(() => {
    if (!bootstrapped && !loading) void refreshMe()
  }, [bootstrapped, loading, refreshMe])

  if (!bootstrapped || loading) return <LoadingState label="Loading account..." />
  if (!me) return <Navigate to="/login" replace />
  return <Outlet />
}
```

- [ ] **Step 5: Add login page and protected routes**

Create `frontend/src/features/auth/pages/LoginPage.tsx`:

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '@/features/auth/api/auth'
import { useAuthStore } from '@/features/auth/store/authStore'

export function LoginPage() {
  const navigate = useNavigate()
  const refreshMe = useAuthStore((s) => s.refreshMe)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')

  const submit = async () => {
    try {
      setError('')
      await authApi.loginDev({ username: username.trim(), display_name: displayName.trim() || undefined })
      await refreshMe()
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed')
    }
  }

  return null
}
```

Modify `frontend/src/app/routes.tsx`:

```tsx
import { RequireAuth } from '@/features/auth/components/RequireAuth'
import { LoginPage } from '@/features/auth/pages/LoginPage'
```

```tsx
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <MainLayout />,
        children: [
          // existing child routes stay here
        ],
      },
    ],
  },
```

- [ ] **Step 6: Bootstrap auth in app entry**

Modify `frontend/src/main.tsx`:

```tsx
import { useAuthStore } from '@/features/auth/store/authStore'

void useAuthStore.getState().refreshMe()
```

Keep this above `ReactDOM.createRoot(...)` so the store starts loading before first paint.

- [ ] **Step 7: Run frontend auth bootstrap test**

Run: `npm.cmd test -- --test-name-pattern auth-bootstrap`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/auth/api/auth.ts frontend/src/features/auth/store/authStore.ts frontend/src/features/auth/pages/LoginPage.tsx frontend/src/features/auth/components/RequireAuth.tsx frontend/src/app/routes.tsx frontend/src/main.tsx frontend/tests/auth-bootstrap.test.mjs
git commit -m "feat(frontend): add dev auth bootstrap and login route"
```

## Task 4: Wire team admin to real current identity

**Files:**
- Modify: `frontend/src/features/team/pages/TeamAdminPage.tsx`
- Modify: `frontend/src/features/team/pages/TeamMembersTab.tsx`
- Modify: `frontend/tests/team-admin-console.test.mjs`
- Test: `frontend/tests/auth-bootstrap.test.mjs`

- [ ] **Step 1: Write the failing team admin assertion**

Modify `frontend/tests/team-admin-console.test.mjs`:

```javascript
assert.doesNotMatch(page, /currentUserId=\"admin\"/, 'Team admin page must not hardcode the current user id.')
assert.match(membersTab, /useAuthStore/, 'Members tab should read the current user from auth state.')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm.cmd test -- --test-name-pattern team-admin-console`
Expected: FAIL because `TeamAdminPage.tsx` still contains `currentUserId="admin"`.

- [ ] **Step 3: Remove the hardcoded current user prop**

Modify `frontend/src/features/team/pages/TeamAdminPage.tsx`:

```tsx
        {tab === 'members' ? <TeamMembersTab /> : null}
```

Modify `frontend/src/features/team/pages/TeamMembersTab.tsx` imports and current-user logic:

```tsx
import { useAuthStore } from '@/features/auth/store/authStore'
```

```tsx
export function TeamMembersTab() {
  const currentUserId = useAuthStore((s) => s.me?.username ?? '')
```

Keep the existing self-protection comparison:

```tsx
            const isSelf = m.user_id === currentUserId
```

- [ ] **Step 4: Run the team admin test to verify it passes**

Run: `npm.cmd test -- --test-name-pattern team-admin-console`
Expected: PASS for the team admin console assertions.

- [ ] **Step 5: Run frontend build**

Run: `npm.cmd run build`
Expected: `vite build` completes successfully.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/team/pages/TeamAdminPage.tsx frontend/src/features/team/pages/TeamMembersTab.tsx frontend/tests/team-admin-console.test.mjs
git commit -m "fix(team): use authenticated current user in team admin"
```

## Task 5: Add backend compatibility and consumer regression coverage

**Files:**
- Modify: `backend/tests/test_auth_api.py`
- Modify: `backend/tests/test_team_admin_api.py`
- Modify: `frontend/tests/auth-bootstrap.test.mjs`
- Modify: `frontend/tests/team-admin-console.test.mjs`

- [ ] **Step 1: Add disabled-user and expired-session backend tests**

Append to `backend/tests/test_auth_api.py`:

```python
from backend.app.models import AuthSession, User
from backend.app.utils.time import local_now
from datetime import timedelta


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
```

- [ ] **Step 2: Add one session-backed team admin flow test**

Append to `backend/tests/test_team_admin_api.py`:

```python
def test_team_admin_members_list_works_with_dev_session(client, db_session):
    login = client.post("/api/v1/auth/login/dev", json={"username": "admin"})
    assert login.status_code == 200
    db_session.add(TeamMember(tenant_id="admin", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()

    response = client.get("/api/v1/team/admin/members")
    assert response.status_code == 200
    assert response.json()["total"] == 1
```

- [ ] **Step 3: Run focused backend regressions**

Run: `pytest backend/tests/test_auth_api.py backend/tests/test_team_admin_api.py -v`
Expected: PASS

- [ ] **Step 4: Add route/auth regression assertions**

Append to `frontend/tests/auth-bootstrap.test.mjs`:

```javascript
const loginPage = readFileSync(resolve(root, 'src/features/auth/pages/LoginPage.tsx'), 'utf8')
assert.match(loginPage, /authApi\.loginDev/, 'Login page should call the dev login endpoint.')
assert.match(loginPage, /navigate\('\/'/, 'Login page should return to the main app on success.')
```

- [ ] **Step 5: Run focused frontend regressions**

Run: `npm.cmd test -- --test-name-pattern "auth-bootstrap|team-admin-console"`
Expected: PASS for auth bootstrap and team admin structure tests.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_auth_api.py backend/tests/test_team_admin_api.py frontend/tests/auth-bootstrap.test.mjs frontend/tests/team-admin-console.test.mjs
git commit -m "test(auth): add bootstrap and compatibility regression coverage"
```

## Final verification

- [ ] **Step 1: Run backend auth and team-admin tests**

Run: `pytest backend/tests/test_auth_api.py backend/tests/test_team_admin_api.py -v`
Expected: PASS

- [ ] **Step 2: Run frontend focused auth tests**

Run: `npm.cmd test -- --test-name-pattern "auth-bootstrap|team-admin-console"`
Expected: PASS

- [ ] **Step 3: Run frontend build**

Run: `npm.cmd run build`
Expected: `vite build` completes successfully.

- [ ] **Step 4: Review changed files**

Run: `git diff --stat HEAD~4..HEAD`
Expected: auth models, auth APIs, actor resolution, login page, auth store, and team admin identity wiring only.

- [ ] **Step 5: Optional full-repo checkpoint**

Run: `git status --short`
Expected: only known unrelated local edits outside this plan remain.

## Self-review

- Spec coverage:
  - `users` and `auth_sessions`: Task 1
  - session-first actor resolution and header fallback: Task 2
  - `/auth/login/dev`, `/auth/logout`, `/auth/me`: Task 2
  - frontend auth store, login page, protected routes: Task 3
  - team admin current-user fix: Task 4
  - compatibility and regression coverage: Task 5
- Placeholder scan:
  - No `TODO`, `TBD`, or unnamed “appropriate handling” steps remain.
- Type consistency:
  - Backend public identity uses `username` as `actor_id`.
  - Frontend `me.username` is the value consumed by team admin self-protection.
