import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  FileText,
  HelpCircle,
  Image,
  Layers,
  Library,
  Loader2,
  MessageSquarePlus,
  Music,
  Pencil,
  Plus,
  Search,
  Send,
  Video,
  X,
} from 'lucide-react'
import {
  useChatStore,
  SOURCE_TYPE_OPTIONS,
  normalizeEvidenceItems,
  type ClarifyOption,
  type ClarifyRequest,
  type EvidenceItem,
  type Message,
  type Source,
  type ToolRunStatus,
  type ToolRun,
  type ThinkingStep,
} from '@/app/chatStore'
import type { GraphRagExplain, GraphRagPathEntry, ResourceMediaType } from '@/app/api'
import { knowledgeApi, chatApi, traceApi, type KnowledgeTopic } from '@/app/api'
import { evidenceTypeLabel as formatEvidenceTypeLabel, graphPathLabels } from '@/app/graphrag'
import { cn, genId } from '@/lib/utils'

const starterPrompts = [
  '总结我上传资料里的核心观点',
  '基于知识库帮我列一个行动清单',
  '哪些资料可以回答这个问题？',
]

const chatStreamTimeoutEnv = (
  import.meta as unknown as { env?: { VITE_CHAT_STREAM_TIMEOUT_SECONDS?: string } }
).env?.VITE_CHAT_STREAM_TIMEOUT_SECONDS
const CHAT_STREAM_TIMEOUT_SECONDS = Number(chatStreamTimeoutEnv || 300)
const CHAT_STREAM_TIMEOUT_MS = Number.isFinite(CHAT_STREAM_TIMEOUT_SECONDS)
  ? CHAT_STREAM_TIMEOUT_SECONDS * 1000
  : 300_000
const CHAT_TYPEWRITER_INTERVAL_MS = 18

const sourceTypeIcon = (type: ResourceMediaType) => {
  const icons: Record<ResourceMediaType, ReturnType<typeof FileText>> = {
    document: <FileText size={14} />,
    image: <Image size={14} />,
    audio: <Music size={14} />,
    video: <Video size={14} />,
  }
  return icons[type] ?? <FileText size={14} />
}

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

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeStepStatus(value: unknown): ToolRunStatus {
  return value === 'running' || value === 'error' ? value : 'success'
}

function normalizeSources(value: unknown): Source[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((source): source is Record<string, unknown> => typeof source === 'object' && source !== null)
    .map((source) => ({
      chunk_id: String(source.chunk_id ?? ''),
      item_id: String(source.item_id ?? ''),
      source_kind: typeof source.source_kind === 'string' ? source.source_kind : undefined,
      source_id: typeof source.source_id === 'string' ? source.source_id : undefined,
      display_type: typeof source.display_type === 'string' ? source.display_type : undefined,
      display_id: typeof source.display_id === 'string' ? source.display_id : undefined,
      display_title: typeof source.display_title === 'string' ? source.display_title : undefined,
      display_label: typeof source.display_label === 'string' ? source.display_label : undefined,
      score: Number(source.score ?? 0),
      raw_score: typeof source.raw_score === 'number' ? source.raw_score : undefined,
      doc_name: typeof source.doc_name === 'string' ? source.doc_name : undefined,
      title: typeof source.title === 'string' ? source.title : undefined,
      snippet: typeof source.snippet === 'string' ? source.snippet : undefined,
      text: typeof source.text === 'string' ? source.text : undefined,
    }))
    .filter((source) => source.chunk_id || source.item_id || source.display_id || source.source_id)
}

function normalizeThinkingSteps(value: unknown): ThinkingStep[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((step): step is Record<string, unknown> => typeof step === 'object' && step !== null)
    .map((step) => ({
      label: safeString(step.label, safeString(step.agent, 'step')),
      detail: safeString(step.detail),
      agent: typeof step.agent === 'string' ? step.agent : undefined,
      iteration: typeof step.iteration === 'number' ? step.iteration : undefined,
      status: normalizeStepStatus(step.status),
    }))
    .filter((step) => step.label)
}

function mergeThinkingSteps(...values: unknown[]): ThinkingStep[] {
  const steps: ThinkingStep[] = []
  const seen = new Set<string>()
  for (const value of values) {
    for (const step of normalizeThinkingSteps(value)) {
      const key = `${step.iteration || ''}:${step.agent || ''}:${step.label}:${step.detail || ''}`
      if (seen.has(key)) continue
      seen.add(key)
      steps.push(step)
    }
  }
  return steps
}

