import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const routes = readFileSync(resolve(root, 'src/app/routes.tsx'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/MemoryInboxPage.tsx'), 'utf8')

assert.match(routes, /MemoryInboxPage/, 'Routes import MemoryInboxPage.')
assert.match(routes, /memory\/inbox/, 'Routes expose /memory/inbox.')
assert.match(page, /data-testid="memory-inbox-page"/, 'Memory Inbox page has a stable test id.')
assert.match(page, /chatApi\.listSessions/, 'Memory Inbox page loads chat sessions for manual extraction.')
assert.match(page, /memoryApi\.extractSession/, 'Memory Inbox page can manually extract memories from a session.')
assert.match(page, /Extract from session/, 'Memory Inbox page exposes a manual extraction control.')
assert.match(page, /memoryApi\.listDrafts/, 'Memory Inbox page loads drafts.')
assert.match(page, /memoryApi\.confirmDraft/, 'Memory Inbox page can confirm drafts.')
assert.match(page, /memoryApi\.rejectDraft/, 'Memory Inbox page can reject drafts.')
assert.match(page, /memoryApi\.supersedeDraft/, 'Memory Inbox page can supersede conflicting drafts.')
assert.match(page, /conflict_ids/, 'Memory Inbox page exposes conflict ids.')
assert.match(page, /supersededStatementId/, 'Memory Inbox page lets reviewers enter a statement to supersede.')
assert.match(page, /Source/, 'Memory Inbox page shows source evidence.')
