import { Graph, type EdgeData, type GraphData, type NodeData } from '@antv/g6'
import { useCallback, useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import type { UnifiedGraphEdge, UnifiedGraphNode, UnifiedGraphNodeType } from '@/app/api'

// 节点配色沿用 Prism 现状：实体=蓝、分块=青（与 KnowledgeGraphPage.tsx 的 nodeMeta 保持一致）。
const ENTITY_COLOR = '#155eef'
const CHUNK_COLOR = '#0f766e'
const FALLBACK_NODE_COLOR = '#475569'

// 关系边按类型取色（对齐 Yuxi GraphCanvas 的调色板思路）。
const EDGE_COLORS = [
  '#99add1',
  '#3996ae',
  '#13c2c2',
  '#faad14',
  '#f27c7c',
  '#9581cc',
  '#52c41a',
  '#ff9d4d',
]

function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

function nodeColor(type: string): string {
  if (type === 'entity') return ENTITY_COLOR
  if (type === 'document_chunk') return CHUNK_COLOR
  return FALLBACK_NODE_COLOR
}

function edgeColor(type: string): string {
  return EDGE_COLORS[hashString(type) % EDGE_COLORS.length]
}

/** 把 Prism 的 UnifiedGraph 数据映射成 G6 的 { id / source / target / data } 结构。 */
export function formatGraphData(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  typeFilter: Set<UnifiedGraphNodeType>,
): GraphData {
  const visible = new Set(nodes.filter((node) => typeFilter.has(node.type)).map((node) => node.id))

  const degree = new Map<string, number>()
  nodes.forEach((node) => degree.set(node.id, 0))
  edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  })

  const g6Nodes: NodeData[] = nodes
    .filter((node) => visible.has(node.id))
    .map((node) => ({
      id: String(node.id),
      data: {
        label: node.label ?? String(node.id),
        color: nodeColor(node.type),
        degree: degree.get(node.id) ?? 0,
        original: node,
      },
    }))

  const g6Edges: EdgeData[] = edges
    .filter((edge) => visible.has(edge.source) && visible.has(edge.target))
    .map((edge, index) => ({
      id: edge.id ? String(edge.id) : `edge-${index}`,
      source: String(edge.source),
      target: String(edge.target),
      data: {
        label: edge.label || edge.type || '',
        color: edgeColor(edge.type),
        original: edge,
      },
    }))

  return { nodes: g6Nodes, edges: g6Edges }
}

// d3-force 布局参数对齐 Yuxi GraphCanvas.vue 的 defaultLayout。
const DEFAULT_LAYOUT = {
  type: 'd3-force',
  preventOverlap: true,
  alphaDecay: 0.1,
  alphaMin: 0.01,
  velocityDecay: 0.6,
  iterations: 150,
  force: {
    center: { x: 0.5, y: 0.5, strength: 0.1 },
    charge: { strength: -400, distanceMax: 600 },
    link: { distance: 100, strength: 0.8 },
  },
  collide: { radius: 40, strength: 0.8, iterations: 3 },
}

// 交互行为对齐 Yuxi：拖拽/缩放/平移/悬浮 + 点选单跳高亮（click-select degree:1）。
const BEHAVIORS = [
  'drag-element',
  'zoom-canvas',
  'drag-canvas',
  'hover-activate',
  {
    type: 'click-select',
    degree: 1,
    state: 'selected',
    neighborState: 'active',
    unselectedState: 'inactive',
    multiple: true,
    trigger: ['shift'],
    disableDefault: false,
  },
]

export interface UseG6GraphOptions {
  containerRef: RefObject<HTMLDivElement | null>
  data: GraphData
  onNodeClick?: (nodeId: string) => void
  onCanvasClick?: () => void
}

export interface G6GraphHandle {
  fitView: () => void
  zoomIn: () => void
  zoomOut: () => void
  relayout: () => void
}

/** 把 Yuxi GraphCanvas.vue 的 G6 初始化翻译成 React hook。 */
export function useG6Graph({ containerRef, data, onNodeClick, onCanvasClick }: UseG6GraphOptions): G6GraphHandle {
  const graphRef = useRef<Graph | null>(null)
  const callbacksRef = useRef({ onNodeClick, onCanvasClick })
  callbacksRef.current = { onNodeClick, onCanvasClick }
  const dataRef = useRef(data)
  dataRef.current = data

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let disposed = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const init = () => {
      if (disposed) return
      const width = container.clientWidth
      const height = container.clientHeight
      if (width === 0 || height === 0) {
        retryTimer = setTimeout(init, 200)
        return
      }

      const graph = new Graph({
        container,
        width,
        height,
        autoFit: 'view',
        autoResize: true,
        layout: DEFAULT_LAYOUT,
        node: {
          type: 'circle',
          style: {
            labelText: (d: any) => d.data.label,
            labelFill: '#334155',
            labelWordWrap: true,
            labelMaxWidth: '300%',
            size: (d: any) => Math.min(15 + d.data.degree * 5, 50),
            fill: (d: any) => d.data.color,
            opacity: 0.9,
            stroke: '#ffffff',
            lineWidth: 1.5,
          },
        },
        edge: {
          type: 'quadratic',
          style: {
            labelText: (d: any) => d.data.label,
            labelFill: '#475569',
            labelBackground: true,
            labelBackgroundFill: '#f8fafc',
            stroke: (d: any) => d.data.color,
            opacity: 0.8,
            lineWidth: 1.2,
            endArrow: true,
          },
        },
        behaviors: BEHAVIORS,
      })

      graph.on('node:click', (evt: any) => {
        callbacksRef.current.onNodeClick?.(String(evt.target.id))
      })
      graph.on('canvas:click', (evt: any) => {
        if (!evt.target) callbacksRef.current.onCanvasClick?.()
      })

      graph.setData(dataRef.current)
      graph.render()

      graphRef.current = graph
    }

    init()

    return () => {
      disposed = true
      if (retryTimer) clearTimeout(retryTimer)
      graphRef.current?.destroy()
      graphRef.current = null
    }
  }, [containerRef])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.setData(data)
    graph.render()
  }, [data])

  const fitView = useCallback(() => {
    graphRef.current?.fitView()
  }, [])

  const zoomIn = useCallback(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.zoomTo(graph.getZoom() * 1.15)
  }, [])

  const zoomOut = useCallback(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.zoomTo(graph.getZoom() * 0.85)
  }, [])

  const relayout = useCallback(() => {
    graphRef.current?.layout()
  }, [])

  return { fitView, zoomIn, zoomOut, relayout }
}
