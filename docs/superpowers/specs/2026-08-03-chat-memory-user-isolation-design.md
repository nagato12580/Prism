# Prism Chat And Memory User Isolation Design

## Summary

Prism now has real authenticated users, but the chat and memory subsystems still contain legacy assumptions such as `default-user`, global reads, and incomplete actor scoping. This creates a serious data-isolation gap: one logged-in user can potentially see another user's chat sessions, chat-derived memory drafts, or memory graph data.

This design introduces strict per-user isolation for the chat and memory subsystems only. It also defines a one-time historical migration rule: all legacy chat and memory data that is currently unowned or owned by `default-user` will be reassigned to the administrator account `nizhenshigoule@gmail.com`.

## Goals

- Ensure each authenticated user can access only their own chat and memory data
- Remove remaining `default-user` behavior from live chat and memory request paths
- Make all new chat and memory writes use `actor.actor_id` as the authoritative user key
- Reassign historical legacy chat and memory data to `nizhenshigoule@gmail.com`
- Keep the scope limited to chat and memory for this phase

## Non-Goals

- Knowledge base isolation
- Document and file isolation
- Asset and wiki isolation
- Admin cross-user audit access
- Team-shared chat or shared memory
- Refactoring the entire product to use `users.id` instead of username-shaped ids

## Scope

This phase covers only:

- `chat_session`
- `chat_message` via its parent session
- `memory_source`
- `memory_draft`
- `memory_statement`
- `memory_entry`
- `memory_entity`
- `memory_relation`
- `memory_event`
- `memory_insight`
- `memory_extraction_run`

The user-isolation key for this phase is:

- `actor.actor_id`

Under the current auth model, this is the authenticated user's `username`.

## Current Problems

The current codebase shows several isolation hazards:

- chat sessions already have `user_id`, but not every read/write path is guaranteed to enforce it
- many memory tables have `user_id`, but memory APIs still query using `DEFAULT_USER_ID`
- some extraction, graph, and derived-memory flows still assume a global default user
- some APIs read broad datasets and depend on frontend behavior rather than backend authorization

This means the data model mostly has the right columns, but the application logic is not consistently enforcing user ownership.

## User Isolation Rule

The first-phase rule is intentionally simple:

- a user may access only their own chat and memory data
- ownership is determined by `actor.actor_id`
- administrators do not get cross-user read access in this phase

This means `nizhenshigoule@gmail.com`, even as an admin, should not automatically browse other users' chat or memory data after isolation is enforced.

## Ownership Model

### Chat

Canonical ownership field:

- `chat_session.user_id`

Rules:

- every chat session belongs to exactly one user
- every chat message inherits ownership from its parent session
- all chat reads and writes must first resolve the session and confirm `session.user_id == actor.actor_id`

`chat_message` does not need its own user column in this phase because the session boundary is already sufficient.

### Memory

Canonical ownership field:

- `memory_*.user_id`

Rules:

- every memory row belongs to exactly one user
- all memory reads and writes must require `row.user_id == actor.actor_id`
- all memory extraction and derivation jobs must create rows using the current actor's id

### Session-Linked Memory

`memory_source.session_id` can continue to point at a chat session, but any extraction or review operation that traverses from memory back to chat must still validate that the linked session belongs to the same current user.

This prevents indirect leakage through joined session metadata.

## Historical Data Migration

All historical chat and memory data that is currently legacy-owned should be reassigned to:

- `nizhenshigoule@gmail.com`

### Migration Rule

For chat:

- any `chat_session.user_id` that is null, empty, or `default-user` becomes `nizhenshigoule@gmail.com`

For memory:

- any `memory_*` row whose `user_id` is `default-user`, null, or empty becomes `nizhenshigoule@gmail.com`

### Why This Rule

The repository does not currently have a trustworthy way to infer original owners for historical legacy data. Trying to guess ownership from content, timestamps, or session text would be error-prone and would risk assigning private data to the wrong user.

A single deterministic admin reassignment is safer than heuristic redistribution.

### Post-Migration Behavior

After migration:

- `nizhenshigoule@gmail.com` will see all historical chat and memory data that used to live under legacy ownership
- other users will see none of that historical legacy data
- newly created data will belong only to the currently authenticated user

## Backend Enforcement Design

### Chat API Enforcement

All chat endpoints must be updated to use `ActorContext` and enforce ownership.

Required behavior:

