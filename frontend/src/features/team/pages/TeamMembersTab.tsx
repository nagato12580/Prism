import { useEffect, useState } from 'react'
import { Loader2, Plus, ShieldCheck, Trash2, Users } from 'lucide-react'
import {
  teamAdminApi,
  type TeamMember,
  type TeamMemberStatus,
  type TeamRole,
} from '@/features/team/api/teamAdmin'
import { ApiProblem } from '@/features/knowledge/api/client'
import { useAuthStore } from '@/features/auth/store/authStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, LoadingState } from '@/components/ui/StateView'

const ROLE_OPTIONS: TeamRole[] = ['admin', 'member']
const ROLE_LABELS: Record<TeamRole, string> = { admin: '管理员', member: '成员' }
const ROLE_TONES: Record<TeamRole, 'blue' | 'green'> = { admin: 'blue', member: 'green' }
const STATUS_OPTIONS: TeamMemberStatus[] = ['active', 'disabled']
const STATUS_LABELS: Record<TeamMemberStatus, string> = { active: '启用', disabled: '停用' }
const STATUS_TONES: Record<TeamMemberStatus, 'green' | 'amber'> = { active: 'green', disabled: 'amber' }

export function TeamMembersTab() {
  const currentUserId = useAuthStore((s) => s.me?.username ?? '')
  const [members, setMembers] = useState<TeamMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<TeamRole>('member')
  const [busy, setBusy] = useState(false)
  const [forbidden, setForbidden] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    teamAdminApi.listMembers()
      .then((res) => setMembers(res.items))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) setForbidden(true)
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const addMember = () => {
    if (!userId.trim()) return
    setBusy(true)
    setError(null)
    teamAdminApi.addMember({ user_id: userId.trim(), role })
      .then(() => {
        setUserId('')
        load()
      })
      .catch(setError)
      .finally(() => setBusy(false))
  }

  const updateRole = (member: TeamMember, next: TeamRole) => {
    setError(null)
    teamAdminApi.updateMember(member.user_id, { role: next }).then(load).catch(setError)
  }

  const updateStatus = (member: TeamMember, next: TeamMemberStatus) => {
    setError(null)
    teamAdminApi.updateMember(member.user_id, { status: next }).then(load).catch(setError)
  }

  const removeMember = (member: TeamMember) => {
    setError(null)
    teamAdminApi.removeMember(member.user_id).then(load).catch(setError)
  }

  if (forbidden) return null // handled by parent page 403 fallback

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 rounded-lg border border-[var(--prism-line)] bg-slate-50/60 p-2.5">
        <Input
          aria-label="用户 ID"
          placeholder="输入 user_id 添加成员"
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="flex-1"
        />
        <select
          aria-label="角色"
          value={role}
          onChange={(e) => setRole(e.target.value as TeamRole)}
          className="h-9 rounded-lg border border-[var(--prism-line)] bg-white px-2 text-sm text-slate-700 outline-none focus:border-blue-300"
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}（{r}）
            </option>
          ))}
        </select>
        <Button variant="primary" size="sm" onClick={addMember} loading={busy} disabled={!userId.trim()}>
          {busy ? null : <Plus size={14} />} 添加成员
        </Button>
      </div>

      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '操作失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载成员…" />
      ) : members.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="暂无团队成员" description="添加第一个团队成员开始管理" />
      ) : (
        <ul className="flex flex-col gap-2">
          {members.map((m) => {
            const isSelf = m.user_id === currentUserId
            return (
              <li
                key={m.user_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-2.5"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Users size={14} className="shrink-0 text-slate-400" />
                  <span className="truncate font-mono text-xs text-slate-700">{m.user_id}</span>
                  {isSelf ? <Badge tone="violet">我</Badge> : null}
                  <Badge tone={ROLE_TONES[m.role]}>{ROLE_LABELS[m.role]}</Badge>
                  <Badge tone={STATUS_TONES[m.status]}>{STATUS_LABELS[m.status]}</Badge>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <select
                    aria-label={`${m.user_id} 角色`}
                    value={m.role}
                    disabled={isSelf}
                    onChange={(e) => updateRole(m, e.target.value as TeamRole)}
                    className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-1.5 text-xs text-slate-700 outline-none focus:border-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}（{r}）
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label={`${m.user_id} 状态`}
                    value={m.status}
                    disabled={isSelf}
                    onChange={(e) => updateStatus(m, e.target.value as TeamMemberStatus)}
                    className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-1.5 text-xs text-slate-700 outline-none focus:border-blue-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`移除 ${m.user_id}`}
                    title="移除成员"
                    disabled={isSelf}
                    onClick={() => removeMember(m)}
                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
