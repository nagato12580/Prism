import { create } from 'zustand'

export interface Source {
  chunk_id: string
  item_id: string
  score: number
}

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
  addMessage: (msg: Message) => void
  appendToLast: (text: string) => void
  setLastSources: (sources: Source[]) => void
  setLastAgentStatus: (label: string) => void
  addLastToolRun: (run: ToolRun) => void
  finishLastToolRun: (tool: string, data: Partial<ToolRun>) => void
  setLastClarify: (clarify: ClarifyRequest) => void
  finishLast: () => void
  clear: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
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
}))
