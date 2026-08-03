# Prism Development Auth And Identity Bootstrap Design

## Summary

Prism currently has an `ActorContext` abstraction, but it is populated directly from request headers such as `X-Prism-Actor` and falls back to `default-user` when headers are absent. This is enough for local API testing, but it is not a real identity system. The immediate result is that the frontend cannot reliably know who the current user is, which is already surfacing in the team admin console via hardcoded identity assumptions.

This design introduces a minimal but real identity layer for development use:

- a dedicated `users` table as the authoritative identity source
- a dedicated `auth_sessions` table for browser-backed login state
- development-only login/logout endpoints
- a `/me` endpoint for frontend identity bootstrap
- unified backend identity resolution that prefers session auth and only falls back to `X-Prism-*` headers during migration

The goal is to move Prism off ad hoc header-only identity without forcing a full production auth rollout in the same change.

## Goals

- Introduce a real user record model independent from `team_members`
- Allow a browser session to log in during development without handcrafting request headers
- Provide the frontend a canonical way to fetch the current user
- Preserve compatibility with existing tests and legacy flows during migration
- Unblock UI behaviors that need current-user awareness, including self-protection in team admin flows

## Non-Goals

- Production-grade authentication
- Password-based login
- OAuth, SSO, or external identity provider integration
- Multi-factor auth
- Fine-grained org administration beyond the existing team role model
- Full removal of header-based actor injection in this phase

## Current State

The backend constructs `ActorContext` from request headers. If no headers are present, it falls back to:

- `actor_id = default-user`
- `tenant_id = actor_id`

The frontend has no authenticated bootstrap API and no shared current-user state. Pages that need identity either assume defaults or cannot render correct self-targeting behaviors.

The repository already contains domain models that reference user identity by string fields such as `user_id`, `owner_user_id`, and `actor_id`. This means the identity bootstrap must coexist with those string ids before any deeper normalization happens.

## Proposed Approach

Use a gradual dual-track identity system:

1. Add `users` and `auth_sessions` as real auth primitives
2. Add development-only login/logout and `/me`
3. Change backend actor resolution to:
   - prefer session cookie auth
   - then allow header fallback when enabled
4. Add frontend auth bootstrap and a minimal login page
5. Migrate pages that need current identity to `/me`
6. Keep legacy header-based tests and scripts working during the transition

This is intentionally a bootstrap layer, not the final auth architecture.

## Data Model

### `users`

Authoritative identity table.

Fields:

- `id`: internal primary key, UUID string
- `username`: unique stable login name used by development login
- `display_name`: user-facing name
- `email`: nullable
- `status`: enum-like string, initially `active` or `disabled`
- `created_at`
- `updated_at`

Constraints:

- unique index on `username`
- optional unique index on `email` when not null
- check constraint on `status`

Notes:

- `username` is the development login handle
- existing domain tables may continue storing string user ids equal to `username` in this phase
- `users.id` exists now to avoid a future redesign even if most current references still use username-shaped identifiers

### `auth_sessions`

Browser session table.

Fields:

- `id`: opaque session id, UUID string
- `user_id`: foreign key to `users.id`
- `expires_at`
- `created_at`
- `last_seen_at`
- `created_by_mode`: string such as `dev_login`
- `ip_address`: nullable
- `user_agent`: nullable

Constraints:

- index on `user_id`
- index on `expires_at`

Notes:

- sessions are revocable server-side
- the browser stores only the opaque session id in an `HttpOnly` cookie

### Relationship To `team_members`

`team_members` remains a role-assignment table, not a user table.

In this phase:

- `team_members.user_id` continues to store the public user identifier string already used by the domain, expected to match `users.username`
- management flows may validate that a target `user_id` exists in `users` before creating team membership

This keeps the change compatible with existing domain assumptions while separating identity data from authorization assignments.

## Backend Authentication Flow

### Session Cookie

