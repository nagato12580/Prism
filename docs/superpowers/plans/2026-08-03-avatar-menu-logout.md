# Avatar Menu Logout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-right avatar account menu that shows the authenticated user and lets them log out so they can switch accounts quickly.

**Architecture:** Reuse the existing backend logout endpoint and frontend auth API, then extend the frontend auth store with a centralized `logout()` action. Update `MainLayout` to render real user identity from `authStore.me`, manage a local account-menu popover, and navigate to `/login` after logout. Keep the change scoped to header chrome and auth state rather than introducing a generic dropdown framework.

**Tech Stack:** React 18, React Router, Zustand, TypeScript, Node test runner, existing Prism UI components

---

## File Map

- Modify: `frontend/src/features/auth/store/authStore.ts`
  - Add a centralized `logout()` action that calls `authApi.logout()`, clears local identity state, and never leaves the app stuck logged in.
- Modify: `frontend/src/layouts/MainLayout.tsx`
  - Replace hardcoded account text with authenticated identity and add a lightweight avatar-triggered account menu.
- Modify: `frontend/tests/auth-bootstrap.test.mjs`
  - Assert `authStore.logout()` exists and calls `authApi.logout()`.
- Modify: `frontend/tests/main-layout-navigation.test.mjs`
  - Assert the header no longer hardcodes `admin@example.com` and includes logout/account-menu wiring.

## Task 1: Add logout support to auth store

**Files:**
- Modify: `frontend/src/features/auth/store/authStore.ts`
- Modify: `frontend/tests/auth-bootstrap.test.mjs`
- Test: `frontend/tests/auth-bootstrap.test.mjs`

- [ ] **Step 1: Write the failing auth store assertions**

Append to `frontend/tests/auth-bootstrap.test.mjs`:

```javascript
assert.match(store, /logout:\s*\(\)\s*=>\s*Promise<void>|async\s+logout\(/, 'auth store should expose a logout action.')
assert.match(store, /authApi\.logout\(/, 'auth store logout should call authApi.logout.')
assert.match(store, /set\(\{\s*me:\s*null/, 'auth store logout should clear the current user state.')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm.cmd test -- --test-name-pattern auth-bootstrap`
Expected: FAIL because `authStore` does not expose `logout`.

- [ ] **Step 3: Add the logout action to the auth store**

Update `frontend/src/features/auth/store/authStore.ts` to extend the interface:

```ts
interface AuthState {
  me: MeResponse | null
  loading: boolean
  bootstrapped: boolean
  refreshMe: () => Promise<void>
  logout: () => Promise<void>
  clear: () => void
}
```

Add the implementation inside the `create<AuthState>(...)` object:

```ts
  async logout() {
    try {
      await authApi.logout()
    } catch {
      // Local logout must still succeed so account switching is never blocked.
    } finally {
      set({ me: null, loading: false, bootstrapped: true })
    }
  },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm.cmd test -- --test-name-pattern auth-bootstrap`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/auth/store/authStore.ts frontend/tests/auth-bootstrap.test.mjs
git commit -m "feat(auth): add frontend logout action"
```

## Task 2: Add the avatar-triggered account menu to MainLayout

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Modify: `frontend/tests/main-layout-navigation.test.mjs`
- Test: `frontend/tests/main-layout-navigation.test.mjs`

- [ ] **Step 1: Write the failing MainLayout assertions**

Append to `frontend/tests/main-layout-navigation.test.mjs`:

```javascript
assert.doesNotMatch(
  mainLayout,
  /admin@example\.com/,
  'MainLayout should not hardcode the authenticated account label.',
)

assert.match(
  mainLayout,
  /useAuthStore/,
  'MainLayout should read the authenticated user from auth state.',
)

assert.match(
  mainLayout,
  /logout|退出登录/,
  'MainLayout should render a logout action in the account area.',
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm.cmd test -- --test-name-pattern main-layout-navigation`
Expected: FAIL because `MainLayout` still hardcodes `admin@example.com`.

- [ ] **Step 3: Read current user from auth state and add local menu state**

Modify the `MainLayout` imports:

```tsx
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { useAuthStore } from '@/features/auth/store/authStore'
```

Add local state near the top of `MainLayout()`:

```tsx
  const navigate = useNavigate()
  const me = useAuthStore((s) => s.me)
  const logout = useAuthStore((s) => s.logout)
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const accountMenuRef = useRef<HTMLDivElement | null>(null)
```

Add derived values:

```tsx
  const accountName = me?.display_name || me?.username || 'Account'
  const accountSubline = me?.username || 'Unknown user'
  const accountInitial = (accountName.trim()[0] || 'U').toUpperCase()
```

- [ ] **Step 4: Add outside-click and Escape close behavior**

Inside `MainLayout()`, add:

```tsx
  useEffect(() => {
    if (!accountMenuOpen) return

    const onPointerDown = (event: MouseEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false)
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAccountMenuOpen(false)
    }

    window.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [accountMenuOpen])
```

- [ ] **Step 5: Add the logout handler**

Inside `MainLayout()`, add:

```tsx
  const handleLogout = async () => {
    setAccountMenuOpen(false)
    setLoggingOut(true)
    try {
      await logout()
      navigate('/login', { replace: true })
    } finally {
      setLoggingOut(false)
    }
  }
```

- [ ] **Step 6: Replace the hardcoded account block with a trigger and menu**

Replace the current header account block:

```tsx
            <div className={cn('hidden items-center gap-2 text-xs sm:flex', isDark ? 'text-slate-300' : 'text-slate-700')}>
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--prism-blue)] text-[11px] font-semibold text-white">A</span>
              <span>admin@example.com</span>
            </div>
            <CircleUserRound size={20} className="text-slate-400 sm:hidden" />
