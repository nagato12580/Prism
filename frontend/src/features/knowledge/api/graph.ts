import { requestJSON } from './client'
import { buildKnowledgeBaseGraphPath } from './graphPath'

export interface KnowledgeBaseGraphNode {
  id: string
  type: string
  label: string
  ref_id?: string
  file_uid?: string
  chunk_uid?: string
  source_kind?: string
  source_id?: string
  item_id?: string
  confidence?: number
  status?: string
}

export interface KnowledgeBaseGraphEdge {
  id: string
  source: string
  target: string
  type: string
  label: string
  confidence?: number
}

export interface KnowledgeBaseGraphPayload {
  view: 'entity' | 'source'
  nodes: KnowledgeBaseGraphNode[]
  edges: KnowledgeBaseGraphEdge[]
  stats: {
    node_count: number
    edge_count: number
    entity_count: number
    source_count: number
    node_counts: Record<string, number>
    edge_counts: Record<string, number>
  }
  focus: {
    view: 'entity' | 'source'
    kb_uid: string
    file_uids: string[]
  }
}

export interface KnowledgeBaseGraphParams {
  view?: 'entity' | 'source'
  file_uids?: string[]
  limit?: number
}

export const knowledgeBaseGraphApi = {
  get(kbUid: string, params?: KnowledgeBaseGraphParams): Promise<KnowledgeBaseGraphPayload> {
    return requestJSON<KnowledgeBaseGraphPayload>(buildKnowledgeBaseGraphPath(kbUid, params))
  },
}

export { buildKnowledgeBaseGraphPath }
