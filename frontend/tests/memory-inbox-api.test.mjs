import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')

assert.match(api, /interface MemoryDraft/, 'API client exposes MemoryDraft type.')
assert.match(api, /interface MemoryStatement/, 'API client exposes MemoryStatement type.')
assert.match(api, /interface MemoryExtractionResult/, 'API client exposes memory extraction result type.')
assert.match(api, /listDrafts:/, 'memoryApi lists memory drafts.')
assert.match(api, /createDraft:/, 'memoryApi creates memory drafts.')
assert.match(api, /extractSession:/, 'memoryApi extracts memory drafts from a chat session.')
assert.match(api, /confirmDraft:/, 'memoryApi confirms memory drafts.')
assert.match(api, /rejectDraft:/, 'memoryApi rejects memory drafts.')
assert.match(api, /supersedeDraft:/, 'memoryApi supersedes old statements from drafts.')
assert.match(api, /listStatements:/, 'memoryApi lists confirmed statements.')
assert.match(api, /\/memories\/drafts/, 'memoryApi uses the memory drafts endpoint.')
assert.match(api, /\/memories\/extract\/session\/\$\{sessionId\}/, 'memoryApi uses the session extraction endpoint.')
assert.match(api, /\/memories\/drafts\/\$\{id\}\/confirm/, 'memoryApi confirms via the memory drafts endpoint.')
assert.match(api, /\/memories\/drafts\/\$\{id\}\/reject/, 'memoryApi rejects via the memory drafts endpoint.')
assert.match(api, /\/memories\/drafts\/\$\{id\}\/supersede/, 'memoryApi supersedes via the memory drafts endpoint.')
assert.match(api, /\/memories\/statements/, 'memoryApi lists memory statements.')
