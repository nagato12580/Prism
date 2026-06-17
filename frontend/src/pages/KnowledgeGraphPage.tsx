import { useEffect, useMemo, useState } from 'react'
import {
  BookOpen,
  Boxes,
  FileText,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react'
import {
  knowledgeGraphApi,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeType,
  type KnowledgeGraphPayload,
} from '@/app/api'
import { cn } from '@/lib/utils'

type PositionedNode = KnowledgeGraphNode & { x: number; y: number }

const nodeMeta: Record<KnowledgeGraphNodeType, { label: string; color: string; fill: string; icon: typeof Network }> = {
  canonical: { label: 'CKP', color: '#155eef', fill: '#eff6ff', icon: Sparkles },
  pku: { label: 'PKU', color: '#7c3aed', fill: '#f5f3ff', icon: Boxes },
  asset: { label: '碎片', color: '#d97706', fill: '#fffbeb', icon: BookOpen },
  document_chunk: { label: '文档', color: '#0f766e', fill: '#ecfdf5', icon: FileText },
}

const graphWidth = 1120
const graphHeight = 680

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function truncate(value: string | null | undefined, max = 34) {
  const text = (value || '').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max)}...`
}

function layoutNodes(nodes: KnowledgeGraphNode[]): PositionedNode[] {
  const columns: KnowledgeGraphNodeType[] = ['canonical', 'pku', 'asset', 'document_chunk']
  const xByType: Record<KnowledgeGraphNodeType, number> = {
    canonical: 150,
    pku: 480,
    asset: 840,
    document_chunk: 840,
  }
  const grouped = columns.reduce(
    (acc, type) => {
      acc[type] = nodes.filter((node) => node.type === type)
      return acc
    },
    {} as Record<KnowledgeGraphNodeType, KnowledgeGraphNode[]>,
  )

  return columns.flatMap((type) => {
    const list = grouped[type]
    const available = graphHeight - 140
    const gap = list.length > 1 ? Math.min(96, available / (list.length - 1)) : 0
    const start = list.length > 1 ? (graphHeight - gap * (list.length - 1)) / 2 : graphHeight / 2
    return list.map((node, index) => {
      const offset = type === 'document_chunk' ? 42 : type === 'asset' ? -42 : 0
      return {
        ...node,
        x: xByType[type],
        y: start + index * gap + offset,
      }
    })
  })
}

export function KnowledgeGraphPage() {
  const [payload, setPayload] = useState<KnowledgeGraphPayload | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const nodes = useMemo(() => layoutNodes(payload?.nodes ?? []), [payload])
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])
  const selected = selectedId ? nodeById.get(selectedId) ?? null : nodes[0] ?? null
  const selectedEdges = useMemo(
    () => (payload?.edges ?? []).filter((edge) => edge.source === selected?.id || edge.target === selected?.id),
    [payload?.edges, selected?.id],
  )

  const loadGraph = async (nextQuery = query) => {
    setLoading(true)
    setError(null)
    try {
      const data = await knowledgeGraphApi.get({ q: nextQuery.trim() || undefined, limit: 40 })
      setPayload(data)
      setSelectedId((current) => {
        if (current && data.nodes.some((node) => node.id === current)) return current
        return data.nodes[0]?.id ?? null
      })
    } catch (err) {
      setError(`加载知识图谱失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadGraph('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col gap-4">
      <header className="flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <Network size={15} />
            <span>知识治理图谱</span>
          </div>
          <h1 className="mt-1 text-xl font-semibold text-slate-950">CKP、PKU 与来源证据</h1>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 sm:w-80">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') loadGraph()
              }}
              placeholder="搜索知识点、PKU 或来源"
              className="h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-9 pr-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
            />
          </div>
          <button
            type="button"
            onClick={() => loadGraph()}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            刷新
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
          {error}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="prism-panel min-h-[34rem] overflow-hidden rounded-lg">
          <div className="grid grid-cols-2 gap-px border-b border-[var(--prism-line)] bg-[var(--prism-line)] md:grid-cols-4">
            {(['canonical', 'pku', 'asset', 'document_chunk'] as KnowledgeGraphNodeType[]).map((type) => {
              const meta = nodeMeta[type]
              const Icon = meta.icon
              return (
                <div key={type} className="flex items-center gap-2 bg-white px-4 py-3">
                  <Icon size={16} style={{ color: meta.color }} />
                  <span className="text-xs font-medium text-slate-500">{meta.label}</span>
                  <span className="ml-auto text-sm font-semibold text-slate-950">
                    {payload?.stats.node_counts[type] ?? 0}
                  </span>
                </div>
              )
            })}
          </div>

          <div className="h-[calc(100%-3.1rem)] overflow-auto bg-[#f8fafc]">
            {loading && !payload ? (
              <div className="flex h-full min-h-[32rem] items-center justify-center text-sm text-slate-500">
                <Loader2 size={18} className="mr-2 animate-spin" />
                正在加载图谱
              </div>
            ) : nodes.length === 0 ? (
              <div className="flex h-full min-h-[32rem] items-center justify-center px-6 text-center text-sm leading-6 text-slate-500">
                暂无可展示的治理图谱。确认碎片或向量化文档后会生成 PKU 和 CKP。
              </div>
            ) : (
              <svg
                viewBox={`0 0 ${graphWidth} ${graphHeight}`}
                className="min-h-[38rem] w-[70rem] max-w-none"
                role="img"
                aria-label="知识治理图谱"
              >
                <defs>
                  <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                    <path d="M0,0 L7,3 L0,6 Z" fill="#94a3b8" />
                  </marker>
                </defs>
                <g>
                  {(payload?.edges ?? []).map((edge) => {
                    const source = nodeById.get(edge.source)
                    const target = nodeById.get(edge.target)
                    if (!source || !target) return null
                    const active = selected?.id === edge.source || selected?.id === edge.target
                    return (
                      <line
                        key={edge.id}
                        x1={source.x + 92}
                        y1={source.y}
                        x2={target.x - 92}
                        y2={target.y}
                        stroke={active ? '#155eef' : '#cbd5e1'}
                        strokeWidth={active ? 2.4 : 1.4}
                        markerEnd="url(#graph-arrow)"
                      />
                    )
                  })}
                </g>
                <g>
                  {nodes.map((node) => (
                    <GraphNode
                      key={node.id}
                      node={node}
                      active={selected?.id === node.id}
                      onSelect={() => setSelectedId(node.id)}
                    />
                  ))}
                </g>
              </svg>
            )}
          </div>
        </section>

        <GraphInspector node={selected} edges={selectedEdges} nodes={nodeById} />
      </div>
    </div>
  )
}

