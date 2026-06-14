import { create } from 'zustand'
import type { ResourceMediaType } from './api'

export interface Source {
  chunk_id: string
  item_id: string
  score: number
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

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  streaming?: boolean
  toolRuns?: ToolRun[]
  clarify?: ClarifyRequest
  agentStatus?: string
}

interface ChatState {
  messages: Message[]
  selectedTopicId: string | null
  selectedTopicName: string | null
  selectedSourceTypes: ResourceMediaType[]
  addMessage: (msg: Message) => void
  appendToLast: (text: string) => void
  setLastSources: (sources: Source[]) => void
  setLastAgentStatus: (label: string) => void
  addLastToolRun: (run: ToolRun) => void
  finishLastToolRun: (tool: string, data: Partial<ToolRun>) => void
  setLastClarify: (clarify: ClarifyRequest) => void
  finishLast: () => void
  clear: () => void
  setSelectedTopic: (topicId: string, topicName: string) => void
  clearSelectedTopic: () => void
  toggleSourceType: (type: ResourceMediaType) => void
  setSelectedSourceTypes: (types: ResourceMediaType[]) => void
  clearSelectedSourceTypes: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  selectedTopicId: null,
  selectedTopicName: null,
  selectedSourceTypes: [],
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
      if (last) msgs[msgs.length - 1] = { ...last, agentStatus: label }
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
      toolRuns[runIndex] = { ...toolRuns[runIndex], ...data }
      msgs[msgs.length - 1] = { ...last, toolRuns }
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
}))