```

With:

```tsx
            <div ref={accountMenuRef} className="relative">
              <button
                type="button"
                aria-label="Open account menu"
                aria-expanded={accountMenuOpen}
                onClick={() => setAccountMenuOpen((open) => !open)}
                className={cn(
                  'hidden items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition sm:flex',
                  isDark
                    ? 'border-white/10 bg-white/[0.06] text-slate-200 hover:bg-white/[0.1]'
                    : 'border-slate-200 bg-white text-slate-700 shadow-sm hover:border-blue-200',
                )}
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--prism-blue)] text-[11px] font-semibold text-white">
                  {accountInitial}
                </span>
                <span className="min-w-0">
                  <span className="block max-w-[180px] truncate font-medium">{accountName}</span>
                  <span className="block max-w-[180px] truncate text-[11px] text-slate-500">{accountSubline}</span>
                </span>
                <ChevronDown size={14} className="shrink-0 text-slate-400" />
              </button>

              <button
                type="button"
                aria-label="Open account menu"
                aria-expanded={accountMenuOpen}
                onClick={() => setAccountMenuOpen((open) => !open)}
                className="rounded-md p-1 text-slate-400 sm:hidden"
              >
                <CircleUserRound size={20} />
              </button>

              {accountMenuOpen ? (
                <div
                  className={cn(
                    'absolute right-0 top-[calc(100%+8px)] z-20 min-w-[220px] rounded-xl border p-2 shadow-lg',
                    isDark ? 'border-white/10 bg-[#0c0f24] text-slate-100' : 'border-slate-200 bg-white text-slate-900',
                  )}
                >
                  <div className="px-2 py-1.5">
                    <div className="truncate text-sm font-semibold">{accountName}</div>
                    <div className="truncate text-xs text-slate-500">{accountSubline}</div>
                  </div>
                  <div className={cn('my-1 h-px', isDark ? 'bg-white/10' : 'bg-slate-200')} />
                  <button
                    type="button"
                    onClick={() => { void handleLogout() }}
                    disabled={loggingOut}
                    className={cn(
                      'flex w-full items-center rounded-lg px-2 py-2 text-left text-sm transition',
                      isDark ? 'hover:bg-white/8 disabled:opacity-50' : 'hover:bg-slate-100 disabled:opacity-50',
                    )}
                  >
                    {loggingOut ? 'Signing out...' : '退出登录'}
                  </button>
                </div>
              ) : null}
            </div>
```

- [ ] **Step 7: Run the MainLayout test to verify it passes**

Run: `npm.cmd test -- --test-name-pattern main-layout-navigation`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/layouts/MainLayout.tsx frontend/tests/main-layout-navigation.test.mjs
git commit -m "feat(layout): add avatar account menu logout"
```

## Task 3: Run focused frontend verification

**Files:**
- Modify: none
- Test: `frontend/tests/auth-bootstrap.test.mjs`
- Test: `frontend/tests/main-layout-navigation.test.mjs`

- [ ] **Step 1: Run both focused frontend test files**

Run: `npm.cmd test -- --test-name-pattern "auth-bootstrap|main-layout-navigation"`
Expected: PASS for the auth bootstrap and main layout navigation assertions.

- [ ] **Step 2: Run the team-admin structural regression**

Run: `npm.cmd test -- --test-name-pattern team-admin-console`
Expected: PASS so the header/auth changes did not regress team-admin assertions.

- [ ] **Step 3: Run the frontend build**

Run: `npm.cmd run build`
Expected: `vite build` completes successfully.

- [ ] **Step 4: Review changed files**

Run: `git diff --stat HEAD~2..HEAD`
Expected: only `authStore`, `MainLayout`, and frontend tests related to auth/layout are included.

## Self-review

- Spec coverage:
  - account menu in header: Task 2
  - real authenticated identity in header: Task 2
  - centralized logout action: Task 1
  - redirect to `/login`: Task 2
  - frontend structure tests: Tasks 1-3
- Placeholder scan:
  - No `TODO`, `TBD`, or vague unnamed follow-up steps remain.
- Type consistency:
  - `logout()` is added to `AuthState` and consumed from `useAuthStore` in `MainLayout`.
  - The UI uses `display_name` and `username`, matching the existing `MeResponse` shape.
