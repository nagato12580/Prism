import { create } from 'zustand'

export interface Source {
  chunk_id: string
  item_id: string
  score: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  streaming?: boolean
}

interface ChatState {
  messages: Message[]
  addMessage: (msg: Message) => void
  appendToLast: (text: string) => void
  setLastSources: (sources: Source[]) => void
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
  finishLast: () =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last) msgs[msgs.length - 1] = { ...last, streaming: false }
      return { messages: msgs }
    }),
  clear: () => set({ messages: [] }),
}))