function sourceDisplayTitle(source: Source) {
  return source.display_title || source.doc_name || source.title || source.item_id || source.display_id || source.source_id || '来源'
}

function sourceDisplayLabel(source: Source) {
  if (source.display_label) return source.display_label
  if (source.display_type === 'knowledge_item') return '知识文档'
  if (source.display_type === 'personal_asset_unit') return '知识单元'
  if (source.source_kind === 'document_chunk') return '知识文档'
  if (source.source_kind === 'personal_asset_unit') return '知识单元'
  if (source.source_kind === 'personal_asset_item') return '来源碎片'
  return '来源'
}

function sourceSnippet(source: Source) {
  return source.snippet || source.text || ''
}

function formatSessionTime(dateStr: string) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

function historyContent(message: Message) {
  if (message.role === 'assistant' && message.clarify) {
    const options = message.clarify.options.map((option) => option.label).filter(Boolean).join('\n')
    return [message.content, message.clarify.question, options].filter(Boolean).join('\n')
  }
  return message.content
}

function shouldAutoGenerateTitle(title?: string | null) {
  const normalized = (title || '').trim()
  return !normalized || normalized === '新对话' || normalized === 'New conversation' || normalized === 'Untitled session'
}

function buildAssistantProcess(message: Message) {
  return {
    trace_id: message.traceId || null,
    agent_status: message.agentStatus || null,
    tool_runs: message.toolRuns || [],
    thinking_steps: message.thinkingSteps || [],
  }
}

