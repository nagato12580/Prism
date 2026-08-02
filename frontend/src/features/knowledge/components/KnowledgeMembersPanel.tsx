import { useEffect, useState } from 'react'
import { Users, Plus, Trash2, Loader2 } from 'lucide-react'
import {
  knowledgeBasesApi,
  type KnowledgeBaseMember,
  type KnowledgeBaseMemberRole,
} from '@/features/knowledge/api/knowledgeBases'
import { Dialog } from '@/components/ui/Dialog'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'

// Membership roles are exactly the four supported team roles.
const ROLE_OPTIONS: KnowledgeBaseMemberRole[] = ['viewer', 'contributor', 'editor', 'manager']

const ROLE_LABELS: Record<KnowledgeBaseMemberRole, string> = {
  viewer: '查看者',
  contributor: '贡献者',
  editor: '编辑者',
  manager: '管理者',
}

const ROLE_TONES: Record<KnowledgeBaseMemberRole, 'amber' | 'green' | 'cyan' | 'blue'> = {
  viewer: 'amber',
  contributor: 'green',
  editor: 'cyan',
  manager: 'blue',
}

interface KnowledgeMembersPanelProps {
  kbUid: string
  open: boolean
  onClose: () => void
}

export function KnowledgeMembersPanel({ kbUid, open, onClose }: KnowledgeMembersPanelProps) {
  const [members, setMembers] = useState<KnowledgeBaseMember[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<KnowledgeBaseMemberRole>('viewer')
  const [busy, setBusy] = useState(false)

  const load = () => {
    if (!open || !kbUid) return
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .listMembers(kbUid)
      .then((res) => setMembers(res.items))
      .catch(setError)
      .finally(() => setLoading(false))
  }

  useEffect(load, [kbUid, open])

  const addMember = () => {
    if (!kbUid || !userId.trim()) return
    setBusy(true)
    setError(null)
    knowledgeBasesApi
      .updateMember(kbUid, userId.trim(), { role })
      .then(() => {
        setUserId('')
        load()
      })
      .catch(setError)
      .finally(() => setBusy(false))
  }

  const updateRole = (member: KnowledgeBaseMember, next: KnowledgeBaseMemberRole) => {
    if (!kbUid) return
    setError(null)
    knowledgeBasesApi
      .updateMember(kbUid, member.user_id, { role: next })
      .then(load)
      .catch(setError)
  }

  const removeMember = (member: KnowledgeBaseMember) => {
    if (!kbUid) return
    setError(null)
    knowledgeBasesApi
      .deleteMember(kbUid, member.user_id)
      .then(load)
      .catch(setError)
  }

  return (
    <Dialog open={open} onClose={onClose} title="成员管理" width="md">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 rounded-lg border border-[var(--prism-line)] bg-slate-50/60 p-2.5">
          <Input
            aria-label="用户 ID"
            placeholder="输入 user_id 添加或更新成员"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="flex-1"
          />
          <select
            aria-label="角色"
            value={role}
            onChange={(e) => setRole(e.target.value as KnowledgeBaseMemberRole)}
            className="h-9 rounded-lg border border-[var(--prism-line)] bg-white px-2 text-sm text-slate-700 outline-none focus:border-blue-300"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}（{r}）
              </option>
            ))}
          </select>
          <Button variant="primary" size="sm" onClick={addMember} loading={busy} disabled={!userId.trim()}>
            {busy ? null : <Plus size={14} />} 添加 / 更新
          </Button>
        </div>

        {error ? <span className="text-xs text-red-500">{(error as { message?: string }).message}</span> : null}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-slate-400">
            <Loader2 size={14} className="animate-spin" /> 加载成员…
          </div>
        ) : members.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-400">暂无成员</div>
        ) : (
          <ul className="flex flex-col gap-2">
            {members.map((m) => (
              <li
                key={m.user_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-2.5"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <Users size={14} className="shrink-0 text-slate-400" />
                  <span className="truncate font-mono text-xs text-slate-700">{m.user_id}</span>
                  <Badge tone={ROLE_TONES[m.role]}>{ROLE_LABELS[m.role]}</Badge>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <select
                    aria-label={`${m.user_id} 角色`}
                    value={m.role}
                    onChange={(e) => updateRole(m, e.target.value as KnowledgeBaseMemberRole)}
                    className="h-8 rounded-md border border-[var(--prism-line)] bg-white px-1.5 text-xs text-slate-700 outline-none focus:border-blue-300"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}（{r}）
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label={`移除 ${m.user_id}`}
                    title="移除成员"
                    onClick={() => removeMember(m)}
                    className="rounded-md p-1.5 text-slate-400 transition hover:bg-red-50 hover:text-red-500"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  )
}
