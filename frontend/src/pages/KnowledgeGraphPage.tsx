import React, { type PointerEvent, type WheelEvent, useEffect, useMemo, useRef, useState } from 'react'
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

type PositionedNode = UnifiedGraphNode & { x: number; y: number }
type PositionMap = Record<string, { x: number; y: number }>
type PinnedState = Record<string, boolean>
type DragState = { id: string; dx: number; dy: number; originX: number; originY: number; moved: boolean } | null
type PanState = { startX: number; startY: number; originPanX: number; originPanY: number } | null
type DistanceTier = 'focus' | 'near' | 'mid' | 'far' | 'dim'

const minGraphWidth = 1180
const minGraphHeight = 720
const graphNodeClampPadding = 44
const maxNodeVisualExtent = 33
const minGraphZoom = 0.55
const maxGraphZoom = 1.8
const graphZoomStep = 0.15
const scatterPaddingX = graphNodeClampPadding
const scatterPaddingY = graphNodeClampPadding
const scatterMinSpacing = 180
const scatterIdealEdgeLength = 228
const scatterRepelStrength = 18
const scatterAttractStrength = 0.018
const scatterRelaxationPasses = 60
const dragThreshold = 3
const maxExplorerDepth = 3
const defaultVisibleSeedLimit = 4
const defaultVisibleSeedNeighborDepth = 1
const defaultVisibleSeedMinNodeCount = 12
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

function positionKey(view: UnifiedGraphView, nodeId: string) {
  return `${view}:${nodeId}`
}

function clampScatterPoint(point: { x: number; y: number }, width: number, height: number) {
  const pad = scatterPaddingX + maxNodeVisualExtent
  return {
    x: clamp(point.x, pad, width - pad),
    y: clamp(point.y, pad, height - pad),
  }
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

function buildSeedDistanceMap(nodes: UnifiedGraphNode[], edges: UnifiedGraphEdge[], rootIds: string[]) {
  const distances = new Map<string, number>()
  if (!rootIds.length) return distances

  const adjacency = buildAdjacency(nodes, edges)
  const queue: string[] = []

  rootIds.forEach((rootId) => {
    if (!adjacency.has(rootId) || distances.has(rootId)) return
    distances.set(rootId, 0)
    queue.push(rootId)
  })

  for (let index = 0; index < queue.length; index += 1) {
    const currentId = queue[index]
    const currentDistance = distances.get(currentId)
    if (typeof currentDistance !== 'number') continue

    ;(adjacency.get(currentId) ?? []).forEach((neighborId) => {
      const nextDistance = currentDistance + 1
      const seenDistance = distances.get(neighborId)
      if (typeof seenDistance === 'number' && seenDistance <= nextDistance) return
      distances.set(neighborId, nextDistance)
      queue.push(neighborId)
    })
  }

  return distances
}

function selectDefaultVisibleNodeIds(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  {
    seedLimit = defaultVisibleSeedLimit,
    neighborDepth = defaultVisibleSeedNeighborDepth,
    minNodeCount = defaultVisibleSeedMinNodeCount,
  }: {
    seedLimit?: number
    neighborDepth?: number
    minNodeCount?: number
  } = {},
) {
  const allIds = new Set(nodes.map((node) => node.id))
  if (nodes.length <= minNodeCount) return allIds

  const adjacency = buildAdjacency(nodes, edges)
  const rankedSeeds = nodes
    .slice()
    .sort((a, b) => {
      const degreeOrder = (adjacency.get(b.id)?.length ?? 0) - (adjacency.get(a.id)?.length ?? 0)
      if (degreeOrder !== 0) return degreeOrder
      if (a.type === 'entity' && b.type !== 'entity') return -1
      if (a.type !== 'entity' && b.type === 'entity') return 1
      return compareNodeIdentity(a, b)
    })
    .slice(0, seedLimit)

  const visible = new Set<string>(rankedSeeds.map((node) => node.id))
  const queue = rankedSeeds.map((node) => ({ id: node.id, depth: 0 }))
  const seen = new Set<string>(visible)

  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index]
    if (current.depth >= neighborDepth) continue
    ;(adjacency.get(current.id) ?? []).forEach((neighborId) => {
      if (seen.has(neighborId)) return
      seen.add(neighborId)
      visible.add(neighborId)
      queue.push({ id: neighborId, depth: current.depth + 1 })
    })
  }

  return visible.size ? visible : allIds
}

function distanceTier(distance: number | undefined, focusDepth: number): DistanceTier {
  if (distance === 0) return 'focus'
  if (distance === 1) return 'near'
  if (typeof distance !== 'number') return 'dim'
  if (distance <= focusDepth) return 'mid'
  if (distance === focusDepth + 1) return 'far'
  return 'dim'
}

function edgeDistanceTier(
  sourceDistance: number | undefined,
  targetDistance: number | undefined,
  focusDepth: number,
): DistanceTier {
  if (typeof sourceDistance !== 'number' && typeof targetDistance !== 'number') return 'dim'

  const nearest = Math.min(sourceDistance ?? Number.POSITIVE_INFINITY, targetDistance ?? Number.POSITIVE_INFINITY)
  const farthest = Math.max(sourceDistance ?? Number.POSITIVE_INFINITY, targetDistance ?? Number.POSITIVE_INFINITY)

  if (nearest === 0 && farthest <= 1) return 'focus'
  if (farthest <= 1) return 'near'
  if (farthest <= focusDepth) return 'mid'
  if (nearest <= focusDepth && farthest === focusDepth + 1) return 'far'
  return 'dim'
}

function tierOpacity(tier: DistanceTier) {
  switch (tier) {
    case 'focus':
      return 1
    case 'near':
      return 0.98
    case 'mid':
      return 0.88
    case 'far':
      return 0.62
    default:
      return 0.3
  }
}