The backend adds a cookie-based session mechanism:

- cookie name: `prism_session`
- `HttpOnly`: true
- `SameSite`: `Lax`
- `Secure`: configurable by environment
- path: `/`

The cookie value is the `auth_sessions.id`.

### Actor Resolution Order

Introduce a unified auth resolver used by `get_actor_context`:

1. Try session cookie auth
2. If session exists and is valid:
   - load `auth_sessions`
   - load `users`
   - construct `ActorContext` from that identity
3. If no valid session and `HEADER_AUTH_FALLBACK_ENABLED=true`:
   - parse `X-Prism-Actor`, `X-Prism-Tenant`, `X-Prism-Roles`
   - construct fallback `ActorContext`
4. If neither path applies:
   - return unauthenticated or legacy default behavior only where explicitly allowed

### `ActorContext` Extensions

Extend `ActorContext` with:

- `auth_mode`: `"session"` or `"header-fallback"`
- `user_pk`: `str | None`

Semantics:

- `actor_id` remains the public user identifier used by the current domain
- under session auth, `actor_id = users.username`
- `user_pk = users.id`
- under header fallback, `user_pk = None`

This lets current domain logic keep using `actor_id` while future work can pivot toward internal user primary keys.

## API Design

All new auth endpoints live under `/api/v1/auth`.

### `POST /auth/login/dev`

Purpose:

- create a development login session

Request body:

- `username: string`
- optional `display_name: string`

Behavior:

- available only when `DEV_AUTH_ENABLED=true`
- trims and validates `username`
- finds existing user by `username`
- if not found, auto-creates a new active user
- creates an `auth_sessions` row
- sets the `prism_session` cookie
- returns the current user payload

Rationale:

- development bootstrap should be frictionless
- auto-create avoids building admin user provisioning before the auth skeleton exists

### `POST /auth/logout`

Purpose:

- destroy current session

Behavior:

- if session cookie exists, delete matching `auth_sessions` row
- clear the session cookie
- always return success to keep logout idempotent

### `GET /auth/me`

Purpose:

- bootstrap frontend identity

Response fields:

- `id`
- `username`
- `display_name`
- `email`
- `status`
- `tenant_id`
- `auth_mode`
- `team_role`

Behavior:

- under session auth, returns authoritative user identity
- under header fallback, returns a synthetic compatible payload
- when unauthenticated and no fallback applies, returns `401`

`team_role` is derived from `KnowledgeAccessPolicy.get_team_role(actor)` or equivalent logic.

### Optional Follow-Up Endpoint

Not required in the first implementation, but strongly recommended next:

- `GET /auth/users`

Purpose:

- support user pickers for admin pages
- replace free-text `user_id` entry with selectable existing users

This endpoint is intentionally outside the bootstrap critical path and can ship after `/me`.

## Frontend Design

### Auth Store

Add a small global auth store with:

- `me`
- `loading`
- `isAuthenticated`
- `refreshMe()`
- `logout()`

Responsibilities:

- call `/api/v1/auth/me` on app bootstrap
- hold the current user for reuse across pages
- expose a single source of truth for "who am I"

### Login Page

Add `/login` as a lightweight development login screen.

UI:

- one `username` input
- optional `display_name` input
- submit button
- simple error feedback

Behavior:

- submit to `POST /auth/login/dev`
- on success, refresh auth state and navigate to the main app

This page is deliberately minimal. It is a dev bootstrap, not a final branded auth experience.

### Route Guard

Protected app routes should:

- allow rendering while auth state is loading
- redirect to `/login` when `/me` returns unauthenticated

### Team Admin Fix

`TeamMembersTab` should stop receiving `currentUserId="admin"` from the page shell.

Instead:

- read `authStore.me.username` or the equivalent current-user identifier
- compare member rows against that value
- disable self-targeting role/status/delete controls based on real identity

This change becomes trivial once `/me` exists.

