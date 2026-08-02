import { useEffect, useState } from 'react'
import { ArrowRight, BookOpen, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  knowledgeBasesApi,
  type KnowledgeBase,
} from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, LoadingState } from '@/components/ui/StateView'
import { KnowledgeMembersPanel } from '@/features/knowledge/components/KnowledgeMembersPanel'

export function TeamKbsTab({ onForbidden }: { onForbidden?: () => void }) {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [membersKb, setMembersKb] = useState<KnowledgeBase | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .list({ limit: 200 })
      .then((res) => setItems(res.items.filter((kb) => kb.governance_status === 'managed')))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) onForbidden?.()
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div className="flex flex-col gap-3">
      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '加载失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载团队库…" />
      ) : items.length === 0 ? (
        <EmptyState icon={BookOpen} title="暂无团队库" description="接收的知识库会出现在这里" />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((kb) => (
            <li key={kb.kb_uid} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-900">{kb.name}</span>
                  <Badge tone="blue">团队库</Badge>
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{kb.description || '暂无描述'}</div>
                <div className="mt-1 text-[11px] text-slate-400">创建者：{kb.owner_user_id}</div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button variant="ghost" size="sm" onClick={() => setMembersKb(kb)}>
                  <Users size={14} /> 成员
                </Button>
                <Button variant="ghost" size="sm" onClick={() => navigate(`/knowledge/${kb.kb_uid}/files`)}>
                  <ArrowRight size={14} /> 进入
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <KnowledgeMembersPanel
        kbUid={membersKb?.kb_uid ?? ''}
        open={!!membersKb}
        onClose={() => setMembersKb(null)}
      />
    </div>
  )
}
