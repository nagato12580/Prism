import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(
  chatPage,
  /const CHAT_TYPEWRITER_INTERVAL_MS = 18/,
  'ChatPage should define a short typewriter interval for assistant token output.',
)

assert.match(
  chatPage,
  /const enqueueTypewriterText = \(text: string\) =>/,
  'ChatPage should enqueue received token text for incremental rendering.',
)

assert.match(
  chatPage,
  /else if \(msg\.type === 'token'\) enqueueTypewriterText\(safeString\(msg\.data\)\)/,
  'Stream token events should enter the typewriter queue instead of appending whole chunks immediately.',
)

assert.doesNotMatch(
  chatPage,
  /else if \(msg\.type === 'token'\) appendToLast\(msg\.data,\s*sessionId,\s*assistantMessageId\)/,
  'Stream token events should not append full backend chunks in one render.',
)

assert.match(
  chatPage,
  /await flushTypewriterText\(\)/,
  'ChatPage should flush pending typewriter text before final persistence and completion.',
)

assert.match(
  chatPage,
  /clearTypewriterTimer\(\)/,
  'ChatPage should clear the typewriter timer when the stream exits.',
)
