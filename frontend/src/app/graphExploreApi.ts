const BASE = '/api/v1'

export interface GraphExploreNode {
  id: string
  label: string
  type: string
  properties: Record<string, unknown>
}

export interface GraphExploreLink {
  source: string
  target: string
  type: string
  properties: Record<string, unknown>
}

export interface GraphExplorePayload {
  nodes: GraphExploreNode[]
  links: GraphExploreLink[]
  node_count: number
  link_count: number
}

export interface GraphNodeDetail {
  node: GraphExploreNode | null
  neighbors: GraphExploreNode[]
  links: GraphExploreLink[]
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const detail = await resp.text()
    throw new Error(detail)
  }
  return resp.json()
}

export const graphExploreApi = {
  explore: (params: { types?: string; limit?: number; q?: string }) => {
    const search = new URLSearchParams()
    if (params.types) search.set('types', params.types)
    if (params.limit) search.set('limit', String(params.limit))
    if (params.q) search.set('q', params.q)
    return request<GraphExplorePayload>(`/graph/explore?${search}`)
  },

  nodeDetail: (nodeId: string) =>
    request<GraphNodeDetail>(`/graph/explore/nodes/${encodeURIComponent(nodeId)}`),

  expand: (nodeId: string, depth = 1) =>
    request<GraphExplorePayload>(
      `/graph/explore/nodes/${encodeURIComponent(nodeId)}/expand?depth=${depth}`,
    ),
}
