import { create } from 'zustand'
import { ApiProblem } from '@/features/knowledge/api/client'
import { authApi, type MeResponse } from '@/features/auth/api/auth'

interface AuthState {
  me: MeResponse | null
  loading: boolean
  bootstrapped: boolean
  refreshMe: () => Promise<void>
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  me: null,
  loading: false,
  bootstrapped: false,
  async refreshMe() {
    set({ loading: true })
    try {
      const me = await authApi.me()
      set({ me, loading: false, bootstrapped: true })
    } catch (error) {
      const problem = error as ApiProblem
      if (problem.status === 401) {
        set({ me: null, loading: false, bootstrapped: true })
        return
      }
      throw error
    }
  },
  clear() {
    set({ me: null, loading: false, bootstrapped: true })
  },
}))
