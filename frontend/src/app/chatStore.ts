import { create } from 'zustand'
import type { ChatSessionOut, ChatMessageOut, ResourceMediaType } from './api'
import { normalizeAgentContinuation } from './chatContinuation'

export {
  applyAgentContinuationEvent,
  buildAgentHistory,
  buildAssistantProcess,
  normalizeAgentContinuation,
} from './chatContinuation'

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

export interface EvidenceItem {
  evidence_id: string
  source_kind?: string
  source_id?: string
  chunk_id?: string
  parent_chunk_id?: string | null
  item_id?: string
  display_title?: string
  excerpt?: string
  hit_reason?: string
  score?: number | null
  retrieval_path?: string[]
  metadata?: Record<string, unknown>
}

export interface ToolRun {
  id: string
  tool: string
  query: string
  status: ToolRunStatus
  summary?: string
  stats?: Record<string, unknown>
  latencyMs?: number
  evidenceItems?: EvidenceItem[]
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
  startedAtMs?: number
  agent?: string
  iteration?: number
  status?: ToolRunStatus
  tool?: string
}

export interface AgentContinuation {
  version: 1
  objective: string
  kb_uid: string
  file_uid: string
  next_offset: number
  has_more_after: boolean
}

type ToolRunPatch = Partial<ToolRun> & {
  traceSteps?: ThinkingStep[]
  evidenceItems?: EvidenceItem[]
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
  traceId?: string
  agentContinuation?: AgentContinuation
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
  setLastTraceId: (traceId: string, sessionId?: string, messageId?: string) => void
  setLastContinuation: (continuation: AgentContinuation, sessionId: string, messageId: string) => void
  finishLast: (sessionId?: string, messageId?: string, remainingToolStatus?: ToolRunStatus) => void
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

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function normalizeEvidenceItems(value: unknown): EvidenceItem[] | undefined {
  if (!Array.isArray(value)) return undefined
  const items = value
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => {
      const normalizedScore = typeof item.score === 'number'
        ? item.score
        : typeof item.score === 'string'
          ? Number(item.score)
          : NaN
      return {
        evidence_id: typeof item.evidence_id === 'string' ? item.evidence_id : '',
        source_kind: typeof item.source_kind === 'string' ? item.source_kind : undefined,
        source_id: typeof item.source_id === 'string' ? item.source_id : undefined,
        chunk_id: typeof item.chunk_id === 'string' ? item.chunk_id : undefined,
        parent_chunk_id: typeof item.parent_chunk_id === 'string' ? item.parent_chunk_id : null,
        item_id: typeof item.item_id === 'string' ? item.item_id : undefined,
        display_title: typeof item.display_title === 'string' ? item.display_title : undefined,
        excerpt: typeof item.excerpt === 'string' ? item.excerpt : undefined,
        hit_reason: typeof item.hit_reason === 'string' ? item.hit_reason : undefined,
        score: Number.isFinite(normalizedScore) ? normalizedScore : null,
        retrieval_path: Array.isArray(item.retrieval_path)
          ? item.retrieval_path.filter((entry): entry is string => typeof entry === 'string')
          : undefined,
        metadata: isPlainRecord(item.metadata)
          ? {
              ...item.metadata,
              graph_path: Array.isArray(item.metadata.graph_path) ? item.metadata.graph_path : undefined,
              graph_explain: isPlainRecord(item.metadata.graph_explain) ? item.metadata.graph_explain : undefined,
              evidence_type: typeof item.metadata.evidence_type === 'string' ? item.metadata.evidence_type : undefined,
            }
          : undefined,
      }
    })
    .filter((item) => item.evidence_id)
  return items.length > 0 ? items : undefined
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
      evidenceItems: normalizeEvidenceItems(run.evidenceItems ?? run.evidence_items),
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
      startedAtMs: typeof step.startedAtMs === 'number' ? step.startedAtMs : undefined,
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
    const traceId = typeof process?.trace_id === 'string' ? process.trace_id : undefined
    const agentContinuation = m.role === 'assistant'
      ? normalizeAgentContinuation(process?.agent_continuation)
      : undefined
    const isPendingAssistantMessage =
      m.role === 'assistant' &&
      !(m.content || '').trim() &&
      !m.sources?.length &&
      !m.clarify &&
      !agentContinuation

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
      traceId,
      agentContinuation,
    }
  })
}

function repairAssistantUserRaceOrder(msgs: ChatMessageOut[]) {
  const repaired: ChatMessageOut[] = []
  for (let index = 0; index < msgs.length; index += 1) {
    const current = msgs[index]
    const next = msgs[index + 1]
    const previous = repaired[repaired.length - 1]
    if (current?.role === 'assistant' && next?.role === 'user' && previous?.role !== 'user') {
      repaired.push(next, current)
      index += 1
    } else {
      repaired.push(current)
    }
  }
  return repaired
}

function mergePersistedWithCachedMessages(persistedMsgs: ChatMessageOut[], cached: Message[]) {
  const persisted = toMessages(repairAssistantUserRaceOrder(persistedMsgs))
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

function finishRunningStep(step: ThinkingStep, now: number, status: ToolRunStatus = 'success') {
  if (step.status !== 'running') return step
  return {
    ...step,
    latencyMs: step.latencyMs ?? (step.startedAtMs !== undefined ? now - step.startedAtMs : undefined),
    status,
  }
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
          const now = Date.now()
          const previousSteps = (last.thinkingSteps ?? []).map((step) => finishRunningStep(step, now))
          const step: ThinkingStep = { label, status: 'running', tool: 'agent_status', startedAtMs: now }
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
          const now = Date.now()
          const previousSteps = (last.thinkingSteps ?? []).map((step) => finishRunningStep(step, now))
          const step: ThinkingStep = {
            label: _toolLabel(run.tool),
            detail: run.query,
            status: 'running',
            tool: run.tool,
            startedAtMs: now,
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
          const now = Date.now()
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
                latencyMs: updated.latencyMs ?? (step.startedAtMs !== undefined ? now - step.startedAtMs : undefined),
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
  setLastTraceId: (traceId, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => ({ ...last, traceId })),
      ),
    ),
  setLastContinuation: (continuation, sessionId, messageId) =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (message) =>
          message.role === 'assistant' ? { ...message, agentContinuation: continuation } : message,
        ),
      ),
    ),
  finishLast: (sessionId, messageId, remainingToolStatus = 'success') =>
    set((s) =>
      updateMessagesForSession(s, sessionId, (messages) =>
        replaceMessage(messages, messageId, (last) => {
          const now = Date.now()
          return {
            ...last,
            streaming: false,
            toolRuns: last.toolRuns?.map((run) =>
              run.status === 'running' ? { ...run, status: remainingToolStatus } : run,
            ),
            thinkingSteps: (last.thinkingSteps ?? []).map((step) => finishRunningStep(step, now)),
          }
        }),
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