function tierWeight(tier: DistanceTier) {
  switch (tier) {
    case 'focus':
      return 5
    case 'near':
      return 4
    case 'mid':
      return 3
    case 'far':
      return 2
    default:
      return 1
  }
}

function distanceLabel(distance: number) {
  return distance === 1 ? '1 跳' : `${distance} 跳`
}

function seededScatterPoint(index: number, count: number, width: number, height: number) {
  if (count <= 1) {
    return { x: width / 2, y: height / 2 }
  }

  const angle = index * 2.399963229728653
  const radius = Math.sqrt((index + 0.5) / Math.max(1, count))
  const usableWidth = width - scatterPaddingX * 2
  const usableHeight = height - scatterPaddingY * 2

  return clampScatterPoint({
    x: width / 2 + Math.cos(angle) * radius * (usableWidth / 2),
    y: height / 2 + Math.sin(angle) * radius * (usableHeight / 2),
  }, width, height)
}

function relaxScatterLayout(
  points: Array<{ id: string; x: number; y: number; pinned: boolean }>,
  edges: UnifiedGraphEdge[],
  width: number,
  height: number,
) {
  const relaxed = points.map((point) => ({ ...clampScatterPoint(point, width, height), pinned: point.pinned, id: point.id }))
  const indexById = new Map(relaxed.map((point, index) => [point.id, index]))

  for (let pass = 0; pass < scatterRelaxationPasses; pass += 1) {
    for (let sourceIndex = 0; sourceIndex < relaxed.length; sourceIndex += 1) {
      for (let targetIndex = sourceIndex + 1; targetIndex < relaxed.length; targetIndex += 1) {
        const source = relaxed[sourceIndex]
        const target = relaxed[targetIndex]
        let dx = target.x - source.x
        let dy = target.y - source.y
        let distanceSquared = dx * dx + dy * dy

        if (distanceSquared >= scatterMinSpacing * scatterMinSpacing) continue

        if (distanceSquared < 1) {
          const angle = (sourceIndex + 1) * 1.618 + (targetIndex + 1) * 0.618
          dx = Math.cos(angle)
          dy = Math.sin(angle)
          distanceSquared = dx * dx + dy * dy
        }

        const distance = Math.sqrt(distanceSquared)
        const overlap = (scatterMinSpacing - distance) / scatterMinSpacing
        const pushX = (dx / distance) * overlap * scatterRepelStrength
        const pushY = (dy / distance) * overlap * scatterRepelStrength

        if (!source.pinned && !target.pinned) {
          source.x -= pushX / 2
          source.y -= pushY / 2
          target.x += pushX / 2
          target.y += pushY / 2
        } else if (source.pinned && !target.pinned) {
          target.x += pushX
          target.y += pushY
        } else if (!source.pinned && target.pinned) {
          source.x -= pushX
          source.y -= pushY
        }
      }
    }

    edges.forEach((edge) => {
      const sourceIndex = indexById.get(edge.source)
      const targetIndex = indexById.get(edge.target)
      if (sourceIndex === undefined || targetIndex === undefined) return

      const source = relaxed[sourceIndex]
      const target = relaxed[targetIndex]
      const dx = target.x - source.x
      const dy = target.y - source.y
      const distance = Math.max(1, Math.hypot(dx, dy))
      if (distance <= scatterIdealEdgeLength) return

      const pull = Math.min(10, (distance - scatterIdealEdgeLength) * scatterAttractStrength)
      const pullX = (dx / distance) * pull
      const pullY = (dy / distance) * pull

      if (!source.pinned && !target.pinned) {
        source.x += pullX / 2
        source.y += pullY / 2
        target.x -= pullX / 2
        target.y -= pullY / 2
      } else if (source.pinned && !target.pinned) {
        target.x -= pullX
        target.y -= pullY
      } else if (!source.pinned && target.pinned) {
        source.x += pullX
        source.y += pullY
      }
    })

    relaxed.forEach((point) => {
      if (!point.pinned) {
        point.x += (width / 2 - point.x) * 0.012
        point.y += (height / 2 - point.y) * 0.012
      }
      const clamped = clampScatterPoint(point, width, height)
      point.x = clamped.x
      point.y = clamped.y
    })
  }

  return relaxed
}

function solveFreeScatterLayout(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  view: UnifiedGraphView,
  pinned: PinnedState,
  current: PositionMap,
  width: number,
  height: number,
): PositionMap {
  const adjacency = buildAdjacency(nodes, edges)
  const ordered = nodes.slice().sort((a, b) => {
    const degreeOrder = (adjacency.get(b.id)?.length ?? 0) - (adjacency.get(a.id)?.length ?? 0)
    if (degreeOrder !== 0) return degreeOrder
    return compareNodeIdentity(a, b)
  })

  const floatingNodes = ordered.filter((node) => {
    const key = positionKey(view, node.id)
    return !(pinned[key] && current[key])
  })
  const seededById = new Map(
    floatingNodes.map((node, index) => [node.id, seededScatterPoint(index, floatingNodes.length, width, height)] as const),
  )
  const relaxed = relaxScatterLayout(
    ordered.map((node) => {
      const key = positionKey(view, node.id)
      const pinnedPoint = pinned[key] ? current[key] : undefined
      const seededPoint = seededById.get(node.id) ?? { x: width / 2, y: height / 2 }
      const point = pinnedPoint ? clampScatterPoint(pinnedPoint, width, height) : seededPoint
      return {
        id: node.id,
        x: point.x,
        y: point.y,
        pinned: Boolean(pinnedPoint),
      }
    }),
    edges,
    width,
    height,
  )

  return relaxed.reduce((acc, point) => {
    acc[positionKey(view, point.id)] = { x: point.x, y: point.y }
    return acc
  }, {} as PositionMap)
}

