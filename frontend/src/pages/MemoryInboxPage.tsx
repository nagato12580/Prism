import { useCallback, useEffect, useMemo, useState } from 'react'
import { BrainCircuit, Check, ChevronDown, ChevronRight, GitCompareArrows, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { chatApi, memoryApi, type ChatSessionOut, type MemoryDraft, type MemoryExtractionResult } from '@/app/api'

function draftTitle(draft: MemoryDraft) {
  const content = draft.payload?.content
  if (typeof content === 'string' && content.trim()) return content
  return `${draft.draft_type} draft`
}

function formatPayload(payload: Record<string, unknown>) {
  return JSON.stringify(payload, null, 2)
}

function PayloadBlock({ payload }: { payload: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false)
  const text = formatPayload(payload)
  const lineCount = text.split('\n').length
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-2 rounded-md bg-slate-950 px-3 py-2 text-[11px] font-medium text-slate-200 transition-colors hover:bg-slate-800"
      >
        <span>负载数据</span>
        <span className="flex shrink-0 items-center gap-1.5 text-slate-400">
          {lineCount} 行
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>
      {expanded ? (
        <pre className="mt-1 max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
          {text}
        </pre>
      ) : null}
    </div>
  )
}

export function MemoryInboxPage() {
  const [drafts, setDrafts] = useState<MemoryDraft[]>([])
  const [sessions, setSessions] = useState<ChatSessionOut[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [extractLimit, setExtractLimit] = useState(20)
  const [extracting, setExtracting] = useState(false)
  const [extractionResult, setExtractionResult] = useState<MemoryExtractionResult | null>(null)
  const [status, setStatus] = useState('draft')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [supersededStatementId, setSupersededStatementId] = useState<Record<string, string>>({})
  const [reviewingDraftIds, setReviewingDraftIds] = useState<Set<string>>(() => new Set())

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return drafts
    return drafts.filter((draft) =>
      [
        draft.draft_type,
        draft.risk_level,
        draft.decision_hint,
        draft.source?.span_text ?? '',
        formatPayload(draft.payload),
      ]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [drafts, query])

  const loadDrafts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await memoryApi.listDrafts(status ? { status } : undefined)
      setDrafts(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    loadDrafts()
  }, [loadDrafts])

  useEffect(() => {
    let cancelled = false
    chatApi.listSessions()
      .then((next) => {
        if (cancelled) return
        setSessions(next)
        setSelectedSessionId((current) => current || next[0]?.id || '')
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const extractFromSession = async () => {
    const sessionId = selectedSessionId.trim()
    if (!sessionId) {
      setError('Select a chat session before extracting memories.')
      return
    }
    setExtracting(true)
    setError(null)
    setExtractionResult(null)
    try {
      const result = await memoryApi.extractSession(sessionId, { limit: extractLimit })
      setExtractionResult(result)
      await loadDrafts()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setExtracting(false)
    }
  }

  const review = async (draft: MemoryDraft, action: 'confirm' | 'reject' | 'supersede') => {
    if (reviewingDraftIds.has(draft.id)) return
    setError(null)
    let targetId = ''
    if (action === 'supersede') {
      targetId = (supersededStatementId[draft.id] || draft.conflict_ids[0] || '').trim()
      if (!targetId) {
        setError('Supersede requires an existing statement id.')
        return
      }
    }
    setReviewingDraftIds((current) => new Set(current).add(draft.id))
    try {
      if (action === 'confirm') await memoryApi.confirmDraft(draft.id)
      else if (action === 'reject') await memoryApi.rejectDraft(draft.id)
      else await memoryApi.supersedeDraft(draft.id, targetId)
      await loadDrafts()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setReviewingDraftIds((current) => {
        const next = new Set(current)
        next.delete(draft.id)
        return next
      })
    }
  }

  return (
    <div data-testid="memory-inbox-page" className="flex h-[calc(100vh-9rem)] flex-col space-y-3 text-[13px]">
      <section className="shrink-0 border-b border-[var(--prism-line)] pb-3">
        <div className="text-xs font-medium text-slate-500">记忆治理</div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">记忆收件箱</h1>
      </section>

      <section className="shrink-0 rounded-lg border border-[var(--prism-line)] bg-white p-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-end">
          <label className="min-w-0 flex-1">
            <span className="mb-1 block text-[11px] font-medium text-slate-500">聊天会话</span>
            <select
              value={selectedSessionId}
              onChange={(event) => setSelectedSessionId(event.target.value)}
              aria-label="用于记忆提取的聊天会话"
              className="h-9 w-full rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs outline-none focus:border-[var(--prism-blue)]"
            >
              {sessions.length === 0 ? <option value="">暂无聊天会话</option> : null}
              {sessions.map((session) => (
                <option key={session.id} value={session.id} title={session.title || '未命名会话'}>
                  {session.title || '未命名会话'}
                </option>
              ))}
            </select>
          </label>
          <label className="w-full md:w-28">
            <span className="mb-1 block text-[11px] font-medium text-slate-500">消息数</span>
            <input
              type="number"
              min={1}
              max={100}
              value={extractLimit}
              onChange={(event) => setExtractLimit(Number(event.target.value) || 20)}
              aria-label="用于记忆提取的扫描消息数"
              className="h-9 w-full rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs outline-none focus:border-[var(--prism-blue)]"
            />
          </label>
          <button
            type="button"
            onClick={extractFromSession}
            disabled={extracting || !selectedSessionId}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-slate-900 px-3 text-xs font-medium text-white disabled:opacity-50"
          >
            {extracting ? <Loader2 size={15} className="animate-spin" /> : <BrainCircuit size={15} />}
            从会话中提取
          </button>
        </div>
        {extractionResult ? (
          <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            扫描了 {extractionResult.messages_scanned} 条消息，发现 {extractionResult.candidates_found} 个候选，
            创建了 {extractionResult.drafts_created} 条草稿，跳过 {extractionResult.candidates_skipped} 个候选。
          </div>
        ) : null}
      </section>

      <section className="shrink-0 flex flex-col gap-2 rounded-lg border border-[var(--prism-line)] bg-white p-3 md:flex-row md:items-center">
        <label className="relative min-w-0 flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="搜索记忆草稿"
            placeholder="搜索草稿、来源文本、负载数据"
            className="h-9 w-full rounded-md border border-[var(--prism-line)] bg-white pl-8 pr-3 text-xs outline-none focus:border-[var(--prism-blue)]"
          />
        </label>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          aria-label="按状态过滤记忆草稿"
          className="h-9 rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs"
        >
          <option value="draft">草稿</option>
          <option value="confirmed">已确认</option>
          <option value="rejected">已拒绝</option>
          <option value="">全部</option>
        </select>
        <button
          type="button"
          onClick={loadDrafts}
          disabled={loading}
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600 disabled:opacity-50"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          刷新
        </button>
      </section>

      {error ? <div className="shrink-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div> : null}

      <section className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-[var(--prism-line)] bg-white">
        <div className="grid gap-3 p-3">
        {filtered.map((draft) => {
          const reviewing = reviewingDraftIds.has(draft.id)
          return (
          <article key={draft.id} className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.draft_type}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">risk: {draft.risk_level}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">confidence: {Math.round(draft.confidence * 100)}%</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.status}</span>
                </div>
                <h2 className="mt-2 break-words text-sm font-semibold leading-6 text-slate-950">{draftTitle(draft)}</h2>
                {draft.source?.span_text ? (
                  <blockquote className="mt-3 break-words rounded-md border-l-2 border-blue-300 bg-blue-50 px-3 py-2 text-xs leading-5 text-slate-600">
                    <div className="mb-1 font-medium text-slate-700">来源</div>
                    {draft.source.span_text}
                  </blockquote>
                ) : null}
                {draft.conflict_ids.length > 0 ? (
                  <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <div className="font-medium">冲突</div>
                    <div className="mt-1 break-all">{draft.conflict_ids.join(', ')}</div>
                  </div>
                ) : null}
                <PayloadBlock payload={draft.payload} />
              </div>
              {draft.status === 'draft' ? (
                <div className="flex shrink-0 flex-col gap-2 md:w-64">
                  <button
                    type="button"
                    onClick={() => review(draft, 'confirm')}
                    disabled={reviewing}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-emerald-600 px-3 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {reviewing ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => review(draft, 'reject')}
                    disabled={reviewing}
                    className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600 disabled:opacity-50"
                  >
                    <X size={14} />
                    Reject
                  </button>
                  {draft.conflict_ids.length > 0 ? (
                    <div className="space-y-2 rounded-md border border-[var(--prism-line)] bg-slate-50 p-2">
                      <input
                        value={supersededStatementId[draft.id] ?? draft.conflict_ids[0] ?? ''}
                        onChange={(event) =>
                          setSupersededStatementId((current) => ({
                            ...current,
                            [draft.id]: event.target.value,
                          }))
                        }
                        aria-label="要替换的陈述 ID"
                        className="h-8 w-full rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs outline-none focus:border-[var(--prism-blue)]"
                      />
                      <button
                        type="button"
                        onClick={() => review(draft, 'supersede')}
                        disabled={reviewing}
                        className="inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-slate-900 px-3 text-xs font-medium text-white disabled:opacity-50"
                      >
                        <GitCompareArrows size={14} />
                        Supersede
                      </button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </article>
        )})}
        {!loading && filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-white p-8 text-center text-xs text-slate-500">
            No memory drafts match the current filters.
          </div>
        ) : null}
      </div>
      </section>
    </div>
  )
}
