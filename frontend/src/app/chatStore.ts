import { create } from 'zustand'
import type { ChatSessionOut, ChatMessageOut, ResourceMediaType } from './api'

export interface Source {
  chunk_id: string
  item_id: string
  source_kind?: string
  source_id?: string
  display_type?: string
  display_id?: string
  display_title?: string
  display_label?: string
  score: number
  raw_score?: number
  doc_name?: string
  title?: string
  snippet?: string
  text?: string
}

/** 数据来源类型，与后端 source_type 对齐 */
export const SOURCE_TYPE_OPTIONS: { value: ResourceMediaType; label: string }[] = [
  { value: 'document', label: '文档' },
  { value: 'image', label: '图片' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
]

export type ToolRunStatus = 'running' | 'success' | 'error'
export type DeepSearchDepth = 'quick' | 'standard' | 'deep'

export interface ToolRun {
  id: string
  tool: string
  query: string
  status: ToolRunStatus
  summary?: string
  stats?: Record<string, unknown>
  latencyMs?: number
}

export interface ClarifyOption {
  label: string
  value: string
}

export interface ClarifyRequest {
  question: string
  options: ClarifyOption[]
}

export interface ThinkingStep {
  label: string
  detail?: string
  latencyMs?: number
  agent?: string
  iteration?: number
  status?: ToolRunStatus
  tool?: string
}

type ToolRunPatch = Partial<ToolRun> & {
  traceSteps?: ThinkingStep[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  streaming?: boolean
  toolRuns?: ToolRun[]
  thinkingSteps?: ThinkingStep[]
  clarify?: ClarifyRequest
  agentStatus?: string
}

interface ChatState {
  messages: Message[]
  sessionMessages: Record<string, Message[]>
  selectedTopicId: string | null
  selectedTopicName: string | null
  selectedSourceTypes: ResourceMediaType[]
  deepSearchEnabled: boolean
  deepSearchDepth: DeepSearchDepth
  // Session state
  currentSessionId: string | null
  sessions: ChatSessionOut[]
  sessionsLoading: boolean
  // Message actions
  addMessage: (msg: Message, sessionId?: string) => void
  appendToLast: (text: string, sessionId?: string, messageId?: string) => void
  setLastSources: (sources: Source[], sessionId?: string, messageId?: string) => void
  setLastAgentStatus: (label: string, sessionId?: string, messageId?: string) => void
  addLastToolRun: (run: ToolRun, sessionId?: string, messageId?: string) => void
  finishLastToolRun: (tool: string, data: ToolRunPatch, sessionId?: string, messageId?: string) => void
  setLastClarify: (clarify: ClarifyRequest, sessionId?: string, messageId?: string) => void
  finishLast: (sessionId?: string, messageId?: string) => void
  replaceMessageId: (sessionId: string, fromId: string, toId: string) => void
  clear: () => void
  getSessionMessages: (sessionId: string) => Message[]
  // Topic/source actions
  setSelectedTopic: (topicId: string, topicName: string) => void
  clearSelectedTopic: () => void
  toggleSourceType: (type: ResourceMediaType) => void
  setSelectedSourceTypes: (types: ResourceMediaType[]) => void
  clearSelectedSourceTypes: () => void
  setDeepSearchEnabled: (enabled: boolean) => void
  setDeepSearchDepth: (depth: DeepSearchDepth) => void
  // Session actions
  setCurrentSessionId: (id: string | null) => void
  setSessions: (sessions: ChatSessionOut[]) => void
  setSessionsLoading: (loading: boolean) => void
  prependSession: (session: ChatSessionOut) => void
  updateSessionTitle: (id: string, title: string) => void
  removeSession: (id: string) => void
  loadMessages: (sessionId: string, msgs: ChatMessageOut[]) => void
  restoreFromSession: (session: ChatSessionOut) => void
}

function _toolLabel(tool: string) {
  const labels: Record<string, string> = {
    knowledge_search: '检索知识库',
    clarify_user: '追问用户',
    datetime: '获取时间',
    web_search: '网络搜索',
    chat: '对话',
  }
  return labels[tool] || tool
}

function normalizeToolRunStatus(value: unknown): ToolRunStatus {
  return value === 'running' || value === 'error' ? value : 'success'
}

function normalizeToolRuns(value: unknown): ToolRun[] | undefined {
  if (!Array.isArray(value)) return undefined
  const runs = value
    .filter((run): run is Record<string, unknown> => typeof run === 'object' && run !== null)
    .map((run) => ({
      id: typeof run.id === 'string' ? run.id : `run-${Math.random().toString(36).slice(2, 10)}`,
      tool: typeof run.tool === 'string' ? run.tool : 'tool',
      query: typeof run.query === 'string' ? run.query : '',
      status: normalizeToolRunStatus(run.status),
      summary: typeof run.summary === 'string' ? run.summary : undefined,
      stats: typeof run.stats === 'object' && run.stats !== null ? run.stats as Record<string, unknown> : undefined,
      latencyMs: typeof run.latencyMs === 'number' ? run.latencyMs : undefined,
    }))
  return runs.length > 0 ? runs : undefined
}

function normalizeThinkingSteps(value: unknown): ThinkingStep[] | undefined {
  if (!Array.isArray(value)) return undefined
  const steps = value
    .filter((step): step is Record<string, unknown> => typeof step === 'object' && step !== null)
    .map((step) => ({
      label: typeof step.label === 'string' ? step.label : 'step',
      detail: typeof step.detail === 'string' ? step.detail : undefined,
      latencyMs: typeof step.latencyMs === 'number' ? step.latencyMs : undefined,
      agent: typeof step.agent === 'string' ? step.agent : undefined,
      iteration: typeof step.iteration === 'number' ? step.iteration : undefined,
      status: normalizeToolRunStatus(step.status),
      tool: typeof step.tool === 'string' ? step.tool : undefined,
    }))
  return steps.length > 0 ? steps : undefined
}

function toMessages(msgs: ChatMessageOut[]): Message[] {
  return msgs.map((m) => {
    const process = typeof m.process === 'object' && m.process !== null ? m.process : undefined
    const toolRuns = normalizeToolRuns(process?.tool_runs)
    const thinkingSteps = normalizeThinkingSteps(process?.thinking_steps)
    const agentStatus = typeof process?.agent_status === 'string' ? process.agent_status : undefined
    const isPendingAssistantMessage =
      m.role === 'assistant' &&
      !(m.content || '').trim() &&
      !m.sources?.length &&
      !m.clarify

    return {
      id: m.id,
      role: m.role as 'user' | 'assistant',
      content: m.content || '',
      sources: (m.sources || undefined) as Message['sources'],
      clarify: (m.clarify || undefined) as Message['clarify'],
      streaming: isPendingAssistantMessage,
      toolRuns,
      thinkingSteps,
      agentStatus,
    }
  })
}

function mergePersistedWithCachedMessages(persistedMsgs: ChatMessageOut[], cached: Message[]) {
  const persisted = toMessages(persistedMsgs)
  const merged = [...persisted]
  const persistedIds = new Set(persisted.map((msg) => msg.id))

  for (const cachedMsg of cached) {
    if (persistedIds.has(cachedMsg.id)) continue
    const alreadyPersisted = persisted.some(
      (msg) =>
        msg.role === cachedMsg.role &&
        msg.content === cachedMsg.content &&
        (!cachedMsg.streaming || msg.role === 'user'),
    )
    if (!cachedMsg.streaming && alreadyPersisted) continue
    if (cachedMsg.role === 'user' && alreadyPersisted) continue
    merged.push(cachedMsg)
  }

  return merged
}

function replaceMessage(messages: Message[], messageId: string | undefined, update: (msg: Message) => Message) {
  const index = messageId ? messages.findIndex((msg) => msg.id === messageId) : messages.length - 1
  if (index < 0) return messages
  const next = [...messages]
  next[index] = update(next[index])
  return next
}

function updateMessagesForSession(
  state: ChatState,
  sessionId: string | undefined,
  updater: (messages: Message[]) => Message[],
) {
  const targetSessionId = sessionId ?? state.currentSessionId ?? undefined
  const currentMessages = targetSessionId
    ? state.sessionMessages[targetSessionId] ?? (state.currentSessionId === targetSessionId ? state.messages : [])
    : state.messages
  const nextMessages = updater(currentMessages)

  if (!targetSessionId) {
    return { messages: nextMessages }
  }

  const sessionMessages = {
    ...state.sessionMessages,
    [targetSessionId]: nextMessages,
  }
  return {
    sessionMessages,
    messages: state.currentSessionId === targetSessionId ? nextMessages : state.messages,
  }
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  sessionMessages: {},
  selectedTopicId: null,
  selectedTopicName: null,
  selectedSourceTypes: [],
  deepSearchEnabled: false,
  deepSearchDepth: 'standard',
  currentSessionId: null,
  sessions: [],
  sessionsLoading: false,
  addMessage: (msg, sessionId) =>
    set((s) => updateMessagesForSession(s, sessionId, (messages) => [...messages, msg])),
  appendToLast: (text, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => ({ ...last, content: last.content + text })),
      ),
    ),
  setLastSources: (sources, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => ({ ...last, sources })),
      ),
    ),
  setLastAgentStatus: (label, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => {
          const previousSteps = (last.thinkingSteps ?? []).map((step) =>
            step.status === 'running' ? { ...step, status: 'success' as ToolRunStatus } : step,
          )
          const step: ThinkingStep = { label, status: 'running', tool: 'agent_status' }
          return {
            ...last,
            agentStatus: label,
            thinkingSteps: [...previousSteps, step],
          }
        }),
      ),
    ),
  addLastToolRun: (run, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => {
          const previousSteps = (last.thinkingSteps ?? []).map((step) =>
            step.status === 'running' ? { ...step, status: 'success' as ToolRunStatus } : step,
          )
          const step: ThinkingStep = {
            label: _toolLabel(run.tool),
            detail: run.query,
            status: 'running',
            tool: run.tool,
          }
          return {
            ...last,
            toolRuns: [...(last.toolRuns ?? []), run],
            thinkingSteps: [...previousSteps, step],
          }
        }),
      ),
    ),
  finishLastToolRun: (tool, data, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => {
          if (!last.toolRuns) return last

          let runIndex = -1
          for (let index = last.toolRuns.length - 1; index >= 0; index -= 1) {
            const run = last.toolRuns[index]
            if (run.tool === tool && run.status === 'running') {
              runIndex = index
              break
            }
          }
          if (runIndex === -1) return last

          const toolRuns = [...last.toolRuns]
          const updated = { ...toolRuns[runIndex], ...data }
          toolRuns[runIndex] = updated
          const traceSteps = Array.isArray(data.traceSteps) ? data.traceSteps : []
          const stepLabel = _toolLabel(tool)
          const stepStatus = updated.status || 'success'
          const previousSteps = [...(last.thinkingSteps ?? [])]
          let stepUpdated = false
          for (let index = previousSteps.length - 1; index >= 0; index -= 1) {
            const step = previousSteps[index]
            if (step.status === 'running' && (step.tool === tool || step.label === stepLabel)) {
              previousSteps[index] = {
                ...step,
                detail: updated.query || updated.summary,
                latencyMs: updated.latencyMs,
                status: stepStatus,
                tool,
              }
              stepUpdated = true
              break
            }
          }
          const step: ThinkingStep = {
            label: stepLabel,
            detail: updated.query || updated.summary,
            latencyMs: updated.latencyMs,
            status: stepStatus,
            tool,
          }
          return {
            ...last,
            toolRuns,
            thinkingSteps: [
              ...previousSteps,
              ...(stepUpdated ? [] : [step]),
              ...traceSteps.map((traceStep) => ({
                ...traceStep,
                status: traceStep.status || stepStatus,
              })),
            ],
          }
        }),
      ),
    ),
  setLastClarify: (clarify, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => ({ ...last, clarify })),
      ),
    ),
  finishLast: (sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => ({
          ...last,
          streaming: false,
          thinkingSteps: (last.thinkingSteps ?? []).map((step) =>
            step.status === 'running' ? { ...step, status: 'success' as ToolRunStatus } : step,
          ),
        })),
      ),
    ),
  replaceMessageId: (sessionId, fromId, toId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        messages.map((message) => (message.id === fromId ? { ...message, id: toId } : message)),
      ),
    ),
  clear: () => set({ messages: [] }),
  getSessionMessages: (sessionId) => get().sessionMessages[sessionId] ?? [],
  setSelectedTopic: (topicId, topicName) => set({ selectedTopicId: topicId, selectedTopicName: topicName }),
  clearSelectedTopic: () => set({ selectedTopicId: null, selectedTopicName: null }),
  toggleSourceType: (type) =>
    set((s) => {
      const exists = s.selectedSourceTypes.includes(type)
      return {
        selectedSourceTypes: exists
          ? s.selectedSourceTypes.filter((t) => t !== type)
          : [...s.selectedSourceTypes, type],
      }
    }),
  setSelectedSourceTypes: (types) => set({ selectedSourceTypes: types }),
  clearSelectedSourceTypes: () => set({ selectedSourceTypes: [] }),
  setDeepSearchEnabled: (enabled) => set({ deepSearchEnabled: enabled }),
  setDeepSearchDepth: (depth) => set({ deepSearchDepth: depth }),

  // Session actions
  setCurrentSessionId: (id) =>
    set((s) => ({
      currentSessionId: id,
      messages: id ? s.sessionMessages[id] ?? [] : [],
    })),
  setSessions: (sessions) => set({ sessions }),
  setSessionsLoading: (loading) => set({ sessionsLoading: loading }),
  prependSession: (session) =>
    set((s) => ({ sessions: [session, ...s.sessions] })),
  updateSessionTitle: (id, title) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === id ? { ...sess, title } : sess,
      ),
    })),
  removeSession: (id) =>
    set((s) => {
      const sessions = s.sessions.filter((sess) => sess.id !== id)
      const isCurrent = s.currentSessionId === id
      return {
        sessions,
        currentSessionId: isCurrent ? null : s.currentSessionId,
        messages: isCurrent ? [] : s.messages,
        sessionMessages: Object.fromEntries(Object.entries(s.sessionMessages).filter(([sessionId]) => sessionId !== id)),
        selectedTopicId: isCurrent ? null : s.selectedTopicId,
        selectedTopicName: isCurrent ? null : s.selectedTopicName,
        selectedSourceTypes: isCurrent ? [] : s.selectedSourceTypes,
      }
    }),
  loadMessages: (sessionId, msgs) =>
    set((s) => {
      const merged = mergePersistedWithCachedMessages(msgs, s.sessionMessages[sessionId] ?? [])
      return {
        sessionMessages: {
          ...s.sessionMessages,
          [sessionId]: merged,
        },
        messages: s.currentSessionId === sessionId ? merged : s.messages,
      }
    }),
  restoreFromSession: (session) =>
    set({
      selectedTopicId: session.topic_id || null,
      selectedSourceTypes: (session.source_types as ResourceMediaType[]) || [],
    }),
}))
