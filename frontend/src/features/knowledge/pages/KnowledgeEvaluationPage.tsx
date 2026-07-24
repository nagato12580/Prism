import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { FlaskConical, Loader2, Trash2, XCircle, RefreshCw } from 'lucide-react'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import {
  evaluationApi,
  type EvaluationDatasetSummary,
  type EvaluationRun,
  type EvaluationRunDetail,
} from '@/features/knowledge/api/evaluation'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Tabs } from '@/components/ui/Tabs'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'
import { cn } from '@/lib/utils'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

export function KnowledgeEvaluationPage() {
  const { kb } = useOutletContext<Ctx>()
  const kbUid = kb?.kb_uid ?? ''
  const [tab, setTab] = useState<'datasets' | 'runs'>('datasets')
  const [datasets, setDatasets] = useState<EvaluationDatasetSummary[]>([])
  const [runs, setRuns] = useState<EvaluationRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [activeRun, setActiveRun] = useState<EvaluationRunDetail | null>(null)

  const load = () => {
    if (!kbUid) return
    setLoading(true)
    setError(null)
    Promise.all([evaluationApi.listDatasets(kbUid), evaluationApi.listRuns(kbUid)])
      .then(([d, r]) => {
        setDatasets(d)
        setRuns(r)
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }

  useEffect(load, [kbUid])

  const cancelRun = (runUid: string) => {
    evaluationApi.cancelRun(kbUid, runUid).then(load).catch((e) => setError(e))
  }
  const deleteRun = (runUid: string) => {
    evaluationApi.deleteRun(kbUid, runUid).then(load).catch((e) => setError(e))
  }
  const openRun = (runUid: string) => {
    evaluationApi.getRun(kbUid, runUid).then(setActiveRun).catch((e) => setError(e))
  }

  return (
    <div data-testid="knowledge-evaluation-page" className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">检索评估</h2>
        <Button size="sm" variant="secondary" onClick={load}><RefreshCw size={14} /> 刷新</Button>
      </div>

      <Tabs
        items={[
          { key: 'datasets', label: `数据集 (${datasets.length})` },
          { key: 'runs', label: `运行 (${runs.length})` },
        ]}
        active={tab}
        onChange={(k) => setTab(k as 'datasets' | 'runs')}
      />

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState problem={error} onRetry={load} />
      ) : tab === 'datasets' ? (
        datasets.length === 0 ? (
          <EmptyState icon={FlaskConical} title="还没有评估数据集" description="可通过导入 JSONL 或基于检索证据生成数据集" />
        ) : (
          <div className="flex flex-col gap-2">
            {datasets.map((d) => (
              <div key={d.dataset_uid} className="flex items-center justify-between rounded-lg border border-[var(--prism-line)] bg-white p-3">
                <div>
                  <div className="text-sm font-medium text-slate-800">{d.name}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                    <Badge tone="neutral">{d.source}</Badge>
                    <span>{d.item_count} 条</span>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    evaluationApi.exportDataset(kbUid, d.dataset_uid).then(({ blob, filename }) => {
                      const url = URL.createObjectURL(blob)
                      const a = document.createElement('a')
                      a.href = url
                      a.download = filename ?? `${d.name}.jsonl`
                      document.body.appendChild(a)
                      a.click()
                      a.remove()
                      setTimeout(() => URL.revokeObjectURL(url), 1000)
                    })
                  }}
                >
                  导出 JSONL
                </Button>
              </div>
            ))}
          </div>
        )
      ) : runs.length === 0 ? (
        <EmptyState icon={FlaskConical} title="还没有评估运行" description="创建数据集后可发起一次可复现的评估运行" />
      ) : (
        <div className="flex flex-col gap-2">
          {runs.map((r) => (
            <div key={r.run_uid} className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-slate-800">运行 {r.run_uid}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                    <Badge tone={runTone(r.status)}>{r.status}</Badge>
                    <span>索引快照 {r.index_generation ?? '—'}</span>
                    {kb?.active_index_generation ? (
                      <span>当前索引 {kb.active_index_generation}</span>
                    ) : null}
                    <span className="font-mono">{r.progress_current}/{r.progress_total}</span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="ghost" onClick={() => openRun(r.run_uid)}>详情</Button>
                  {['queued', 'running', 'cancel_requested', 'claimed'].includes(r.status) ? (
                    <Button size="sm" variant="ghost" onClick={() => cancelRun(r.run_uid)}><XCircle size={14} /> 取消</Button>
                  ) : null}
                  <Button size="sm" variant="ghost" onClick={() => deleteRun(r.run_uid)}><Trash2 size={14} /></Button>
                </div>
              </div>
              {r.metrics ? (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                  {Object.entries(r.metrics).map(([k, v]) => (
                    typeof v === 'number' ? (
                      <span key={k} className="rounded bg-slate-50 px-1.5 py-0.5 font-mono text-slate-600">
                        {k}: {Number(v).toFixed(4)}
                      </span>
                    ) : null
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {activeRun ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 sm:p-8">
          <div className="my-8 w-full max-w-3xl rounded-2xl border border-[var(--prism-line)] bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-[var(--prism-line)] px-5 py-3">
              <span className="text-sm font-semibold text-slate-900">运行详情 {activeRun.run_uid}</span>
              <button onClick={() => setActiveRun(null)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100">✕</button>
            </div>
            <div className="max-h-[70vh] overflow-y-auto p-5">
              <div className="mb-3 flex flex-wrap gap-2 text-[11px]">
                <Badge tone="blue">索引 {activeRun.index_generation ?? '—'}</Badge>
                <Badge tone="violet">图谱 {activeRun.graph_generation ?? '—'}</Badge>
                {activeRun.model ? <Badge tone="neutral">模型 {activeRun.model}</Badge> : null}
              </div>
              <ul className="flex flex-col gap-1.5">
                {activeRun.items.map((it) => (
                  <li key={it.id} className="rounded-lg border border-[var(--prism-line)] bg-slate-50/40 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium text-slate-700">{it.query}</span>
                      <Badge tone={it.status === 'succeeded' ? 'green' : it.status === 'failed' ? 'red' : 'amber'}>{it.status}</Badge>
                    </div>
                    {it.error_message ? <div className="mt-1 text-[11px] text-red-500">{it.error_message}</div> : null}
                    {it.metrics ? (
                      <div className="mt-1 flex flex-wrap gap-1.5 text-[10px]">
                        {Object.entries(it.metrics).map(([k, v]) =>
                          typeof v === 'number' ? (
                            <span key={k} className="rounded bg-white px-1 py-0.5 font-mono text-slate-500">{k}: {Number(v).toFixed(3)}</span>
                          ) : null,
                        )}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function runTone(status: string): 'green' | 'amber' | 'red' | 'blue' {
  if (status === 'succeeded') return 'green'
  if (status === 'failed' || status === 'canceled') return 'red'
  if (['queued', 'running', 'cancel_requested', 'claimed'].includes(status)) return 'amber'
  return 'blue'
}

export { cn, Loader2 }
