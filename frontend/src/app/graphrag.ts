import type { GraphRagExplain, GraphRagPathEntry, GraphRagPathRoute, GraphRagPathStep } from './api'

type GraphRagNodeLike = {
  graph_rag?: { explain?: GraphRagExplain } | null
  evidence_type?: GraphRagExplain['evidence_type']
}

type GraphRagEdgeLike = GraphRagNodeLike & {
  reason?: string | null
  evidence_span?: string | null
}

export function evidenceTypeLabel(evidenceType: string | undefined) {
  if (evidenceType === 'INFERRED') return '\u56fe\u63a8\u65ad'
  if (evidenceType === 'EXTRACTED') return '\u76f4\u63a5\u8bc1\u636e'
  return evidenceType
}

export function graphStepLabel(step: GraphRagPathStep) {
  if (typeof step.label === 'string' && step.label.trim()) return step.label
  if (typeof step.edge_type === 'string' && step.edge_type.trim()) return step.edge_type
  if (typeof step.node_id === 'string' && step.node_id.trim()) return step.node_id
  return 'step'
}

function isGraphRagPathRoute(entry: GraphRagPathEntry): entry is GraphRagPathRoute {
  return Array.isArray((entry as GraphRagPathRoute).steps)
}

export function graphPathLabels(graphPath: GraphRagPathEntry[]) {
  return graphPath.flatMap((entry) => {
    if (isGraphRagPathRoute(entry) && entry.steps.length > 0) {
      const sourceMarker = typeof entry.source_marker === 'string' && entry.source_marker.trim()
        ? entry.source_marker
        : '图谱路径'
      const matchedEntityIds = Array.isArray(entry.matched_entity_ids)
        ? entry.matched_entity_ids.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
        : []
      const routeLabel = matchedEntityIds.length > 0
        ? `${sourceMarker}: ${matchedEntityIds.join(' -> ')}`
        : sourceMarker
      return [routeLabel, ...entry.steps.map((step) => graphStepLabel(step))]
    }
    if (isGraphRagPathRoute(entry)) {
      return [entry.source_marker?.trim() || '图谱路径']
    }
    return [graphStepLabel(entry)]
  })
}

export function nodeGraphExplain(node: GraphRagNodeLike): GraphRagExplain | null {
  const explain = node.graph_rag?.explain
  if (explain?.why && explain?.evidence_type) return explain
  if (node.evidence_type) {
    return {
      why: '该节点包含检索返回的图证据。',
      evidence_type: node.evidence_type,
    }
  }
  return null
}

export function edgeGraphExplain(edge: GraphRagEdgeLike): GraphRagExplain | null {
  const explain = edge.graph_rag?.explain
  if (explain?.why && explain?.evidence_type) return explain
  if (edge.evidence_type) {
    return {
      why:
        edge.reason?.trim() ||
        edge.evidence_span?.trim() ||
        '该关系包含检索返回的图证据。',
      evidence_type: edge.evidence_type,
    }
  }
  return null
}

export function collectEdgeExplains<T extends GraphRagEdgeLike & { id: string }>(edges: T[]) {
  return edges.flatMap((edge) => {
    const explain = edgeGraphExplain(edge)
    return explain ? [{ edge, explain }] : []
  })
}

export function selectInspectorExplain<T extends GraphRagEdgeLike & { id: string }>(
  node: GraphRagNodeLike,
  edges: T[],
) {
  const nodeExplain = nodeGraphExplain(node)
  if (nodeExplain) return nodeExplain

  const edgeExplains = collectEdgeExplains(edges)
  if (edgeExplains.length === 0) return null
  if (edgeExplains.length === 1) return edgeExplains[0].explain

  const sourceMarkers = Array.from(
    new Set(
      edgeExplains
        .map(({ explain }) => explain.source_marker?.trim())
        .filter((marker): marker is string => Boolean(marker)),
    ),
  )

  return {
    why: `该节点包含 ${edgeExplains.length} 条检索返回的关联关系，请在下方逐一查看关系详情。`,
    evidence_type: edgeExplains.some(({ explain }) => explain.evidence_type === 'INFERRED')
      ? 'INFERRED'
      : edgeExplains[0].explain.evidence_type,
    source_marker: sourceMarkers.length === 1 ? sourceMarkers[0] : undefined,
  } satisfies GraphRagExplain
}