function GraphNode({
  node,
  active,
  onSelect,
}: {
  node: PositionedNode
  active: boolean
  onSelect: () => void
}) {
  const meta = nodeMeta[node.type]
  return (
    <g transform={`translate(${node.x - 88}, ${node.y - 28})`} onClick={onSelect} className="cursor-pointer">
      <rect
        width="176"
        height="56"
        rx="8"
        fill={active ? '#ffffff' : meta.fill}
        stroke={active ? meta.color : '#d7dee9'}
        strokeWidth={active ? 2.5 : 1}
      />
      <circle cx="20" cy="28" r="8" fill={meta.color} opacity={active ? 1 : 0.82} />
      <text x="36" y="23" className="fill-slate-950 text-[12px] font-semibold">
        {truncate(node.label, 18)}
      </text>
      <text x="36" y="40" className="fill-slate-500 text-[10px]">
        {meta.label}
        {node.modality ? ` · ${node.modality}` : ''}
      </text>
    </g>
  )
}

function GraphInspector({
  node,
  edges,
  nodes,
}: {
  node: PositionedNode | null
  edges: KnowledgeGraphEdge[]
  nodes: Map<string, PositionedNode>
}) {
  if (!node) {
    return (
      <aside className="prism-panel flex min-h-[24rem] items-center justify-center rounded-lg p-5 text-center text-sm text-slate-500">
        选择一个节点查看证据关系
      </aside>
    )
  }
  const meta = nodeMeta[node.type]
  return (
    <aside className="prism-panel flex min-h-0 flex-col rounded-lg p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className="mt-1 h-3 w-3 rounded-full" style={{ background: meta.color }} />
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-500">{meta.label}</div>
          <h2 className="mt-1 break-words text-base font-semibold leading-6 text-slate-950">{node.label}</h2>
        </div>
      </div>

      <div className="space-y-3 overflow-y-auto pr-1">
        <DetailBlock label="内容" value={node.statement || node.summary || node.text || ''} />
        <div className="grid grid-cols-2 gap-2">
          <MiniStat label="类型" value={node.canonical_type || node.unit_type || node.source_kind || node.type} />
          <MiniStat label="置信度" value={typeof node.confidence === 'number' ? node.confidence.toFixed(2) : '-'} />
        </div>
        {node.tags?.length ? <ChipBlock label="标签" values={node.tags} /> : null}
        {node.keywords?.length ? <ChipBlock label="关键词" values={node.keywords.slice(0, 10)} /> : null}

        <div className="border-t border-[var(--prism-line)] pt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-950">连接关系</h3>
          {edges.length === 0 ? (
            <p className="text-sm leading-6 text-slate-500">暂无连接</p>
          ) : (
            <div className="space-y-2">
              {edges.map((edge) => {
                const otherId = edge.source === node.id ? edge.target : edge.source
                const other = nodes.get(otherId)
                return (
                  <div key={edge.id} className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
                    <div className="text-xs font-medium text-slate-500">{edge.label}</div>
                    <div className="mt-1 text-sm font-semibold text-slate-900">{other?.label ?? otherId}</div>
                    {edge.role ? <div className="mt-1 text-xs text-slate-500">{edge.role}</div> : null}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

function DetailBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{label}</div>
      <p className="rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
        {value || '无'}
      </p>
    </div>
  )
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{value || '-'}</div>
    </div>
  )
}

function ChipBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span key={value} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
            {value}
          </span>
        ))}
      </div>
    </div>
  )
}
