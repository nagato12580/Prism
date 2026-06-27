import { useEffect, useMemo, useState } from 'react'
import { Brain, CircleDot, Gauge, Lightbulb, Loader2, MessageSquareText, Package, RefreshCw, ShieldCheck, Sparkles, Target } from 'lucide-react'
import { memoryApi, type ConsolidationResult, type MemoryInsight, type MemoryStatement } from '@/app/api'
import { cn } from '@/lib/utils'
import { type MemoryView, entryToView, formatDate, getMemoryMeta, groupMemories, importantTags, memoryTypeMeta, statementToView } from './memoryUtils'

export function UserProfilePage() {
  const [memories, setMemories] = useState<MemoryView[]>([])
  const [insights, setInsights] = useState<MemoryInsight[]>([])
  const [reflecting, setReflecting] = useState(false)
  const [consolidating, setConsolidating] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const groups = useMemo(() => groupMemories(memories), [memories])
  const topTags = useMemo(() => importantTags(memories), [memories])
  const averageImportance = memories.length
    ? Math.round((memories.reduce((sum, item) => sum + Number(item.importance || 0), 0) / memories.length) * 100)
    : 0

  const loadMemories = async () => {
    setLoading(true)
    setError(null)
    try {
      const [entries, statements, insightList] = await Promise.all([
        memoryApi.list({ limit: 160 }),
        memoryApi.listStatements({ limit: 200 }).catch(() => [] as MemoryStatement[]),
        memoryApi.listInsights({ limit: 20 }).catch(() => [] as MemoryInsight[]),
      ])
      const views = [
        ...entries.map(entryToView),
        ...statements.map(statementToView),
      ].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0))
      setMemories(views)
      setInsights(insightList)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const triggerReflection = async () => {
    setReflecting(true)
    setNotice(null)
    setError(null)
    try {
      const result = await memoryApi.reflect()
      if (result.skipped) {
        setNotice(`反思跳过：${result.skipped === 'too_few_memories' ? '记忆太少，至少需要 4 条' : '暂无可归纳内容'}`)
      } else {
        setNotice(`反思完成，生成 ${result.insights} 条洞察。`)
      }
      const insightList = await memoryApi.listInsights({ limit: 20 }).catch(() => [] as MemoryInsight[])
      setInsights(insightList)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setReflecting(false)
    }
  }

  const triggerConsolidation = async () => {
    setConsolidating(true)
    setNotice(null)
    setError(null)
    try {
      const result: ConsolidationResult = await memoryApi.consolidate()
      setNotice(`巩固完成，提升 ${result.total_promoted} 条高频记忆重要度。`)
      await loadMemories()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setConsolidating(false)
    }
  }

  useEffect(() => {
    loadMemories()
  }, [])

  const strongest = memories[0]

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col space-y-3 text-[13px]">
      <header className="shrink-0 flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <Brain size={16} className="text-[var(--prism-blue)]" />
            用户记忆
          </div>
          <h1 className="mt-1 text-xl font-semibold tracking-normal text-slate-950">用户画像</h1>
          <p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">
            汇总 Prism 已保存的偏好、目标、事实和上下文，用来校准后续知识整理与对话行为。
          </p>
        </div>
        <button
          type="button"
          onClick={loadMemories}
          disabled={loading}
          className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:opacity-50"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          刷新
        </button>
      </header>

      {error ? <div className="shrink-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div> : null}

      {loading && memories.length === 0 ? (
        <EmptyState text="正在读取用户记忆。" />
      ) : memories.length === 0 ? (
        <EmptyState text="还没有用户记忆。确认碎片时开启记忆写入或从对话提取确认后，这里会形成画像。" />
      ) : (
        <div className="min-h-0 flex-1 grid gap-4 overflow-hidden xl:grid-cols-[22rem_minmax(0,1fr)]">
          <aside className="overflow-y-auto space-y-3 pe-1">
            <section className="rounded-lg border border-[var(--prism-line)] bg-slate-950 p-4 text-white">
              <div className="flex items-center gap-2 text-xs font-medium text-blue-100">
                <Sparkles size={15} />
                画像强度
              </div>
              <div className="mt-4 flex items-end gap-2">
                <span className="text-4xl font-semibold tabular-nums">{averageImportance}</span>
                <span className="pb-1 text-xs text-slate-300">/ 100</span>
              </div>
              <p className="mt-3 text-xs leading-5 text-slate-300">
                基于 {memories.length} 条记忆计算。分数越高，表示当前画像中高权重记忆占比越高。
              </p>
            </section>

            <section className="rounded-lg border border-amber-200 bg-amber-50/50 p-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-950">
                  <Lightbulb size={15} className="text-amber-600" />
                  画像洞察
                </div>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={triggerConsolidation}
                    disabled={consolidating || memories.length === 0}
                    className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-[11px] font-medium text-slate-600 transition hover:border-amber-300 hover:text-amber-700 disabled:opacity-40"
                  >
                    {consolidating ? <Loader2 size={12} className="animate-spin" /> : <Gauge size={12} />}
                    巩固
                  </button>
                  <button
                    type="button"
                    onClick={triggerReflection}
                    disabled={reflecting || memories.length < 4}
                    className="inline-flex h-7 items-center gap-1 rounded-md bg-amber-600 px-2 text-[11px] font-medium text-white transition hover:brightness-95 disabled:opacity-40"
                  >
                    {reflecting ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                    生成洞察
                  </button>
                </div>
              </div>
              {notice ? <div className="mb-2 text-[11px] text-amber-700">{notice}</div> : null}
              <div className="max-h-48 overflow-y-auto space-y-2">
                {insights.length ? (
                  insights.map((ins) => (
                    <div key={ins.id} className="rounded-md border border-amber-100 bg-white p-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-semibold text-amber-700">{ins.theme}</span>
                        <span className="text-[10px] text-slate-400">{Math.round(Number(ins.importance || 0) * 100)}</span>
                      </div>
                      <p className="mt-1 text-[11px] leading-4 text-slate-600">{ins.content}</p>
                    </div>
                  ))
                ) : (
                  <div className="text-[11px] text-slate-400">暂无洞察。积累足够记忆后点「生成洞察」归纳画像。</div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-950">
                <ShieldCheck size={15} className="text-emerald-600" />
                最稳定信号
              </div>
              {strongest ? (
                <MemoryCard item={strongest} featured />
              ) : null}
            </section>

            <section className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="mb-3 text-xs font-semibold text-slate-950">高频标签</div>
              <div className="flex flex-wrap gap-1.5">
                {topTags.length ? (
                  topTags.map(([tag, count]) => (
                    <span key={tag} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                      #{tag} · {count}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-400">暂无标签</span>
                )}
              </div>
            </section>
          </aside>

          <main className="overflow-y-auto grid gap-3 lg:grid-cols-2 pe-1">
            {Object.keys(memoryTypeMeta).map((type) => (
              <MemorySection key={type} type={type} items={groups[type] ?? []} />
            ))}
          </main>
        </div>
      )}
    </div>
  )
}

function MemorySection({ type, items }: { type: string; items: MemoryView[] }) {
  const meta = getMemoryMeta(type)
  return (
    <section className="min-h-[16rem] rounded-lg border border-[var(--prism-line)] bg-white p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={cn('flex h-7 w-7 items-center justify-center rounded-lg border text-xs font-semibold', meta.tone)}>
            {meta.short}
          </span>
          <div>
            <h2 className="text-sm font-semibold text-slate-950">{meta.label}</h2>
            <p className="text-[11px] text-slate-400">{items.length} 条记忆</p>
          </div>
        </div>
        <Target size={15} className="text-slate-300" />
      </div>
      <div className="space-y-2">
        {items.length ? items.map((item) => <MemoryCard key={item.id} item={item} />) : <EmptyLine />}
      </div>
    </section>
  )
}

function MemoryCard({ item, featured = false }: { item: MemoryView; featured?: boolean }) {
  const meta = getMemoryMeta(item.memory_type)
  return (
    <article className={cn('rounded-lg border bg-white p-3', featured ? 'border-blue-100' : 'border-slate-100')}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-[13px] font-semibold leading-5 text-slate-950">{item.title}</h3>
        <span className={cn('shrink-0 rounded-md border px-1.5 py-0.5 text-[10px]', meta.tone)}>
          {Math.round(Number(item.importance || 0) * 100)}
        </span>
      </div>
      <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-500">{item.content}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
        <span className="inline-flex items-center gap-1">
          <CircleDot size={10} />
          {item.category || meta.label}
        </span>
        <span className="inline-flex items-center gap-1" title={item.origin === 'conversation' ? '对话提取记忆' : '资产沉淀记忆'}>
          {item.origin === 'conversation' ? <MessageSquareText size={10} /> : <Package size={10} />}
          {item.origin === 'conversation' ? '对话' : '资产'}
        </span>
        <span>{formatDate(item.updated_at)}</span>
      </div>
    </article>
  )
}

function EmptyLine() {
  return (
    <div className="flex min-h-24 items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-slate-50 text-xs text-slate-400">
      暂无此类记忆
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex min-h-96 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white text-center text-xs leading-5 text-slate-500">
      <Brain size={32} className="mb-3 text-slate-300" />
      {text}
    </div>
  )
}
