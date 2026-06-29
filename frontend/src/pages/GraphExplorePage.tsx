import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import {
  Boxes,
  FileText,
  Loader2,
  Network,
  RefreshCw,
  Search,
  Sparkles,
  Tag,
  Users,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import {
  graphExploreApi,
  type GraphExploreNode,
  type GraphExploreLink,
  type GraphExplorePayload,
  type GraphNodeDetail,
} from '@/app/graphExploreApi'
import { cn } from '@/lib/utils'

const NODE_TYPE_META: Record<string, { label: string; color: string; icon: typeof Network }> = {
  CKP: { label: 'CKP', color: '#155eef', icon: Sparkles },
  PKU: { label: 'PKU', color: '#6d28d9', icon: Boxes },
  Source: { label: '来源', color: '#0f766e', icon: FileText },
  Entity: { label: '实体', color: '#b45309', icon: Users },
  Alias: { label: '别名', color: '#be185d', icon: Tag },
  TopicGroup: { label: '主题组', color: '#0891b2', icon: Network },
}

const FALLBACK_META = { label: '节点', color: '#64748b', icon: Network }

function nodeMeta(type: string) {
  return NODE_TYPE_META[type] ?? FALLBACK_META
}

const REL_DASHED: Record<string, boolean> = {
  EVIDENCED_BY: true,
  MENTIONED_IN: true,
  ALIAS_OF: false,
  SUPPORTED_BY: false,
  HAS_CHILD: false,
  RELATED_TO: true,
  AUTHORED: false,
  CO_AUTHOR: false,
  AFFILIATED_WITH: false,
  CONTAINS: false,
}

type GraphData = {
  nodes: { id: string; label: string; type: string; properties: Record<string, unknown> }[]
  links: { source: string; target: string; type: string }[]
}

export function GraphExplorePage() {
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [activeTypes, setActiveTypes] = useState<Set<string>>(
    new Set(['CKP', 'PKU', 'Source', 'Entity', 'Alias']),
  )
  const [selectedNode, setSelectedNode] = useState<GraphExploreNode | null>(null)
  const [nodeDetail, setNodeDetail] = useState<GraphNodeDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [limit, setLimit] = useState(50)

  const fgRef = useRef<any>(null)

  const loadGraph = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const types = [...activeTypes].join(',')
      const params: { types: string; limit: number; q?: string } = { types, limit }
      if (query.trim()) params.q = query.trim()
      const payload: GraphExplorePayload = await graphExploreApi.explore(params)
      const graphData: GraphData = {
        nodes: payload.nodes.map((n) => ({
          id: n.id,
          label: n.label,
          type: n.type,
          properties: n.properties,
        })),
        links: payload.links.map((l) => ({
          source: l.source,
          target: l.target,
          type: l.type,
        })),
      }
      setData(graphData)
    } catch (err) {
      setError(`加载图谱失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setLoading(false)
    }
  }, [activeTypes, limit, query])

  useEffect(() => {
    loadGraph()
  }, [loadGraph])

  const handleNodeClick = useCallback(async (node: GraphExploreNode) => {
    setSelectedNode(node)
    setDetailLoading(true)
    setNodeDetail(null)
    try {
      const detail = await graphExploreApi.nodeDetail(node.id)
      setNodeDetail(detail)
    } catch {
      setNodeDetail({ node, neighbors: [], links: [] })
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const handleNodeDblClick = useCallback(
    async (node: GraphExploreNode) => {
      try {
        const expanded = await graphExploreApi.expand(node.id, 2)
        const newNodes = expanded.nodes.filter((n) => !data.nodes.some((existing) => existing.id === n.id))
        const newLinks = expanded.links.filter(
          (l) => !data.links.some((existing) => existing.source === l.source && existing.target === l.target),
        )
        setData((current) => ({
          nodes: [...current.nodes, ...newNodes.map((n) => ({ id: n.id, label: n.label, type: n.type, properties: n.properties }))],
          links: [...current.links, ...newLinks.map((l) => ({ source: l.source, target: l.target, type: l.type }))],
        }))
      } catch {
        // ignore expand errors
      }
    },
    [data],
  )

  const toggleType = (type: string) => {
    setActiveTypes((current) => {
      const next = new Set(current)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const zoomIn = () => fgRef.current?.zoom(1.3)
  const zoomOut = () => fgRef.current?.zoom(0.77)
  const fitGraph = () => fgRef.current?.zoomToFit(200, 60)

  const filteredData = useMemo(() => {
    const nodes = data.nodes.filter((n) => activeTypes.has(n.type))
    const nodeIds = new Set(nodes.map((n) => n.id))
    const links = data.links.filter((l) => nodeIds.has(l.source) && nodeIds.has(l.target))
    return { nodes, links }
  }, [data, activeTypes])

  const nodeCanvasObject = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const meta = nodeMeta(node.type)
    const label = node.label
    const fontSize = 12 / globalScale
    ctx.font = `${fontSize}px sans-serif`
    const textWidth = ctx.measureText(label).width
    const radius = Math.max(5, Math.min(10, textWidth / 2 + 4))

    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI)
    ctx.fillStyle = node.id === selectedNode?.id ? '#ffffff' : meta.color
    ctx.fill()
    ctx.strokeStyle = node.id === selectedNode?.id ? meta.color : '#ffffff'
    ctx.lineWidth = 1.5 / globalScale
    ctx.stroke()

    if (globalScale >= 0.8) {
      ctx.fillStyle = '#334155'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      const truncated = label.length > 16 ? `${label.slice(0, 16)}…` : label
      ctx.fillText(truncated, node.x, node.y + radius + fontSize / 2 + 2)
    }
  }, [selectedNode])

  const linkCanvasObject = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isDashed = REL_DASHED[link.type] ?? false
    const source = link.source as { x: number; y: number }
    const target = link.target as { x: number; y: number }
    if (!source || !target || source.x == null || target.x == null) return

    ctx.beginPath()
    ctx.moveTo(source.x, source.y)
    ctx.lineTo(target.x, target.y)
    ctx.strokeStyle = '#94a3b8'
    ctx.lineWidth = 1 / globalScale
    if (isDashed) ctx.setLineDash([4 / globalScale, 3 / globalScale])
    else ctx.setLineDash([])
    ctx.stroke()
    ctx.setLineDash([])
  }, [])

  return (
    <div className="flex h-full min-h-0 gap-4 p-4 lg:p-6">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-950">图谱探索</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              直接从 Neo4j 查询节点与关系，力导向布局自动排列
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadGraph}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--prism-line)] px-3 py-1.5 text-sm text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
            >
              <RefreshCw size={14} className={cn(loading && 'animate-spin')} />
              刷新
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-[var(--prism-line)] px-2.5 py-1.5">
            <Search size={14} className="text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadGraph()}
              placeholder="搜索节点标签…"
              className="w-40 bg-transparent text-sm text-slate-700 outline-none placeholder:text-slate-400"
            />
            {query && (
              <button onClick={() => { setQuery(''); }} className="text-slate-400 hover:text-slate-600">
                <X size={14} />
              </button>
            )}
          </div>

          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-lg border border-[var(--prism-line)] px-2.5 py-1.5 text-sm text-slate-600"
          >
            <option value={30}>30 节点</option>
            <option value={50}>50 节点</option>
            <option value={100}>100 节点</option>
            <option value={200}>200 节点</option>
          </select>

          <div className="flex flex-wrap items-center gap-1.5">
            {Object.entries(NODE_TYPE_META).map(([type, meta]) => (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition',
                  activeTypes.has(type)
                    ? 'border-transparent text-white'
                    : 'border-[var(--prism-line)] text-slate-500 hover:bg-slate-50',
                )}
                style={activeTypes.has(type) ? { backgroundColor: meta.color } : undefined}
              >
                <meta.icon size={12} />
                {meta.label}
              </button>
            ))}
          </div>
        </div>

        <div className="relative flex min-h-0 flex-1 overflow-hidden rounded-lg border border-[var(--prism-line)] bg-white">
          {loading && data.nodes.length === 0 ? (
            <div className="flex h-full w-full items-center justify-center text-sm text-slate-500">
              <Loader2 size={18} className="mr-2 animate-spin" />
              正在从 Neo4j 加载图谱…
            </div>
          ) : error ? (
            <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-red-500">
              {error}
            </div>
          ) : filteredData.nodes.length === 0 ? (
            <div className="flex h-full w-full items-center justify-center px-6 text-center text-sm text-slate-500">
              没有匹配的节点。尝试切换节点类型过滤器或调整搜索关键词。
            </div>
          ) : (
            <ForceGraph2D
              {...({ ref: fgRef, graphData: filteredData } as any)}
              nodeCanvasObject={nodeCanvasObject}
              linkCanvasObject={linkCanvasObject}
              onNodeClick={handleNodeClick}
              onNodeDblClick={handleNodeDblClick}
              nodeRelSize={6}
              cooldownTicks={120}
              width={800}
              height={600}
              backgroundColor="#fafafa"
            />
          )}

          {!loading && !error && filteredData.nodes.length > 0 && (
            <div className="absolute bottom-3 left-3 flex items-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white/90 px-2 py-1 shadow-sm backdrop-blur">
              <button onClick={zoomOut} className="rounded p-1 text-slate-500 hover:bg-slate-100" title="缩小">
                <ZoomOut size={16} />
              </button>
              <button onClick={fitGraph} className="rounded p-1 text-slate-500 hover:bg-slate-100" title="适应">
                <Network size={16} />
              </button>
              <button onClick={zoomIn} className="rounded p-1 text-slate-500 hover:bg-slate-100" title="放大">
                <ZoomIn size={16} />
              </button>
            </div>
          )}

          {!loading && !error && filteredData.nodes.length > 0 && (
            <div className="absolute bottom-3 right-3 rounded-lg border border-[var(--prism-line)] bg-white/90 px-3 py-1.5 text-xs text-slate-500 shadow-sm backdrop-blur">
              {filteredData.nodes.length} 节点 · {filteredData.links.length} 关系
            </div>
          )}
        </div>
      </div>

      {selectedNode && (
        <NodeDetailPanel
          node={selectedNode}
          detail={nodeDetail}
          loading={detailLoading}
          onClose={() => { setSelectedNode(null); setNodeDetail(null) }}
        />
      )}
    </div>
  )
}

function NodeDetailPanel({
  node,
  detail,
  loading,
  onClose,
}: {
  node: GraphExploreNode
  detail: GraphNodeDetail | null
  loading: boolean
  onClose: () => void
}) {
  const meta = nodeMeta(node.type)
  const props = node.properties
  const neighborLinks = detail?.links ?? []

  return (
    <aside className="flex w-[340px] shrink-0 flex-col overflow-hidden rounded-lg border border-[var(--prism-line)] bg-white">
      <div className="flex items-center justify-between border-b border-[var(--prism-line)] px-4 py-3">
        <div className="flex items-center gap-2">
          <meta.icon size={16} style={{ color: meta.color }} />
          <span className="text-xs font-medium text-slate-500">{meta.label}</span>
        </div>
        <button onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100">
          <X size={16} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <h2 className="text-sm font-semibold text-slate-950">{node.label}</h2>

        <div className="mt-3 space-y-2">
          {Object.entries(props)
            .filter(([key]) => !['_labels', 'id'].includes(key))
            .slice(0, 12)
            .map(([key, value]) => (
              <div key={key} className="flex gap-2 text-xs">
                <span className="shrink-0 text-slate-400">{key}</span>
                <span className="min-w-0 break-words text-slate-700">
                  {typeof value === 'string'
                    ? value.length > 120
                      ? `${value.slice(0, 120)}…`
                      : value
                    : value == null
                      ? '-'
                      : String(value)}
                </span>
              </div>
            ))}
        </div>

        <div className="mt-5">
          <div className="mb-2 text-xs font-medium text-slate-500">
            邻居节点（{detail?.neighbors.length ?? 0}）
          </div>
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Loader2 size={14} className="animate-spin" />
              加载中…
            </div>
          ) : detail && detail.neighbors.length > 0 ? (
            <div className="space-y-1.5">
              {detail.neighbors.slice(0, 20).map((neighbor) => {
                const nMeta = nodeMeta(neighbor.type)
                const link = neighborLinks.find(
                  (l) =>
                    (l.source === node.id && l.target === neighbor.id) ||
                    (l.target === node.id && l.source === neighbor.id),
                )
                return (
                  <div key={neighbor.id} className="flex items-center gap-2 rounded-lg border border-[var(--prism-line)] px-2.5 py-1.5">
                    <nMeta.icon size={12} style={{ color: nMeta.color }} />
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-700">{neighbor.label}</span>
                    {link && (
                      <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                        {link.type}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-xs text-slate-400">无邻居节点</div>
          )}
        </div>
      </div>
    </aside>
  )
}
