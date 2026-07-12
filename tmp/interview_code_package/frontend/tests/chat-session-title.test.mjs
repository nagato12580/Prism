import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(
  chatPage,
  /shouldAutoGenerateTitle/,
  'ChatPage should use a helper to decide when to auto-generate session titles.',
)

assert.doesNotMatch(
  chatPage,
  /session\?\.title === '新对话'/,
  'Auto title generation should not depend on one exact default title string.',
)

assert.match(
  chatPage,
  /chatApi\.generateTitle\(sessionId\)/,
  'ChatPage should request automatic title generation after the first exchange.',
)

assert.match(
  chatPage,
  /const userPersistPromise = persistUserMessage\(sessionId, query\)/,
  'ChatPage should keep the user message persistence promise for title generation.',
)

assert.match(
  chatPage,
  /await userPersistPromise/,
  'ChatPage should wait for user message persistence before generating the title.',
)

assert.match(
  chatPage,
  /await chatApi\.addMessage\(sessionId,[\s\S]*role: 'assistant'/,
  'ChatPage should wait for assistant message persistence before generating the title.',
)

assert.match(
  chatPage,
  /editingSessionId/,
  'ChatPage should track which session title is being edited.',
)

assert.match(
  chatPage,
  /chatApi\.updateSession\(sessionId,\s*\{\s*title/,
  'ChatPage should persist edited session titles through chatApi.updateSession.',
)

assert.match(
  chatPage,
  /aria-label=\{`编辑 \$\{session\.title\}`\}/,
  'ChatPage should expose an accessible edit title control for each session.',
)
