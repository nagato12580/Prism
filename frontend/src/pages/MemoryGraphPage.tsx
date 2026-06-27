import { useEffect, useMemo, useState } from 'react'
import { BrainCircuit, Boxes, Loader2, RefreshCw, Search } from 'lucide-react'
import { memoryApi, type MemoryEntityGraph, type MemoryEntityNode, type MemoryStatement } from '@/app/api'
import { cn } from '@/lib/utils'
import { type MemoryView, entryToView, formatDate, getMemoryMeta, groupMemories, memoryTypeMeta, statementToView } from './memoryUtils'

type GraphNode = {
  id: string
  label: string
  kind: 'self' | 'type' | 'memory' | 'entity'
  x: number
  y: number
  item?: MemoryView
  entity?: MemoryEntityNode
}

type GraphEdge = { from: string; to: string; dashed?: boolean }

const ENTITY_TYPE_META: Record<string, { label: string; tone: string }> = {
  project: { label: '项目', tone: 'border-blue-200 bg-blue-50 text-blue-700' },
  technology: { label: '技术', tone: 'border-cyan-200 bg-cyan-50 text-cyan-700' },
  topic: { label: '主题', tone: 'border-violet-200 bg-violet-50 text-violet-700' },
  person: { label: '人物', tone: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  product: { label: '产品', tone: 'border-amber-200 bg-amber-50 text-amber-700' },
}

function entityMeta(type: string) {
  return ENTITY_TYPE_META[type] ?? { label: type || '实体', tone: 'border-slate-200 bg-slate-100 text-slate-600' }
}

export function MemoryGraphPage() {
  const [memories, setMemories] = useState<MemoryView[]>([])
  const [entityGraph, setEntityGraph] = useState<MemoryEntityGraph | null>(null)
  const [mode, setMode] = useState<'entity' | 'type'>('entity')
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

  const typeGraph = useMemo(() => buildTypeGraph(filtered), [filtered])
  const entityGraphData = useMemo(() => buildEntityGraph(entityGraph, filtered), [entityGraph, filtered])
  const graph = mode === 'entity' ? entityGraphData : typeGraph
  const hasEntities = (entityGraph?.entities?.length ?? 0) > 0

  const selected = selectedId ? graph.nodes.find((n) => n.id === selectedId) ?? null : graph.nodes.find((n) => n.kind === 'entity' || n.kind === 'memory') ?? null

  const loadMemories = async () => {
    setLoading(true)
    setError(null)
    try {
      const [entries, statements, entities] = await Promise.all([
        memoryApi.list({ limit: 180 }),
        memoryApi.listStatements({ limit: 200 }).catch(() => [] as MemoryStatement[]),
        memoryApi.listEntities({ limit: 120 }).catch(() => ({ entities: [], relations: [] }) as MemoryEntityGraph),
      ])
      const views = [
        ...entries.map(entryToView),
        ...statements.map(statementToView),
      ].sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0))
      setMemories(views)
      setEntityGraph(entities)
      if (entities.entities?.length) {
        setMode('entity')
      } else {
        setMode('type')
      }
      setSelectedId((current) => (current && views.some((item) => item.id === current) ? current : null))
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
          <div className="flex flex-wrap gap-2">
            <div className="inline-flex rounded-lg border border-[var(--prism-line)] bg-white p-0.5">
              <button
                type="button"
                onClick={() => setMode('entity')}
                disabled={!hasEntities}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition disabled:opacity-40',
                  mode === 'entity' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-50',
                )}
              >
                <Boxes size={13} />
                实体图
              </button>
              <button
                type="button"
                onClick={() => setMode('type')}
                className={cn(
                  'inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition',
                  mode === 'type' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-50',
                )}
              >
                <BrainCircuit size={13} />
                类型图
              </button>
            </div>
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
          ) : graph.nodes.length === 0 ? (
            <GraphEmpty text="暂无实体数据。确认记忆后会自动抽取实体，或切换到「类型图」查看。" />
          ) : (
            <svg viewBox="0 0 1200 720" className="h-full min-h-[36rem] w-full">
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
                    strokeDasharray={edge.dashed ? '4 3' : undefined}
                  />
                )
              })}
              {graph.nodes.map((node) => (
                <GraphNodeShape
                  key={node.id}
                  node={node}
                  active={node.id === selectedId}
                  onSelect={() => setSelectedId(node.id)}
                />
              ))}
            </svg>
          )}
        </div>
      </section>

      <aside className="min-h-0 overflow-hidden rounded-lg border border-[var(--prism-line)] bg-white">
        <div className="border-b border-[var(--prism-line)] p-3">
          <div className="text-xs font-medium text-slate-500">{selected?.kind === 'entity' ? '选中实体' : '选中记忆'}</div>
          <h2 className="mt-1 truncate text-base font-semibold text-slate-950">
            {selected?.kind === 'entity' ? selected.entity?.name : selected?.label ?? '暂无选中'}
          </h2>
        </div>
        <div className="min-h-0 space-y-3 overflow-y-auto p-3">
          {selected?.kind === 'entity' && selected.entity ? (
            <EntityDetail entity={selected.entity} memories={filtered} />
          ) : selected?.item ? (
            <>
              <MemoryDetail item={selected.item} />
              <RelationList selected={selected.item} items={filtered} />
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-slate-50 p-4 text-xs leading-5 text-slate-500">
              选择图谱中的实体或记忆节点后，这里会显示详情和关联。
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

function buildTypeGraph(items: MemoryView[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const groups = groupMemories(items)
  const typeOrder = Object.keys(memoryTypeMeta).filter((type) => groups[type]?.length)
  const centerX = 600
  const centerY = 360
  const nodes: GraphNode[] = [{ id: 'self', label: '用户', kind: 'self', x: centerX, y: centerY }]
  const edges: GraphEdge[] = []
  const typeRadius = 230
  // 记忆网格块：每类在类型节点外侧排成 2 列网格，间距大于节点尺寸避免重叠
  const cols = 2
  const colGap = 146
  const rowGap = 52
  const startOffset = 120
  const maxPerType = 10
  typeOrder.forEach((type, index) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / Math.max(typeOrder.length, 1)
    const dirX = Math.cos(angle)
    const dirY = Math.sin(angle)
    const perpX = -dirY
    const perpY = dirX
    const typeNode = {
      id: `type:${type}`,
      label: getMemoryMeta(type).label,
      kind: 'type' as const,
      x: centerX + dirX * typeRadius,
      y: centerY + dirY * typeRadius,
    }
    nodes.push(typeNode)
    edges.push({ from: 'self', to: typeNode.id })
    const groupItems = groups[type].slice(0, maxPerType)
    groupItems.forEach((item, itemIndex) => {
      const row = Math.floor(itemIndex / cols)
      const col = itemIndex % cols
      const rowCount = Math.ceil(groupItems.length / cols)
      const radialDist = startOffset + col * colGap
      const perpSpread = (row - (rowCount - 1) / 2) * rowGap
      const memoryNode = {
        id: item.id,
        label: item.title,
        kind: 'memory' as const,
        x: typeNode.x + dirX * radialDist + perpX * perpSpread,
        y: typeNode.y + dirY * radialDist + perpY * perpSpread,
        item,
      }
      nodes.push(memoryNode)
      edges.push({ from: typeNode.id, to: memoryNode.id })
    })
  })
  return { nodes, edges }
}

function buildEntityGraph(eg: MemoryEntityGraph | null, memories: MemoryView[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (!eg || !eg.entities?.length) {
    return { nodes: [], edges: [] }
  }
  const centerX = 600
  const centerY = 360
  const radius = 200
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []
  const entityById = new Map(eg.entities.map((e) => [e.id, e]))
  const memoryById = new Map(memories.map((m) => [m.id, m]))

  // 实体节点：环形分布，按 mention_count 降序取前 14 个
  const topEntities = [...eg.entities].sort((a, b) => (b.mention_count ?? 0) - (a.mention_count ?? 0)).slice(0, 14)
  topEntities.forEach((entity, index) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / topEntities.length
    nodes.push({
      id: entity.id,
      label: entity.name,
      kind: 'entity',
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
      entity,
    })
  })

  // 实体间关系边
  eg.relations.forEach((rel) => {
    if (entityById.has(rel.subject_entity_id) && entityById.has(rel.object_entity_id)) {
      edges.push({ from: rel.subject_entity_id, to: rel.object_entity_id })
    }
  })

  // 实体关联的记忆节点：挂在实体外侧 2 列网格。同一记忆被多实体引用时只渲染一次，挂在第一个引用它的实体上。
  const seenMemoryIds = new Set<string>()
  const cols = 2
  const colGap = 146
  const rowGap = 48
  const startOffset = 90
  const maxPerEntity = 4
  topEntities.forEach((entity, index) => {
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / topEntities.length
    const dirX = Math.cos(angle)
    const dirY = Math.sin(angle)
    const perpX = -dirY
    const perpY = dirX
    const ex = centerX + dirX * radius
    const ey = centerY + dirY * radius
    const linkedMemories = (entity.source_ids ?? [])
      .map((sid) => memoryById.get(sid))
      .filter((m): m is MemoryView => Boolean(m))
      .filter((m) => !seenMemoryIds.has(m.id))
      .slice(0, maxPerEntity)
    linkedMemories.forEach((item) => { seenMemoryIds.add(item.id) })
    linkedMemories.forEach((item, itemIndex) => {
      const row = Math.floor(itemIndex / cols)
      const col = itemIndex % cols
      const rowCount = Math.ceil(linkedMemories.length / cols)
      const radialDist = startOffset + col * colGap
      const perpSpread = (row - (rowCount - 1) / 2) * rowGap
      nodes.push({
        id: `mem:${item.id}`,
        label: item.title,
        kind: 'memory',
        x: ex + dirX * radialDist + perpX * perpSpread,
        y: ey + dirY * radialDist + perpY * perpSpread,
        item,
      })
      edges.push({ from: entity.id, to: `mem:${item.id}`, dashed: true })
    })
  })
  return { nodes, edges }
}

function GraphNodeShape({ node, active, onSelect }: { node: GraphNode; active: boolean; onSelect: () => void }) {
  const memMeta = node.item ? getMemoryMeta(node.item.memory_type) : null
  const entMeta = node.entity ? entityMeta(node.entity.entity_type) : null
  const fill = node.kind === 'self' ? '#0f172a' : active ? '#eff6ff' : '#ffffff'
  const stroke = node.kind === 'self' ? '#0f172a' : active ? '#2563eb' : node.kind === 'entity' ? '#94a3b8' : '#cbd5e1'
  const width = node.kind === 'memory' ? 132 : node.kind === 'type' ? 76 : 96
  const height = node.kind === 'memory' ? 42 : 40
  const selectable = node.kind === 'memory' || node.kind === 'entity'
  return (
    <g
      role={selectable ? 'button' : undefined}
      tabIndex={selectable ? 0 : undefined}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (selectable && (event.key === 'Enter' || event.key === ' ')) onSelect()
      }}
      className={selectable ? 'cursor-pointer outline-none' : undefined}
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
          {memMeta?.label} · {Math.round(Number(node.item.importance || 0) * 100)}
        </text>
      ) : null}
      {node.kind === 'entity' && node.entity ? (
        <text x={node.x} y={node.y + 14} textAnchor="middle" className="select-none fill-slate-400 text-[9px]">
          {entMeta?.label} · {node.entity.mention_count ?? 1}
        </text>
      ) : null}
    </g>
  )
}

