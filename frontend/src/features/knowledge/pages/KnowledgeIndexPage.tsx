import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, FolderPlus, Loader2, Trash2 } from 'lucide-react'
import { knowledgeBasesApi, type KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'

function isDeleteDisabled(kb: KnowledgeBase) {
  return kb.is_system || kb.delete_disabled
}

function systemKbLabel(kb: KnowledgeBase) {
  if (kb.system_type === 'personal_inbox') return '个人随手记'
  return '系统知识库'
}

export function KnowledgeIndexPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState<KnowledgeBase | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .list({ limit: 200 })
      .then((res) => setItems(res.items))
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const submitCreate = () => {
    if (!name.trim()) return
    setCreating(true)
    setCreateError(null)
    knowledgeBasesApi
      .create({ name: name.trim(), description: description.trim() || null })
      .then((kb) => {
        setCreateOpen(false)
        setName('')
        setDescription('')
        navigate(`/knowledge/${kb.kb_uid}/files`)
      })
      .catch((e) => setCreateError(e))
      .finally(() => setCreating(false))
  }

  const confirmDelete = () => {
    if (!deleting) return
    if (isDeleteDisabled(deleting)) {
      setCreateError(new Error('系统知识库不能删除'))
      return
    }
    knowledgeBasesApi
      .delete(deleting.kb_uid)
      .then(() => {
        setDeleting(null)
        load()
      })
      .catch((e) => setCreateError(e))
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="knowledge-index-page">
      <header className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">知识库</h1>
          <p className="text-xs text-slate-500">创建并管理你的知识库</p>
        </div>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>
          <FolderPlus size={15} /> 新建知识库
        </Button>
      </header>

      {loading ? (
        <LoadingState label="加载知识库列表…" />
      ) : error ? (
        <ErrorState problem={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="还没有知识库"
          description="新建一个知识库，开始上传文档并检索"
          action={
            <Button variant="primary" onClick={() => setCreateOpen(true)}>
              <FolderPlus size={15} /> 新建知识库
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((kb) => (
            <button
              key={kb.kb_uid}
              type="button"
              onClick={() => navigate(`/knowledge/${kb.kb_uid}/files`)}
              className="group flex flex-col gap-3 rounded-xl border border-[var(--prism-line)] bg-white p-4 text-left shadow-[0_8px_30px_-18px_rgba(15,23,42,0.25)] transition hover:border-blue-200 hover:shadow-[0_16px_40px_-24px_rgba(37,99,235,0.4)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--prism-blue)]/10 text-[var(--prism-blue)]">
                  <BookOpen size={18} />
                </div>
                {isDeleteDisabled(kb) ? (
                  <span
                    aria-label="系统知识库不能删除"
                    title="系统知识库不能删除"
                    className="rounded-md px-2 py-1 text-[10px] font-medium text-slate-400 opacity-0 transition group-hover:opacity-100"
                  >
                    系统保护
                  </span>
                ) : (
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label="删除知识库"
                    title="删除知识库"
                    onClick={(e) => {
                      e.stopPropagation()
                      setCreateError(null)
                      setDeleting(kb)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        e.stopPropagation()
                        setCreateError(null)
                        setDeleting(kb)
                      }
                    }}
                    className="rounded-md p-1.5 text-slate-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                  >
                    <Trash2 size={14} />
                  </span>
                )}
              </div>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-slate-900">{kb.name}</div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">
                  {kb.description || '暂无描述'}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={kb.status === 'active' ? 'green' : 'amber'}>{kb.status}</Badge>
                {kb.is_system || kb.system_type ? (
                  <Badge tone="violet">{systemKbLabel(kb)}</Badge>
                ) : null}
                {kb.active_index_generation ? (
                  <Badge tone="blue">已索引</Badge>
                ) : (
                  <Badge tone="neutral">未索引</Badge>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="新建知识库" width="sm">
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            名称
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：产品文档" autoFocus />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            描述（可选）
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要描述知识库内容"
            />
          </label>
          {createError ? (
            <div className="text-xs text-red-600">{(createError as ApiProblem).message ?? '创建失败'}</div>
          ) : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={submitCreate} loading={creating} disabled={!name.trim()}>
              {creating ? null : <FolderPlus size={14} />} 创建
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog open={!!deleting} onClose={() => setDeleting(null)} title="删除知识库" width="sm">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600">
            确认删除知识库「{deleting?.name}」？该操作会标记为删除并清理相关文件与索引，不可恢复。
          </p>
          {createError ? (
            <div className="text-xs text-red-600">{(createError as ApiProblem).message ?? '删除失败'}</div>
          ) : null}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmDelete} disabled={!!deleting && isDeleteDisabled(deleting)}>
              <Trash2 size={14} /> 确认删除
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}

export { LoadingState, Loader2 }