function mergeSolvedPositions(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  current: PositionMap,
  pinned: PinnedState,
  view: UnifiedGraphView,
  width: number,
  height: number,
): PositionMap {
  const solved = solveFreeScatterLayout(nodes, edges, view, pinned, current, width, height)
  return nodes.reduce((acc, node) => {
    const key = positionKey(view, node.id)
    acc[key] = solved[key] ?? current[key] ?? { x: width / 2, y: height / 2 }
    return acc
  }, {} as PositionMap)
}

function pickLayoutDimensions(nodes: UnifiedGraphNode[], positions: PositionMap, view: UnifiedGraphView) {
  const positioned = nodes
    .map((n) => positions[positionKey(view, n.id)])
    .filter((p): p is { x: number; y: number } => Boolean(p))
  return computeNodesBounds(positioned, scatterPaddingX)
}

function omitViewEntries<T>(record: Record<string, T>, view: UnifiedGraphView) {
  const prefix = `${view}:`
  return Object.fromEntries(Object.entries(record).filter(([key]) => !key.startsWith(prefix))) as Record<string, T>
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

function edgeStyle(edge: UnifiedGraphEdge, tier: DistanceTier) {
  const focused = tier === 'focus'
  const strong = tier === 'near'
  const medium = tier === 'mid'
  const faded = tier === 'far'

  if (edge.type === 'related_to' || edge.type === 'co_occurs_with') {
    return {
      stroke: focused ? '#5776a5' : strong ? '#708ab5' : medium ? '#9fb5d0' : faded ? '#d5dfeb' : '#e9eff6',
      strokeWidth: focused ? 2.1 : strong ? 1.7 : medium ? 1.2 : faded ? 0.95 : 0.78,
      strokeDasharray: undefined,
      opacity: focused ? 0.74 : strong ? 0.56 : medium ? 0.28 : faded ? 0.14 : 0.08,
    }
  }

  if (edge.type === 'shares_entity_with') {
    return {
      stroke: focused ? '#9b5c7e' : strong ? '#b27798' : medium ? '#cfacc1' : faded ? '#ead7e1' : '#f5edf1',
      strokeWidth: focused ? 1.95 : strong ? 1.55 : medium ? 1.15 : faded ? 0.92 : 0.78,
      strokeDasharray: '7 6',
      opacity: focused ? 0.7 : strong ? 0.5 : medium ? 0.24 : faded ? 0.12 : 0.07,
    }
  }

  return {
    stroke: focused ? '#4f847f' : strong ? '#699893' : medium ? '#9ec0bb' : faded ? '#d8e7e4' : '#edf4f2',
    strokeWidth: focused ? 1.9 : strong ? 1.5 : medium ? 1.1 : faded ? 0.9 : 0.76,
    strokeDasharray: undefined,
    opacity: focused ? 0.7 : strong ? 0.5 : medium ? 0.24 : faded ? 0.12 : 0.07,
  }
}

function nodeScale(tier: DistanceTier, active: boolean, focusRoot: boolean) {
  if (active) return 1.08
  if (focusRoot) return 1.05
  switch (tier) {
    case 'near':
      return 1.01
    case 'mid':
      return 0.98
    case 'far':
      return 0.95
    case 'dim':
      return 0.93
    default:
      return 1
  }
}

function nodeVisualRadiusForTier(tier: DistanceTier, active: boolean, focusRoot: boolean) {
  if (active || focusRoot) return 26
  if (tier === 'near') return 22
  if (tier === 'mid') return 19
  if (tier === 'far') return 17
  return 15
}

function edgeAnchorRadius(tier: DistanceTier, active: boolean, focusRoot: boolean) {
  return nodeVisualRadiusForTier(tier, active, focusRoot) * nodeScale(tier, active, focusRoot)
}

function nodeDetachedLabelHitArea({
  nodeHitRadius,
  primaryLabelLength,
  showPrimaryLabel,
  showMetaLabel,
  primaryLabelY,
  metaLabelY,
}: {
  nodeHitRadius: number
  primaryLabelLength: number
  showPrimaryLabel: boolean
  showMetaLabel: boolean
  primaryLabelY: number
  metaLabelY: number
}) {
  if (!showPrimaryLabel && !showMetaLabel) {
    return {
      enabled: false,
      x: -nodeHitRadius,
      y: -nodeHitRadius,
      width: nodeHitRadius * 2,
      height: nodeHitRadius * 2,
    }
  }

  const primaryFontSize = showMetaLabel ? 10 : 11
  const metaFontSize = 8
  const primaryHorizontalPadding = showMetaLabel ? 26 : 22
  const primaryLabelWidth = showPrimaryLabel ? primaryLabelLength * primaryFontSize + primaryHorizontalPadding : 0
  const metaLabelWidth = showMetaLabel ? metaFontSize * 8 + 20 : 0
  const labelWidth = Math.max(primaryLabelWidth, metaLabelWidth)
  const width = Math.max(nodeHitRadius * 2, labelWidth)
  const labelTop = showPrimaryLabel ? primaryLabelY - primaryFontSize : metaLabelY - metaFontSize
  const labelBottom = showMetaLabel ? metaLabelY + 10 : primaryLabelY + 10
  const top = Math.min(-nodeHitRadius, labelTop - 12)
  const bottom = Math.max(nodeHitRadius, labelBottom)

  return {
    enabled: true,
    x: -width / 2,
    y: top,
    width,
    height: bottom - top,
  }
}

function nodeShadow(tier: DistanceTier, active: boolean, focusRoot: boolean) {
  if (active) return 'drop-shadow(0 10px 20px rgb(148 163 184 / 0.18))'
  if (focusRoot) return 'drop-shadow(0 8px 16px rgb(148 163 184 / 0.14))'
  if (tier === 'near') return 'drop-shadow(0 6px 12px rgb(148 163 184 / 0.12))'
  if (tier === 'mid') return 'drop-shadow(0 4px 8px rgb(148 163 184 / 0.08))'
  return undefined
}

function svgPoint(svg: SVGSVGElement, event: PointerEvent<SVGSVGElement>) {
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  return point.matrixTransform(svg.getScreenCTM()?.inverse())
}

function formatConfidence(value?: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '-'
}

function countFor(payload: UnifiedGraphPayload | null, type: UnifiedGraphNodeType) {
  return payload?.stats.node_counts[type] ?? 0
}

function graphNodeAriaLabel(node: UnifiedGraphNode, metaLabel: string, active: boolean, focusRoot: boolean) {
  const states = [metaLabel]
  if (focusRoot) states.push('当前焦点')
  if (active) states.push('当前选中')
  return `图节点 ${node.label}，状态：${states.join('、')}`
}

function computeNodesBounds(nodes: Array<{ x: number; y: number }>, padding: number) {
  if (!nodes.length) {
    return { minX: 0, minY: 0, maxX: minGraphWidth, maxY: minGraphHeight, width: minGraphWidth, height: minGraphHeight }
  }
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  nodes.forEach((n) => {
    if (n.x < minX) minX = n.x
    if (n.y < minY) minY = n.y
    if (n.x > maxX) maxX = n.x
    if (n.y > maxY) maxY = n.y
  })
  const padX = padding + maxNodeVisualExtent + 60
  const padY = padding + maxNodeVisualExtent + 80
  const rawW = maxX - minX + padX * 2
  const rawH = maxY - minY + padY * 2
  const width = Math.max(minGraphWidth, rawW)
  const height = Math.max(minGraphHeight, rawH)
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  const halfW = width / 2
  const halfH = height / 2
  return {
    minX: cx - halfW,
    minY: cy - halfH,
    maxX: cx + halfW,
    maxY: cy + halfH,
    width,
    height,
  }
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
  const initialView = initialGraphView(initialPayload)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const graphContainerRef = useRef<HTMLDivElement | null>(null)
  const [graphContainerWidth, setGraphContainerWidth] = useState(minGraphWidth)
  const [graphContainerHeight, setGraphContainerHeight] = useState(minGraphHeight)
  const didDragRef = useRef(false)
  const hasEverFittedRef = useRef(false)
  const justDraggedRef = useRef(false)
  const justDraggedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pinnedRef = useRef<PinnedState>({})
  const skipInitialLoadRef = useRef(Boolean(initialPayload))
  const loadRunnerRef = useRef(createLatestRequestRunner())
  const [payload, setPayload] = useState<UnifiedGraphPayload | null>(initialPayload)
  const [positions, setPositions] = useState<PositionMap>(() =>
    initialPayload
      ? mergeSolvedPositions(
          initialPayload.nodes,
          initialPayload.edges,
          {},
          {},
          initialView,
          Math.max(minGraphWidth, graphContainerWidth || minGraphWidth),
          Math.max(minGraphHeight, graphContainerHeight || minGraphHeight),
        )
      : {},
  )
  const [pinned, setPinned] = useState<PinnedState>({})
  const [query, setQuery] = useState(() => initialPayload?.focus?.query ?? '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId)
  const [focusRootId, setFocusRootId] = useState<string | null>(initialSelectedId)
  const [focusDepth, setFocusDepth] = useState(1)
  const [view, setView] = useState<UnifiedGraphView>(() => initialPayload?.focus?.view ?? initialPayload?.view ?? 'entity')
  const [graphZoom, setGraphZoom] = useState(1)
  const [dragging, setDragging] = useState<DragState>(null)
  const [panning, setPanning] = useState<PanState>(null)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const draggingRef = useRef<DragState>(null)
  const panningRef = useRef<PanState>(null)
  const panXRef = useRef(0)
  const panYRef = useRef(0)

  useEffect(() => { draggingRef.current = dragging }, [dragging])
  useEffect(() => { panningRef.current = panning }, [panning])
  useEffect(() => { panXRef.current = panX }, [panX])
  useEffect(() => { panYRef.current = panY }, [panY])
  const [typeFilter, setTypeFilter] = useState<Set<UnifiedGraphNodeType>>(
    () => new Set<UnifiedGraphNodeType>(['entity', 'document_chunk']),
  )
  const [showFilterMenu, setShowFilterMenu] = useState(false)

  useEffect(() => {
    pinnedRef.current = pinned
  }, [pinned])

  useEffect(() => {
    return () => {
      if (justDraggedTimerRef.current) {
        clearTimeout(justDraggedTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    const el = graphContainerRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) {
        setGraphContainerWidth(entry.contentRect.width)
        setGraphContainerHeight(entry.contentRect.height)
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const layoutWidth = Math.max(minGraphWidth, graphContainerWidth)
  const layoutHeight = Math.max(minGraphHeight, graphContainerHeight)

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
          setPositions((current) => {
            const dims = pickLayoutDimensions(data.nodes, current, nextView)
            const w = Math.max(dims.width, graphContainerWidth, minGraphWidth)
            const h = Math.max(dims.height, graphContainerHeight, minGraphHeight)
            return {
              ...current,
              ...mergeSolvedPositions(
                data.nodes,
                data.edges,
                current,
                pinnedRef.current,
                nextView,
                w,
                h,
              ),
            }
          })
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

  const nodes = useMemo<PositionedNode[]>(
    () =>
      (payload?.nodes ?? []).map((node) => ({
        ...node,
        ...(positions[positionKey(view, node.id)] ?? { x: layoutWidth / 2, y: layoutHeight / 2 }),
      })),
    [payload?.nodes, positions, view, layoutWidth, layoutHeight],
  )

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
  const defaultVisibleNodeIds = useMemo(
    () => selectDefaultVisibleNodeIds(payload?.nodes ?? [], payload?.edges ?? []),
    [payload?.edges, payload?.nodes],
  )
  const defaultSeedDistances = useMemo(
    () => buildSeedDistanceMap(payload?.nodes ?? [], payload?.edges ?? [], Array.from(defaultVisibleNodeIds)),
    [defaultVisibleNodeIds, payload?.edges, payload?.nodes],
  )
  const visibleNodeIds = useMemo(() => {
    if (focusRoot?.id || selected?.id) return null
    return defaultVisibleNodeIds
  }, [defaultVisibleNodeIds, focusRoot?.id, selected?.id])
  const activeDistances = focusRoot?.id ? focusDistances : defaultSeedDistances
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
  const nodeTiers = useMemo(
    () => new Map(nodes.map((node) => [node.id, distanceTier(activeDistances.get(node.id), focusDepth)] as const)),
    [activeDistances, focusDepth, nodes],
  )
  const renderedNodes = useMemo(
    () =>
      nodes
        .filter((node) => !visibleNodeIds || visibleNodeIds.has(node.id))
        .filter((node) => typeFilter.has(node.type))
        .slice()
        .sort((a, b) => {
          const tierOrder = tierWeight(nodeTiers.get(a.id) ?? 'dim') - tierWeight(nodeTiers.get(b.id) ?? 'dim')
          if (tierOrder !== 0) return tierOrder
          if (selected?.id === a.id) return 1
          if (selected?.id === b.id) return -1
          if (focusRoot?.id === a.id) return 1
          if (focusRoot?.id === b.id) return -1
          return compareNodeIdentity(a, b)
        }),
    [focusRoot?.id, nodeTiers, nodes, selected?.id, visibleNodeIds, typeFilter],
  )
  const renderedEdges = useMemo(
    () =>
      (payload?.edges ?? [])
        .filter((edge) => !visibleNodeIds || (visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)))
        .filter((edge) => {
          const source = nodeById.get(edge.source)
          const target = nodeById.get(edge.target)
          return source && target && typeFilter.has(source.type) && typeFilter.has(target.type)
        })
        .map((edge) => {
          let tier = edgeDistanceTier(activeDistances.get(edge.source), activeDistances.get(edge.target), focusDepth)
          if (tier === 'dim' && selected?.id && (selected.id === edge.source || selected.id === edge.target)) {
            tier = 'far'
          }
          return { edge, tier }
        })
        .sort((a, b) => tierWeight(a.tier) - tierWeight(b.tier)),
    [activeDistances, focusDepth, payload?.edges, selected?.id, visibleNodeIds, typeFilter, nodeById],
  )
  const selectedEdges = useMemo(
    () => (payload?.edges ?? []).filter((edge) => edge.source === selected?.id || edge.target === selected?.id),
    [payload?.edges, selected?.id],
  )
  const relatedNodes = useMemo(
    () => {
      const deduped = new Map<string, PositionedNode>()
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

  const graphBounds = useMemo(
    () => computeNodesBounds(renderedNodes, scatterPaddingX),
    [renderedNodes],
  )
  const graphWidth = graphBounds.width
  const graphHeight = graphBounds.height
  const graphViewMinX = graphBounds.minX
  const graphViewMinY = graphBounds.minY

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

  const setZoom = (nextZoom: number) => {
    setGraphZoom(clamp(Number(nextZoom.toFixed(2)), minGraphZoom, maxGraphZoom))
  }

  const zoomIn = () => setZoom(graphZoom + graphZoomStep)
  const zoomOut = () => setZoom(graphZoom - graphZoomStep)
  const applyFitToContainer = (bounds: { width: number; height: number; minX: number; minY: number }) => {
    const cw = graphContainerWidth
    const ch = graphContainerHeight
    if (bounds.width <= 0 || bounds.height <= 0 || cw <= 0 || ch <= 0) {
      setGraphZoom(1)
      panXRef.current = 0
      panYRef.current = 0
      setPanX(0)
      setPanY(0)
      return
    }
    const pad = 64
    const scaleX = (cw - pad * 2) / bounds.width
    const scaleY = (ch - pad * 2) / bounds.height
    const fitZoom = clamp(Math.min(scaleX, scaleY), minGraphZoom, maxGraphZoom)
    const contentCenterX = bounds.minX + bounds.width / 2
    const contentCenterY = bounds.minY + bounds.height / 2
    const fitPanX = contentCenterX * (1 - fitZoom)
    const fitPanY = contentCenterY * (1 - fitZoom)
    setGraphZoom(fitZoom)
    panXRef.current = fitPanX
    panYRef.current = fitPanY
    setPanX(fitPanX)
    setPanY(fitPanY)
  }

  const fitGraph = () => {
    if (!renderedNodes.length) {
      setGraphZoom(1)
      panXRef.current = 0
      panYRef.current = 0
      setPanX(0)
      setPanY(0)
      return
    }
    applyFitToContainer(graphBounds)
  }
  const resetScatterLayout = () => {
    if (!payload) return

    const nextPinned = omitViewEntries(pinnedRef.current, view)
    pinnedRef.current = nextPinned
    setPinned(nextPinned)
    const w = Math.max(graphContainerWidth, minGraphWidth)
    const h = Math.max(graphContainerHeight, minGraphHeight)
    setPositions((current) => {
      const nextPositions = omitViewEntries(current, view)
      return {
        ...nextPositions,
        ...mergeSolvedPositions(payload.nodes, payload.edges, nextPositions, nextPinned, view, w, h),
      }
    })
    setGraphZoom(1)
    panXRef.current = 0
    panYRef.current = 0
    setPanX(0)
    setPanY(0)
    hasEverFittedRef.current = false
  }

  const applyFitToContainerRef = useRef(applyFitToContainer)
  applyFitToContainerRef.current = applyFitToContainer

  useEffect(() => {
    if (!payload || !renderedNodes.length) return
    const cw = graphContainerWidth
    const ch = graphContainerHeight
    if (cw <= 0 || ch <= 0) return
    if (hasEverFittedRef.current) return

    hasEverFittedRef.current = true
    const raf = requestAnimationFrame(() => {
      applyFitToContainerRef.current(graphBounds)
    })
    return () => cancelAnimationFrame(raf)
  }, [payload, renderedNodes.length, graphContainerWidth, graphContainerHeight, graphBounds])

  const handlePointerDown = (event: PointerEvent<SVGGElement>, node: PositionedNode) => {
    const svg = svgRef.current
    if (!svg) return
    didDragRef.current = false
    justDraggedRef.current = false
    if (justDraggedTimerRef.current) {
      clearTimeout(justDraggedTimerRef.current)
      justDraggedTimerRef.current = null
    }
    const point = svgPoint(svg, event as unknown as PointerEvent<SVGSVGElement>)
    const dragState: DragState = {
      id: node.id,
      dx: point.x - node.x,
      dy: point.y - node.y,
      originX: node.x,
      originY: node.y,
      moved: false,
    }
    draggingRef.current = dragState
    setDragging(dragState)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handleSvgPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    const target = event.target as SVGElement
    if (target.closest('[role="button"]')) return

    const svg = svgRef.current
    if (!svg) return
    const point = svgPoint(svg, event)
    const panState: PanState = { startX: point.x, startY: point.y, originPanX: panXRef.current, originPanY: panYRef.current }
    panningRef.current = panState
    setPanning(panState)
    svg.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const currentDrag = draggingRef.current
    if (currentDrag && svgRef.current) {
      const bounds = graphBounds
      const dragPad = graphNodeClampPadding + maxNodeVisualExtent
      const point = svgPoint(svgRef.current, event)
      const x = clamp(point.x - currentDrag.dx, bounds.minX + dragPad, bounds.maxX - dragPad)
      const y = clamp(point.y - currentDrag.dy, bounds.minY + dragPad, bounds.maxY - dragPad)
      const moved =
        currentDrag.moved || Math.abs(x - currentDrag.originX) >= dragThreshold || Math.abs(y - currentDrag.originY) >= dragThreshold
      if (!moved) return

      didDragRef.current = true
      const key = positionKey(view, currentDrag.id)
      setPositions((current) => ({ ...current, [key]: { x, y } }))
      setPinned((current) => {
        if (current[key]) return current
        const next = { ...current, [key]: true }
        pinnedRef.current = next
        return next
      })
      const updatedDrag = { ...currentDrag, moved: true }
      draggingRef.current = updatedDrag
      setDragging(updatedDrag)
      return
    }

    const currentPan = panningRef.current
    if (currentPan && svgRef.current) {
      const point = svgPoint(svgRef.current, event)
      const dx = point.x - currentPan.startX
      const dy = point.y - currentPan.startY
      const nextPanX = currentPan.originPanX + dx
      const nextPanY = currentPan.originPanY + dy
      panXRef.current = nextPanX
      panYRef.current = nextPanY
      setPanX(nextPanX)
      setPanY(nextPanY)
      return
    }
  }

  const stopInteraction = () => {
    const currentDrag = draggingRef.current
    if (didDragRef.current || currentDrag?.moved) {
      justDraggedRef.current = true
      if (justDraggedTimerRef.current) {
        clearTimeout(justDraggedTimerRef.current)
      }
      justDraggedTimerRef.current = setTimeout(() => {
        justDraggedRef.current = false
        justDraggedTimerRef.current = null
      }, 0)
    }
    didDragRef.current = false
    draggingRef.current = null
    panningRef.current = null
    setDragging(null)
    setPanning(null)
  }

  const handleNodeSelect = (nodeId: string) => {
    if (justDraggedRef.current) {
      justDraggedRef.current = false
      return
    }
    inspectNode(nodeId)
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

  const handleGraphWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return
    event.preventDefault()
    const svg = svgRef.current
    if (!svg) return
    const point = svgPoint(svg, event as unknown as PointerEvent<SVGSVGElement>)
    const oldZoom = graphZoom
    const newZoom = clamp(oldZoom + (event.deltaY > 0 ? -graphZoomStep : graphZoomStep), minGraphZoom, maxGraphZoom)
    const scale = newZoom / oldZoom
    const newPanX = point.x - scale * (point.x - panXRef.current)
    const newPanY = point.y - scale * (point.y - panYRef.current)
    setZoom(newZoom)
    panXRef.current = newPanX
    panYRef.current = newPanY
    setPanX(newPanX)
    setPanY(newPanY)
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
          <div className="min-w-14 text-center text-xs font-medium text-slate-500">{Math.round(graphZoom * 100)}%</div>
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
            onClick={resetScatterLayout}
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
            onClick={fitGraph}
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
          <div
            ref={graphContainerRef}
            className="relative min-h-0 h-full overflow-auto rounded-[24px] border border-white/70 bg-[radial-gradient(circle_at_50%_42%,_rgba(255,255,255,0.72),_rgba(255,255,255,0.08)_58%,_rgba(219,231,244,0.16)_100%),linear-gradient(135deg,_#fffefb_0%,_#f8f8f4_52%,_#eff4fb_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.42)]"
            onWheel={handleGraphWheel}
          >
            {!nodes.length ? (
              <div className="flex min-h-full items-center justify-center px-6 py-10">
                <GraphCanvasGuidance hasGraphData={false} />
              </div>
            ) : (
              <>
                <svg
                  ref={svgRef}
                  viewBox={`${graphViewMinX} ${graphViewMinY} ${graphWidth} ${graphHeight}`}
                  preserveAspectRatio="xMidYMid meet"
                  className="block h-full w-full touch-none select-none"
                  role="group"
                  aria-label={view === 'entity' ? '实体图谱浏览器' : '来源图谱浏览器'}
                  aria-roledescription="交互式知识图谱"
                  onPointerDown={handleSvgPointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={stopInteraction}
                  onPointerLeave={stopInteraction}
                  onPointerCancel={stopInteraction}
                >
                  <title>{view === 'entity' ? '实体图谱浏览器' : '来源图谱浏览器'}</title>
                  <desc>
                    交互式图谱，展示实体、文档分块及其关联证据与关系。
                  </desc>
                  <defs>
                    <linearGradient id="graph-drift" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#fffefb" />
                      <stop offset="52%" stopColor="#f8f8f4" />
                      <stop offset="100%" stopColor="#eff4fb" />
                    </linearGradient>
                    <radialGradient id="graph-haze" cx="50%" cy="50%" r="70%">
                      <stop offset="0%" stopColor="#ffffff" stopOpacity="0.66" />
                      <stop offset="68%" stopColor="#ffffff" stopOpacity="0.1" />
                      <stop offset="100%" stopColor="#dbe7f4" stopOpacity="0.12" />
                    </radialGradient>
                    <linearGradient id="node-sheen" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#ffffff" stopOpacity="0.52" />
                      <stop offset="45%" stopColor="#ffffff" stopOpacity="0.12" />
                      <stop offset="100%" stopColor="#ffffff" stopOpacity="0.02" />
                    </linearGradient>
                    {(['focus', 'near', 'mid', 'far', 'dim'] as DistanceTier[]).map((tier) => {
                      const markerColor =
                        tier === 'focus'
                          ? '#68778b'
                          : tier === 'near'
                            ? '#8692a2'
                            : tier === 'mid'
                              ? '#b0b8c4'
                              : tier === 'far'
                                ? '#d1d7de'
                                : '#e8ecf0'
                      return (
                        <marker
                          key={`graph-arrow-${tier}`}
                          id={`graph-arrow-${tier}`}
                          markerWidth="8"
                          markerHeight="8"
                          refX="7"
                          refY="3"
                          orient="auto"
                        >
                          <path d="M0,0 L7,3 L0,6 Z" fill={markerColor} />
                        </marker>
                      )
                    })}
                  </defs>
                  <rect
                    x={graphViewMinX}
                    y={graphViewMinY}
                    width={graphWidth}
                    height={graphHeight}
                    fill="url(#graph-drift)"
                    pointerEvents="none"
                  />
                  <rect
                    x={graphViewMinX}
                    y={graphViewMinY}
                    width={graphWidth}
                    height={graphHeight}
                    fill="url(#graph-haze)"
                    opacity="0.9"
                    pointerEvents="none"
                  />
                  <g transform={`translate(${panX}, ${panY}) scale(${graphZoom})`}>
                    {renderedEdges.map(({ edge, tier }) => {
                      const source = nodeById.get(edge.source)
                      const target = nodeById.get(edge.target)
                      if (!source || !target) return null
                      const sourceTier = nodeTiers.get(source.id) ?? 'dim'
                      const targetTier = nodeTiers.get(target.id) ?? 'dim'
                      const sourceActive = selected?.id === source.id
                      const targetActive = selected?.id === target.id
                      const sourceFocusRoot = focusRoot?.id === source.id
                      const targetFocusRoot = focusRoot?.id === target.id
                      const dx = target.x - source.x
                      const dy = target.y - source.y
                      const distance = Math.max(1, Math.hypot(dx, dy))
                      const sourceRadius = edgeAnchorRadius(sourceTier, sourceActive, sourceFocusRoot)
                      const targetRadius = edgeAnchorRadius(targetTier, targetActive, targetFocusRoot)
                      const sx = source.x + (dx / distance) * sourceRadius
                      const sy = source.y + (dy / distance) * sourceRadius
                      const tx = target.x - (dx / distance) * targetRadius
                      const ty = target.y - (dy / distance) * targetRadius
                      const curve = Math.min(96, distance * 0.35)
                      const cx1 = sx + (dx / distance) * curve
                      const cy1 = sy + (dy / distance) * curve
                      const cx2 = tx - (dx / distance) * curve
                      const cy2 = ty - (dy / distance) * curve
                      const style = edgeStyle(edge, tier)
                      return (
                        <path
                          key={edge.id}
                          d={`M ${sx} ${sy} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${tx} ${ty}`}
                          fill="none"
                          stroke={style.stroke}
                          strokeWidth={style.strokeWidth}
                          strokeDasharray={style.strokeDasharray}
                          opacity={style.opacity}
                          markerEnd={`url(#graph-arrow-${tier})`}
                          pointerEvents="none"
                        />
                      )
                    })}
                  </g>
                  <g transform={`translate(${panX}, ${panY}) scale(${graphZoom})`}>
                    {renderedNodes.map((node) => (
                      <GraphNode
                        key={node.id}
                        node={node}
                        active={selected?.id === node.id}
                        focusRoot={focusRoot?.id === node.id}
                        tier={nodeTiers.get(node.id) ?? 'dim'}
                        dragging={dragging?.id === node.id}
                        onPointerDown={(event) => handlePointerDown(event, node)}
                        onSelect={() => {
                          if (dragging?.moved) return
                          handleNodeSelect(node.id)
                        }}
                      />
                    ))}
                  </g>
                </svg>
                {!selected ? (
                  <div className="pointer-events-none absolute inset-x-6 bottom-6 z-10 flex justify-start">
                    <GraphCanvasGuidance hasGraphData />
                  </div>
                ) : null}
              </>
            )}
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

function GraphNode({
  node,
  active,
  focusRoot,
  tier,
  dragging,
  onPointerDown,
  onSelect,
}: {
  node: PositionedNode
  active: boolean
  focusRoot: boolean
  tier: DistanceTier
  dragging: boolean
  onPointerDown: (event: PointerEvent<SVGGElement>) => void
  onSelect: () => void
}) {
  const meta = getNodeMeta(node.type)
  const scale = nodeScale(tier, active, focusRoot)
  const shadow = nodeShadow(tier, active, focusRoot)
  const showPrimaryLabel = active || focusRoot || tier === 'near' || (node.type === 'entity' && tier === 'mid')
  const showMetaLabel = active || focusRoot || tier === 'near'
  const nodeVisualRadius = nodeVisualRadiusForTier(tier, active, focusRoot)
  const nodeHitRadius = Math.max(nodeVisualRadius + 10, 24)
  const nodeHaloRadius = nodeVisualRadius + (active || focusRoot ? 7 : tier === 'near' ? 5 : 4)
  const strokeWidth = active ? 2.2 : focusRoot ? 1.8 : tier === 'near' ? 1.25 : tier === 'mid' ? 1.1 : 0.95
  const bodyFill = active || focusRoot ? '#ffffff' : tier === 'dim' ? '#f8fafc' : '#fcfdff'
  const stroke =
    active || focusRoot ? meta.color : tier === 'near' ? '#b8c3cf' : tier === 'mid' ? '#ccd6e2' : '#dbe3ec'
  const tintOpacity = active || focusRoot ? 0.2 : tier === 'near' ? 0.18 : tier === 'mid' ? 0.15 : tier === 'far' ? 0.11 : 0.08
  const primaryLabelY = nodeVisualRadius + 18
  const primaryLabelSize = showMetaLabel ? 'text-[10px]' : 'text-[11px]'
  const primaryLabelLength = showMetaLabel ? 12 : 14
  const metaLabelY = nodeVisualRadius + 31
  const nodeLabelHitArea = nodeDetachedLabelHitArea({
    nodeHitRadius,
    primaryLabelLength,
    showPrimaryLabel,
    showMetaLabel,
    primaryLabelY,
    metaLabelY,
  })
  const nodeHitX = nodeLabelHitArea.x
  const nodeHitWidth = nodeLabelHitArea.width
  const nodeHitHeight = nodeLabelHitArea.height
  const nodeHitY = nodeLabelHitArea.y
  const handleKeyDown = (event: React.KeyboardEvent<SVGGElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onSelect()
  }
  return (
    <g
      transform={`translate(${node.x} ${node.y}) scale(${scale})`}
      onPointerDown={onPointerDown}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={cn('cursor-grab', dragging && 'cursor-grabbing')}
      opacity={active ? 1 : tierOpacity(tier)}
      role="button"
      tabIndex={0}
      aria-pressed={active}
      aria-label={graphNodeAriaLabel(node, meta.label, active, focusRoot)}
    >
      {!showPrimaryLabel && !showMetaLabel ? (
        <title>{node.label}</title>
      ) : null}
      {nodeLabelHitArea.enabled ? (
        <rect
          x={nodeHitX}
          y={nodeHitY}
          width={nodeHitWidth}
          height={nodeHitHeight}
          rx={Math.min(nodeHitHeight / 2, nodeHitRadius)}
          fill="transparent"
          pointerEvents="all"
        />
      ) : null}
      <circle
        cx="0"
        cy="0"
        r={nodeHitRadius}
        fill="transparent"
        pointerEvents="all"
      />
      <circle
        cx="0"
        cy="0"
        r={nodeHaloRadius}
        fill={meta.fill}
        opacity={active || focusRoot ? 0.42 : tier === 'near' ? 0.3 : tier === 'mid' ? 0.24 : tier === 'far' ? 0.18 : 0.14}
        pointerEvents="none"
      />
      <circle
        cx="0"
        cy="0"
        r={nodeVisualRadius}
        fill={bodyFill}
        stroke={stroke}
        strokeWidth={strokeWidth}
        filter={shadow}
        pointerEvents="none"
      />
      <circle
        cx="0"
        cy="0"
        r={Math.max(0, nodeVisualRadius - 1.5)}
        fill={meta.fill}
        opacity={tintOpacity}
        pointerEvents="none"
      />
      {!active && !focusRoot ? (
        <circle
          cx="0"
          cy="0"
          r={Math.max(0, nodeVisualRadius - 1.5)}
          fill="url(#node-sheen)"
          opacity={tier === 'near' ? 0.22 : tier === 'mid' ? 0.16 : 0.1}
          pointerEvents="none"
        />
      ) : null}
      <circle
        cx="0"
        cy="0"
        r="5.5"
        fill={meta.color}
        opacity={active || focusRoot ? 0.96 : tier === 'dim' ? 0.46 : tier === 'far' ? 0.62 : 0.72}
        pointerEvents="none"
      />
      {showPrimaryLabel ? (
        <text
          x="0"
          y={primaryLabelY}
          textAnchor="middle"
          className={cn('fill-slate-900 font-medium', primaryLabelSize)}
          pointerEvents="none"
        >
          {truncate(node.label, primaryLabelLength)}
        </text>
      ) : null}
      {showMetaLabel ? (
        <text
          x="0"
          y={metaLabelY}
          textAnchor="middle"
          className={cn(
            'text-[8px] font-medium',
            tier === 'dim' ? 'fill-slate-400' : focusRoot || active ? 'fill-slate-600' : 'fill-slate-500',
          )}
          pointerEvents="none"
        >
          {meta.label}
        </text>
      ) : null}
    </g>
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
  node: PositionedNode | null
  view: UnifiedGraphView
  edges: UnifiedGraphEdge[]
  nodes: Map<string, PositionedNode>
  relatedNodes: PositionedNode[]
  focusRoot: PositionedNode | null
  focusDepth: number
  explorerNodes: PositionedNode[]
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
