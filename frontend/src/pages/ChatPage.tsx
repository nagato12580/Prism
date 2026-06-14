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
  FileText,
  Image,
  Layers,
  Library,
  Loader2,
  MessageSquarePlus,
  Music,
  Plus,
  Send,
  Video,
  X,
} from 'lucide-react'
import {
  useChatStore,
  SOURCE_TYPE_OPTIONS,
  type ClarifyOption,
  type ClarifyRequest,
  type Message,
  type Source,
  type ToolRun,
} from '@/app/chatStore'
import type { ResourceMediaType } from '@/app/api'
import { knowledgeApi, type KnowledgeTopic } from '@/app/api'
import { cn } from '@/lib/utils'

const starterPrompts = [
  '总结我上传资料里的核心观点',
  '基于知识库帮我列一个行动清单',
  '哪些资料可以回答这个问题？',
]

const sourceTypeIcon = (type: ResourceMediaType) => {
  const icons: Record<ResourceMediaType, ReturnType<typeof FileText>> = {
    document: <FileText size={14} />,
    image: <Image size={14} />,
    audio: <Music size={14} />,
    video: <Video size={14} />,
  }
  return icons[type] ?? <FileText size={14} />
}

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

function normalizeClarifyOptions(value: unknown): ClarifyOption[] {
  if (!Array.isArray(value)) return []
  return value
    .filter(
      (option): option is ClarifyOption =>
        typeof option === 'object' &&
        option !== null &&
        typeof (option as ClarifyOption).label === 'string' &&
        typeof (option as ClarifyOption).value === 'string'
    )
    .slice(0, 3)
}

function normalizeClarifyQuestion(value: unknown) {
  return typeof value === 'string' && value.trim() ? value : '我需要你补充一点信息。'
}

function safeString(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback
}

function normalizeSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((source): source is Record<string, unknown> => typeof source === 'object' && source !== null)
    .map((source) => ({
      chunk_id: String(source.chunk_id ?? ''),
      item_id: String(source.item_id ?? ''),
      score: Number(source.score ?? 0),
    }))
    .filter((source) => source.chunk_id || source.item_id)
}

function historyContent(message: Message) {
  if (message.role === 'assistant' && message.clarify) {
    const options = message.clarify.options.map((option) => option.label).filter(Boolean).join('\n')
    return [message.content, message.clarify.question, options].filter(Boolean).join('\n')
  }
  return message.content
}

