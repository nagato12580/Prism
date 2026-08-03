import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '@/features/auth/api/auth'
import { useAuthStore } from '@/features/auth/store/authStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'

export function LoginPage() {
  const navigate = useNavigate()
  const refreshMe = useAuthStore((s) => s.refreshMe)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    try {
      setError('')
      setBusy(true)
      await authApi.loginDev({ username: username.trim(), display_name: displayName.trim() || undefined })
      await refreshMe()
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-xl border border-[var(--prism-line)] bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-lg font-semibold text-slate-900">登录 Prism</h1>
        <p className="mb-5 text-xs text-slate-500">开发模式：输入用户名即可创建/进入本地账号</p>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
          className="flex flex-col gap-3"
        >
          <Input
            aria-label="用户名"
            placeholder="用户名 (username)"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <Input
            aria-label="显示名"
            placeholder="显示名 (可选)"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          {error ? <span className="text-xs text-red-500">{error}</span> : null}
          <Button type="submit" variant="primary" loading={busy} disabled={!username.trim() || busy}>
            {busy ? null : '登录'}
          </Button>
        </form>
      </div>
    </div>
  )
}
