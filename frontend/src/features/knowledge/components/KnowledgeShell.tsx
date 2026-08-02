import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import { knowledgeBasesApi, type KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { LoadingState, ErrorState, NotFoundState } from '@/components/ui/StateView'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { KnowledgeMembersPanel } from '@/features/knowledge/components/KnowledgeMembersPanel'

interface TabDef {
  key: string
  label: string
  path: string
}

const TABS: TabDef[] = [
  { key: 'files', label: '文件', path: 'files' },
  { key: 'retrieval', label: '检索', path: 'retrieval' },
  { key: 'mindmap', label: '导图', path: 'mindmap' },
  { key: 'evaluation', label: '评估', path: 'evaluation' },
  { key: 'graph', label: '图谱', path: 'graph' },
  { key: 'settings', label: '设置', path: 'settings' },
]

export function tabLabel(key: string): string {
  return TABS.find((t) => t.key === key)?.label ?? key
}

export function KnowledgeShell() {
  const { kbUid } = useParams<{ kbUid: string }>()
  const navigate = useNavigate()
  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [membersOpen, setMembersOpen] = useState(false)

  const load = () => {
    if (!kbUid) return
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .get(kbUid)
      .then(setKb)
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }

  useEffect(load, [kbUid])

  if (!kbUid) return <NotFoundState />
  if (loading) return <LoadingState label="加载知识库…" />
  if (error) {
    const p = error as ApiProblem
    if (p?.status === 404 || p?.status === 403) {
      return (
        <div className="flex flex-col gap-3">
          <NotFoundState
            title={p.status === 403 ? '无权访问该知识库' : '未找到该知识库'}
            description={p.message}
          />
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
    return <ErrorState problem={error} onRetry={load} />
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="mb-3 flex items-center gap-3 border-b border-[var(--prism-line)] pb-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)]/10 text-[var(--prism-blue)]">
          <BookOpen size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => navigate('/knowledge')}
            className="mb-1 inline-flex items-center gap-1 text-[11px] text-slate-400 transition hover:text-slate-600"
          >
            <ArrowLeft size={12} /> 返回知识库
          </button>
          <div className="flex items-center gap-2">
            <div className="truncate text-base font-semibold text-slate-900">{kb?.name}</div>
            {kb?.my_role ? (
              <Badge tone={roleBadgeTone(kb.my_role)}>{ROLE_LABELS[kb.my_role] ?? kb.my_role}</Badge>
            ) : null}
          </div>
          <div className="truncate text-xs text-slate-500">
            {kb?.description || '暂无描述'} · 状态：{kb?.status}
          </div>
        </div>
        {kb?.can_manage_members ? (
          <Button variant="secondary" size="sm" onClick={() => setMembersOpen(true)}>
            <Users size={14} /> 成员管理
          </Button>
        ) : null}
      </header>

      <nav className="mb-3 flex flex-wrap items-center gap-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.key}
            to={tab.path}
            className={({ isActive }) =>
              cn(
                'inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
                isActive
                  ? 'bg-[var(--prism-blue)] text-white'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <div className="min-h-0 flex-1">
        <Outlet context={{ kb: kb ?? undefined, reload: load }} />
      </div>

      <KnowledgeMembersPanel
        kbUid={kbUid}
        open={membersOpen}
        onClose={() => setMembersOpen(false)}
      />
    </div>
  )
}

// Role badge helpers. Roles come verbatim from the Backend `my_role` field
// ('admin' | 'owner' | viewer/contributor/editor/manager). The frontend only
// renders what the Backend reports; it never derives permissions itself.
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  owner: '所有者',
  manager: '管理者',
  editor: '编辑者',
  contributor: '贡献者',
  viewer: '查看者',
}

function roleBadgeTone(role: string): 'blue' | 'violet' | 'cyan' | 'green' | 'amber' | 'neutral' {
  switch (role) {
    case 'admin':
    case 'owner':
      return 'violet'
    case 'manager':
      return 'blue'
    case 'editor':
      return 'cyan'
    case 'contributor':
      return 'green'
    case 'viewer':
      return 'amber'
    default:
      return 'neutral'
  }
}
