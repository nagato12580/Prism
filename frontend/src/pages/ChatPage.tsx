import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  ChevronDown,
  Clock3,
  MessageSquarePlus,
  Plus,
  Send,
} from 'lucide-react'
import { useChatStore, type Message } from '@/app/chatStore'
import { cn } from '@/lib/utils'

const starterPrompts = [
  '总结我上传资料里的核心观点',
  '基于知识库帮我列一个行动清单',
  '哪些资料可以回答这个问题？',
]

const conversationList = [
  {
    id: 'current',
    title: '当前对话',
    summary: '基于知识库进行可追溯问答',
    status: '进行中',
    time: '刚刚',
  },
  {
    id: 'brief',
    title: '资料核心观点总结',
    summary: '整理上传资料里的重点结论',
    status: '已保存',
    time: '今天',
  },
  {
    id: 'todo',
    title: '行动清单',
    summary: '把知识库内容转成待办步骤',
    status: '草稿',
    time: '昨天',
  },
]

export function ChatPage() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [activeConversation, setActiveConversation] = useState('current')
  const messages = useChatStore((s) => s.messages)
  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLast = useChatStore((s) => s.appendToLast)
  const setLastSources = useChatStore((s) => s.setLastSources)
  const finishLast = useChatStore((s) => s.finishLast)
  const clear = useChatStore((s) => s.clear)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const send = async (value = input) => {
    if (!value.trim() || sending) return

    const query = value.trim()
    setInput('')
    setSending(true)

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: m.content }))

    addMessage({ id: crypto.randomUUID(), role: 'user', content: query })
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true })

    const handleStreamLine = (line: string) => {
      if (!line.trim()) return

      try {
        const msg = JSON.parse(line)
        if (msg.type === 'sources') setLastSources(msg.data)
        else if (msg.type === 'token') appendToLast(msg.data)
        else if (msg.type === 'done') finishLast()
        else if (msg.type === 'error') {
          appendToLast(`\n\n请求失败：${msg.data}`)
          finishLast()
        }
      } catch {
        appendToLast('收到了一段无法解析的流式响应。')
      }
    }

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
      if (!reader) {
        throw new Error('响应没有可读取的内容流')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          handleStreamLine(line)
        }
      }

      buffer += decoder.decode()
      handleStreamLine(buffer)
      finishLast()
    } catch (e) {
      appendToLast('请求失败：' + (e as Error).message)
      finishLast()
    } finally {
      setSending(false)
    }
  }

  const startNewConversation = () => {
    setActiveConversation('current')
    setExpandedSources({})
    clear()
  }

  return (
    <div className="grid h-full min-h-0 w-full gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-[0_18px_48px_-40px_rgba(15,23,42,0.35)]">
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-slate-100 px-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-950">会话</h2>
            <p className="mt-0.5 text-xs text-slate-400">多轮问答状态</p>
          </div>
          <button
            type="button"
            aria-label="新建对话"
            onClick={startNewConversation}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--prism-blue)] text-white shadow-sm transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]"
          >
            <Plus size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="space-y-2">
            {conversationList.map((conversation) => {
              const active = activeConversation === conversation.id
              return (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => setActiveConversation(conversation.id)}
                  className={cn(
                    'w-full rounded-xl border p-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]',
                    active
                      ? 'border-blue-200 bg-blue-50 shadow-sm'
                      : 'border-transparent bg-slate-50 hover:border-slate-200 hover:bg-white'
                  )}
                >
                  <div className="flex items-start gap-2">
                    <div
                      className={cn(
                        'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                        active ? 'bg-[var(--prism-blue)] text-white' : 'bg-white text-slate-400'
                      )}
                    >
                      <MessageSquarePlus size={15} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-semibold text-slate-950">
                        {conversation.title}
                      </div>
                      <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                        {conversation.summary}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2 text-[11px]">
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 font-medium',
                        conversation.status === '进行中'
                          ? 'bg-emerald-50 text-emerald-700'
                          : conversation.status === '草稿'
                            ? 'bg-amber-50 text-amber-700'
                            : 'bg-slate-100 text-slate-500'
                      )}
                    >
                      {conversation.status}
                    </span>
                    <span className="inline-flex items-center gap-1 text-slate-400">
                      <Clock3 size={12} />
                      {conversation.time}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      </aside>

      <section className="prism-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8">
          {messages.length === 0 ? (
            <EmptyState onStarterPrompt={send} disabled={sending} />
          ) : (
            <div className="space-y-5">
              {messages.map((msg) => (
                <MessageBlock
                  key={msg.id}
                  msg={msg}
                  sourcesOpen={!!expandedSources[msg.id]}
                  onToggleSources={() =>
                    setExpandedSources((current) => ({
                      ...current,
                      [msg.id]: !current[msg.id],
                    }))
                  }
                />
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <form
          className="shrink-0 border-t border-[var(--prism-line)] bg-white/90 p-3 sm:p-4"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          <div className="flex min-w-0 gap-2 rounded-xl border border-[var(--prism-line)] bg-white p-2 shadow-[0_14px_34px_-28px_rgba(16,24,40,0.6)] focus-within:border-blue-200 focus-within:ring-2 focus-within:ring-cyan-100">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder="输入问题，Prism 会检索知识库后回答"
              disabled={sending}
              rows={2}
              className="max-h-36 min-h-[3rem] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-60"
            />
            <button
              type="submit"
              aria-label="发送"
              disabled={sending || !input.trim()}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)] text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] disabled:bg-slate-300"
            >
              <Send size={18} />
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

function EmptyState({
  onStarterPrompt,
  disabled,
}: {
  onStarterPrompt: (value: string) => void
  disabled: boolean
}) {
  return (
    <div className="flex min-h-full items-center justify-center py-10">
      <div className="w-full max-w-2xl text-center">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-950 text-white shadow-[0_20px_50px_-28px_rgba(21,94,239,0.9)]">
          <BookOpen size={24} />
        </div>
        <h2 className="text-balance text-2xl font-semibold tracking-normal text-slate-950">
          Prism 知识问答工作台
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-slate-500">
          先上传资料，再让 Prism 从你的知识库里检索、组织并给出可追溯回答。
        </p>

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onStarterPrompt(prompt)}
              disabled={disabled}
              className="max-w-full rounded-full border border-blue-100 bg-blue-50 px-3 py-2 text-sm font-medium text-[var(--prism-blue)] transition hover:border-blue-200 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] disabled:opacity-50"
            >
              {prompt}
            </button>
          ))}
        </div>

        <Link
          to="/knowledge"
          className="mt-7 inline-flex items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:border-blue-200 hover:text-[var(--prism-blue)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]"
        >
          去知识库添加资料
          <ArrowRight size={16} />
        </Link>
      </div>
    </div>
  )
}

