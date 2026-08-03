import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuthStore } from '@/features/auth/store/authStore'
import { LoadingState } from '@/components/ui/StateView'

export function RequireAuth() {
  const { me, loading, bootstrapped, refreshMe } = useAuthStore()

  useEffect(() => {
    if (!bootstrapped && !loading) void refreshMe()
  }, [bootstrapped, loading, refreshMe])

  if (!bootstrapped || loading) return <LoadingState label="Loading account..." />
  if (!me) return <Navigate to="/login" replace />
  return <Outlet />
}
