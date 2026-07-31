import { requestJSON } from './client'
import { buildKnowledgeBaseGraphPath } from './graphPath'
import type {
  UnifiedGraphEdge,
  UnifiedGraphNode,
  UnifiedGraphPayload,
  UnifiedGraphView,
} from '@/app/api'

export type KnowledgeBaseGraphNode = UnifiedGraphNode & {
  file_uid?: string
  chunk_uid?: string
  item_id?: string
}

export type KnowledgeBaseGraphEdge = UnifiedGraphEdge

export interface KnowledgeBaseGraphPayload extends UnifiedGraphPayload {
  view: UnifiedGraphView
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
  view?: UnifiedGraphView
  file_uids?: string[]
  limit?: number
}

export const knowledgeBaseGraphApi = {
  get(kbUid: string, params?: KnowledgeBaseGraphParams): Promise<KnowledgeBaseGraphPayload> {
    return requestJSON<KnowledgeBaseGraphPayload>(buildKnowledgeBaseGraphPath(kbUid, params))
  },
}

export { buildKnowledgeBaseGraphPath }