## Migration Strategy

### Phase 1: Bootstrap Primitives

- add `users`
- add `auth_sessions`
- add auth config flags
- add `/auth/login/dev`, `/auth/logout`, `/auth/me`

### Phase 2: Session-First Identity Resolution

- extend `ActorContext`
- update `get_actor_context` to prefer session auth
- preserve header fallback

### Phase 3: Frontend Bootstrap

- add auth store
- add login page
- call `/auth/me` at startup

### Phase 4: First Consumer Migration

- migrate team admin page to real current-user identity
- optionally validate team member creation against existing `users`

### Phase 5: Wider Adoption

- move other pages off inferred identity assumptions
- gradually reduce fallback-only behaviors

### Phase 6: Hardening

Later, not in this design:

- disable development login in production
- disable header fallback
- replace dev login with real auth provider

## Compatibility Rules

To keep this rollout safe:

- session auth always wins over headers
- header fallback remains opt-in via config
- legacy tests that explicitly set `X-Prism-Actor` remain valid while fallback is on
- old endpoints should not be forced to understand `users.id` yet

This avoids a high-blast-radius rewrite of domain ownership fields.

## Error Handling

### Backend

- invalid session id: clear cookie, treat as unauthenticated
- expired session: delete row, clear cookie, treat as unauthenticated
- disabled user under session auth: reject as `403`
- dev login disabled by config: `404` or `403`, but prefer a stable explicit auth-disabled error code
- malformed dev login username: `422`

### Frontend

- `/me` 401 on bootstrap redirects to `/login`
- `/me` 403 for disabled user shows a blocked-access state
- logout clears local auth state even if backend session is already gone

## Security Notes

This is intentionally not production auth, but basic guardrails still matter:

- use `HttpOnly` cookie instead of storing auth state in local storage
- maintain server-side session revocation
- avoid trusting arbitrary frontend-submitted user identity once session auth is present
- gate dev login behind config so it cannot be accidentally exposed in hardened environments

Because this phase still allows header fallback, it is not a final trust boundary. The trust boundary becomes meaningful only after fallback is disabled.

## Testing Strategy

### Backend Tests

- dev login creates a user when one does not exist
- dev login reuses existing user when username already exists
- dev login sets a session cookie
- `/auth/me` returns current user from session auth
- `/auth/me` returns fallback identity when header fallback is enabled
- logout invalidates the session and clears the cookie
- expired sessions are rejected and cleared
- disabled users cannot authenticate successfully

### Frontend Tests

- unauthenticated protected route redirects to `/login`
- successful dev login loads and stores `/me`
- auth store exposes current user after bootstrap
- team admin page disables self-targeting actions for the actual logged-in user
- logout clears auth state and returns protected pages to login flow

### Migration Safety Tests

- existing header-based API tests still pass when fallback is enabled
- session auth overrides conflicting header identity when both are present

## Open Decisions Deferred

These are intentionally deferred, not left ambiguous:

- production login mechanism
- password storage and reset flows
- external identity provider integration
- whether `tenant_id` should remain equal to username by default for personal/dev users
- whether domain tables should later migrate from username strings to `users.id`

They are outside the bootstrap scope and should not block this implementation.

## Recommended Implementation Order

1. Database migrations for `users` and `auth_sessions`
2. Backend auth config and session-first actor resolution
3. `/auth/login/dev`, `/auth/logout`, `/auth/me`
4. Frontend auth store and `/login`
5. Team admin current-user fix
6. Optional validation that team member targets exist in `users`

This order gives immediate user-visible value while containing migration risk.

## Success Criteria

The bootstrap is successful when:

- a developer can log into Prism from the browser without manually crafting actor headers
- the frontend can reliably determine the current user via `/me`
- team admin self-protection uses real current identity
- existing header-based tests still pass under fallback mode
- new auth logic is isolated enough to later replace dev login without redesigning consumer pages
