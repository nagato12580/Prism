import { useEffect, useMemo, useState } from 'react'
import { BrainCircuit, Loader2, RefreshCw, Search } from 'lucide-react'
import { memoryApi, type MemoryEntry } from '@/app/api'
import { cn } from '@/lib/utils'
import { formatDate, getMemoryMeta, groupMemories, memoryTypeMeta } from './memoryUtils'

type GraphNode = {
  id: string
  label: string
  kind: 'self' | 'type' | 'memory'
  x: number
  y: number
  item?: MemoryEntry
}

type GraphEdge = { from: string; to: string }

export function MemoryGraphPage() {
  const [memories, setMemories] = useState<MemoryEntry[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return memories
    return memories.filter((item) =>
      [item.title, item.content, item.category, item.memory_type, ...(item.tags ?? [])].join(' ').toLowerCase().includes(q),
    )
  }, [memories, query])

  const graph = useMemo(() => buildGraph(filtered), [filtered])
  const selected = selectedId ? filtered.find((item) => item.id === selectedId) ?? null : filtered[0] ?? null

  const loadMemories = async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await memoryApi.list({ limit: 180 })
      setMemories(next)
      setSelectedId((current) => (current && next.some((item) => item.id === current) ? current : next[0]?.id ?? null))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMemories()
  }, [])

  return (
    <div className="grid min-h-[calc(100vh-9rem)] gap-4 overflow-hidden text-[13px] xl:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="flex min-h-0 flex-col rounded-lg border border-[var(--prism-line)] bg-white">
        <header className="flex flex-col gap-3 border-b border-[var(--prism-line)] p-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
              <BrainCircuit size={16} className="text-[var(--prism-blue)]" />
              用户记忆
            </div>
            <h1 className="mt-1 text-xl font-semibold text-slate-950">记忆图谱</h1>
          </div>
          <div className="flex gap-2">
            <label className="relative block w-full min-w-0 sm:w-64">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索记忆、标签、分类"
                className="h-8 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-8 pr-2 text-xs outline-none transition focus:border-[var(--prism-blue)]"
              />
            </label>
            <button
              type="button"
              onClick={loadMemories}
              disabled={loading}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:opacity-50"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              刷新
            </button>
          </div>
        </header>

        {error ? <div className="m-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div> : null}

        <div className="min-h-0 flex-1 overflow-auto bg-slate-50">
          {loading && memories.length === 0 ? (
            <GraphEmpty text="正在读取记忆图谱。" />
          ) : filtered.length === 0 ? (
            <GraphEmpty text="没有匹配的记忆。清空搜索后可以查看完整图谱。" />
          ) : (
            <svg viewBox="0 0 980 620" className="h-full min-h-[34rem] w-full">
              <defs>
                <filter id="memoryShadow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="10" stdDeviation="12" floodColor="#0f172a" floodOpacity="0.12" />
                </filter>
              </defs>
              {graph.edges.map((edge) => {
                const from = graph.nodes.find((node) => node.id === edge.from)
                const to = graph.nodes.find((node) => node.id === edge.to)
                if (!from || !to) return null
                return (
                  <line
                    key={`${edge.from}-${edge.to}`}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="#cbd5e1"
                    strokeWidth={edge.from === 'self' ? 1.4 : 1}
                  />
                )
              })}
              {graph.nodes.map((node) => (
                <GraphNodeShape
                  key={node.id}
                  node={node}
                  active={node.item?.id === selected?.id}
                  onSelect={() => node.item && setSelectedId(node.item.id)}
                />
              ))}
            </svg>
          )}
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded-lg border border-[var(--prism-line)] bg-white">
        <div className="border-b border-[var(--prism-line)] p-3">
          <div className="text-xs font-medium text-slate-500">选中记忆</div>
          <h2 className="mt-1 truncate text-base font-semibold text-slate-950">{selected?.title ?? '暂无记忆'}</h2>
        </div>
        <div className="min-h-0 space-y-3 overflow-y-auto p-3">
          {selected ? (
            <>
              <MemoryDetail item={selected} />
              <RelationList selected={selected} items={filtered} />
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-slate-50 p-4 text-xs leading-5 text-slate-500">
              选择图谱中的记忆节点后，这里会显示来源、标签和相邻记忆。
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

function buildGraph(items: MemoryEntry[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const groups = groupMemories(items)
  const typeOrder = Object.keys(memoryTypeMeta).filter((type) => groups[type]?.length)
  const nodes: GraphNode[] = [{ id: 'self', label: '用户', kind: 'self', x: 490, y: 310 }]
  const edges: GraphEdge[] = []
  const radiusX = 270
  const radiusY = 190
  typeOrder.forEach((type, index) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / Math.max(typeOrder.length, 1)
    const typeNode = {
      id: `type:${type}`,
      label: getMemoryMeta(type).label,
      kind: 'type' as const,
      x: 490 + Math.cos(angle) * radiusX,
      y: 310 + Math.sin(angle) * radiusY,
    }
    nodes.push(typeNode)
    edges.push({ from: 'self', to: typeNode.id })
    groups[type].slice(0, 12).forEach((item, itemIndex) => {
      const spread = (itemIndex - (groups[type].slice(0, 12).length - 1) / 2) * 26
      const memoryNode = {
        id: item.id,
        label: item.title,
        kind: 'memory' as const,
        x: typeNode.x + Math.cos(angle) * 128 - Math.sin(angle) * spread,
        y: typeNode.y + Math.sin(angle) * 88 + Math.cos(angle) * spread,
        item,
      }
      nodes.push(memoryNode)
      edges.push({ from: typeNode.id, to: memoryNode.id })
    })
  })
  return { nodes, edges }
}

function GraphNodeShape({ node, active, onSelect }: { node: GraphNode; active: boolean; onSelect: () => void }) {
  const meta = node.item ? getMemoryMeta(node.item.memory_type) : null
  const fill = node.kind === 'self' ? '#0f172a' : node.kind === 'type' ? '#ffffff' : active ? '#eff6ff' : '#ffffff'
  const stroke = node.kind === 'self' ? '#0f172a' : active ? '#2563eb' : '#cbd5e1'
  const width = node.kind === 'memory' ? 132 : node.kind === 'type' ? 76 : 86
  const height = node.kind === 'memory' ? 42 : 40
  return (
    <g
      role={node.item ? 'button' : undefined}
      tabIndex={node.item ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (node.item && (event.key === 'Enter' || event.key === ' ')) onSelect()
      }}
      className={node.item ? 'cursor-pointer outline-none' : undefined}
      filter="url(#memoryShadow)"
    >
      <rect
        x={node.x - width / 2}
        y={node.y - height / 2}
        width={width}
        height={height}
        rx={8}
        fill={fill}
        stroke={stroke}
        strokeWidth={active ? 2 : 1}
      />
      <text
        x={node.x}
        y={node.y + (node.kind === 'memory' ? -2 : 4)}
        textAnchor="middle"
        className={cn('select-none text-[11px] font-semibold', node.kind === 'self' ? 'fill-white' : 'fill-slate-800')}
      >
        {node.kind === 'memory' ? truncate(node.label, 12) : node.label}
      </text>
      {node.kind === 'memory' && node.item ? (
        <text x={node.x} y={node.y + 14} textAnchor="middle" className="select-none fill-slate-400 text-[9px]">
          {meta?.label} · {Math.round(Number(node.item.importance || 0) * 100)}
        </text>
      ) : null}
    </g>
  )
}

function MemoryDetail({ item }: { item: MemoryEntry }) {
  const meta = getMemoryMeta(item.memory_type)
  return (
    <article className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={cn('rounded-md border px-2 py-1 text-[11px]', meta.tone)}>{meta.label}</span>
        <span className="text-[11px] text-slate-400">{formatDate(item.updated_at)}</span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-xs leading-5 text-slate-600">{item.content}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {(item.tags ?? []).map((tag) => (
          <span key={tag} className="rounded-md bg-slate-100 px-2 py-1 text-[10px] text-slate-600">
            #{tag}
          </span>
        ))}
      </div>
    </article>
  )
}

function RelationList({ selected, items }: { selected: MemoryEntry; items: MemoryEntry[] }) {
  const related = items
    .filter((item) => item.id !== selected.id)
    .map((item) => ({
      item,
      score:
        (item.memory_type === selected.memory_type ? 2 : 0) +
        (item.category && item.category === selected.category ? 1 : 0) +
        (item.tags ?? []).filter((tag) => selected.tags?.includes(tag)).length,
    }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 6)

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold text-slate-950">相邻记忆</h3>
      <div className="space-y-2">
        {related.length ? (
          related.map(({ item, score }) => (
            <div key={item.id} className="rounded-lg border border-slate-100 bg-slate-50 p-2">
              <div className="text-xs font-medium text-slate-800">{item.title}</div>
              <div className="mt-1 text-[11px] text-slate-400">关联强度 {score}</div>
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-slate-50 p-3 text-xs text-slate-400">
            暂无可推断的相邻记忆
          </div>
        )}
      </div>
    </section>
  )
}

function GraphEmpty({ text }: { text: string }) {
  return (
    <div className="flex min-h-96 items-center justify-center text-xs text-slate-500">
      {text}
    </div>
  )
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max)}...` : value
}
