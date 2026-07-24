import { useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { Search, Loader2, Save, Network, AlertTriangle } from 'lucide-react'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { retrievalApi, type RetrievalResult } from '@/features/knowledge/api/retrieval'
import { ApiProblem } from '@/features/knowledge/api/client'
import {
  type Evidence,
  type RetrievalMode,
  retrievalStatusLabel,
  channelScoreLabel,
} from '@/features/knowledge/api/contracts'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'
import { cn } from '@/lib/utils'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

export function KnowledgeRetrievalPage() {
  const { kb } = useOutletContext<Ctx>()
  const [searchParams, setSearchParams] = useSearchParams()
  const kbUid = kb?.kb_uid ?? ''
  const query = searchParams.get('q') ?? ''
  const mode = (searchParams.get('mode') ?? 'fast') as RetrievalMode
  const [topK, setTopK] = useState<number>(Number(searchParams.get('top_k') ?? '10'))
  const [graphHops, setGraphHops] = useState<string>(searchParams.get('graph_hops') ?? '')
  const [result, setResult] = useState<RetrievalResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [openEvidence, setOpenEvidence] = useState<Evidence | null>(null)

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next)
  }

  const run = () => {
    if (!kbUid || !query.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    retrievalApi
      .query(kbUid, {
        query: query.trim(),
        mode,
        config: { top_k: topK, graph_hops: graphHops ? Number(graphHops) : null },
      })
      .then(setResult)
      .catch((e) => {
        const p = e as ApiProblem
        // The backend returns RETRIEVAL_UNAVAILABLE / INVALID_RETRIEVAL_REQUEST as
        // error envelopes. Map them to the unified status vocabulary for display.
        if (p?.code === 'RETRIEVAL_UNAVAILABLE') {
          setResult({ status: 'unavailable' as never, evidence: [], warnings: [], httpStatus: 503 })
          setError(null)
        } else if (p?.code === 'INVALID_RETRIEVAL_REQUEST') {
          setResult({ status: 'invalid_request' as never, evidence: [], warnings: [], httpStatus: 422 })
          setError(null)
        } else {
          setError(e)
        }
      })
      .finally(() => setLoading(false))
  }

  const status = result?.status as string

  return (
    <div data-testid="knowledge-retrieval-page" className="flex h-full min-h-0 flex-col gap-3">
      <h2 className="text-base font-semibold text-slate-900">检索实验台</h2>

      <div className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <div className="flex items-center gap-2">
          <Input
            aria-label="查询"
            placeholder="输入检索问题…"
            value={query}
            onChange={(e) => setParam('q', e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') run()
            }}
          />
          <Button variant="primary" onClick={run} loading={loading} disabled={!query.trim()}>
            {loading ? null : <Search size={15} />} 运行检索
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-600">
          <label className="flex items-center gap-1.5">
            模式：
            <select
              value={mode}
              onChange={(e) => setParam('mode', e.target.value)}
              className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-2 text-xs"
            >
              <option value="fast">快速</option>
              <option value="deep">深度</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            Top K：
            <Input
              type="number"
              min={1}
              max={100}
              value={topK}
              onChange={(e) => {
                setTopK(Number(e.target.value))
                setParam('top_k', e.target.value)
              }}
              className="h-8 w-20"
            />
          </label>
          <label className="flex items-center gap-1.5">
            Graph hops：
            <Input
              type="number"
              min={1}
              max={3}
              value={graphHops}
              placeholder="可选"
              onChange={(e) => {
                setGraphHops(e.target.value)
                setParam('graph_hops', e.target.value)
              }}
              className="h-8 w-24"
            />
          </label>
        </div>
      </div>

      {loading ? (
        <LoadingState label="检索中…" />
      ) : error ? (
        <ErrorState problem={error} onRetry={run} />
      ) : !result ? (
        <EmptyState
          icon={Search}
          title="输入问题开始检索"
          description="结果将展示各检索通道的原始分数、RRF、Rerank 与证据"
        />
      ) : (
        <RetrievalBody status={status} result={result} onOpen={setOpenEvidence} kbUid={kbUid} />
      )}

      {openEvidence ? (
        <EvidenceDetailDrawer evidence={openEvidence} onClose={() => setOpenEvidence(null)} kbUid={kbUid} />
      ) : null}
    </div>
  )
}

