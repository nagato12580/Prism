import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { mkdtempSync, writeFileSync } from 'node:fs'
import ts from 'typescript'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const helperPath = resolve(root, 'src/pages/chatRequestPayload.ts')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const helperSource = readFileSync(helperPath, 'utf8')
const transpiled = ts.transpileModule(helperSource, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText

const tempDir = mkdtempSync(resolve(tmpdir(), 'prism-chat-payload-'))
const tempModule = resolve(tempDir, 'chatRequestPayload.mjs')
writeFileSync(tempModule, transpiled, 'utf8')

const { buildChatRequestPayload } = await import(pathToFileURL(tempModule).href)

const baseArgs = {
  query: 'hello',
  effectiveTopicId: 'kb-1',
  history: [{ role: 'user', content: 'previous' }],
  sessionId: 'session-1',
  engineUserMessageId: 'message-1',
  deepSearchEnabled: false,
  deepSearchDepth: 'standard',
}

const defaultPayload = JSON.parse(JSON.stringify(buildChatRequestPayload({
  ...baseArgs,
  includePersonalInbox: false,
})))

assert.equal(
  defaultPayload.include_personal_inbox,
  false,
  'Serialized chat payload should include include_personal_inbox=false by default.',
)
assert.equal(
  defaultPayload.deep_search_enabled,
  false,
  'Serialized chat payload should include the deep search toggle.',
)
assert.equal(
  defaultPayload.deep_search_depth,
  'standard',
  'Serialized chat payload should include the selected deep search depth.',
)
assert.equal(
  defaultPayload.mode,
  'standard',
  'Serialized chat payload should keep standard mode when deep search is off.',
)
assert.deepEqual(
  defaultPayload.kb_uids,
  ['kb-1'],
  'Serialized chat payload should authorize the selected knowledge base.',
)
assert.equal(
  'topic_id' in defaultPayload,
  false,
  'Serialized chat payload should use the backend authorized proxy schema, not the legacy Engine topic_id.',
)

const enabledPayload = JSON.parse(JSON.stringify(buildChatRequestPayload({
  ...baseArgs,
  includePersonalInbox: true,
})))

assert.equal(
  enabledPayload.include_personal_inbox,
  true,
  'Serialized chat payload should include include_personal_inbox=true after enabling the control.',
)

const deepPayload = JSON.parse(JSON.stringify(buildChatRequestPayload({
  ...baseArgs,
  deepSearchEnabled: true,
  deepSearchDepth: 'deep',
  includePersonalInbox: false,
})))

assert.equal(
  deepPayload.mode,
  'deep',
  'Serialized chat payload should switch to deep mode when deep search is on.',
)
assert.equal(
  deepPayload.deep_search_depth,
  'deep',
  'Serialized chat payload should carry the selected agentic depth.',
)

assert.match(
  chatPage,
  /buildChatRequestPayload\(\{/,
  'ChatPage should use the tested payload helper for the fetch body.',
)