function EntityDetail({ entity, memories }: { entity: MemoryEntityNode; memories: MemoryView[] }) {
  const meta = entityMeta(entity.entity_type)
  const linked = (entity.source_ids ?? [])
    .map((sid) => memories.find((m) => m.id === sid))
    .filter((m): m is MemoryView => Boolean(m))
  return (
    <div className="space-y-3">
      <article className="rounded-lg border border-[var(--prism-line)] bg-white p-3">
        <div className="flex items-center justify-between gap-2">
          <span className={cn('rounded-md border px-2 py-1 text-[11px]', meta.tone)}>{meta.label}</span>
          <span className="text-[11px] text-slate-400">提及 {entity.mention_count ?? 1} 次</span>
        </div>
        {entity.description ? (
          <p className="mt-3 whitespace-pre-wrap text-xs leading-5 text-slate-600">{entity.description}</p>
        ) : null}
      </article>
      <section>
        <h3 className="mb-2 text-xs font-semibold text-slate-950">关联记忆（{linked.length}）</h3>
        <div className="space-y-2">
          {linked.length ? (
            linked.map((item) => (
              <div key={item.id} className="rounded-lg border border-slate-100 bg-slate-50 p-2">
                <div className="text-xs font-medium text-slate-800">{item.title}</div>
                <div className="mt-1 line-clamp-2 text-[11px] text-slate-400">{item.content}</div>
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-dashed border-[var(--prism-line)] bg-slate-50 p-3 text-xs text-slate-400">
              暂无关联记忆
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function MemoryDetail({ item }: { item: MemoryView }) {
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

function RelationList({ selected, items }: { selected: MemoryView; items: MemoryView[] }) {
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
