import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Filter,
  Loader2,
  Maximize2,
  Network,
  RefreshCw,
  Search,
  Sparkles,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import {
  unifiedGraphApi,
  type GraphRagExplain,
  type UnifiedGraphEdge,
  type UnifiedGraphNode,
  type UnifiedGraphNodeType,
  type UnifiedGraphPayload,
  type UnifiedGraphView,
} from '@/app/api'
import {
  collectEdgeExplains,
  evidenceTypeLabel as formatEvidenceTypeLabel,
  selectInspectorExplain as chooseInspectorExplain,
} from '@/app/graphrag'
import { createLatestRequestRunner } from '@/app/latestRequest'
import { cn } from '@/lib/utils'
import { formatGraphData, useG6Graph } from './graph/useG6Graph'

const maxExplorerDepth = 3
const inspectorTitleMaxLength = 72
const floatingSurfaceMotionClass = 'transition-[transform,opacity,box-shadow] duration-200 ease-out'
const graphControlFocusClass =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] focus-visible:ring-offset-2 focus-visible:ring-offset-white/80'
const graphInputFocusClass =
  'focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100 focus-visible:ring-[var(--prism-cyan)] focus-visible:ring-offset-2 focus-visible:ring-offset-white/80'
const graphControlTransitionClass =
  'transition-[transform,opacity,box-shadow,background-color,border-color,color] duration-200 ease-out'
const graphInspectorMotionClass = 'motion-reduce:translate-x-0 motion-reduce:transition-none'

const nodeMeta: Record<
  UnifiedGraphNodeType,
  {
    label: string
    color: string
    fill: string
    icon: typeof Network
  }
> = {
  entity: {
    label: '实体',
    color: '#155eef',
    fill: '#eff6ff',
    icon: Sparkles,
  },
  document_chunk: {
    label: '文档分块',
    color: '#0f766e',
    fill: '#ecfdf5',
    icon: FileText,
  },
}

const fallbackNodeMeta = {
  label: '节点',
  color: '#475569',
  fill: '#f8fafc',
  icon: Network,
}

