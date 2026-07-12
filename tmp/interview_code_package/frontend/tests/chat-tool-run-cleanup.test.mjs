import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatPage = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')
const chatStore = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')

assert.match(
  chatStore,
  /finishLast:\s*\(sessionId\?:\s*string,\s*messageId\?:\s*string,\s*remainingToolStatus\?:\s*ToolRunStatus\)\s*=>\s*void/,
  'finishLast should accept a status for any tool runs that never received tool_result.',
)

assert.match(
  chatStore,
  /run\.status === 'running'\s*\?\s*\{\s*\.\.\.run,\s*status:\s*remainingToolStatus/,
  'finishLast should close remaining running tool runs with the requested terminal status.',
)

assert.match(
  chatPage,
  /finishLast\(sessionId,\s*assistantMessageId,\s*'error'\)/,
  'ChatPage should mark unfinished tool runs as error when the stream reports or throws an error.',
)

assert.match(
  chatPage,
  /finishLast\(sessionId,\s*assistantMessageId,\s*'success'\)/,
  'ChatPage should mark unfinished tool runs as success when a stream finishes normally.',
)

assert.match(
  chatPage,
  /const chatStreamTimeoutEnv = \([\s\S]*import\.meta as unknown as \{ env\?: \{ VITE_CHAT_STREAM_TIMEOUT_SECONDS\?: string \} \}[\s\S]*\)\.env\?\.VITE_CHAT_STREAM_TIMEOUT_SECONDS/,
  'ChatPage should read an optional Vite stream watchdog env var without requiring global Vite types.',
)

assert.match(
  chatPage,
  /const CHAT_STREAM_TIMEOUT_SECONDS = Number\(chatStreamTimeoutEnv \|\| 300\)/,
  'ChatPage should default the stream watchdog to the same 300s budget as the backend tool timeout.',
)

assert.match(
  chatPage,
  /const CHAT_STREAM_TIMEOUT_MS = Number\.isFinite\(CHAT_STREAM_TIMEOUT_SECONDS\)[\s\S]*CHAT_STREAM_TIMEOUT_SECONDS \* 1000[\s\S]*300_000/,
  'ChatPage should convert the configurable stream watchdog seconds to milliseconds.',
)

assert.match(
  chatPage,
  /const streamAbortController = new AbortController\(\)/,
  'ChatPage should use AbortController to stop a stalled chat stream.',
)

assert.match(
  chatPage,
  /signal:\s*streamAbortController\.signal/,
  'The chat fetch should be wired to the stream abort signal.',
)

assert.match(
  chatPage,
  /streamTimedOut = true[\s\S]*streamAbortController\.abort\(\)[\s\S]*CHAT_STREAM_TIMEOUT_MS/,
  'ChatPage should abort the chat stream when no response arrives within the UX budget.',
)

assert.match(
  chatPage,
  /window\.clearTimeout\(streamTimeoutId\)/,
  'ChatPage should clear the stream watchdog after each progress event and when the stream exits.',
)
