// Knowledge base CRUD against the real Backend `/knowledge-bases` routes.

import { requestJSON } from './client'

export interface KnowledgeBase {
  kb_uid: string
  tenant_id: string
  owner_user_id: string
  name: string
  description: string | null
  status: string // "active" | "deleting"
  system_type: string | null
  is_system: boolean
  delete_disabled: boolean
  version: number
  active_index_generation: string | null
  active_graph_generation: string | null
}

export interface KnowledgeBaseListResponse {
  items: KnowledgeBase[]
  total: number
  cursor: string | null
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string | null
}

export interface KnowledgeBaseUpdate {
  name?: string | null
  description?: string | null
  version: number
}

export interface ParserCapability {
  extensions: string[]
  media_types?: string[]
  description?: string | null
}

export interface ParserCapabilities {
  parsers: ParserCapability[]
}

export const knowledgeBasesApi = {
  list(params?: { cursor?: string; limit?: number }): Promise<KnowledgeBaseListResponse> {
    const qs = new URLSearchParams()
    if (params?.cursor) qs.set('cursor', params.cursor)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return requestJSON<KnowledgeBaseListResponse>(`/knowledge-bases${suffix}`)
  },

  get(kbUid: string): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(kbUid)}`)
  },

  create(data: KnowledgeBaseCreate): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>('/knowledge-bases', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  update(kbUid: string, data: KnowledgeBaseUpdate): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(kbUid)}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  delete(kbUid: string): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(kbUid)}`, {
      method: 'DELETE',
    })
  },

  parserCapabilities(): Promise<ParserCapabilities> {
    // No auth, no {kb_uid}.
    return requestJSON<ParserCapabilities>('/knowledge-bases/capabilities/parsers')
  },
}
