import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send } from 'lucide-react'
import { useChatStore, type Message } from '@/app/chatStore'

export function ChatPage() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const messages = useChatStore((s) => s.messages)
  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLast = useChatStore((s) => s.appendToLast)
  const setLastSources = useChatStore((s) => s.setLastSources)
  const finishLast = useChatStore((s) => s.finishLast)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    if (!input.trim() || sending) return
    const query = input.trim()
    setInput('')
    setSending(true)

    // Build history from non-streaming messages
    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: m.content }))

    addMessage({ id: crypto.randomUUID(), role: 'user', content: query })
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true })

    try {
      const resp = await fetch('/api/v1/chat/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, history }),
      })

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const reader = resp.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const msg = JSON.parse(line)
            if (msg.type === 'sources') setLastSources(msg.data)
            else if (msg.type === 'token') appendToLast(msg.data)
            else if (msg.type === 'done') finishLast()
            else if (msg.type === 'error') appendToLast(`\n\n⚠️ 错误: ${msg.data}`)
          } catch {
            // ignore parse errors
          }
        }
      }
      finishLast()
    } catch (e) {
      appendToLast('⚠️ 请求失败: ' + (e as Error).message)
      finishLast()
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex flex-col h-full max-w-3xl mx-auto">
      {/* Message area */}
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 py-20">
            <p className="text-4xl mb-4">🔮</p>
            <p>我是你的个人知识助手 Prism</p>
            <p className="text-sm mt-2">先到知识库上传一些资料，然后在这里提问吧</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={endRef} />
      </div>

      {/* Input area */}
      <div className="flex gap-2 border-t border-gray-200 pt-4">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="输入消息..."
          disabled={sending}
          className="flex-1 px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary disabled:opacity-50"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="px-4 py-2.5 bg-primary text-white rounded-xl hover:opacity-90 disabled:opacity-50"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm ${
          isUser
            ? 'bg-primary text-white rounded-br-md'
            : 'bg-white border border-gray-200 rounded-bl-md'
        }`}
      >
        {msg.content ? (
          isUser ? (
            <p className="whitespace-pre-wrap">{msg.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          )
        ) : (
          <span className="text-gray-400">思考中...</span>
        )}
        {msg.streaming && (
          <span className="inline-block w-2 h-4 bg-gray-400 ml-1 animate-pulse" />
        )}
        {msg.sources && msg.sources.length > 0 && !msg.streaming && (
          <div className="mt-2 flex flex-wrap gap-1">
            {msg.sources.map((s, i) => (
              <span key={i} className="text-xs px-1.5 py-0.5 bg-blue-50 text-primary rounded">
                📎 {i + 1}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
