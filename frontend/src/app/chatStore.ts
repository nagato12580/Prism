import { create } from 'zustand'
import type { ChatSessionOut, ChatMessageOut, ResourceMediaType } from './api'

export interface Source {
  chunk_id: string
  item_id: string
  score: number
  raw_score?: number
  doc_name?: string
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
  selectedTopicId: string | null
  selectedTopicName: string | null
  selectedSourceTypes: ResourceMediaType[]
  // Session state
  currentSessionId: string | null
  sessions: ChatSessionOut[]
  sessionsLoading: boolean
  // Message actions
  addMessage: (msg: Message) => void
  appendToLast: (text: string) => void
  setLastSources: (sources: Source[]) => void
  setLastAgentStatus: (label: string) => void
  addLastToolRun: (run: ToolRun) => void
  finishLastToolRun: (tool: string, data: Partial<ToolRun>) => void
  setLastClarify: (clarify: ClarifyRequest) => void
  finishLast: () => void
  clear: () => void
  // Topic/source actions
  setSelectedTopic: (topicId: string, topicName: string) => void
  clearSelectedTopic: () => void
  toggleSourceType: (type: ResourceMediaType) => void
  setSelectedSourceTypes: (types: ResourceMediaType[]) => void
  clearSelectedSourceTypes: () => void
  // Session actions
  setCurrentSessionId: (id: string | null) => void
  setSessions: (sessions: ChatSessionOut[]) => void
  setSessionsLoading: (loading: boolean) => void
  prependSession: (session: ChatSessionOut) => void
  updateSessionTitle: (id: string, title: string) => void
  removeSession: (id: string) => void
  loadMessages: (msgs: ChatMessageOut[]) => void
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

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  selectedTopicId: null,
  selectedTopicName: null,
  selectedSourceTypes: [],
  currentSessionId: null,
  sessions: [],
  sessionsLoading: false,
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  appendToLast: (text) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) {
        msgs[msgs.length - 1] = { ...last, content: last.content + text }
      }
      return { messages: msgs }
    }),
  setLastSources: (sources) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) msgs[msgs.length - 1] = { ...last, sources }
      return { messages: msgs }
    }),
  setLastAgentStatus: (label) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) {
        const step: ThinkingStep = { label }
        msgs[msgs.length - 1] = {
          ...last,
          agentStatus: label,
          thinkingSteps: [...(last.thinkingSteps ?? []), step],
        }
      }
      return { messages: msgs }
    }),
  addLastToolRun: (run) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) {
        msgs[msgs.length - 1] = { ...last, toolRuns: [...(last.toolRuns ?? []), run] }
      }
      return { messages: msgs }
    }),
  finishLastToolRun: (tool, data) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (!last?.toolRuns) return { messages: msgs }

      let runIndex = -1
      for (let index = last.toolRuns.length - 1; index >= 0; index -= 1) {
        const run = last.toolRuns[index]
        if (run.tool === tool && run.status === 'running') {
          runIndex = index
          break
        }
      }
      if (runIndex === -1) return { messages: msgs }

      const toolRuns = [...last.toolRuns]
      const updated = { ...toolRuns[runIndex], ...data }
      toolRuns[runIndex] = updated
      // Append a thinking step
      const stepLabel = _toolLabel(tool)
      const step: ThinkingStep = {
        label: stepLabel,
        detail: updated.query || updated.summary,
        latencyMs: updated.latencyMs,
      }
      msgs[msgs.length - 1] = {
        ...last,
        toolRuns,
        thinkingSteps: [...(last.thinkingSteps ?? []), step],
      }
      return { messages: msgs }
    }),
  setLastClarify: (clarify) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) msgs[msgs.length - 1] = { ...last, clarify }
      return { messages: msgs }
    }),
  finishLast: () =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) msgs[msgs.length - 1] = { ...last, streaming: false }
      return { messages: msgs }
    }),
  clear: () => set({ messages: [] }),
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

  // Session actions
  setCurrentSessionId: (id) => set({ currentSessionId: id }),
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
        selectedTopicId: isCurrent ? null : s.selectedTopicId,
        selectedTopicName: isCurrent ? null : s.selectedTopicName,
        selectedSourceTypes: isCurrent ? [] : s.selectedSourceTypes,
      }
    }),
  loadMessages: (msgs) =>
    set({
      messages: msgs.map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content || '',
        sources: (m.sources || undefined) as Message['sources'],
        clarify: (m.clarify || undefined) as Message['clarify'],
        streaming: false,
      })),
    }),
  restoreFromSession: (session) =>
    set({
      selectedTopicId: session.topic_id || null,
      selectedSourceTypes: (session.source_types as ResourceMediaType[]) || [],
    }),
}))
