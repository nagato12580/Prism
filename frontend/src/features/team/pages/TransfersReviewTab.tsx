import { useEffect, useState } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import {
  knowledgeBasesApi,
  type KnowledgeBase,
} from '@/features/knowledge/api/knowledgeBases'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, LoadingState } from '@/components/ui/StateView'

export function TransfersReviewTab({ onForbidden }: { onForbidden?: () => void }) {
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [rejecting, setRejecting] = useState<KnowledgeBase | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => {
    setLoading(true)
    setError(null)
    knowledgeBasesApi
      .listTransferRequests()
      .then((res) => setItems(res.items))
      .catch((e) => {
        const p = e as ApiProblem
        if (p?.status === 403) onForbidden?.()
        else setError(e)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const accept = (kb: KnowledgeBase) => {
    setBusy(true)
    setError(null)
    knowledgeBasesApi
      .acceptTransfer(kb.kb_uid)
      .then(load)
      .catch(setError)
      .finally(() => setBusy(false))
  }

  const confirmReject = () => {
    if (!rejecting) return
    setBusy(true)
    setError(null)
    knowledgeBasesApi
      .rejectTransfer(rejecting.kb_uid, { reason: reason.trim() || null })
      .then(() => {
        setRejecting(null)
        setReason('')
        load()
      })
      .catch(setError)
      .finally(() => setBusy(false))
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message ?? '操作失败'}</span> : null}

      {loading ? (
        <LoadingState label="加载待接收…" />
      ) : items.length === 0 ? (
        <EmptyState icon={Check} title="暂无待接收知识库" description="成员提交的知识库会出现在这里等待审核" />
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((kb) => (
            <li key={kb.kb_uid} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--prism-line)] bg-white p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-900">{kb.name}</span>
                  <Badge tone="amber">待接收</Badge>
                </div>
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{kb.description || '暂无描述'}</div>
                <div className="mt-1 text-[11px] text-slate-400">
                  提交者：{kb.transfer_requested_by || kb.owner_user_id}
                  {kb.transfer_message ? ` · 说明：${kb.transfer_message}` : ''}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button variant="primary" size="sm" onClick={() => accept(kb)} loading={busy}>
                  <Check size={14} /> 接收
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setRejecting(kb)}>
                  <X size={14} /> 拒绝
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={!!rejecting} onClose={() => setRejecting(null)} title="拒绝提交" width="sm">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600">确认拒绝「{rejecting?.name}」的团队库提交？</p>
          <input
            aria-label="拒绝原因"
            placeholder="拒绝原因（可选）"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="h-9 w-full rounded-md border border-[var(--prism-line)] px-3 text-sm text-slate-700 outline-none focus:border-blue-300"
          />
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmReject} loading={busy}>
              确认拒绝
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