function MessageBlock({
  msg,
  sourcesOpen,
  onToggleSources,
}: {
  msg: Message
  sourcesOpen: boolean
  onToggleSources: () => void
}) {
  const isUser = msg.role === 'user'
  const isError = !isUser && msg.content.includes('请求失败：')

  return (
    <div className={cn('flex min-w-0', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn('min-w-0 max-w-[92%] sm:max-w-[78%]', isUser ? 'text-right' : 'text-left')}>
        <div
          className={cn(
            'min-w-0 break-words rounded-2xl px-4 py-3 text-sm leading-6',
            isUser
              ? 'rounded-br-md bg-[var(--prism-blue)] text-white shadow-sm'
              : 'rounded-bl-md border border-[var(--prism-line)] bg-white text-slate-800 shadow-[0_16px_34px_-30px_rgba(16,24,40,0.7)]',
            isError && 'border-red-200 bg-red-50 text-red-700',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap text-left">{msg.content}</p>
          ) : (
            <AssistantContent msg={msg} isError={isError} />
          )}
        </div>

        {!isUser && msg.sources && msg.sources.length > 0 && !msg.streaming && (
          <div className="mt-2 text-left">
            <button
              type="button"
              onClick={onToggleSources}
              className="inline-flex items-center gap-1.5 rounded-full border border-cyan-100 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-cyan-200 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]"
            >
              来源 {msg.sources.length}
              <ChevronDown
                size={14}
                className={cn('transition-transform', sourcesOpen && 'rotate-180')}
              />
            </button>

            {sourcesOpen && (
              <div className="mt-2 grid gap-2">
                {msg.sources.map((source, index) => (
                  <div
                    key={`${source.chunk_id}-${source.item_id}-${index}`}
                    className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-xs text-slate-600 shadow-sm"
                  >
                    <dl className="grid gap-1 sm:grid-cols-[4.5rem_1fr]">
                      <dt className="text-slate-400">chunk id</dt>
                      <dd className="min-w-0 break-all font-mono">{source.chunk_id}</dd>
                      <dt className="text-slate-400">item id</dt>
                      <dd className="min-w-0 break-all font-mono">{source.item_id}</dd>
                      <dt className="text-slate-400">score</dt>
                      <dd className="min-w-0 break-all font-mono">{formatScore(source.score)}</dd>
                    </dl>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function AssistantContent({ msg, isError }: { msg: Message; isError: boolean }) {
  if (isError) {
    return (
      <div className="flex min-w-0 items-start gap-2 text-left">
        <AlertTriangle className="mt-0.5 shrink-0" size={17} />
        <p className="min-w-0 whitespace-pre-wrap break-words">{msg.content}</p>
      </div>
    )
  }

  if (!msg.content && msg.streaming) {
    return (
      <div className="flex items-center gap-2 text-slate-500">
        <span
          className="h-2 w-2 rounded-full bg-[var(--prism-cyan)]"
          style={{ animation: 'prism-pulse 1s ease-in-out infinite' }}
        />
        <span>正在检索知识库...</span>
      </div>
    )
  }

  return (
    <div className="markdown-body min-w-0 max-w-full overflow-x-auto text-left">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
      {msg.streaming && (
        <span
          className="ml-1 inline-block h-2 w-2 rounded-full bg-[var(--prism-cyan)] align-middle"
          style={{ animation: 'prism-pulse 1s ease-in-out infinite' }}
        />
      )}
    </div>
  )
}

function formatScore(score: number) {
  const numericScore = Number(score)
  if (!Number.isFinite(numericScore)) return String(score)
  return numericScore.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
}
