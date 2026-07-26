import test, { after, before } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { createServer } from 'vite'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chatStoreSource = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')
const chatPageSource = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

let server
let chatStoreModule

before(async () => {
  server = await createServer({
    configFile: resolve(root, 'vite.config.ts'),
    root,
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
  })
  chatStoreModule = await server.ssrLoadModule('/src/app/chatStore.ts')
})

after(async () => {
  await server?.close()
})

const continuation = {
  version: 1,
  objective: 'Continue synthesizing the document',
  kb_uid: 'kb-public',
  file_uid: 'file-public',
  next_offset: 24,
  has_more_after: true,
}

function persistedMessage(id, role, content, process) {
  return {
    id,
    session_id: 'session-a',
    role,
    content,
    sources: null,
    clarify: null,
    process,
    created_at: '2026-07-26T00:00:00Z',
  }
}

test('declares the exact version 1 continuation shape on messages', () => {
  assert.match(
    chatStoreSource,
    /export interface AgentContinuation\s*{\s*version:\s*1\s*objective:\s*string\s*kb_uid:\s*string\s*file_uid:\s*string\s*next_offset:\s*number\s*has_more_after:\s*boolean\s*}/,
  )
  assert.match(chatStoreSource, /agentContinuation\?:\s*AgentContinuation/)
})

test('normalizes persisted continuation state and rejects malformed state', () => {
  const { normalizeAgentContinuation } = chatStoreModule
  assert.equal(typeof normalizeAgentContinuation, 'function')
  assert.deepEqual(normalizeAgentContinuation(continuation), continuation)
  assert.equal(
    normalizeAgentContinuation({ ...continuation, next_offset: '24' }),
    undefined,
  )

  const { useChatStore } = chatStoreModule
  useChatStore.setState({ currentSessionId: 'session-a', messages: [], sessionMessages: {} })
  useChatStore.getState().loadMessages('session-a', [
    persistedMessage('valid', 'assistant', '', { agent_continuation: continuation }),
    persistedMessage('invalid', 'assistant', 'answer 2', {
      agent_continuation: { ...continuation, has_more_after: 'yes' },
    }),
  ])

  const restored = useChatStore.getState().messages
  assert.deepEqual(restored[0].agentContinuation, continuation)
  assert.equal(restored[0].streaming, false, 'A persisted continuation must survive history streaming filters.')
  assert.equal(restored[1].agentContinuation, undefined)
})

test('setLastContinuation updates only the named assistant in the named session', () => {
  const { useChatStore } = chatStoreModule
  const original = {
    currentSessionId: 'session-a',
    messages: [
      { id: 'user-a', role: 'user', content: 'question' },
      { id: 'assistant-a', role: 'assistant', content: 'answer' },
      { id: 'assistant-b', role: 'assistant', content: 'other answer' },
    ],
    sessionMessages: {
      'session-a': [
        { id: 'user-a', role: 'user', content: 'question' },
        { id: 'assistant-a', role: 'assistant', content: 'answer' },
        { id: 'assistant-b', role: 'assistant', content: 'other answer' },
      ],
      'session-b': [{ id: 'assistant-a', role: 'assistant', content: 'different session' }],
    },
  }
  useChatStore.setState(original)

  const { setLastContinuation } = useChatStore.getState()
  assert.equal(typeof setLastContinuation, 'function')
  setLastContinuation(continuation, 'session-a', 'assistant-a')
  setLastContinuation({ ...continuation, next_offset: 99 }, 'session-a', 'user-a')

  const state = useChatStore.getState()
  assert.deepEqual(state.sessionMessages['session-a'][1].agentContinuation, continuation)
  assert.equal(state.sessionMessages['session-a'][0].agentContinuation, undefined)
  assert.equal(state.sessionMessages['session-a'][2].agentContinuation, undefined)
  assert.equal(state.sessionMessages['session-b'][0].agentContinuation, undefined)
})

test('history indexes the filtered messages before attaching continuation to the latest assistant', () => {
  assert.match(
    chatPageSource,
    /export function buildChatHistory\(messages: Message\[]\)\s*{[\s\S]*const historyMessages = messages\.filter\(\(message\) => !message\.streaming\)[\s\S]*let latestAssistantIndex = -1[\s\S]*for \(let index = historyMessages\.length - 1; index >= 0; index -= 1\)[\s\S]*historyMessages\[index\]\.role === 'assistant'[\s\S]*return historyMessages\.map\(\(message, index\) => \([\s\S]*content: historyContent\(message\)[\s\S]*index === latestAssistantIndex && message\.agentContinuation[\s\S]*agent_continuation: message\.agentContinuation/,
    'History must find and map the assistant index on the same post-filter array.',
  )
  assert.doesNotMatch(chatPageSource, /findLastIndex/, 'ES2020 does not provide findLastIndex.')
})

test('stream continuation events are validated, stored before done, and queued for persistence', () => {
  const continuationBranch = /else if \(msg\.type === 'continuation'\)\s*{([\s\S]*?)}\s*else if \(msg\.type === 'done'\)/.exec(chatPageSource)
  assert.ok(continuationBranch, 'continuation handling must occur before done')
  assert.match(continuationBranch[1], /normalizeAgentContinuation\(msg\.data\)/)
  assert.match(continuationBranch[1], /if \(continuation\)/)
  assert.match(continuationBranch[1], /setLastContinuation\(continuation,\s*sessionId,\s*assistantMessageId\)/)
  assert.match(continuationBranch[1], /if \(assistantPersistedId\) queueAssistantProcessSnapshot\(sessionId,\s*assistantPersistedId\)/)
})

test('assistant process snapshots persist continuation state or null', () => {
  assert.match(
    chatPageSource,
    /function buildAssistantProcess\(message: Message\)\s*{[\s\S]*agent_continuation:\s*message\.agentContinuation \|\| null/,
  )
})
