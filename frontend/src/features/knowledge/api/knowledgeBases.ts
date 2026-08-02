// Knowledge base CRUD against the real Backend `/knowledge-bases` routes.

import { requestJSON } from './client'

export type KnowledgeGovernanceStatus = 'personal' | 'pending_transfer' | 'managed'
export type KnowledgeBaseMemberRole = 'viewer' | 'contributor' | 'editor' | 'manager'

export interface KnowledgeBaseMember {
  user_id: string
  role: KnowledgeBaseMemberRole
  granted_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface KnowledgeBaseMembersResponse {
  items: KnowledgeBaseMember[]
  total: number
}

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
  governance_status: KnowledgeGovernanceStatus
  transfer_requested_by: string | null
  transfer_requested_at: string | null
  transfer_message: string | null
  transfer_reviewed_by: string | null
  transfer_reviewed_at: string | null
  transfer_rejection_reason: string | null
  my_role: 'admin' | 'owner' | KnowledgeBaseMemberRole | null
  can_read: boolean
  can_contribute: boolean
  can_edit: boolean
  can_manage_members: boolean
  can_delete: boolean
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

  requestTransfer(kbUid: string, data: { message?: string | null }): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(kbUid)}/transfer-request`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  withdrawTransfer(kbUid: string): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/${encodeURIComponent(kbUid)}/transfer-request`, {
      method: 'DELETE',
    })
  },

  listTransferRequests(): Promise<KnowledgeBaseListResponse> {
    return requestJSON<KnowledgeBaseListResponse>('/knowledge-bases/admin/transfer-requests')
  },

  acceptTransfer(kbUid: string): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/admin/transfer-requests/${encodeURIComponent(kbUid)}/accept`, {
      method: 'POST',
    })
  },

  rejectTransfer(kbUid: string, data: { reason?: string | null }): Promise<KnowledgeBase> {
    return requestJSON<KnowledgeBase>(`/knowledge-bases/admin/transfer-requests/${encodeURIComponent(kbUid)}/reject`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  listMembers(kbUid: string): Promise<KnowledgeBaseMembersResponse> {
    return requestJSON<KnowledgeBaseMembersResponse>(`/knowledge-bases/${encodeURIComponent(kbUid)}/members`)
  },

  updateMember(kbUid: string, userId: string, data: { role: KnowledgeBaseMemberRole }): Promise<KnowledgeBaseMember> {
    return requestJSON<KnowledgeBaseMember>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/members/${encodeURIComponent(userId)}`,
      {
        method: 'PUT',
        body: JSON.stringify(data),
      },
    )
  },

  deleteMember(kbUid: string, userId: string): Promise<{ detail: string }> {
    return requestJSON<{ detail: string }>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/members/${encodeURIComponent(userId)}`,
      {
        method: 'DELETE',
      },
    )
  },
}
