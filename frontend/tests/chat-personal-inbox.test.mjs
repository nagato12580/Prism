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

const enabledPayload = JSON.parse(JSON.stringify(buildChatRequestPayload({
  ...baseArgs,
  includePersonalInbox: true,
})))

assert.equal(
  enabledPayload.include_personal_inbox,
  true,
  'Serialized chat payload should include include_personal_inbox=true after enabling the control.',
)

assert.match(
  chatPage,
  /buildChatRequestPayload\(\{/,
  'ChatPage should use the tested payload helper for the fetch body.',
)

