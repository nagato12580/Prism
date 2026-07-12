import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const chatStore = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')

assert.match(
  chatStore,
  /sessionMessages:\s*Record<string,\s*Message\[]>/,
  'Chat store should keep per-session message caches for in-flight answers.',
)

assert.match(
  chatStore,
  /getSessionMessages:\s*\(sessionId:\s*string\)\s*=>\s*Message\[]/,
  'Chat store should expose per-session messages so persistence does not read the wrong active window.',
)

assert.match(
  chatStore,
  /mergePersistedWithCachedMessages/,
  'Loading persisted messages should merge cached in-flight messages instead of replacing them.',
)

assert.match(
  chatStore,
  /repairAssistantUserRaceOrder\(persistedMsgs\)/,
  'Loading persisted messages should repair assistant-before-user races before rendering a switched session.',
)

assert.match(
  chatStore,
  /previous\?\.role !== 'user'/,
  'Race repair should only swap assistant/user pairs when the assistant is not already preceded by a user turn.',
)

assert.match(
  chatPage,
  /const temporaryAssistantMessageId = genId\(\)/,
  'ChatPage should assign a stable assistant message id for stream updates.',
)

assert.match(
  chatPage,
  /persistAssistantPlaceholder\(sessionId\)/,
  'ChatPage should persist an assistant placeholder before streaming starts so refresh can restore the pending bubble.',
)

assert.match(
  chatPage,
  /const userPersistPromise = persistUserMessage\(sessionId, query\)\s+await userPersistPromise\s+const assistantPersistPromise = persistAssistantPlaceholder\(sessionId\)/,
  'ChatPage should persist the user message before the assistant placeholder so refresh restores messages in conversational order.',
)

assert.match(
  chatPage,
  /chatApi\.updateMessage\(sessionId,\s*assistantPersistedId/,
  'ChatPage should update the persisted assistant placeholder with the completed answer.',
)

assert.match(
  chatPage,
  /else if \(msg\.type === 'token'\) enqueueTypewriterText\(safeString\(msg\.data\)\)/,
  'Stream tokens should enter the typewriter queue before updating the assistant message.',
)

assert.match(
  chatPage,
  /appendToLast\(chunk,\s*sessionId,\s*assistantMessageId\)/,
  'The typewriter queue should update the assistant message in the originating session.',
)

assert.match(
  chatPage,
  /loadMessages\(sessionId,\s*msgs\)/,
  'Session switches should load messages for the requested session, not overwrite whichever session is currently active.',
)

assert.match(
  chatStore,
  /isPendingAssistantMessage/,
  'Chat store should restore empty persisted assistant placeholders as pending streaming messages after page refresh.',
)

assert.match(
  chatStore,
  /process\?\.tool_runs/,
  'Chat store should restore persisted tool runs for the thinking process panel.',
)

assert.match(
  chatPage,
  /buildAssistantProcess\(aiMsg\)/,
  'ChatPage should persist the assistant thinking process with the completed answer.',
)

assert.match(
  chatPage,
  /persistAssistantProcessSnapshot\(sessionId,\s*assistantPersistedId/,
  'ChatPage should save process snapshots while streaming so refresh can restore the process panel.',
)