- list sessions: filter by `ChatSession.user_id == actor.actor_id`
- create session: always write `user_id = actor.actor_id`
- update session: load session by `id` and `user_id == actor.actor_id`
- delete session: load session by `id` and `user_id == actor.actor_id`
- list messages: resolve the session first and verify ownership
- add message: resolve the session first and verify ownership
- update message: resolve the parent session and verify ownership
- generate title or any session-derived action: verify ownership through the session

The important rule is that no chat path should ever load a session by id without also applying user ownership.

### Memory API Enforcement

All memory endpoints must stop using `DEFAULT_USER_ID` and switch to `actor.actor_id`.

Required behavior:

- list memory entries: filter by `actor.actor_id`
- create/update review source rows: write `user_id = actor.actor_id`
- list drafts: filter by `actor.actor_id`
- confirm/reject/supersede draft: load draft by both `id` and `user_id == actor.actor_id`
- list statements, entities, relations, events, insights: filter by `actor.actor_id`
- extraction endpoints: create all derived rows with `actor.actor_id`
- memory graph API payloads: include only rows for `actor.actor_id`

### Service-Layer Enforcement

Any chat or memory services called from APIs must either:

- accept `actor: ActorContext` and enforce ownership internally, or
- be called only with explicitly scoped ids already checked by the route layer

If both route and service can enforce it cheaply, prefer defense in depth for mutation paths.

## Error Semantics

For chat and memory access violations:

- missing target resource for the current user should return `404`
- not-owned resources should also resolve as `404`

This avoids leaking whether another user's resource exists.

The only exception should be true authentication failure, which remains `401`.

## Data Migration Implementation

The migration should be explicit and idempotent.

### Recommended Migration Strategy

Create a database migration or startup-safe data backfill step that:

1. updates legacy `chat_session.user_id`
2. updates all `memory_*` tables' `user_id`
3. leaves already non-legacy user ids untouched

For chat:

- `UPDATE chat_session SET user_id = 'nizhenshigoule@gmail.com' WHERE user_id IS NULL OR user_id = '' OR user_id = 'default-user'`

For memory:

- apply the same predicate to every `memory_*` table with a `user_id` column

### Idempotency Requirement

The backfill must be safe to run more than once. It must not overwrite rows that already belong to a concrete user other than the legacy default values.

## Frontend Impact

Frontend changes should be minimal if backend isolation is implemented correctly.

Expected effects:

- chat session sidebar will only list the current user's sessions
- memory inbox and memory graph will only show the current user's data
- switching accounts via logout/login will immediately switch visible chat and memory datasets

The frontend should not be responsible for filtering other users' data. If a page currently assumes broad backend results, that assumption should be removed.

## Testing Strategy

### Backend Chat Tests

Add tests covering:

- user A sees only their own sessions
- user A cannot load user B's messages
- user A cannot update or delete user B's session
- newly created sessions always use the current actor id

### Backend Memory Tests

Add tests covering:

- user A sees only their own drafts, statements, entries, and graph payload
- user A cannot confirm or reject user B's draft
- extraction writes rows for the current actor
- historical `default-user` rows become visible only to `nizhenshigoule@gmail.com` after migration

### Cross-Account Regression Tests

Add focused multi-user tests that:

1. create data as user A
2. authenticate as user B
3. verify the same data is not visible

This is the core regression class for this project and should be treated as mandatory.

## Risks

### Risk 1: Hidden legacy write paths

Some extraction or background flows may still write `default-user` or omit explicit ownership. If those are missed, isolation will drift over time even after read paths are corrected.

Mitigation:

- audit all chat-to-memory and memory derivation write sites
- add regression tests for new-row ownership

### Risk 2: Session-linked leakage

A memory row might be filtered correctly by `user_id`, but a linked session lookup might still be global.

Mitigation:

- any lookup crossing between memory and chat must validate both sides under the current actor

### Risk 3: Historical data surprises

Users other than `nizhenshigoule@gmail.com` may expect to see legacy data they previously accessed under the global `default-user` model.

Mitigation:

- make the reassignment explicit and deterministic
- treat the migration as a policy change, not a best-effort guess

## Recommended Rollout Order

1. Add migration/backfill for legacy chat and memory ownership
2. Lock down chat API ownership
3. Lock down memory API ownership
4. Lock down extraction and derived-memory writes
5. Add multi-user regression tests
6. Verify account switching shows isolated chat and memory datasets

## Success Criteria

This phase is successful when:

- user A cannot see user B's chat sessions or messages
- user A cannot see user B's memory data, drafts, or memory graph
- all new chat and memory rows are written with the current authenticated user id
- all historical legacy chat and memory data is reassigned to `nizhenshigoule@gmail.com`
- switching accounts via logout/login changes the visible chat and memory dataset with no cross-user leakage