export function ChatPage() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({})
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [editingSessionTitle, setEditingSessionTitle] = useState('')
  const messages = useChatStore((s) => s.messages)
  const selectedTopicId = useChatStore((s) => s.selectedTopicId)
  const selectedTopicName = useChatStore((s) => s.selectedTopicName)
  const selectedSourceTypes = useChatStore((s) => s.selectedSourceTypes)
  const deepSearchEnabled = useChatStore((s) => s.deepSearchEnabled)
  const deepSearchDepth = useChatStore((s) => s.deepSearchDepth)
  const currentSessionId = useChatStore((s) => s.currentSessionId)
  const sessions = useChatStore((s) => s.sessions)
  const sessionsLoading = useChatStore((s) => s.sessionsLoading)
  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLast = useChatStore((s) => s.appendToLast)
  const setLastSources = useChatStore((s) => s.setLastSources)
  const setLastAgentStatus = useChatStore((s) => s.setLastAgentStatus)
  const addLastToolRun = useChatStore((s) => s.addLastToolRun)
  const finishLastToolRun = useChatStore((s) => s.finishLastToolRun)
  const setLastClarify = useChatStore((s) => s.setLastClarify)
  const setLastTraceId = useChatStore((s) => s.setLastTraceId)
  const finishLast = useChatStore((s) => s.finishLast)
  const clear = useChatStore((s) => s.clear)
  const setSelectedTopic = useChatStore((s) => s.setSelectedTopic)
  const clearSelectedTopic = useChatStore((s) => s.clearSelectedTopic)
  const toggleSourceType = useChatStore((s) => s.toggleSourceType)
  const clearSelectedSourceTypes = useChatStore((s) => s.clearSelectedSourceTypes)
  const setDeepSearchEnabled = useChatStore((s) => s.setDeepSearchEnabled)
  const setDeepSearchDepth = useChatStore((s) => s.setDeepSearchDepth)
  const setCurrentSessionId = useChatStore((s) => s.setCurrentSessionId)
  const setSessions = useChatStore((s) => s.setSessions)
  const prependSession = useChatStore((s) => s.prependSession)
  const updateSessionTitle = useChatStore((s) => s.updateSessionTitle)
  const removeSession = useChatStore((s) => s.removeSession)
  const loadMessages = useChatStore((s) => s.loadMessages)
  const replaceMessageId = useChatStore((s) => s.replaceMessageId)
  const getSessionMessages = useChatStore((s) => s.getSessionMessages)
  const restoreFromSession = useChatStore((s) => s.restoreFromSession)
  const [showTopicPicker, setShowTopicPicker] = useState(false)
  const [showSourcePicker, setShowSourcePicker] = useState(false)
  const [topics, setTopics] = useState<KnowledgeTopic[]>([])
  const [loadingTopics, setLoadingTopics] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const pendingClarifyRef = useRef<string | null>(null)
  const topicPickerRef = useRef<HTMLDivElement>(null)
  const sourcePickerRef = useRef<HTMLDivElement>(null)
  const processPersistenceQueuesRef = useRef<Record<string, {
    running: Promise<void> | null
    latest: { sessionId: string; messageId: string } | null
  }>>({})

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  // 页面加载：恢复最近会话
  useEffect(() => {
    let cancelled = false
    async function restore() {
      try {
        const list = await chatApi.listSessions()
        if (cancelled) return
        setSessions(list)
        if (list.length > 0) {
          const latest = list[0]
          setCurrentSessionId(latest.id)
          restoreFromSession(latest)
          if (latest.topic_id) {
            try {
              const topics = await knowledgeApi.listTopics()
              if (!cancelled) {
                const matched = topics.find((t) => t.id === latest.topic_id)
                if (matched) setSelectedTopic(matched.id, matched.name)
              }
            } catch { /* topic name restore best-effort */ }
          }
          try {
            const msgs = await chatApi.listMessages(latest.id)
            if (!cancelled) loadMessages(latest.id, msgs)
          } catch { /* messages restore best-effort */ }
        }
      } catch { /* sessions load failed — stay empty */ }
    }
    restore()
    return () => { cancelled = true }
  }, [])

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

    // 确保会话存在（首次发消息时创建）
    let sessionId = currentSessionId
    if (!sessionId) {
      try {
        const session = await chatApi.createSession({
          topic_id: selectedTopicId || undefined,
          source_types: selectedSourceTypes.length > 0 ? selectedSourceTypes : undefined,
        })
        sessionId = session.id
        setCurrentSessionId(sessionId)
        prependSession(session)
      } catch {
        setSending(false)
        return
      }
    }

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: historyContent(m) }))

    const userMessageId = genId()
    const temporaryAssistantMessageId = genId()
    let engineUserMessageId = userMessageId
    let assistantMessageId = temporaryAssistantMessageId
    let assistantPersistedId: string | null = null
    let traceId: string | null = null
    addMessage({ id: userMessageId, role: 'user', content: query }, sessionId)
    addMessage({ id: temporaryAssistantMessageId, role: 'assistant', content: '', streaming: true }, sessionId)

    const userPersistPromise = persistUserMessage(sessionId, query)
    await userPersistPromise
    const assistantPersistPromise = persistAssistantPlaceholder(sessionId)
    try {
      const persistedUserMessage = await userPersistPromise
      if (persistedUserMessage) {
        replaceMessageId(sessionId, userMessageId, persistedUserMessage.id)
        engineUserMessageId = persistedUserMessage.id
      }
    } catch { /* user persistence failure falls back to the optimistic id */ }
    try {
      const persisted = await assistantPersistPromise
      if (persisted) {
        assistantPersistedId = persisted.id
        replaceMessageId(sessionId, temporaryAssistantMessageId, persisted.id)
        assistantMessageId = persisted.id
      }
    } catch { /* placeholder persistence is best-effort */ }

    let titleReceived = false
    const streamAbortController = new AbortController()
    let streamTimedOut = false
    let streamTimeoutId: number | undefined
    const refreshStreamTimeout = () => {
      if (streamTimeoutId !== undefined) window.clearTimeout(streamTimeoutId)
      streamTimeoutId = window.setTimeout(() => {
        streamTimedOut = true
        streamAbortController.abort()
      }, CHAT_STREAM_TIMEOUT_MS)
    }
    const clearStreamTimeout = () => {
      if (streamTimeoutId !== undefined) {
        window.clearTimeout(streamTimeoutId)
        streamTimeoutId = undefined
      }
    }
    let typewriterBuffer = ''
    let typewriterTimerId: number | undefined
    let typewriterFlushResolvers: Array<() => void> = []
    const clearTypewriterTimer = () => {
      if (typewriterTimerId !== undefined) {
        window.clearTimeout(typewriterTimerId)
        typewriterTimerId = undefined
      }
      typewriterBuffer = ''
      resolveTypewriterFlushes()
    }
    const resolveTypewriterFlushes = () => {
      if (typewriterBuffer.length > 0 || typewriterTimerId !== undefined) return
      const resolvers = typewriterFlushResolvers
      typewriterFlushResolvers = []
      resolvers.forEach((resolve) => resolve())
    }
    const pumpTypewriterText = () => {
      if (!typewriterBuffer) {
        clearTypewriterTimer()
        resolveTypewriterFlushes()
        return
      }
      const chunkSize = typewriterBuffer.length > 80 ? 3 : 1
      const chunk = typewriterBuffer.slice(0, chunkSize)
      typewriterBuffer = typewriterBuffer.slice(chunkSize)
      appendToLast(chunk, sessionId, assistantMessageId)
      typewriterTimerId = window.setTimeout(pumpTypewriterText, CHAT_TYPEWRITER_INTERVAL_MS)
    }
    const enqueueTypewriterText = (text: string) => {
      if (!text) return
      typewriterBuffer += text
      if (typewriterTimerId === undefined) {
        typewriterTimerId = window.setTimeout(pumpTypewriterText, CHAT_TYPEWRITER_INTERVAL_MS)
      }
    }
    const flushTypewriterText = () => {
      if (typewriterBuffer.length === 0 && typewriterTimerId === undefined) return Promise.resolve()
      return new Promise<void>((resolve) => {
        typewriterFlushResolvers.push(resolve)
      })
    }

    const handleStreamLine = async (line: string) => {
      if (!line.trim()) return
      refreshStreamTimeout()

      try {
        const msg = JSON.parse(line)
        if (msg.type === 'trace') {
          traceId = safeString(msg.data?.trace_id)
          if (traceId) {
            setLastTraceId(traceId, sessionId, assistantMessageId)
            if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
          }
        } else if (msg.type === 'agent_status') {
          setLastAgentStatus(safeString(msg.data?.label), sessionId, assistantMessageId)
          if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
        } else if (msg.type === 'tool_call') {
          addLastToolRun({
            id: genId(),
            tool: safeString(msg.data?.tool, 'tool'),
            query: safeString(msg.data?.query),
            status: 'running',
          }, sessionId, assistantMessageId)
          if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
        } else if (msg.type === 'tool_result') {
          finishLastToolRun(safeString(msg.data?.tool, 'tool'), {
            status: safeString(msg.data?.status) === 'error' ? 'error' : 'success',
            summary: safeString(msg.data?.summary),
            stats: msg.data?.stats,
            latencyMs: msg.data?.latency_ms,
            evidenceItems: normalizeEvidenceItems(msg.data?.evidence_items),
            traceSteps: mergeThinkingSteps(
              msg.data?.trace_steps,
              msg.data?.stats?.deep_trace_steps,
              msg.data?.stats?.trace_steps,
            ),
          }, sessionId, assistantMessageId)
          if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
        } else if (msg.type === 'clarify') {
          setLastClarify({
            question: normalizeClarifyQuestion(msg.data?.question),
            options: normalizeClarifyOptions(msg.data?.options),
          }, sessionId, assistantMessageId)
        } else if (msg.type === 'sources') setLastSources(normalizeSources(msg.data), sessionId, assistantMessageId)
        else if (msg.type === 'token') enqueueTypewriterText(safeString(msg.data))
        else if (msg.type === 'done') {
          clearStreamTimeout()
          await flushTypewriterText()
          finishLast(sessionId, assistantMessageId, 'success')
          if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
        }
        else if (msg.type === 'title') {
          const title = safeString(msg.data)
          if (sessionId && title) {
            titleReceived = true
            updateSessionTitle(sessionId, title)
            chatApi.updateSession(sessionId, { title }).catch(() => {})
          }
        }
        else if (msg.type === 'error') {
          await flushTypewriterText()
          appendToLast(`\n\n请求失败：${msg.data}`, sessionId, assistantMessageId)
          finishLast(sessionId, assistantMessageId, 'error')
        }
      } catch {
        await flushTypewriterText()
        appendToLast('收到了一段无法解析的流式响应。', sessionId, assistantMessageId)
      }
    }

    try {
      const resp = await fetch('/api/v1/chat/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: streamAbortController.signal,
        body: JSON.stringify({
          query,
          history,
          session_id: sessionId,
          user_message_id: engineUserMessageId,
          topic_id: selectedTopicId || undefined,
          source_types: selectedSourceTypes.length > 0 ? selectedSourceTypes : undefined,
          deep_search_enabled: deepSearchEnabled,
          deep_search_depth: deepSearchDepth,
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
      refreshStreamTimeout()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        refreshStreamTimeout()
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          await handleStreamLine(line)
        }
      }

      buffer += decoder.decode()
      await handleStreamLine(buffer)
      clearStreamTimeout()
      await flushTypewriterText()
      finishLast(sessionId, assistantMessageId, 'success')
    } catch (e) {
      clearStreamTimeout()
      await flushTypewriterText()
      const message = streamTimedOut
        ? '知识库检索时间过长，已停止本次请求。可以换个更具体的问题再试。'
        : (e as Error).message
      appendToLast('请求失败：' + message, sessionId, assistantMessageId)
      finishLast(sessionId, assistantMessageId, 'error')
    } finally {
      clearStreamTimeout()
      clearTypewriterTimer()
      setSending(false)
      // 持久化 AI 回复 + 标题生成
      if (sessionId) {
        const msgs = getSessionMessages(sessionId)
        const aiMsg = msgs.find((m) => m.id === assistantMessageId && m.role === 'assistant' && !m.streaming)
        if (aiMsg) {
          try {
            if (!assistantPersistedId) {
              const persisted = await assistantPersistPromise
              assistantPersistedId = persisted?.id || null
            }
            if (assistantPersistedId) await chatApi.updateMessage(sessionId, assistantPersistedId, {
              content: aiMsg.content,
              sources: aiMsg.sources || undefined,
              clarify: aiMsg.clarify || undefined,
              process: buildAssistantProcess(aiMsg),
            })
            else {
              const persistedAssistant = await chatApi.addMessage(sessionId, {
                role: 'assistant',
                content: aiMsg.content,
                sources: aiMsg.sources || undefined,
                clarify: aiMsg.clarify || undefined,
                process: buildAssistantProcess(aiMsg),
              })
              assistantPersistedId = persistedAssistant.id
              replaceMessageId(sessionId, assistantMessageId, persistedAssistant.id)
              assistantMessageId = persistedAssistant.id
            }
            if (assistantPersistedId) {
              await flushAssistantProcessSnapshot(sessionId, assistantPersistedId)
            }
            if (traceId && assistantPersistedId) {
              await traceApi.bindMessage(traceId, {
                session_id: sessionId,
                assistant_message_id: assistantPersistedId,
              })
            }
          } catch { /* persistence is best-effort for the chat UI */ }
        }
        // 首轮问答后自动生成标题
        const userCount = msgs.filter((m) => m.role === 'user').length
        const session = useChatStore.getState().sessions.find((s) => s.id === sessionId)
        if (!titleReceived && userCount === 1 && shouldAutoGenerateTitle(session?.title)) {
          try {
            const updated = await chatApi.generateTitle(sessionId)
            updateSessionTitle(sessionId, updated.title)
          } catch { /* title generation is best-effort */ }
        }
      }
    }
  }

  const persistUserMessage = (sessionId: string, content: string) => {
    return chatApi.addMessage(sessionId, { role: 'user', content }).catch(() => undefined)
  }

  const persistAssistantPlaceholder = (sessionId: string) => {
    return chatApi.addMessage(sessionId, { role: 'assistant', content: '' }).catch(() => undefined)
  }

  const persistAssistantProcessSnapshot = async (sessionId: string, messageId: string) => {
    const msg = getSessionMessages(sessionId).find((message) => message.id === messageId)
    if (!msg) return
    await chatApi.updateMessage(sessionId, messageId, { process: buildAssistantProcess(msg) })
  }

  const processPersistenceKey = (sessionId: string, messageId: string) => `${sessionId}:${messageId}`

  const queueAssistantProcessSnapshot = (sessionId: string, messageId: string) => {
    // Queues persistAssistantProcessSnapshot(sessionId, assistantPersistedId) calls during streaming.
    const key = processPersistenceKey(sessionId, messageId)
    const queue = processPersistenceQueuesRef.current[key] ?? {
      running: null,
      latest: null,
    }
    queue.latest = { sessionId, messageId }
    processPersistenceQueuesRef.current[key] = queue

    if (!queue.running) {
      queue.running = runAssistantProcessSnapshotQueue(key)
    }
    return queue.running
  }

  const runAssistantProcessSnapshotQueue = async (key: string): Promise<void> => {
    const queue = processPersistenceQueuesRef.current[key]
    if (!queue) return

    while (queue.latest) {
      const snapshot = queue.latest
      queue.latest = null
      try {
        await persistAssistantProcessSnapshot(snapshot.sessionId, snapshot.messageId)
      } catch { /* process persistence is best-effort while streaming */ }
    }

    queue.running = null
    if (queue.latest) {
      queue.running = runAssistantProcessSnapshotQueue(key)
      await queue.running
    } else {
      delete processPersistenceQueuesRef.current[key]
    }
  }

  const flushAssistantProcessSnapshot = async (sessionId: string, messageId: string) => {
    await queueAssistantProcessSnapshot(sessionId, messageId)
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
    setCurrentSessionId(null)
    setExpandedSources({})
    clear()
    clearSelectedTopic()
    clearSelectedSourceTypes()
  }

  const switchSession = async (sessionId: string) => {
    if (sessionId === currentSessionId) return
    clearSelectedTopic()
    clearSelectedSourceTypes()
    setExpandedSources({})
    setCurrentSessionId(sessionId)

    const session = useChatStore.getState().sessions.find((s) => s.id === sessionId)
    if (session) {
      restoreFromSession(session)
      if (session.topic_id) {
        try {
          const topics = await knowledgeApi.listTopics()
          const matched = topics.find((t) => t.id === session.topic_id)
          if (matched) setSelectedTopic(matched.id, matched.name)
        } catch { /* best effort */ }
      }
    }
    try {
      const msgs = await chatApi.listMessages(sessionId)
      loadMessages(sessionId, msgs)
    } catch { /* best effort */ }
  }

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确认删除这个会话吗？')) return
    try {
      await chatApi.deleteSession(sessionId)
      removeSession(sessionId)
    } catch { /* silent */ }
  }

  const startEditingSessionTitle = (sessionId: string, title: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingSessionId(sessionId)
    setEditingSessionTitle(title)
  }

  const cancelEditingSessionTitle = (e?: React.MouseEvent) => {
    e?.stopPropagation()
    setEditingSessionId(null)
    setEditingSessionTitle('')
  }

  const saveSessionTitle = async (sessionId: string, e: React.FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const title = editingSessionTitle.trim()
    if (!title) return
    try {
      const updated = await chatApi.updateSession(sessionId, { title })
      updateSessionTitle(sessionId, updated.title)
      cancelEditingSessionTitle()
    } catch { /* keep editing so the user can retry */ }
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
          {sessionsLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400">
              <Loader2 size={14} className="animate-spin" />
              加载会话...
            </div>
          ) : sessions.length === 0 ? (
            <div className="py-10 text-center text-xs text-slate-400">
              暂无会话，发送第一条消息开始
            </div>
          ) : (
            <div className="space-y-2">
              {sessions.map((session) => {
                const active = currentSessionId === session.id
                const time = formatSessionTime(session.updated_at)
                const editing = editingSessionId === session.id
                return (
                  <div key={session.id} className="group relative">
                    {editing ? (
                      <form
                        onSubmit={(e) => saveSessionTitle(session.id, e)}
                        className={cn(
                          'w-full rounded-xl border p-3 text-left transition focus-within:ring-2 focus-within:ring-[var(--prism-cyan)]',
                          active
                            ? 'border-blue-200 bg-blue-50 shadow-sm'
                            : 'border-slate-200 bg-white',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <input
                            value={editingSessionTitle}
                            onChange={(event) => setEditingSessionTitle(event.target.value)}
                            aria-label="Session title"
                            className="min-w-0 flex-1 rounded-md border border-[var(--prism-line)] bg-white px-2 py-1.5 text-sm font-semibold text-slate-950 outline-none focus:border-[var(--prism-blue)]"
                            autoFocus
                          />
                          <button
                            type="submit"
                            aria-label="保存会话标题"
                            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--prism-blue)] text-white"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={cancelEditingSessionTitle}
                            aria-label="取消编辑会话标题"
                            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[var(--prism-line)] bg-white text-slate-400"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </form>
                    ) : (
                      <button
                        type="button"
                        onClick={() => switchSession(session.id)}
                        className={cn(
                          'w-full rounded-xl border p-3 pr-16 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]',
                          active
                            ? 'border-blue-200 bg-blue-50 shadow-sm'
                            : 'border-transparent bg-slate-50 hover:border-slate-200 hover:bg-white',
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className={cn(
                              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                              active ? 'bg-[var(--prism-blue)] text-white' : 'bg-white text-slate-400',
                            )}
                          >
                            <MessageSquarePlus size={15} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-semibold text-slate-950">
                              {session.title}
                            </div>
                            <div className="mt-1 text-[11px] text-slate-400">{time}</div>
                          </div>
                        </div>
                      </button>
                    )}
                    {!editing ? (
                      <button
                        type="button"
                        onClick={(e) => startEditingSessionTitle(session.id, session.title, e)}
                        className="absolute right-8 top-2 hidden h-6 w-6 items-center justify-center rounded-md text-slate-300 transition hover:bg-blue-50 hover:text-[var(--prism-blue)] group-hover:flex"
                        aria-label={`编辑 ${session.title}`}
                      >
                        <Pencil size={13} />
                      </button>
                    ) : null}
                    {!editing ? (
                      <button
                        type="button"
                        onClick={(e) => deleteSession(session.id, e)}
                        className="absolute right-2 top-2 hidden h-6 w-6 items-center justify-center rounded-md text-slate-300 transition hover:bg-red-50 hover:text-red-500 group-hover:flex"
                        aria-label={`删除 ${session.title}`}
                      >
                        <X size={13} />
                      </button>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
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
              <div className="flex shrink-0 items-center overflow-hidden rounded-md border border-slate-200 bg-slate-50">
                <button
                  type="button"
                  onClick={() => setDeepSearchEnabled(!deepSearchEnabled)}
                  aria-pressed={deepSearchEnabled}
                  className={cn(
                    'inline-flex h-7 items-center gap-1 px-2 text-[11px] font-medium transition',
                    deepSearchEnabled
                      ? 'bg-emerald-50 text-emerald-700'
                      : 'bg-transparent text-slate-500 hover:text-emerald-700',
                  )}
                >
                  <Search size={12} />
                  深度搜索
                </button>
                {deepSearchEnabled && (
                  <div className="flex border-l border-slate-200">
                    {([
                      ['quick', '快速'],
                      ['standard', '标准'],
                      ['deep', '深入'],
                    ] as const).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setDeepSearchDepth(value)}
                        className={cn(
                          'h-7 px-2 text-[11px] font-medium transition',
                          deepSearchDepth === value
                            ? 'bg-emerald-600 text-white'
                            : 'text-slate-500 hover:bg-white hover:text-emerald-700',
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

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
        {!isUser && <ThinkingPanel msg={msg} />}
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
              {msg.toolRuns && msg.toolRuns.length > 0 && <ToolEvidenceList runs={msg.toolRuns} />}
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
                    key={`${source.display_type || source.source_kind || 'source'}-${source.display_id || source.source_id || source.chunk_id || source.item_id}-${index}`}
                    className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2.5 text-xs text-slate-600 shadow-sm"
                  >
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-semibold text-slate-800">
                          {sourceDisplayTitle(source)}
                        </div>
                        <div className="mt-0.5 truncate text-[11px] text-slate-400">
                          {source.display_id || source.item_id || source.source_id}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                          {sourceDisplayLabel(source)}
                        </span>
                        <span className="rounded-full bg-blue-50 px-2 py-0.5 font-mono text-[10px] font-medium text-[var(--prism-blue)]">
                          {source.raw_score ? `匹配 ${(source.raw_score * 100).toFixed(0)}%` : `相关度 ${formatScore(source.score)}`}
                        </span>
                      </div>
                    </div>
                    {sourceSnippet(source) && (
                      <p className="line-clamp-3 leading-5 text-slate-500">
                        {sourceSnippet(source).slice(0, 300)}
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

function stepIcon(tool: string, status?: string) {
  if (status === 'running') return <Loader2 size={13} className="animate-spin" />
  if (status === 'error') return <AlertTriangle size={13} />
  if (status === 'success') return <Check size={13} />
  if (tool === 'knowledge_search') return <Search size={13} />
  if (tool === 'deep_knowledge_search') return <Search size={13} />
  if (tool === 'SearcherAgent') return <Search size={13} />
  if (tool === 'JudgeAgent') return <Check size={13} />
  if (tool === 'clarify_user') return <HelpCircle size={13} />
  return <Check size={13} />
}

function formatLatency(ms?: number) {
  if (ms === undefined || ms === null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function EvidenceMetadata({ evidence }: { evidence: EvidenceItem }) {
  const graph_explain = isPlainRecord(evidence.metadata?.graph_explain)
    ? evidence.metadata.graph_explain as GraphRagExplain & Record<string, unknown>
    : null
  const graph_path = Array.isArray(evidence.metadata?.graph_path)
    ? evidence.metadata.graph_path as GraphRagPathEntry[]
    : []
  const evidence_type = typeof evidence.metadata?.evidence_type === 'string'
    ? evidence.metadata.evidence_type
    : typeof graph_explain?.evidence_type === 'string'
      ? graph_explain.evidence_type
      : undefined

  if (!graph_explain && graph_path.length === 0 && !evidence_type) return null

  return (
    <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-500">
      {evidence_type && (
        <div className="font-medium text-slate-600">
          {formatEvidenceTypeLabel(evidence_type)}
        </div>
      )}
      {graph_explain ? (
        <div className="mt-1">
          {typeof graph_explain.why === 'string' && graph_explain.why.trim()
            ? graph_explain.why
            : 'graph explanation available'}
        </div>
      ) : null}
      {graph_path.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {graphPathLabels(graph_path).map((label, index) => (
            <span
              key={`${evidence.evidence_id}-graph_path-${index}`}
              className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600"
            >
              {label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function ToolEvidenceList({ runs }: { runs: ToolRun[] }) {
  const evidenceItems = runs.flatMap((run) => run.evidenceItems ?? [])

  if (evidenceItems.length === 0) return null

  return (
    <div className="mb-3 space-y-2">
      {evidenceItems.slice(0, 3).map((evidence) => (
        <div
          key={evidence.evidence_id}
          className="rounded-lg border border-[var(--prism-line)] bg-white/80 px-3 py-2 text-xs text-slate-600"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-medium text-slate-700">
                {evidence.display_title || evidence.source_id || evidence.evidence_id}
              </div>
              {evidence.excerpt && (
                <p className="mt-1 line-clamp-2 leading-5 text-slate-500">
                  {evidence.excerpt}
                </p>
              )}
            </div>
            {typeof evidence.score === 'number' ? (
              <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500">
                {formatScore(evidence.score)}
              </span>
            ) : null}
          </div>
          <EvidenceMetadata evidence={evidence} />
        </div>
      ))}
    </div>
  )
}

function stepLatencyMs(step: ThinkingStep, nowMs: number) {
  if (step.latencyMs !== undefined) return step.latencyMs
  if (step.status === 'running' && step.startedAtMs !== undefined) return nowMs - step.startedAtMs
  return undefined
}

function ThinkingPanel({ msg }: { msg: Message }) {
  const [expanded, setExpanded] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const steps = msg.thinkingSteps
  const runs = msg.toolRuns
  const hasRunningTimedStep = (steps ?? []).some((step) => step.status === 'running' && step.startedAtMs !== undefined)

  useEffect(() => {
    if (!expanded || !hasRunningTimedStep) return undefined
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [expanded, hasRunningTimedStep])

  if ((!steps || steps.length === 0) && (!runs || runs.length === 0)) return null

  return (
    <div className="mb-1.5 text-left">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
      >
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {expanded ? '收起思考过程' : '查看思考过程'}
        {steps && steps.length > 0 && (
          <span className="text-slate-300">· {steps.length} 步</span>
        )}
      </button>
      {expanded && (
        <div className="mt-1 rounded-lg border border-[var(--prism-line)] bg-slate-50/70 px-3 py-2">
          {steps && steps.length > 0 ? (
            <div className="space-y-1.5">
              {steps.map((step, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span className="mt-0.5 shrink-0 text-slate-400">
                    {stepIcon(step.agent || step.tool || runs?.[0]?.tool || '', step.status)}
                  </span>
                  <span className="min-w-0 flex-1 text-slate-700">{step.label}</span>
                  {step.detail && (
                    <span className="max-w-40 shrink-0 truncate text-slate-400 sm:max-w-64">
                      {step.iteration ? `#${step.iteration} ` : ''}{step.agent ? `${step.agent} · ` : ''}{step.detail}
                    </span>
                  )}
                  {stepLatencyMs(step, nowMs) !== undefined && (
                    <span className="shrink-0 text-[10px] text-slate-400">
                      {formatLatency(stepLatencyMs(step, nowMs))}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-1.5">
              {runs?.map((run) => (
                <div key={run.id} className="flex items-start gap-2 text-xs">
                  <span className="mt-0.5 shrink-0 text-slate-400">
                    {stepIcon(run.tool)}
                  </span>
                  <span className="min-w-0 flex-1 text-slate-700">{toolLabel(run.tool)}</span>
                  {run.query && (
                    <span className="max-w-32 shrink-0 truncate text-slate-400 sm:max-w-48">
                      {run.query}
                    </span>
                  )}
                  {run.latencyMs && (
                    <span className="shrink-0 text-[10px] text-slate-400">
                      {formatLatency(run.latencyMs)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
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
