import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(
  chatPage,
  /const activeStreamRef = useRef<\{[\s\S]*controller:\s*AbortController[\s\S]*stop:\s*\(\)\s*=>\s*void[\s\S]*\}\s*\|\s*null>\(null\)/,
  'ChatPage should keep the active stream controller in a ref so the UI can stop it.',
)

assert.match(
  chatPage,
  /const stopStreaming = \(\) => \{[\s\S]*activeStreamRef\.current\?\.stop\(\)[\s\S]*\}/,
  'ChatPage should expose a stopStreaming handler that aborts the active stream.',
)

assert.doesNotMatch(
  chatPage,
  /return\s+\(\)\s*=>\s*\{\s*activeStreamRef\.current\?\.stop\(\)\s*\}/,
  'Navigating away from ChatPage should not abort the active stream; only the explicit stop button should.',
)

assert.match(
  chatPage,
  /activeStreamRef\.current = \{[\s\S]*controller:\s*streamAbortController,[\s\S]*stop:\s*\(\)\s*=> \{[\s\S]*streamStoppedByUser = true[\s\S]*streamAbortController\.abort\(\)[\s\S]*\}/,
  'ChatPage should mark user-initiated stops before aborting the stream.',
)

assert.match(
  chatPage,
  /const isUserStop = streamStoppedByUser && streamAbortController\.signal\.aborted/,
  'ChatPage should distinguish user stops from timeouts and other failures.',
)

assert.match(
  chatPage,
  /if \(isUserStop\) \{[\s\S]*appendToLast\(`\\n\\n已停止本次回答。`,\s*sessionId,\s*assistantMessageId\)[\s\S]*finishLast\(sessionId,\s*assistantMessageId,\s*'error'\)[\s\S]*return[\s\S]*\}/,
  'User stops should preserve partial text and close the assistant message without showing a request failure.',
)

assert.match(
  chatPage,
  /aria-label=\{sending \? '停止生成' : '发送'\}/,
  'The send button should become an accessible stop button while streaming.',
)

assert.match(
  chatPage,
  /onClick=\{sending \? stopStreaming : undefined\}/,
  'Clicking the streaming action button should stop the active request.',
)

assert.match(
  chatPage,
  /sending \? <Square size=\{16\}/,
  'The streaming action should use a stop icon instead of the send icon.',
)

assert.match(
  chatPage,
  /if \(!titleReceived && !streamStoppedByUser && userCount === 1/,
  'Stopped first-turn answers should not trigger automatic title generation from partial content.',
)
