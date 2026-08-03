# Prism Avatar Menu Logout Design

## Summary

Prism already has the backend and frontend primitives for logout:

- backend `POST /api/v1/auth/logout`
- frontend `authApi.logout()`
- frontend `RequireAuth` gate

What is missing is a user-facing way to invoke logout and clear identity state so a developer can switch accounts quickly. This design adds a small avatar-triggered account menu in the top-right header and wires it to a centralized auth-store logout action.

## Goals

- Add a visible account menu in the main app chrome
- Replace hardcoded account display text with the authenticated user identity
- Let a user log out from anywhere in the protected app
- Return the user to `/login` immediately after logout so account switching is fast

## Non-Goals

- Full account settings page
- Profile editing
- Avatar uploads
- Multi-account switcher
- Generic reusable dropdown/menu system for the entire app

## Current State

The authenticated app shell is already protected by `RequireAuth`, and `authStore` already tracks `me`. The header in `MainLayout` still shows hardcoded account UI:

- avatar badge `A`
- label `admin@example.com`

There is no user-triggered logout action in the current protected shell.

## Proposed Approach

Add a lightweight account menu in the header:

- click the account area to open a small dropdown
- show current `display_name`
- show current `username`
- show a `logout` action

Logout behavior:

1. call `authStore.logout()`
2. clear frontend identity state
3. navigate to `/login`

If the backend logout request fails, frontend state should still clear and navigation should still continue to `/login`. The primary goal is fast account switching in development.

## Frontend Design

### Auth Store

Extend the existing auth store with:

- `logout(): Promise<void>`

Responsibilities:

- call `authApi.logout()`
- clear `me`
- keep `bootstrapped = true`
- swallow backend logout failure after local cleanup so UI never gets stuck in the logged-in shell

### Header Account Menu

Replace the current hardcoded header account block with a real account trigger derived from `authStore.me`.

Trigger content:

- compact circular badge showing the first letter of `display_name` or `username`
- primary line: `display_name`
- secondary line: `username`

Menu content:

- current display name
- current username
- divider
- `logout`

### Menu Behavior

The account menu should be lightweight and local to `MainLayout`:

- click trigger to toggle open
- click outside to close
- press `Escape` to close
- selecting `logout` closes the menu and starts logout
- while logout is in flight, disable repeated logout clicks

This should remain a focused header interaction, not a generalized menu abstraction.

### Navigation After Logout

After logout:

- navigate to `/login` with `replace: true`

This should happen even if the backend session delete fails. `RequireAuth` remains a secondary guard, but proactive redirect makes the interaction immediate and predictable.

## Error Handling

- If `authStore.me` is unexpectedly null inside the protected shell, the menu trigger should fall back to a generic user icon label and still allow logout if rendered.
- If `authApi.logout()` throws:
  - local auth state is still cleared
  - redirect to `/login` still happens
- If navigation fails for any reason, `RequireAuth` should still move the user out of the protected area on the next render because `me` is null

## Testing Strategy

### Frontend Structure Tests

Add assertions that:

- `MainLayout` imports and uses `useAuthStore`
- `MainLayout` no longer hardcodes `admin@example.com`
- `MainLayout` renders a logout action label
- `authStore` exposes `logout`
- `logout` calls `authApi.logout`

### Optional Interaction Tests

If the current test setup allows it cheaply, add a focused interaction test for:

- opening the menu
- clicking logout
- verifying state clear or redirect intent

This is optional for the first pass if the existing frontend tests are mostly source-structure assertions.

## Files Expected To Change

- `frontend/src/features/auth/store/authStore.ts`
- `frontend/src/layouts/MainLayout.tsx`
- `frontend/tests/auth-bootstrap.test.mjs`
- optionally `frontend/tests/main-layout-navigation.test.mjs`

## Success Criteria

The feature is successful when:

- the header shows the real authenticated user identity instead of a hardcoded placeholder
- clicking the avatar/account area opens an account menu
- clicking `logout` returns the user to `/login`
- account switching can be done by logout, then logging in as another user
