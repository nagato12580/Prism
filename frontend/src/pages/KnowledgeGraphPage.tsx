import { PointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Boxes,
  Check,
  FileText,
  Loader2,
  Network,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import {
  knowledgeGraphApi,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeType,
  type KnowledgeGraphNodeUpdate,
  type KnowledgeGraphPayload,
} from '@/app/api'
import { KnowledgeGraphWorkbench } from '@/pages/KnowledgeGraphWorkbench'
import { cn } from '@/lib/utils'

type PositionedNode = KnowledgeGraphNode & { x: number; y: number }
type PositionMap = Record<string, { x: number; y: number }>
type DragState = { id: string; dx: number; dy: number; moved: boolean } | null

const graphWidth = 1180
const graphHeight = 720
const nodeWidth = 150
const nodeHeight = 42
const nodeRadius = 21

const nodeMeta: Record<
  KnowledgeGraphNodeType,
  { label: string; color: string; fill: string; icon: typeof Network; lane: string }
> = {
  canonical: { label: 'CKP', color: '#155eef', fill: '#eff6ff', icon: Sparkles, lane: '稳定知识点' },
  pku: { label: 'PKU', color: '#6d28d9', fill: '#f5f3ff', icon: Boxes, lane: '原子表达' },
  asset: { label: '碎片', color: '#b45309', fill: '#fffbeb', icon: BookOpen, lane: '个人碎片' },
  personal_asset_unit: { label: '资产单元', color: '#be185d', fill: '#fdf2f8', icon: Boxes, lane: '知识草稿' },
  document_chunk: { label: '文档', color: '#0f766e', fill: '#ecfdf5', icon: FileText, lane: '文档片段' },
}

const fallbackNodeMeta = { label: '节点', color: '#475569', fill: '#f8fafc', icon: Network, lane: '其他节点' }
const graphNodeTypes: KnowledgeGraphNodeType[] = ['canonical', 'pku', 'asset', 'personal_asset_unit', 'document_chunk']

function getNodeMeta(type: string) {
  return nodeMeta[type as KnowledgeGraphNodeType] ?? fallbackNodeMeta
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function truncate(value: string | null | undefined, max = 16) {
  const text = (value || '').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max)}...`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function splitList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function joinList(values?: string[]) {
  return (values ?? []).join(', ')
}

function createInitialPositions(nodes: KnowledgeGraphNode[]): PositionMap {
  const laneX: Record<KnowledgeGraphNodeType, number> = {
    canonical: 150,
    pku: 470,
    asset: 760,
    personal_asset_unit: 930,
    document_chunk: 1020,
  }
  const laneOrder = graphNodeTypes
  const grouped = laneOrder.reduce(
    (acc, type) => {
      acc[type] = nodes.filter((node) => node.type === type)
      return acc
    },
    {} as Record<KnowledgeGraphNodeType, KnowledgeGraphNode[]>,
  )

  const positions: PositionMap = {}
  laneOrder.forEach((type) => {
    const list = grouped[type]
    if (!list.length) return
    const gap = Math.max(76, Math.min(126, (graphHeight - 160) / Math.max(1, list.length - 1)))
    const start = list.length === 1 ? graphHeight / 2 : (graphHeight - gap * (list.length - 1)) / 2
    list.forEach((node, index) => {
      const stagger = type === 'asset' || type === 'document_chunk' ? (index % 2 === 0 ? -18 : 18) : 0
      positions[node.id] = {
        x: laneX[type],
        y: clamp(start + index * gap + stagger, 72, graphHeight - 72),
      }
    })
  })
  return positions
}

function mergePositions(nodes: KnowledgeGraphNode[], current: PositionMap): PositionMap {
  const initial = createInitialPositions(nodes)
  return nodes.reduce((acc, node) => {
    acc[node.id] = current[node.id] ?? initial[node.id]
    return acc
  }, {} as PositionMap)
}

function contentForNode(node: KnowledgeGraphNode) {
  return node.statement || node.text || node.summary || ''
}

function secondaryType(node: KnowledgeGraphNode) {
  return node.canonical_type || node.unit_type || node.asset_kind || node.media_type || node.source_kind || node.type
}

function edgeStyle(edge: KnowledgeGraphEdge, active: boolean) {
  if (edge.type === 'pku_relation') {
    return {
      stroke: active ? '#be185d' : '#f472b6',
      strokeWidth: active ? 2.4 : 1.6,
      strokeDasharray: '6 5',
    }
  }
  if (edge.type === 'pku_source') {
    return {
      stroke: active ? '#0f766e' : '#99f6e4',
      strokeWidth: active ? 2 : 1.25,
      strokeDasharray: '3 5',
    }
  }
  return {
    stroke: active ? '#155eef' : '#cbd5e1',
    strokeWidth: active ? 2.2 : 1.35,
    strokeDasharray: undefined,
  }
}

function svgPoint(svg: SVGSVGElement, event: PointerEvent<SVGSVGElement>) {
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  return point.matrixTransform(svg.getScreenCTM()?.inverse())
}

export function KnowledgeGraphPage() {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [payload, setPayload] = useState<KnowledgeGraphPayload | null>(null)
  const [positions, setPositions] = useState<PositionMap>({})
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [dragging, setDragging] = useState<DragState>(null)
  const [viewMode, setViewMode] = useState<'workbench' | 'network'>('workbench')

  const nodes = useMemo<PositionedNode[]>(
    () =>
      (payload?.nodes ?? []).map((node) => ({
        ...node,
        ...(positions[node.id] ?? { x: graphWidth / 2, y: graphHeight / 2 }),
      })),
    [payload?.nodes, positions],
  )
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
      const data = await knowledgeGraphApi.get({ q: nextQuery.trim() || undefined, limit: 48 })
      setPayload(data)
      setPositions((current) => mergePositions(data.nodes, current))
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

  const resetLayout = () => {
    setPositions(createInitialPositions(payload?.nodes ?? []))
  }

  const updateNode = async (nodeId: string, data: KnowledgeGraphNodeUpdate) => {
    setSaving(true)
    setError(null)
    try {
      const updated = await knowledgeGraphApi.updateNode(nodeId, data)
      setPayload((current) =>
        current
          ? {
              ...current,
              nodes: current.nodes.map((node) => (node.id === updated.id ? { ...node, ...updated } : node)),
            }
          : current,
      )
      setSelectedId(updated.id)
      return updated
    } catch (err) {
      setError(`保存节点失败：${getErrorMessage(err)}`)
      throw err
    } finally {
      setSaving(false)
    }
  }

  const handlePointerDown = (event: PointerEvent<SVGGElement>, node: PositionedNode) => {
    const svg = svgRef.current
    if (!svg) return
    const point = svgPoint(svg, event as unknown as PointerEvent<SVGSVGElement>)
    setDragging({ id: node.id, dx: point.x - node.x, dy: point.y - node.y, moved: false })
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragging || !svgRef.current) return
    const point = svgPoint(svgRef.current, event)
    const x = clamp(point.x - dragging.dx, nodeWidth / 2 + 16, graphWidth - nodeWidth / 2 - 16)
    const y = clamp(point.y - dragging.dy, nodeHeight / 2 + 16, graphHeight - nodeHeight / 2 - 16)
    setPositions((current) => ({ ...current, [dragging.id]: { x, y } }))
    setDragging((current) => (current ? { ...current, moved: true } : current))
  }

  const stopDragging = () => setDragging(null)

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
        {viewMode === 'network' ? (
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
            onClick={resetLayout}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <RotateCcw size={15} />
            重排
          </button>
          <button
            type="button"
            onClick={() => loadGraph()}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            刷新
          </button>
        </div>
        ) : null}
      </header>

      <div className="inline-flex w-fit rounded-lg border border-[var(--prism-line)] bg-white p-1">
        <button
          type="button"
          onClick={() => setViewMode('workbench')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium',
            viewMode === 'workbench' ? 'bg-slate-950 text-white' : 'text-slate-600',
          )}
        >
          CKP Workbench
        </button>
        <button
          type="button"
          onClick={() => setViewMode('network')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm font-medium',
            viewMode === 'network' ? 'bg-slate-950 text-white' : 'text-slate-600',
          )}
        >
          全局网络
        </button>
      </div>

      {viewMode === 'network' && error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
          {error}
        </div>
      ) : null}

      <div className={viewMode === 'workbench' ? 'block' : 'hidden'}>
        <KnowledgeGraphWorkbench onSaveNode={updateNode} />
      </div>
      <div className={cn(
        'min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]',
        viewMode === 'network' ? 'grid' : 'hidden',
      )}>
        <section className="prism-panel min-h-[35rem] overflow-hidden rounded-lg">
          <div className="grid grid-cols-2 gap-px border-b border-[var(--prism-line)] bg-[var(--prism-line)] md:grid-cols-5">
            {graphNodeTypes.map((type) => {
              const meta = getNodeMeta(type)
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
                ref={svgRef}
                viewBox={`0 0 ${graphWidth} ${graphHeight}`}
                className="min-h-[39rem] w-[74rem] max-w-none touch-none select-none"
                role="img"
                aria-label="知识治理图谱"
                onPointerMove={handlePointerMove}
                onPointerUp={stopDragging}
                onPointerLeave={stopDragging}
              >
                <defs>
                  <pattern id="graph-grid" width="32" height="32" patternUnits="userSpaceOnUse">
                    <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#e2e8f0" strokeWidth="0.7" />
                  </pattern>
                  <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                    <path d="M0,0 L7,3 L0,6 Z" fill="#94a3b8" />
                  </marker>
                </defs>
                <rect x="0" y="0" width={graphWidth} height={graphHeight} fill="url(#graph-grid)" opacity="0.72" />
                <g>
                  {graphNodeTypes.map((type) => {
                    const laneX = createInitialPositions([{ id: type, type, label: '' } as KnowledgeGraphNode])[type]?.x
                    if (!laneX) return null
                    return (
                      <text key={type} x={laneX - 48} y="34" className="fill-slate-400 text-[11px] font-medium">
                        {getNodeMeta(type).lane}
                      </text>
                    )
                  })}
                </g>
                <g>
                  {(payload?.edges ?? []).map((edge) => {
                    const source = nodeById.get(edge.source)
                    const target = nodeById.get(edge.target)
                    if (!source || !target) return null
                    const active = selected?.id === edge.source || selected?.id === edge.target
                    const sx = source.x + (target.x >= source.x ? nodeWidth / 2 : -nodeWidth / 2)
                    const tx = target.x + (target.x >= source.x ? -nodeWidth / 2 : nodeWidth / 2)
                    const mid = Math.abs(tx - sx) / 2
                    const style = edgeStyle(edge, active)
                    return (
                      <path
                        key={edge.id}
                        d={`M ${sx} ${source.y} C ${sx + mid} ${source.y}, ${tx - mid} ${target.y}, ${tx} ${target.y}`}
                        fill="none"
                        stroke={style.stroke}
                        strokeWidth={style.strokeWidth}
                        strokeDasharray={style.strokeDasharray}
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
                      dragging={dragging?.id === node.id}
                      onPointerDown={(event) => handlePointerDown(event, node)}
                      onSelect={() => {
                        if (!dragging?.moved) setSelectedId(node.id)
                      }}
                    />
                  ))}
                </g>
              </svg>
            )}
          </div>
        </section>

        <GraphInspector
          node={selected}
          edges={selectedEdges}
          nodes={nodeById}
          saving={saving}
          onSave={updateNode}
        />
      </div>
    </div>
  )
}

function GraphNode({
  node,
  active,
  dragging,
  onPointerDown,
  onSelect,
}: {
  node: PositionedNode
  active: boolean
  dragging: boolean
  onPointerDown: (event: PointerEvent<SVGGElement>) => void
  onSelect: () => void
}) {
  const meta = getNodeMeta(node.type)
  return (
    <g
      transform={`translate(${node.x - nodeWidth / 2}, ${node.y - nodeHeight / 2})`}
      onPointerDown={onPointerDown}
      onClick={onSelect}
      className={cn('cursor-grab', dragging && 'cursor-grabbing')}
    >
      <rect
        width={nodeWidth}
        height={nodeHeight}
        rx={nodeRadius}
        fill={active ? '#ffffff' : meta.fill}
        stroke={active ? meta.color : '#d7dee9'}
        strokeWidth={active ? 2.4 : 1}
        filter={active ? 'drop-shadow(0 8px 16px rgb(15 23 42 / 0.12))' : undefined}
      />
      <circle cx="22" cy="21" r="7" fill={meta.color} opacity={active ? 1 : 0.86} />
      <text x="36" y="18" className="fill-slate-950 text-[11px] font-semibold">
        {truncate(node.label, 15)}
      </text>
      <text x="36" y="32" className="fill-slate-500 text-[9px] font-medium">
        {meta.label}
      </text>
    </g>
  )
}

function GraphInspector({
  node,
  edges,
  nodes,
  saving,
  onSave,
}: {
  node: PositionedNode | null
  edges: KnowledgeGraphEdge[]
  nodes: Map<string, PositionedNode>
  saving: boolean
  onSave: (nodeId: string, data: KnowledgeGraphNodeUpdate) => Promise<unknown>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    label: '',
    content: '',
    summary: '',
    category: '',
    tags: '',
    keywords: '',
    typeValue: '',
    modality: '',
    status: '',
    confidence: '',
    sourcePlatform: '',
    sourceUrl: '',
  })

  useEffect(() => {
    if (!node) return
    setEditing(false)
    setDraft({
      label: node.label ?? '',
      content: contentForNode(node),
      summary: node.summary ?? '',
      category: node.category ?? '',
      tags: joinList(node.tags),
      keywords: joinList(node.keywords),
      typeValue: secondaryType(node) ?? '',
      modality: node.modality ?? '',
      status: node.status ?? '',
      confidence: typeof node.confidence === 'number' ? node.confidence.toFixed(2) : '',
      sourcePlatform: node.source_platform ?? '',
      sourceUrl: node.source_url ?? '',
    })
  }, [node])

  if (!node) {
    return (
      <aside className="prism-panel flex min-h-[24rem] items-center justify-center rounded-lg p-5 text-center text-sm text-slate-500">
        选择一个节点查看详情
      </aside>
    )
  }

  const meta = getNodeMeta(node.type)
  const TypeIcon = meta.icon

  const save = async () => {
    const update: KnowledgeGraphNodeUpdate = {
      label: draft.label.trim(),
      summary: draft.summary,
      category: draft.category,
      tags: splitList(draft.tags),
      keywords: splitList(draft.keywords),
      status: draft.status || undefined,
    }
    if (draft.confidence.trim()) update.confidence = Number(draft.confidence)
    if (node.type === 'canonical') {
      update.statement = draft.content
      update.canonical_type = draft.typeValue
    } else if (node.type === 'pku') {
      update.statement = draft.content
      update.normalized_statement = draft.label
      update.unit_type = draft.typeValue
      update.modality = draft.modality
    } else if (node.type === 'asset') {
      update.text = draft.content
      update.asset_kind = draft.typeValue
      update.source_platform = draft.sourcePlatform
      update.source_url = draft.sourceUrl
    } else if (node.type === 'personal_asset_unit') {
      update.text = draft.content
      update.unit_type = draft.typeValue
    } else {
      update.text = draft.content
    }
    await onSave(node.id, update)
    setEditing(false)
  }

  return (
    <aside className="prism-panel flex min-h-0 flex-col rounded-lg p-5">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            style={{ background: meta.fill, color: meta.color }}
          >
            <TypeIcon size={16} />
          </span>
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-500">{meta.label}</div>
            <h2 className="mt-1 break-words text-base font-semibold leading-6 text-slate-950">{node.label}</h2>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[var(--prism-line)] bg-white text-slate-600 transition hover:bg-slate-50"
          title={editing ? '退出编辑' : '编辑节点'}
        >
          {editing ? <X size={15} /> : <Pencil size={15} />}
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {editing ? (
          <div className="space-y-3">
            <EditInput label="标题" value={draft.label} onChange={(value) => setDraft({ ...draft, label: value })} />
            <EditTextarea
              label={node.type === 'canonical' || node.type === 'pku' ? '表述' : '内容'}
              value={draft.content}
              onChange={(value) => setDraft({ ...draft, content: value })}
              rows={5}
            />
            <EditTextarea label="摘要" value={draft.summary} onChange={(value) => setDraft({ ...draft, summary: value })} />
            <div className="grid grid-cols-2 gap-2">
              <EditInput label="类型" value={draft.typeValue} onChange={(value) => setDraft({ ...draft, typeValue: value })} />
              <EditInput label="状态" value={draft.status} onChange={(value) => setDraft({ ...draft, status: value })} />
            </div>
            {node.type === 'pku' ? (
              <EditInput label="模态" value={draft.modality} onChange={(value) => setDraft({ ...draft, modality: value })} />
            ) : null}
            {node.type === 'asset' ? (
              <div className="grid grid-cols-2 gap-2">
                <EditInput
                  label="平台"
                  value={draft.sourcePlatform}
                  onChange={(value) => setDraft({ ...draft, sourcePlatform: value })}
                />
                <EditInput
                  label="来源链接"
                  value={draft.sourceUrl}
                  onChange={(value) => setDraft({ ...draft, sourceUrl: value })}
                />
              </div>
            ) : null}
            <EditInput label="标签" value={draft.tags} onChange={(value) => setDraft({ ...draft, tags: value })} />
            <EditInput label="关键词" value={draft.keywords} onChange={(value) => setDraft({ ...draft, keywords: value })} />
            <div className="grid grid-cols-2 gap-2">
              <EditInput label="分类" value={draft.category} onChange={(value) => setDraft({ ...draft, category: value })} />
              <EditInput
                label="置信度"
                value={draft.confidence}
                onChange={(value) => setDraft({ ...draft, confidence: value })}
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={save}
                disabled={saving}
                className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
                保存
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                <X size={15} />
                取消
              </button>
            </div>
          </div>
        ) : (
          <>
            <DetailBlock label="内容" value={contentForNode(node)} />
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="类型" value={secondaryType(node)} />
              <MiniStat label="置信度" value={typeof node.confidence === 'number' ? node.confidence.toFixed(2) : '-'} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <MiniStat label="分类" value={node.category || '-'} />
              <MiniStat label="状态" value={node.status || '-'} />
            </div>
            {node.tags?.length ? <ChipBlock label="标签" values={node.tags} /> : null}
            {node.keywords?.length ? <ChipBlock label="关键词" values={node.keywords.slice(0, 10)} /> : null}
          </>
        )}

        <div className="border-t border-[var(--prism-line)] pt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-950">连接关系</h3>
          {edges.length === 0 ? (
            <p className="text-sm leading-6 text-slate-500">暂无连接</p>
          ) : (
            <div className="space-y-2">
              {edges.map((edge) => {
                const otherId = edge.source === node.id ? edge.target : edge.source
                const other = nodes.get(otherId)
                const direction = edge.type === 'pku_relation' ? (edge.source === node.id ? 'outgoing' : 'incoming') : ''
                return (
                  <div key={edge.id} className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
                    <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
                      <Check size={13} />
                      {edge.label}
                      {direction ? <span className="ml-auto text-[11px] text-pink-600">{direction}</span> : null}
                    </div>
                    <div className="mt-1 text-sm font-semibold text-slate-900">{other?.label ?? otherId}</div>
                    {edge.role ? <div className="mt-1 text-xs text-slate-500">{edge.role}</div> : null}
                    {edge.reason ? <div className="mt-1 text-xs leading-5 text-slate-500">{edge.reason}</div> : null}
                    {edge.type === 'pku_relation' ? (
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
                        {typeof edge.confidence === 'number' ? (
                          <span className="rounded-md bg-pink-50 px-2 py-1 text-pink-700">
                            {edge.confidence.toFixed(2)}
                          </span>
                        ) : null}
                        {edge.llm_model ? <span className="rounded-md bg-slate-100 px-2 py-1">{edge.llm_model}</span> : null}
                      </div>
                    ) : null}
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

function EditInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
      />
    </label>
  )
}

function EditTextarea({
  label,
  value,
  rows = 3,
  onChange,
}: {
  label: string
  value: string
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <textarea
        value={value}
        rows={rows}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-y rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
      />
    </label>
  )
}