function RetrievalBody({
  status,
  result,
  onOpen,
  kbUid,
}: {
  status: string
  result: RetrievalResult
  onOpen: (e: Evidence) => void
  kbUid: string
}) {
  const tone =
    status === 'ok' ? 'green' : status === 'no_hits' ? 'neutral' : status === 'degraded' ? 'amber' : 'red'
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Badge tone={tone}>{retrievalStatusLabel(status as never)}</Badge>
        {result.httpStatus === 206 ? <Badge tone="amber">HTTP 206 降级</Badge> : null}
        <span className="text-xs text-slate-400">{result.evidence.length} 条证据</span>
      </div>

      {result.warnings.length ? (
        <div className="flex flex-col gap-1 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
          {result.warnings.map((w, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-amber-700">
              <AlertTriangle size={13} />
              <span className="font-mono">{w.code}</span>
              {w.message ? <span>· {w.message}</span> : null}
              {w.retryable ? <Badge tone="amber">可重试</Badge> : null}
            </div>
          ))}
        </div>
      ) : null}

      {result.evidence.length === 0 ? (
        <EmptyState icon={Search} title="未找到匹配证据" description="可尝试更换关键词或使用深度模式" />
      ) : (
        <ul className="flex flex-col gap-2">
          {result.evidence.map((ev, idx) => (
            <li
              key={`${ev.chunk_uid}-${idx}`}
              className="rounded-xl border border-[var(--prism-line)] bg-white p-3"
            >
              <button
                type="button"
                onClick={() => onOpen(ev)}
                className="flex w-full items-start gap-3 text-left"
              >
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--prism-blue)]/10 text-[11px] font-semibold text-[var(--prism-blue)]">
                  {idx + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-slate-900">{ev.display_title}</span>
                    {ev.evidence_type !== 'chunk' ? (
                      <Badge tone="violet">{ev.evidence_type}</Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-slate-500">{ev.excerpt}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                    {Object.entries(ev.channel_scores).map(([ch, sc]) => (
                      <span key={ch} className="rounded bg-slate-50 px-1.5 py-0.5">
                        {channelScoreLabel(ch)}：{sc.raw_score.toFixed(4)} (#{sc.raw_rank})
                      </span>
                    ))}
                    <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-600">RRF：{ev.rrf_score.toFixed(4)}</span>
                    {ev.rerank_score != null ? (
                      <span className="rounded bg-violet-50 px-1.5 py-0.5 text-violet-600">
                        Rerank：{ev.rerank_score.toFixed(4)}
                      </span>
                    ) : null}
                    {ev.retrieval_channels.map((c) => (
                      <Badge key={c} tone="cyan">{c}</Badge>
                    ))}
                    {ev.graph_path.length ? (
                      <span className="flex items-center gap-1 text-slate-500">
                        <Network size={11} /> 图路径 {ev.graph_path.length}
                      </span>
                    ) : null}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
      <span className="hidden">{kbUid}</span>
    </div>
  )
}

function EvidenceDetailDrawer({
  evidence,
  onClose,
}: {
  evidence: Evidence
  onClose: () => void
  kbUid: string
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 sm:p-8">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-[var(--prism-line)] bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-[var(--prism-line)] px-5 py-3">
          <span className="truncate text-sm font-semibold text-slate-900">{evidence.display_title}</span>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <Loader2 size={16} className="hidden" />
            ✕
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-5">
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-700">
            {evidence.excerpt}
          </pre>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
            {evidence.page_start != null ? <Badge tone="neutral">页 {evidence.page_start}{evidence.page_end != null && evidence.page_end !== evidence.page_start ? `-${evidence.page_end}` : ''}</Badge> : null}
            {evidence.char_start != null ? <Badge tone="neutral">字符 {evidence.char_start}-{evidence.char_end}</Badge> : null}
            <Badge tone="blue">generation {evidence.index_generation}</Badge>
            {evidence.graph_explanation ? <Badge tone="violet">{evidence.graph_explanation}</Badge> : null}
            {evidence.degradation_flags.length ? <Badge tone="amber">{evidence.degradation_flags.join(', ')}</Badge> : null}
          </div>
          <div className="mt-4 flex items-center gap-2 text-[11px] text-slate-400">
            <span className="font-mono">{evidence.chunk_uid}</span>
            <Save size={12} className="text-slate-300" />
            <span>保存为评估样例需在评估页面操作</span>
          </div>
        </div>
      </div>
    </div>
  )
}
