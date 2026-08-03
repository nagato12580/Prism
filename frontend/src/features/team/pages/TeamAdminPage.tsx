import { useEffect, useState } from 'react'
import { ArrowLeft, ShieldCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { LoadingState, NotFoundState } from '@/components/ui/StateView'
import { TransfersReviewTab } from './TransfersReviewTab'
import { TeamKbsTab } from './TeamKbsTab'
import { TeamMembersTab } from './TeamMembersTab'
import { ApiProblem } from '@/features/knowledge/api/client'
import { knowledgeBasesApi } from '@/features/knowledge/api/knowledgeBases'

type TabKey = 'transfers' | 'kbs' | 'members'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'transfers', label: '待接收' },
  { key: 'kbs', label: '团队库授权' },
  { key: 'members', label: '成员管理' },
]

export function TeamAdminPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabKey>('transfers')
  const [probeLoading, setProbeLoading] = useState(true)
  const [forbidden, setForbidden] = useState(false)

  useEffect(() => {
    let cancelled = false
    knowledgeBasesApi
      .listTransferRequests()
      .then(() => { if (!cancelled) setForbidden(false) })
      .catch((e) => {
        const p = e as ApiProblem
        if (!cancelled && p?.status === 403) setForbidden(true)
      })
      .finally(() => { if (!cancelled) setProbeLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (probeLoading) return <LoadingState label="加载团队管理…" />
  if (forbidden) {
    return (
      <div className="flex flex-col gap-3">
        <NotFoundState title="无权访问" description="仅团队管理员可查看此页面" />
        <button
          type="button"
          onClick={() => navigate('/knowledge')}
          className="mx-auto inline-flex items-center gap-1 text-xs text-[var(--prism-blue)] hover:underline"
        >
          <ArrowLeft size={14} /> 返回知识库列表
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="team-admin-page">
      <header className="mb-4 flex items-center gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)]/10 text-[var(--prism-blue)]">
          <ShieldCheck size={18} />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-900">团队管理</h1>
          <p className="text-xs text-slate-500">接收团队库、授权成员、管理团队成员</p>
        </div>
      </header>

      <nav className="mb-3 flex flex-wrap items-center gap-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              'inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
              tab === t.key
                ? 'bg-[var(--prism-blue)] text-white'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-auto">
        {tab === 'transfers' ? <TransfersReviewTab onForbidden={() => setForbidden(true)} /> : null}
        {tab === 'kbs' ? <TeamKbsTab onForbidden={() => setForbidden(true)} /> : null}
        {tab === 'members' ? <TeamMembersTab currentUserId="admin" /> : null}
      </div>
    </div>
  )
}