function getNodeMeta(type: string) {
  return nodeMeta[type as UnifiedGraphNodeType] ?? fallbackNodeMeta
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function truncate(value: string | null | undefined, max = 18) {
  const text = (value || '').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max)}...`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function compareNodeIdentity(a: UnifiedGraphNode, b: UnifiedGraphNode) {
  const labelOrder = (a.label || '').localeCompare(b.label || '', 'zh-Hans-CN')
  if (labelOrder !== 0) return labelOrder
  return a.id.localeCompare(b.id)
}

function buildAdjacency(nodes: UnifiedGraphNode[], edges: UnifiedGraphEdge[]) {
  const validIds = new Set(nodes.map((node) => node.id))
  const adjacency = new Map<string, string[]>()
  nodes.forEach((node) => {
    adjacency.set(node.id, [])
  })
  edges.forEach((edge) => {
    if (!validIds.has(edge.source) || !validIds.has(edge.target)) return
    adjacency.get(edge.source)?.push(edge.target)
    adjacency.get(edge.target)?.push(edge.source)
  })
  return adjacency
}

function buildFocusDistanceMap(nodes: UnifiedGraphNode[], edges: UnifiedGraphEdge[], rootId: string | null) {
  const distances = new Map<string, number>()
  if (!rootId) return distances

  const adjacency = buildAdjacency(nodes, edges)
  if (!adjacency.has(rootId)) return distances

  const queue = [rootId]
  distances.set(rootId, 0)

  for (let index = 0; index < queue.length; index += 1) {
    const currentId = queue[index]
    const currentDistance = distances.get(currentId)
    if (typeof currentDistance !== 'number') continue

    ;(adjacency.get(currentId) ?? []).forEach((neighborId) => {
      if (distances.has(neighborId)) return
      distances.set(neighborId, currentDistance + 1)
      queue.push(neighborId)
    })
  }

  return distances
}

function distanceLabel(distance: number) {
  return distance === 1 ? '1 跳' : `${distance} 跳`
}

function nodeContent(node: UnifiedGraphNode) {
  return node.text || node.summary || ''
}

function compactInspectorTitle(value: string | null | undefined) {
  return truncate(value, inspectorTitleMaxLength)
}

function searchMatchRanges(text: string, query: string) {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  if (!normalizedQuery) return []

  const normalizedText = text.toLocaleLowerCase()
  const ranges: Array<{ start: number; end: number }> = []
  let cursor = 0

  while (cursor < text.length) {
    const index = normalizedText.indexOf(normalizedQuery, cursor)
    if (index === -1) break
    ranges.push({ start: index, end: index + normalizedQuery.length })
    cursor = index + Math.max(normalizedQuery.length, 1)
  }

  return ranges
}

function nodeDetailType(node: UnifiedGraphNode) {
  return node.chunk_type || node.asset_kind || node.media_type || node.source_kind || node.type
}

function edgeDescription(edge: UnifiedGraphEdge) {
  if (edge.label?.trim()) return edge.label
  switch (edge.type) {
    case 'mentioned_in':
      return '来源证据'
    case 'mentions_entity':
      return '提及实体'
    case 'related_to':
      return '语义关联'
    case 'co_occurs_with':
      return '共现'
    case 'shares_entity_with':
      return '共享实体'
    default:
      return edge.type
  }
}

function formatConfidence(value?: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '-'
}

function countFor(payload: UnifiedGraphPayload | null, type: UnifiedGraphNodeType) {
  return payload?.stats.node_counts[type] ?? 0
}

type KnowledgeGraphPageProps = {
  initialPayload?: UnifiedGraphPayload | null
  initialSelectedId?: string | null
  loader?: (params: { view: UnifiedGraphView; q?: string; limit?: number }) => Promise<UnifiedGraphPayload>
  /** Extra root classes. `twMerge` dedupes so a passed height overrides the default. */
  className?: string
}

function initialGraphView(initialPayload: UnifiedGraphPayload | null | undefined): UnifiedGraphView {
  return initialPayload?.focus?.view ?? initialPayload?.view ?? 'entity'
}

export function KnowledgeGraphPage({
  initialPayload = null,
  initialSelectedId = null,
  loader = unifiedGraphApi.get,
  className,
}: KnowledgeGraphPageProps) {
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const skipInitialLoadRef = useRef(Boolean(initialPayload))
  const loadRunnerRef = useRef(createLatestRequestRunner())
  const [payload, setPayload] = useState<UnifiedGraphPayload | null>(initialPayload)
  const [query, setQuery] = useState(() => initialPayload?.focus?.query ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId)
  const [focusRootId, setFocusRootId] = useState<string | null>(initialSelectedId)
  const [focusDepth, setFocusDepth] = useState(1)
  const [view, setView] = useState<UnifiedGraphView>(() => initialGraphView(initialPayload))
  const [typeFilter, setTypeFilter] = useState<Set<UnifiedGraphNodeType>>(
    () => new Set<UnifiedGraphNodeType>(['entity', 'document_chunk']),
  )
  const [showFilterMenu, setShowFilterMenu] = useState(false)

  const loadGraph = async (nextView: UnifiedGraphView = view, nextQuery: string = query) => {
    await loadRunnerRef.current.run(
      () =>
        loader({
          view: nextView,
          q: nextQuery.trim() || undefined,
          limit: 300,
        }),
      {
        onStart: () => {
          setLoading(true)
          setError(null)
        },
        onSuccess: (data) => {
          setPayload(data)
          setSelectedId((current) => {
            if (current && data.nodes.some((node) => node.id === current)) return current
            return null
          })
        },
        onError: (err) => {
          setError(`Failed to load unified graph: ${getErrorMessage(err)}`)
        },
        onFinally: () => {
          setLoading(false)
        },
      },
    )
  }

  useEffect(() => {
    if (skipInitialLoadRef.current) {
      skipInitialLoadRef.current = false
      return
    }
    void loadGraph(view)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view])

  const nodes = useMemo<UnifiedGraphNode[]>(() => payload?.nodes ?? [], [payload?.nodes])

  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node] as const)), [nodes])
  const selected = selectedId ? nodeById.get(selectedId) ?? null : null
  const focusRoot = focusRootId ? nodeById.get(focusRootId) ?? null : null

  const inspectNode = (nodeId: string) => {
    setSelectedId(nodeId)
  }

  const closeInspector = () => {
    setSelectedId(null)
    setFocusRootId(null)
    setFocusDepth(1)
  }

  const selectFocusNode = (nodeId: string) => {
    setSelectedId(nodeId)
    setFocusRootId(nodeId)
    setFocusDepth(1)
  }

  useEffect(() => {
    if (!nodes.length) {
      if (selectedId !== null) setSelectedId(null)
      if (focusRootId !== null) setFocusRootId(null)
      return
    }

    if (selectedId && !nodeById.has(selectedId)) {
      setSelectedId(null)
    }

    const nextFocusRootId =
      focusRootId && nodeById.has(focusRootId) ? focusRootId : selectedId && nodeById.has(selectedId) ? selectedId : null
    if (focusRootId !== nextFocusRootId) {
      setFocusRootId(nextFocusRootId)
      setFocusDepth(1)
    }
  }, [focusRootId, nodeById, nodes.length, selectedId])

  useEffect(() => {
    if (!selected) return

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      closeInspector()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selected])

  const focusDistances = useMemo(
    () => buildFocusDistanceMap(payload?.nodes ?? [], payload?.edges ?? [], focusRoot?.id ?? null),
    [focusRoot?.id, payload?.edges, payload?.nodes],
  )
  const maxFocusDistance = useMemo(
    () => Array.from(focusDistances.values()).reduce((max, distance) => Math.max(max, distance), 1),
    [focusDistances],
  )
  const canExpandExplorer = useMemo(
    () => focusDepth < Math.min(maxExplorerDepth, maxFocusDistance),
    [focusDepth, maxFocusDistance],
  )
  const explorerNodes = useMemo(
    () =>
      nodes
        .filter((node) => {
          const distance = focusDistances.get(node.id)
          return typeof distance === 'number' && distance > 0 && distance <= focusDepth
        })
        .sort((a, b) => {
          const distanceOrder = (focusDistances.get(a.id) ?? 0) - (focusDistances.get(b.id) ?? 0)
          if (distanceOrder !== 0) return distanceOrder
          return compareNodeIdentity(a, b)
        }),
    [focusDepth, focusDistances, nodes],
  )
  const selectedEdges = useMemo(
    () => (payload?.edges ?? []).filter((edge) => edge.source === selected?.id || edge.target === selected?.id),
    [payload?.edges, selected?.id],
  )
  const relatedNodes = useMemo(
    () => {
      const deduped = new Map<string, UnifiedGraphNode>()
      selectedEdges.forEach((edge) => {
        const otherId = edge.source === selected?.id ? edge.target : edge.source
        const otherNode = nodeById.get(otherId)
        if (!otherNode || deduped.has(otherNode.id)) return
        deduped.set(otherNode.id, otherNode)
      })
      return Array.from(deduped.values())
    },
    [nodeById, selected?.id, selectedEdges],
  )

  const graphData = useMemo(
    () => formatGraphData(payload?.nodes ?? [], payload?.edges ?? [], typeFilter),
    [payload?.edges, payload?.nodes, typeFilter],
  )
  const { fitView, zoomIn, zoomOut, relayout } = useG6Graph({
    containerRef: canvasRef,
    data: graphData,
    onNodeClick: inspectNode,
    onCanvasClick: closeInspector,
  })

  const toggleTypeFilter = (type: UnifiedGraphNodeType) => {
    setTypeFilter((prev) => {
      const next = new Set(prev)
      if (next.has(type)) {
        next.delete(type)
      } else {
        next.add(type)
      }
      return next
    })
  }

  const handleRefocus = () => {
    if (!selected) return
    selectFocusNode(selected.id)
  }

  const handleExpandMore = () => {
    const nextRootId = focusRoot?.id ?? selected?.id
    if (!nextRootId) return
    if (focusRootId !== nextRootId) setFocusRootId(nextRootId)
    setFocusDepth((current) => clamp(current + 1, 1, Math.min(maxExplorerDepth, maxFocusDistance)))
  }

  const totalNodeCount = payload?.stats.node_count ?? 0
  const totalEdgeCount = payload?.stats.edge_count ?? 0

  return (
    <div
      className={cn('flex h-[calc(100vh-9rem)] min-h-0 flex-col overflow-hidden', className)}
      data-testid="unified-graph-page"
    >
      {error ? (
        <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-red-700">
          {error}
        </div>
      ) : null}

      <section className="relative min-h-0 flex-1 overflow-hidden rounded-[28px] border border-white/80 bg-[radial-gradient(circle_at_top_right,_rgba(246,214,140,0.14),_transparent_22%),radial-gradient(circle_at_bottom_left,_rgba(161,198,224,0.14),_transparent_24%),linear-gradient(180deg,_rgba(255,255,255,0.92),_rgba(243,246,251,0.94))] shadow-[0_24px_60px_rgba(15,23,42,0.06)]">
        <div
          className={cn(
            'absolute left-5 top-5 z-20 flex max-w-[calc(100%-8rem)] flex-wrap items-center gap-3 rounded-[22px] border border-slate-200/70 bg-white/90 px-4 py-3 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur',
            floatingSurfaceMotionClass,
          )}
          data-testid="graph-floating-controls"
        >
          <div className="inline-flex rounded-full bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setView('entity')}
              className={cn(
                'rounded-full px-3 py-1.5 text-sm font-medium',
                graphControlTransitionClass,
                graphControlFocusClass,
                view === 'entity' ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600',
              )}
            >
              实体视图
            </button>
            <button
              type="button"
              onClick={() => setView('source')}
              className={cn(
                'rounded-full px-3 py-1.5 text-sm font-medium',
                graphControlTransitionClass,
                graphControlFocusClass,
                view === 'source' ? 'bg-slate-950 text-white shadow-sm' : 'text-slate-600',
              )}
            >
              来源视图
            </button>
          </div>
          <div className="relative w-[22rem] max-w-[42vw] min-w-[14rem] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void loadGraph()
              }}
              placeholder={view === 'entity' ? '搜索实体或关系' : '搜索文档或资产来源'}
              className={cn(
                'h-10 w-full rounded-full border border-slate-200 bg-white/90 pl-9 pr-3 text-sm outline-none',
                graphInputFocusClass,
                graphControlTransitionClass,
              )}
            />
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowFilterMenu((prev) => !prev)}
              className={cn(
                'inline-flex h-10 items-center justify-center gap-1.5 rounded-full border px-3 text-sm font-medium',
                graphControlTransitionClass,
                graphControlFocusClass,
                typeFilter.size < 2
                  ? 'border-amber-300 bg-amber-50 text-amber-700'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
              )}
            >
              <Filter size={14} />
              类型过滤
              {typeFilter.size < 2 ? (
                <span className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-200 px-1 text-[10px] font-bold text-amber-800">
                  {typeFilter.size}/2
                </span>
              ) : null}
            </button>
            {showFilterMenu ? (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowFilterMenu(false)} />
                <div className="absolute left-0 top-full z-40 mt-2 w-48 rounded-xl border border-slate-200 bg-white p-1.5 shadow-[0_16px_40px_rgba(15,23,42,0.12)]">
                  {(
                    [
                      ['entity', '实体', '#155eef'],
                      ['document_chunk', '文档分块', '#0f766e'],
                    ] as const
                  ).map(([type, label, color]) => {
                    const checked = typeFilter.has(type)
                    return (
                      <button
                        key={type}
                        type="button"
                        onClick={() => toggleTypeFilter(type)}
                        className={cn(
                          'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                          checked ? 'text-slate-800' : 'text-slate-400',
                        )}
                      >
                        <span
                          className="inline-flex h-3 w-3 shrink-0 rounded-sm border-2"
                          style={{
                            backgroundColor: checked ? color : 'transparent',
                            borderColor: color,
                          }}
                        />
                        <span>{label}</span>
                        {checked ? (
                          <span className="ml-auto text-[10px] text-slate-400">显示</span>
                        ) : (
                          <span className="ml-auto text-[10px] text-slate-300">隐藏</span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void loadGraph()}
            className={cn(
              'inline-flex h-10 items-center justify-center gap-2 rounded-full bg-slate-950 px-4 text-sm font-medium text-white hover:bg-slate-800',
              graphControlTransitionClass,
              graphControlFocusClass,
            )}
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            刷新图谱
          </button>
        </div>

        <div
          className={cn(
            'absolute bottom-5 left-5 z-20 rounded-[20px] border border-slate-200/70 bg-white/88 px-4 py-3 text-sm shadow-[0_12px_30px_rgba(15,23,42,0.08)] backdrop-blur',
            floatingSurfaceMotionClass,
          )}
        >
          <div className="flex items-center gap-3 text-slate-700">
            <span className="font-medium">节点 {totalNodeCount}</span>
            <span className="text-slate-300">|</span>
            <span className="font-medium">边 {totalEdgeCount}</span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <Sparkles size={13} className="text-blue-600" />
            <span>实体 {countFor(payload, 'entity')}</span>
            <FileText size={13} className="ml-1 text-emerald-700" />
            <span>文档分块 {countFor(payload, 'document_chunk')}</span>
          </div>
        </div>

        <div
          className={cn(
            'absolute bottom-5 right-5 z-20 flex flex-col items-center gap-2 rounded-[20px] border border-slate-200/70 bg-white/90 px-3 py-3 shadow-[0_12px_30px_rgba(15,23,42,0.08)] backdrop-blur',
            floatingSurfaceMotionClass,
          )}
        >
          <button
            type="button"
            onClick={zoomIn}
            className={cn(
              'inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-700 hover:bg-slate-50',
              graphControlTransitionClass,
              graphControlFocusClass,
            )}
            title="放大"
          >
            <ZoomIn size={15} />
          </button>
          <button
            type="button"
            onClick={zoomOut}
            className={cn(
              'inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-700 hover:bg-slate-50',
              graphControlTransitionClass,
              graphControlFocusClass,
            )}
            title="缩小"
          >
            <ZoomOut size={15} />
          </button>
          <button
            type="button"
            onClick={relayout}
            disabled={!nodes.length}
            className={cn(
              'inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-700',
              graphControlTransitionClass,
              graphControlFocusClass,
              nodes.length ? 'hover:bg-slate-50' : 'cursor-not-allowed opacity-45',
            )}
            title="重新布局"
            aria-label="重新布局"
          >
            <RefreshCw size={15} />
          </button>
          <button
            type="button"
            onClick={fitView}
            className={cn(
              'inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 text-slate-700 hover:bg-slate-50',
              graphControlTransitionClass,
              graphControlFocusClass,
            )}
            title="适应画布"
          >
            <Maximize2 size={15} />
          </button>
        </div>

        <div className="relative h-full min-h-0 p-4 pt-28">
          <div className="relative min-h-0 h-full overflow-hidden rounded-[24px] border border-white/70 bg-[radial-gradient(circle_at_50%_42%,_rgba(255,255,255,0.72),_rgba(255,255,255,0.08)_58%,_rgba(219,231,244,0.16)_100%),linear-gradient(135deg,_#fffefb_0%,_#f8f8f4_52%,_#eff4fb_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.42)]">
            <div ref={canvasRef} className="absolute inset-0" />
            {!nodes.length ? (
              <div className="relative flex min-h-full items-center justify-center px-6 py-10">
                <GraphCanvasGuidance hasGraphData={false} />
              </div>
            ) : null}
            {!selected ? (
              <div className="pointer-events-none absolute inset-x-6 bottom-6 z-10 flex justify-start">
                <GraphCanvasGuidance hasGraphData />
              </div>
            ) : null}
          </div>

          <div
            data-testid="graph-inspector-overlay"
            data-state={selected ? 'open' : 'closed'}
            aria-hidden={!selected}
            className={cn(
              'pointer-events-none absolute inset-0 z-30 flex items-stretch justify-end overflow-hidden p-4 pt-28 pb-24',
              floatingSurfaceMotionClass,
              graphInspectorMotionClass,
            )}
          >
            <div
              className={cn(
                'flex min-h-0 w-full max-w-[23rem]',
                floatingSurfaceMotionClass,
                graphInspectorMotionClass,
                selected
                  ? 'pointer-events-auto translate-x-0 opacity-100 motion-safe:animate-[graphInspectorIn_180ms_ease-out]'
                  : 'translate-x-8 opacity-0 motion-reduce:translate-x-0',
              )}
            >
              <GraphInspector
                node={selected}
                view={view}
                edges={selectedEdges}
                nodes={nodeById}
                relatedNodes={relatedNodes}
                focusRoot={focusRoot}
                focusDepth={focusDepth}
                explorerNodes={explorerNodes}
                focusDistances={focusDistances}
                canExpandExplorer={canExpandExplorer}
                onSelectNode={inspectNode}
                onClose={closeInspector}
                onRefocus={handleRefocus}
                onExpandMore={handleExpandMore}
              />
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function GraphInspector({
  node,
  view,
  edges,
  nodes,
  relatedNodes,
  focusRoot,
  focusDepth,
  explorerNodes,
  focusDistances,
  canExpandExplorer,
  onSelectNode,
  onClose,
  onRefocus,
  onExpandMore,
}: {
  node: UnifiedGraphNode | null
  view: UnifiedGraphView
  edges: UnifiedGraphEdge[]
  nodes: Map<string, UnifiedGraphNode>
  relatedNodes: UnifiedGraphNode[]
  focusRoot: UnifiedGraphNode | null
  focusDepth: number
  explorerNodes: UnifiedGraphNode[]
  focusDistances: Map<string, number>
  canExpandExplorer: boolean
  onSelectNode: (nodeId: string) => void
  onClose: () => void
  onRefocus: () => void
  onExpandMore: () => void
}) {
  const edgeExplains = useMemo(() => collectEdgeExplains(edges), [edges])
  const edgeExplainById = useMemo(
    () => new Map(edgeExplains.map(({ edge, explain }) => [edge.id, explain])),
    [edgeExplains],
  )
  const retrievalExplain = useMemo(() => (node ? chooseInspectorExplain(node, edges) : null), [node, edges])
  const [entitySearch, setEntitySearch] = useState('')
  const [activeEntityMatch, setActiveEntityMatch] = useState(0)
  const activeEntityMatchRef = useRef<HTMLElement | null>(null)
  const entityLabel = node?.label ?? ''
  const entityMatches = searchMatchRanges(entityLabel, entitySearch)
  const safeActiveEntityMatch = entityMatches.length ? clamp(activeEntityMatch, 0, entityMatches.length - 1) : 0

  useEffect(() => {
    setEntitySearch('')
    setActiveEntityMatch(0)
  }, [node?.id])

  useEffect(() => {
    if (activeEntityMatch !== safeActiveEntityMatch) {
      setActiveEntityMatch(safeActiveEntityMatch)
    }
  }, [activeEntityMatch, safeActiveEntityMatch])

  useEffect(() => {
    activeEntityMatchRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [safeActiveEntityMatch, entitySearch])

  if (!node) {
    return null
  }

  const meta = getNodeMeta(node.type)
  const TypeIcon = meta.icon
  const isFocusNode = focusRoot?.id === node.id
  const nodeDistance = focusDistances.get(node.id)
  const nodeTitle = compactInspectorTitle(node.label)
  const focusRootTitle = compactInspectorTitle(focusRoot?.label ?? node.label)
  const explorerHeading = isFocusNode ? '当前节点是探索中心' : `围绕 ${focusRootTitle} 继续探索`
  const explorerSummary = isFocusNode
    ? `${nodeTitle} 是当前探索中心。你正在查看它在 ${focusDepth} 跳范围内关联到的实体和文档证据。`
    : `${nodeTitle} 当前位于 ${focusRootTitle} 的 ${distanceLabel(nodeDistance ?? 1)} 范围内，可以继续展开或重新聚焦。`
  const explorerHint = isFocusNode
    ? '重新聚焦会把当前节点设为新的中心，并重置到 1 跳视图。'
    : '如果想让当前节点成为新的探索中心，使用[重新聚焦]；如果想保留现有焦点并继续向外看，使用[展开更多关联]。'

  return (
    <aside className="prism-panel flex min-h-0 h-full max-h-full flex-col overflow-hidden rounded-[24px] border border-white/75 bg-white/94 p-5 shadow-[0_24px_60px_rgba(15,23,42,0.18)] backdrop-blur">
      <div className="mb-4 flex items-start gap-3">
        <span
          className="mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ background: meta.fill, color: meta.color }}
        >
          <TypeIcon size={16} />
        </span>
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-500">{meta.label}</div>
          <h2 className="mt-1 break-words text-base font-semibold leading-6 text-slate-950" title={node.label}>
            {nodeTitle}
          </h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {view === 'entity'
              ? '当前位于实体中心视图，右侧以实体与来源证据的连接为主。'
              : '当前位于来源中心视图，右侧以来源与实体的连接为主。'}
          </p>
        </div>
        <button
          type="button"
          data-testid="graph-inspector-close"
          onClick={onClose}
          className={cn(
            'ml-auto inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[var(--prism-line)] bg-white text-slate-600 hover:bg-slate-100',
            graphControlTransitionClass,
            graphControlFocusClass,
          )}
          aria-label="关闭检查器"
          title="关闭检查器"
        >
          <X size={15} />
        </button>
      </div>

      <div data-testid="graph-inspector-scroll" className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        <EntityContentSearchBox
          label={meta.label}
          value={node.label}
          search={entitySearch}
          activeMatch={safeActiveEntityMatch}
          matchRanges={entityMatches}
          activeMatchRef={(element) => {
            activeEntityMatchRef.current = element
          }}
          onSearchChange={(value) => {
            setEntitySearch(value)
            setActiveEntityMatch(0)
          }}
          onStep={(direction) => {
            if (!entityMatches.length) return
            setActiveEntityMatch((current) => (current + direction + entityMatches.length) % entityMatches.length)
          }}
        />
        <div className="rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-medium text-slate-500">探索器</div>
              <div className="mt-1 text-sm font-semibold text-slate-950">{explorerHeading}</div>
            </div>
            <div className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-500">
              {focusDepth} 跳范围
            </div>
          </div>
          <p className="mt-3 text-xs leading-5 text-slate-600">{explorerSummary}</p>
          <p className="mt-2 text-xs leading-5 text-slate-500">{explorerHint}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onRefocus}
              className={cn(
                'rounded-full border border-[var(--prism-line)] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100',
                graphControlTransitionClass,
                graphControlFocusClass,
              )}
            >
              重新聚焦
            </button>
            <button
              type="button"
              onClick={onExpandMore}
              disabled={!canExpandExplorer}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium',
                graphControlTransitionClass,
                graphControlFocusClass,
                canExpandExplorer
                  ? 'border-[var(--prism-line)] bg-white text-slate-700 hover:bg-slate-100'
                  : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400',
              )}
            >
              展开更多关联
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {explorerNodes.length === 0 ? (
              <span className="text-xs text-slate-500">当前探索深度下没有更多关联节点。</span>
            ) : (
              explorerNodes.map((relatedNode) => (
                  <button
                    key={`explorer-${relatedNode.id}`}
                    type="button"
                    onClick={() => onSelectNode(relatedNode.id)}
                    className={cn(
                      'inline-flex max-w-full items-center rounded-full border border-[var(--prism-line)] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50',
                      graphControlTransitionClass,
                      graphControlFocusClass,
                    )}
                  >
                    <span className="max-w-full truncate" title={relatedNode.label}>
                      {compactInspectorTitle(relatedNode.label)}
                    </span>
                    <span className="ml-1 text-[10px] text-slate-400">
                      {distanceLabel(focusDistances.get(relatedNode.id) ?? 1)}
                    </span>
                  </button>
              ))
            )}
          </div>
        </div>
        <DetailBlock label='内容摘要' value={nodeContent(node) || '暂无补充内容'} />
        <div className="grid grid-cols-2 gap-2">
          <MiniStat label="节点类型" value={nodeDetailType(node)} />
          <MiniStat label="置信度" value={formatConfidence(node.confidence)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <MiniStat label="分类" value={node.category || '-'} />
          <MiniStat label="状态" value={node.status || '-'} />
        </div>
        {node.tags?.length ? <ChipBlock label="标签" values={node.tags} /> : null}
        {node.keywords?.length ? <ChipBlock label="关键词" values={node.keywords.slice(0, 10)} /> : null}
        {(node.source_platform || node.source_url) && (
          <div className="space-y-2 rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-3">
            <div className="text-xs font-medium text-slate-500">来源信息</div>
            {node.source_platform ? <div className="text-sm text-slate-700">平台：{node.source_platform}</div> : null}
            {node.source_url ? (
              <a
                href={node.source_url}
                target="_blank"
                rel="noreferrer"
                className="break-all text-sm text-blue-700 underline decoration-blue-200 underline-offset-2"
              >
                {node.source_url}
              </a>
            ) : null}
          </div>
        )}

        {retrievalExplain ? (
          <div className="space-y-2 rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-slate-500">检索证据</div>
              <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">
                {formatEvidenceTypeLabel(retrievalExplain.evidence_type) || '未知证据'}
              </span>
            </div>
            <p className="text-sm leading-6 text-slate-700">
              {retrievalExplain.why || '该节点带有检索返回的图证据说明。'}
            </p>
            {typeof retrievalExplain.source_marker === 'string' && retrievalExplain.source_marker.trim() ? (
              <div className="text-[11px] text-slate-500">
                路径: {retrievalExplain.source_marker}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="border-t border-[var(--prism-line)] pt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-950">关联节点</h3>
          {relatedNodes.length === 0 ? (
            <p className="text-sm leading-6 text-slate-500">当前选中节点没有直接关联的其他节点。</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {relatedNodes.map((relatedNode) => (
                  <button
                    key={relatedNode.id}
                    type="button"
                    onClick={() => onSelectNode(relatedNode.id)}
                    className={cn(
                      'inline-flex max-w-full items-center rounded-full border border-[var(--prism-line)] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50',
                      graphControlTransitionClass,
                      graphControlFocusClass,
                    )}
                  >
                    <span className="max-w-full truncate" title={relatedNode.label}>
                      {compactInspectorTitle(relatedNode.label)}
                    </span>
                  </button>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-[var(--prism-line)] pt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-950">关联边</h3>
          {edges.length === 0 ? (
            <p className="text-sm leading-6 text-slate-500">当前选中节点没有关联的边证据。</p>
          ) : (
            <div className="space-y-2">
              {edges.map((edge) => {
                const otherId = edge.source === node.id ? edge.target : edge.source
                const other = nodes.get(otherId)
                const edgeExplain = edgeExplainById.get(edge.id)
                return (
                  <div key={edge.id} className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
                    <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
                      <Network size={13} />
                      {edgeDescription(edge)}
                    </div>
                      <div className="mt-1 break-words text-sm font-semibold text-slate-900" title={other?.label ?? otherId}>
                        {compactInspectorTitle(other?.label ?? otherId)}
                      </div>
                    {edge.reason ? <div className="mt-1 text-xs leading-5 text-slate-500">{edge.reason}</div> : null}
                    {edgeExplain ? (
                      <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] font-medium text-slate-600">
                            {formatEvidenceTypeLabel(edgeExplain.evidence_type) || '未知证据'}
                          </span>
                          {typeof edgeExplain.source_marker === 'string' && edgeExplain.source_marker.trim() ? (
                            <span className="text-[10px] text-slate-500">
                              路径: {edgeExplain.source_marker}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-slate-600">
                          {edgeExplain.why || '该关系带有检索返回的图证据说明。'}
                        </p>
                      </div>
                    ) : null}
                    {typeof edge.confidence === 'number' ? (
                      <div className="mt-1 text-[11px] text-slate-500">置信度 {edge.confidence.toFixed(2)}</div>
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

function GraphCanvasGuidance({ hasGraphData = true }: { hasGraphData?: boolean }) {
  return (
    <div
      className={cn(
        'w-full max-w-md rounded-[22px] border border-white/80 bg-white/92 p-5 text-sm text-slate-500 shadow-[0_20px_50px_rgba(15,23,42,0.12)] backdrop-blur',
        hasGraphData ? 'pointer-events-none text-left' : 'text-center',
      )}
    >
      {!hasGraphData ? (
        <p className="text-sm leading-6 text-slate-500">
          暂无图谱数据。执行搜索或打开关联查询以加载统一图谱浏览器。
        </p>
      ) : null}
      <p className={cn('leading-6 text-slate-600', hasGraphData ? '' : 'mt-3')}>
        选择一个节点，查看它在统一图谱里的结构、来源证据和关联关系。
      </p>
      <div className={cn('mt-4 flex flex-wrap gap-2', hasGraphData ? '' : 'justify-center')}>
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-full border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-400"
        >
          重新聚焦
        </button>
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-full border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-400"
        >
          展开更多关联
        </button>
      </div>
    </div>
  )
}

function EntityContentSearchBox({
  label,
  value,
  search,
  activeMatch,
  matchRanges,
  activeMatchRef,
  onSearchChange,
  onStep,
}: {
  label: string
  value: string
  search: string
  activeMatch: number
  matchRanges: Array<{ start: number; end: number }>
  activeMatchRef: (element: HTMLElement | null) => void
  onSearchChange: (value: string) => void
  onStep: (direction: number) => void
}) {
  const matchCount = matchRanges.length
  const hasSearch = Boolean(search.trim())
  const pieces: React.ReactNode[] = []
  let cursor = 0

  matchRanges.forEach((range, index) => {
    if (range.start > cursor) {
      pieces.push(value.slice(cursor, range.start))
    }
    pieces.push(
      <mark
        key={`${range.start}-${range.end}-${index}`}
        ref={index === activeMatch ? activeMatchRef : undefined}
        className={cn(
          'rounded px-0.5',
          index === activeMatch ? 'bg-amber-300 text-slate-950' : 'bg-amber-100 text-slate-900',
        )}
      >
        {value.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })

  if (cursor < value.length) {
    pieces.push(value.slice(cursor))
  }

  return (
    <section
      data-testid="graph-inspector-entity-search"
      className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-3"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-medium text-slate-500">{label}内容</div>
        <div className="text-[11px] text-slate-500">
          {hasSearch ? (matchCount ? `${activeMatch + 1}/${matchCount}` : '0/0') : `${value.length} 字符`}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-1.5">
        <label className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="搜索实体内容"
            className={cn(
              'h-8 w-full rounded-lg border border-[var(--prism-line)] bg-slate-50 pl-7 pr-2 text-xs text-slate-800 placeholder:text-slate-400',
              graphInputFocusClass,
            )}
          />
        </label>
        <button
          type="button"
          onClick={() => onStep(-1)}
          disabled={!matchCount}
          className={cn(
            'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border',
            graphControlTransitionClass,
            graphControlFocusClass,
            matchCount
              ? 'border-[var(--prism-line)] bg-white text-slate-600 hover:bg-slate-100'
              : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400',
          )}
          aria-label="上一个匹配"
          title="上一个匹配"
        >
          <ChevronUp size={14} />
        </button>
        <button
          type="button"
          onClick={() => onStep(1)}
          disabled={!matchCount}
          className={cn(
            'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border',
            graphControlTransitionClass,
            graphControlFocusClass,
            matchCount
              ? 'border-[var(--prism-line)] bg-white text-slate-600 hover:bg-slate-100'
              : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400',
          )}
          aria-label="下一个匹配"
          title="下一个匹配"
        >
          <ChevronDown size={14} />
        </button>
      </div>

      <div className="mt-2 max-h-32 min-h-20 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
        <p className="whitespace-pre-wrap break-words">{matchCount ? pieces : value}</p>
      </div>
    </section>
  )
}

function DetailBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{label}</div>
      <p className="rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
        {value}
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
