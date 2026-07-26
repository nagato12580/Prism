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
let chatContinuationModule

before(async () => {
  server = await createServer({
    configFile: resolve(root, 'vite.config.ts'),
    root,
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
  })
  chatContinuationModule = await server.ssrLoadModule('/src/app/chatContinuation.ts')
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
  const { normalizeAgentContinuation } = chatContinuationModule
  assert.equal(typeof normalizeAgentContinuation, 'function')
  assert.deepEqual(
    normalizeAgentContinuation({
      ...continuation,
      objective: `  ${'x'.repeat(8_010)}  `,
      kb_uid: '  kb-public  ',
      file_uid: '  file-public  ',
    }),
    {
      ...continuation,
      objective: 'x'.repeat(8_000),
    },
  )

  for (const invalid of [
    null,
    [],
    { ...continuation, version: 2 },
    { ...continuation, objective: '   ' },
    { ...continuation, kb_uid: '' },
    { ...continuation, file_uid: '   ' },
    { ...continuation, kb_uid: 'k'.repeat(129) },
    { ...continuation, file_uid: 'f'.repeat(129) },
    { ...continuation, next_offset: '24' },
    { ...continuation, next_offset: -1 },
    { ...continuation, next_offset: 1.5 },
    { ...continuation, has_more_after: false },
  ]) {
    assert.equal(normalizeAgentContinuation(invalid), undefined)
  }

  const { useChatStore } = chatStoreModule
  useChatStore.setState({ currentSessionId: 'session-a', messages: [], sessionMessages: {} })
  useChatStore.getState().loadMessages('session-a', [
    persistedMessage('valid', 'assistant', '', {
      agent_continuation: {
        ...continuation,
        objective: '  Continue synthesizing the document  ',
        kb_uid: '  kb-public  ',
        file_uid: '  file-public  ',
      },
    }),
    persistedMessage('invalid', 'assistant', 'answer 2', {
      agent_continuation: { ...continuation, has_more_after: false },
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

test('buildAgentHistory filters before indexing and adds continuation only to the latest assistant', () => {
  const { buildAgentHistory } = chatContinuationModule
  assert.equal(typeof buildAgentHistory, 'function')

  const history = buildAgentHistory([
    { id: 'old', role: 'assistant', content: 'old', agentContinuation: { ...continuation, next_offset: 8 } },
    { id: 'user', role: 'user', content: 'follow up' },
    {
      id: 'latest',
      role: 'assistant',
      content: 'partial answer',
      clarify: { question: 'Choose one', options: [{ label: 'A', value: 'a' }] },
      agentContinuation: continuation,
    },
    { id: 'streaming', role: 'assistant', content: '', streaming: true, agentContinuation: { ...continuation, next_offset: 40 } },
  ])

  assert.deepEqual(history, [
    { role: 'assistant', content: 'old' },
    { role: 'user', content: 'follow up' },
    {
      role: 'assistant',
      content: 'partial answer\nChoose one\nA',
      continuation,
    },
  ])

  assert.deepEqual(buildAgentHistory([
    { id: 'old', role: 'assistant', content: 'old', agentContinuation: continuation },
    { id: 'latest', role: 'assistant', content: 'latest' },
  ]), [
    { role: 'assistant', content: 'old' },
    { role: 'assistant', content: 'latest' },
  ])
})

test('continuation event helper validates data and persists only after updating state', () => {
  const { applyAgentContinuationEvent } = chatContinuationModule
  assert.equal(typeof applyAgentContinuationEvent, 'function')

  const calls = []
  let state
  const accepted = applyAgentContinuationEvent(
    { ...continuation, objective: '  normalized objective  ' },
    (value) => {
      state = value
      calls.push('set')
    },
    () => {
      assert.equal(state.objective, 'normalized objective')
      calls.push('persist')
    },
  )
  assert.equal(accepted, true)
  assert.deepEqual(calls, ['set', 'persist'])

  const rejectedCalls = []
  assert.equal(applyAgentContinuationEvent(
    { ...continuation, next_offset: -1 },
    () => rejectedCalls.push('set'),
    () => rejectedCalls.push('persist'),
  ), false)
  assert.deepEqual(rejectedCalls, [])

  assert.match(
    chatPageSource,
    /msg\.type === 'continuation'[\s\S]*applyAgentContinuationEvent\([\s\S]*setLastContinuation[\s\S]*queueAssistantProcessSnapshot/,
    'The stream branch must use the tested event helper for state and snapshot ordering.',
  )
})

test('buildAssistantProcess keeps continuation under the persistence-only key', () => {
  const { buildAssistantProcess } = chatContinuationModule
  assert.equal(typeof buildAssistantProcess, 'function')
  assert.deepEqual(buildAssistantProcess({
    id: 'assistant',
    role: 'assistant',
    content: 'answer',
    traceId: 'trace-1',
    agentStatus: 'done',
    agentContinuation: continuation,
  }), {
    trace_id: 'trace-1',
    agent_status: 'done',
    tool_runs: [],
    thinking_steps: [],
    agent_continuation: continuation,
  })
})
