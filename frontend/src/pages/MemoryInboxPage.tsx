import { useEffect, useMemo, useState } from 'react'
import { Check, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { memoryApi, type MemoryDraft } from '@/app/api'

function draftTitle(draft: MemoryDraft) {
  const content = draft.payload?.content
  if (typeof content === 'string' && content.trim()) return content
  return `${draft.draft_type} draft`
}

function formatPayload(payload: Record<string, unknown>) {
  return JSON.stringify(payload, null, 2)
}

export function MemoryInboxPage() {
  const [drafts, setDrafts] = useState<MemoryDraft[]>([])
  const [status, setStatus] = useState('draft')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

  const loadDrafts = async () => {
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
  }

  useEffect(() => {
    loadDrafts()
  }, [status])

  const review = async (draft: MemoryDraft, action: 'confirm' | 'reject') => {
    setError(null)
    try {
      if (action === 'confirm') await memoryApi.confirmDraft(draft.id)
      else await memoryApi.rejectDraft(draft.id)
      await loadDrafts()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div data-testid="memory-inbox-page" className="min-h-[calc(100vh-9rem)] space-y-4 text-[13px]">
      <section className="border-b border-[var(--prism-line)] pb-3">
        <div className="text-xs font-medium text-slate-500">Memory governance</div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-950">Memory Inbox</h1>
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-[var(--prism-line)] bg-white p-3 md:flex-row md:items-center">
        <label className="relative min-w-0 flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search memory drafts"
            placeholder="Search drafts, source text, payload"
            className="h-9 w-full rounded-md border border-[var(--prism-line)] bg-white pl-8 pr-3 text-xs outline-none focus:border-[var(--prism-blue)]"
          />
        </label>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-9 rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs"
        >
          <option value="draft">Draft</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
        <button
          type="button"
          onClick={loadDrafts}
          disabled={loading}
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600 disabled:opacity-50"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          Refresh
        </button>
      </section>

      {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div> : null}

      <section className="grid gap-3">
        {filtered.map((draft) => (
          <article key={draft.id} className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.draft_type}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">risk: {draft.risk_level}</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">confidence: {Math.round(draft.confidence * 100)}%</span>
                  <span className="rounded-md bg-slate-100 px-2 py-1">{draft.status}</span>
                </div>
                <h2 className="mt-2 text-sm font-semibold text-slate-950">{draftTitle(draft)}</h2>
                {draft.source?.span_text ? (
                  <blockquote className="mt-3 rounded-md border-l-2 border-blue-300 bg-blue-50 px-3 py-2 text-xs leading-5 text-slate-600">
                    <div className="mb-1 font-medium text-slate-700">Source</div>
                    {draft.source.span_text}
                  </blockquote>
                ) : null}
                <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
                  {formatPayload(draft.payload)}
                </pre>
              </div>
              {draft.status === 'draft' ? (
                <div className="flex shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => review(draft, 'confirm')}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-xs font-medium text-white"
                  >
                    <Check size={14} />
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => review(draft, 'reject')}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs font-medium text-slate-600"
                  >
                    <X size={14} />
                    Reject
                  </button>
                </div>
              ) : null}
            </div>
          </article>
        ))}
        {!loading && filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-white p-8 text-center text-xs text-slate-500">
            No memory drafts match the current filters.
          </div>
        ) : null}
      </section>
    </div>
  )
}
