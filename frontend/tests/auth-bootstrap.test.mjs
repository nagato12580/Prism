import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const main = readFileSync(resolve(root, 'src/main.tsx'), 'utf8')
const store = readFileSync(resolve(root, 'src/features/auth/store/authStore.ts'), 'utf8')

assert.match(routes, /path:\s*'\/login'/, 'routes should expose a login page')
assert.match(routes, /RequireAuth/, 'protected app shell should use RequireAuth')
assert.match(main, /refreshMe|bootstrapAuth/, 'main entry should bootstrap auth state')
assert.match(store, /create\s*<AuthState>\(/, 'auth store should be implemented with Zustand')
assert.match(store, /refreshMe/, 'auth store should expose refreshMe')

const loginPage = readFileSync(resolve(root, 'src/features/auth/pages/LoginPage.tsx'), 'utf8')
assert.match(loginPage, /authApi\.loginDev/, 'Login page should call the dev login endpoint.')
assert.match(loginPage, /navigate\('\/'/, 'Login page should return to the main app on success.')
