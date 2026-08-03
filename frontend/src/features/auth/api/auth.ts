import { requestJSON } from '@/features/knowledge/api/client'

export interface MeResponse {
  id: string
  username: string
  display_name: string
  email: string | null
  status: string
  tenant_id: string
  auth_mode: 'session' | 'header-fallback'
  team_role: string | null
}

export const authApi = {
  loginDev(data: { username: string; display_name?: string }) {
    return requestJSON<MeResponse>('/auth/login/dev', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
  logout() {
    return requestJSON<{ detail: string }>('/auth/logout', { method: 'POST' })
  },
  me() {
    return requestJSON<MeResponse>('/auth/me')
  },
}