export function ChatPage() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [activeConversation, setActiveConversation] = useState('current')
  const messages = useChatStore((s) => s.messages)
  const selectedTopicId = useChatStore((s) => s.selectedTopicId)
  const selectedTopicName = useChatStore((s) => s.selectedTopicName)
  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLast = useChatStore((s) => s.appendToLast)
  const setLastSources = useChatStore((s) => s.setLastSources)
  const setLastAgentStatus = useChatStore((s) => s.setLastAgentStatus)
  const addLastToolRun = useChatStore((s) => s.addLastToolRun)
  const finishLastToolRun = useChatStore((s) => s.finishLastToolRun)
  const setLastClarify = useChatStore((s) => s.setLastClarify)
  const finishLast = useChatStore((s) => s.finishLast)
  const clear = useChatStore((s) => s.clear)
  const setSelectedTopic = useChatStore((s) => s.setSelectedTopic)
  const clearSelectedTopic = useChatStore((s) => s.clearSelectedTopic)
  const selectedSourceTypes = useChatStore((s) => s.selectedSourceTypes)
  const toggleSourceType = useChatStore((s) => s.toggleSourceType)
  const clearSelectedSourceTypes = useChatStore((s) => s.clearSelectedSourceTypes)
  const [showTopicPicker, setShowTopicPicker] = useState(false)
  const [showSourcePicker, setShowSourcePicker] = useState(false)
  const [topics, setTopics] = useState<KnowledgeTopic[]>([])
  const [loadingTopics, setLoadingTopics] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const pendingClarifyRef = useRef<string | null>(null)
  const topicPickerRef = useRef<HTMLDivElement>(null)
  const sourcePickerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  // 点击外部关闭 topic picker
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (topicPickerRef.current && !topicPickerRef.current.contains(e.target as Node)) {
        setShowTopicPicker(false)
      }
    }
    if (showTopicPicker) {
      document.addEventListener('mousedown', handleClick)
      return () => document.removeEventListener('mousedown', handleClick)
    }
  }, [showTopicPicker])

  // 点击外部关闭 source picker
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (sourcePickerRef.current && !sourcePickerRef.current.contains(e.target as Node)) {
        setShowSourcePicker(false)
      }
    }
    if (showSourcePicker) {
      document.addEventListener('mousedown', handleClick)
      return () => document.removeEventListener('mousedown', handleClick)
    }
  }, [showSourcePicker])

  const loadTopics = async () => {
    setLoadingTopics(true)
    try {
      setTopics(await knowledgeApi.listTopics())
    } catch {
      // 静默失败
    } finally {
      setLoadingTopics(false)
    }
  }

  const handleOpenTopicPicker = () => {
    if (!showTopicPicker) {
      if (topics.length === 0) loadTopics()
      setShowTopicPicker(true)
    } else {
      setShowTopicPicker(false)
    }
  }

  const handleSelectTopic = (topic: KnowledgeTopic) => {
    setSelectedTopic(topic.id, topic.name)
    setShowTopicPicker(false)
  }

  const send = async (value = input) => {
    if (!value.trim() || sending) return

    const query = value.trim()
    setInput('')
    setSending(true)

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: historyContent(m) }))

    addMessage({ id: crypto.randomUUID(), role: 'user', content: query })
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true })

    const handleStreamLine = (line: string) => {
      if (!line.trim()) return

      try {
        const msg = JSON.parse(line)
        if (msg.type === 'agent_status') {
          setLastAgentStatus(safeString(msg.data?.label))
        } else if (msg.type === 'tool_call') {
          addLastToolRun({
            id: crypto.randomUUID(),
            tool: safeString(msg.data?.tool, 'tool'),
            query: safeString(msg.data?.query),
            status: 'running',
          })
        } else if (msg.type === 'tool_result') {
          finishLastToolRun(safeString(msg.data?.tool, 'tool'), {
            status: safeString(msg.data?.status) === 'error' ? 'error' : 'success',
            summary: safeString(msg.data?.summary),
            stats: msg.data?.stats,
            latencyMs: msg.data?.latency_ms,
          })
        } else if (msg.type === 'clarify') {
          setLastClarify({
            question: normalizeClarifyQuestion(msg.data?.question),
            options: normalizeClarifyOptions(msg.data?.options),
          })
        } else if (msg.type === 'sources') setLastSources(normalizeSources(msg.data))
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
        body: JSON.stringify({
          query,
          history,
          topic_id: selectedTopicId || undefined,
          source_types: selectedSourceTypes.length > 0 ? selectedSourceTypes : undefined,
        }),
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

  const sendClarifyFollowup = (value: string) => {
    if (sending) {
      pendingClarifyRef.current = value
      return
    }
    send(value)
  }

  useEffect(() => {
    if (sending || !pendingClarifyRef.current) return
    const value = pendingClarifyRef.current
    pendingClarifyRef.current = null
    send(value)
  }, [sending])

  const startNewConversation = () => {
    setActiveConversation('current')
    setExpandedSources({})
    clear()
    clearSelectedTopic()
    clearSelectedSourceTypes()
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

        <div
          data-scroll-region="conversation-list"
          className="min-h-0 flex-1 overflow-y-auto p-3"
        >
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
        <div
          data-scroll-region="message-list"
          className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8"
        >
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
                  onClarifySelect={sendClarifyFollowup}
                />
              ))}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {/* 输入区域：输入框 + 内嵌工具栏 */}
        <form
          className="shrink-0 bg-white/90 p-3 sm:p-4"
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
        >
          <div className="flex flex-col rounded-xl border border-[var(--prism-line)] bg-white shadow-[0_14px_34px_-28px_rgba(16,24,40,0.6)] focus-within:border-blue-200 focus-within:ring-2 focus-within:ring-cyan-100">
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
              className="max-h-36 min-h-[3rem] resize-none border-0 bg-transparent px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-60"
            />
            <div className="flex items-center gap-2 border-t border-slate-100 px-2 py-1.5">
              {/* 知识库选择 */}
              <div className="relative" ref={topicPickerRef}>
                <button
                  type="button"
                  onClick={handleOpenTopicPicker}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition',
                    selectedTopicId
                      ? 'border-blue-200 bg-blue-50 text-[var(--prism-blue)]'
                      : 'border-transparent bg-slate-50 text-slate-500 hover:border-slate-200 hover:text-[var(--prism-blue)]',
                  )}
                >
                  <Library size={12} />
                  {selectedTopicId ? selectedTopicName : '知识库'}
                  <ChevronDown size={10} className={cn('transition', showTopicPicker && 'rotate-180')} />
                </button>

                {showTopicPicker && (
                  <div className="absolute bottom-full left-0 z-30 mb-1 w-44 rounded-lg border border-[var(--prism-line)] bg-white p-1.5 shadow-[0_18px_40px_-20px_rgba(15,23,42,0.45)]">
                    {loadingTopics ? (
                      <div className="flex items-center gap-2 px-2 py-3 text-[11px] text-slate-400">
                        <Loader2 size={12} className="animate-spin" />
                        加载中...
                      </div>
                    ) : topics.length === 0 ? (
                      <p className="px-2 py-3 text-[11px] text-slate-400">暂无知识库</p>
                    ) : (
                      <div className="max-h-44 overflow-y-auto">
                        {topics.map((topic) => (
                          <button
                            key={topic.id}
                            type="button"
                            onClick={() => handleSelectTopic(topic)}
                            className={cn(
                              'flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition',
                              selectedTopicId === topic.id
                                ? 'bg-blue-50 text-[var(--prism-blue)]'
                                : 'text-slate-600 hover:bg-slate-50',
                            )}
                          >
                            <BookOpen size={12} className="shrink-0 text-slate-400" />
                            <span className="min-w-0 flex-1 truncate">{topic.name}</span>
                            <span className="shrink-0 text-[10px] text-slate-400">{topic.resource_count}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 数据来源类型多选 */}
              <div className="relative" ref={sourcePickerRef}>
                <button
                  type="button"
                  onClick={() => setShowSourcePicker((v) => !v)}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition',
                    selectedSourceTypes.length > 0
                      ? 'border-violet-200 bg-violet-50 text-violet-700'
                      : 'border-transparent bg-slate-50 text-slate-500 hover:border-slate-200 hover:text-violet-700',
                  )}
                >
                  <Layers size={12} />
                  {selectedSourceTypes.length > 0
                    ? selectedSourceTypes.map((t) => SOURCE_TYPE_OPTIONS.find((o) => o.value === t)?.label).join('/')
                    : '数据类型'}
                  <ChevronDown size={10} className={cn('transition', showSourcePicker && 'rotate-180')} />
                </button>

                {showSourcePicker && (
                  <div className="absolute bottom-full left-0 z-30 mb-1 w-44 rounded-lg border border-[var(--prism-line)] bg-white p-1.5 shadow-[0_18px_40px_-20px_rgba(15,23,42,0.45)]">
                    <p className="px-2 pb-1 pt-0.5 text-[10px] text-slate-400">可多选，未选则全部</p>
                    <div className="space-y-0.5">
                      {SOURCE_TYPE_OPTIONS.map((option) => {
                        const checked = selectedSourceTypes.includes(option.value)
                        return (
                          <button
                            key={option.value}
                            type="button"
                            onClick={() => toggleSourceType(option.value)}
                            className={cn(
                              'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition',
                              checked
                                ? 'bg-violet-50 text-violet-800'
                                : 'text-slate-600 hover:bg-slate-50',
                            )}
                          >
                            <span
                              className={cn(
                                'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border transition',
                                checked
                                  ? 'border-violet-400 bg-violet-500 text-white'
                                  : 'border-slate-300 bg-white',
                              )}
                            >
                              {checked && (
                                <svg width="8" height="8" viewBox="0 0 10 10" fill="none">
                                  <path d="M2 5l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                              )}
                            </span>
                            <span className="inline-flex items-center gap-1">
                              {sourceTypeIcon(option.value)}
                              {option.label}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                    {selectedSourceTypes.length > 0 && (
                      <div className="mt-1 border-t border-slate-100 pt-1">
                        <button
                          type="button"
                          onClick={clearSelectedSourceTypes}
                          className="w-full rounded-md px-2 py-1 text-left text-[10px] text-slate-400 transition hover:bg-slate-50 hover:text-slate-500"
                        >
                          清除
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 右侧间距 + 清除按钮 */}
              <div className="flex-1" />
              {(selectedTopicId || selectedSourceTypes.length > 0) && (
                <button
                  type="button"
                  onClick={() => { clearSelectedTopic(); clearSelectedSourceTypes() }}
                  className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:text-slate-600"
                >
                  清除筛选
                </button>
              )}

              {/* 发送按钮 */}
              <button
                type="submit"
                aria-label="发送"
                disabled={sending || !input.trim()}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)] text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] disabled:bg-slate-300"
              >
                <Send size={16} />
              </button>
            </div>
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
  onClarifySelect,
}: {
  msg: Message
  sourcesOpen: boolean
  onToggleSources: () => void
  onClarifySelect: (value: string) => void
}) {
  const isUser = msg.role === 'user'
  const handleClarifySelect = (option: ClarifyOption) => {
    onClarifySelect(option.label.trim() || option.value)
  }
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
            <>
              {msg.toolRuns && msg.toolRuns.length > 0 && <ToolProcess runs={msg.toolRuns} />}
              <AssistantContent msg={msg} isError={isError} />
              {msg.clarify && (
                <ClarifyCard clarify={msg.clarify} onSelect={handleClarifySelect} />
              )}
            </>
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
                    className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2.5 text-xs text-slate-600 shadow-sm"
                  >
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate font-semibold text-slate-800">
                        {source.doc_name || source.item_id}
                      </span>
                      <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 font-mono text-[10px] font-medium text-[var(--prism-blue)]">
                        相关度 {formatScore(source.score)}
                      </span>
                    </div>
                    {source.text && (
                      <p className="line-clamp-3 leading-5 text-slate-500">
                        {source.text.slice(0, 300)}
                      </p>
                    )}
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
        <span className="min-w-0 break-words">{agentStatusLabel(msg.agentStatus) || '正在处理...'}</span>
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

function ToolProcess({ runs }: { runs: ToolRun[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-2 text-xs">
      {runs.map((run) => (
        <span
          key={run.id}
          className={cn(
            'inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium',
            run.status === 'running' && 'border-blue-100 bg-blue-50 text-blue-700',
            run.status === 'success' && 'border-emerald-100 bg-emerald-50 text-emerald-700',
            run.status === 'error' && 'border-red-100 bg-red-50 text-red-700'
          )}
          title={run.summary || run.query}
        >
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
          <span className="max-w-28 truncate sm:max-w-36">{toolLabel(run.tool)}</span>
          {run.status === 'running' && <span className="shrink-0">运行中</span>}
          {run.summary && (
            <span className="min-w-0 max-w-40 truncate text-slate-500 sm:max-w-56">
              {run.summary}
            </span>
          )}
        </span>
      ))}
    </div>
  )
}

function ClarifyCard({
  clarify,
  onSelect,
}: {
  clarify: ClarifyRequest
  onSelect: (option: ClarifyOption) => void
}) {
  return (
    <div className="mt-3 rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2.5 text-left">
      <p className="text-sm font-medium leading-6 text-amber-950">{clarify.question}</p>
      {clarify.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {clarify.options.map((option) => (
            <button
              key={`${option.value}-${option.label}`}
              type="button"
              onClick={() => onSelect(option)}
              className="max-w-full rounded-full border border-amber-200 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 transition hover:border-amber-300 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
            >
              <span className="block max-w-full truncate">{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function toolLabel(tool: string) {
  const labels: Record<string, string> = {
    chat: '闲聊',
    knowledge_search: '检索知识库',
    clarify_user: '补充信息',
    retrieve: '检索',
    search: '搜索',
    rerank: '重排',
    synthesize: '生成',
    tool: '工具',
  }
  return labels[tool] ?? tool
}

function agentStatusLabel(status: string | undefined) {
  return status ? toolLabel(status) : ''
}

function formatScore(score: number) {
  const numericScore = Number(score)
  if (!Number.isFinite(numericScore)) return String(score)
  return numericScore.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
}
