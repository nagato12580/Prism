// Team admin member CRUD against the Backend `/team/admin/members` routes.

import { requestJSON } from '@/features/knowledge/api/client'

export type TeamRole = 'admin' | 'member'
export type TeamMemberStatus = 'active' | 'disabled'

export interface TeamMember {
  user_id: string
  role: TeamRole
  status: TeamMemberStatus
  created_at: string | null
  updated_at: string | null
}

export interface TeamMemberListResponse {
  items: TeamMember[]
  total: number
}

export interface TeamMemberCreate {
  user_id: string
  role: TeamRole
  status?: TeamMemberStatus
}

export interface TeamMemberUpdate {
  role?: TeamRole
  status?: TeamMemberStatus
}

export const teamAdminApi = {
  listMembers(): Promise<TeamMemberListResponse> {
    return requestJSON<TeamMemberListResponse>('/team/admin/members')
  },

  addMember(data: TeamMemberCreate): Promise<TeamMember> {
    return requestJSON<TeamMember>('/team/admin/members', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateMember(userId: string, data: TeamMemberUpdate): Promise<TeamMember> {
    return requestJSON<TeamMember>(`/team/admin/members/${encodeURIComponent(userId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  removeMember(userId: string): Promise<{ detail: string }> {
    return requestJSON<{ detail: string }>(`/team/admin/members/${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    })
  },
}
