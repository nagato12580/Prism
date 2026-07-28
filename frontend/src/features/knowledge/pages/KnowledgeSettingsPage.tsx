import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Settings as SettingsIcon, Save, Download, Trash2 } from 'lucide-react'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { knowledgeBasesApi } from '@/features/knowledge/api/knowledgeBases'
import { enrichmentApi, triggerBlobDownload } from '@/features/knowledge/api/enrichment'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { Dialog } from '@/components/ui/Dialog'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

export function KnowledgeSettingsPage() {
  const { kb, reload } = useOutletContext<Ctx>()
  const kbUid = kb?.kb_uid ?? ''
  const [name, setName] = useState(kb?.name ?? '')
  const [description, setDescription] = useState(kb?.description ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [exporting, setExporting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const save = () => {
    if (!kbUid || !kb) return
    setSaving(true)
    setError(null)
    knowledgeBasesApi
      .update(kbUid, { name: name.trim() || undefined, description: description || null, version: kb.version })
      .then(() => {
        reload()
      })
      .catch((e) => setError(e))
      .finally(() => setSaving(false))
  }

  const doExport = () => {
    setExporting(true)
    enrichmentApi
      .exportZip(kbUid)
      .then(({ blob, filename }) => triggerBlobDownload(blob, filename ?? `knowledge-${kbUid}.zip`))
      .catch((e) => setError(e))
      .finally(() => setExporting(false))
  }

  const remove = () => {
    if (!kb || kb.is_system || kb.delete_disabled) {
      setError(new Error('系统知识库不能删除'))
      setConfirmDelete(false)
      return
    }
    knowledgeBasesApi.delete(kbUid).then(() => {
      window.location.href = '/knowledge'
    })
  }

  const deleteDisabled = !!kb && (kb.is_system || kb.delete_disabled)

  return (
    <div data-testid="knowledge-settings-page" className="flex h-full min-h-0 flex-col gap-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
        <SettingsIcon size={16} /> 设置
      </h2>

      <section className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">基本信息</h3>
        <div className="flex max-w-md flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            名称
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            描述
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <div className="flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={save} loading={saving} disabled={!name.trim()}>
              <Save size={14} /> 保存
            </Button>
            {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message}</span> : null}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <h3 className="mb-1 text-sm font-semibold text-slate-800">索引与图谱状态</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <Badge tone="blue">索引 generation：{kb?.active_index_generation ?? '未建立'}</Badge>
          <Badge tone="violet">图谱 generation：{kb?.active_graph_generation ?? '未建立'}</Badge>
          <Badge tone="neutral">版本 {kb?.version}</Badge>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">修改嵌入/分块/检索/图谱配置将创建新的 generation，不会原地篡改活动索引。</p>
      </section>

      <section className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <h3 className="mb-2 text-sm font-semibold text-slate-800">导出</h3>
        <p className="mb-2 text-[11px] text-slate-400">导出包含配置、清单、Markdown、评估与图事实（不含向量、密钥或绝对路径）。</p>
        <Button variant="secondary" size="sm" onClick={doExport} loading={exporting}>
          <Download size={14} /> 导出 ZIP
        </Button>
      </section>

      <section className="rounded-xl border border-red-200 bg-red-50/40 p-4">
        <h3 className="mb-2 text-sm font-semibold text-red-700">危险操作</h3>
        <p className="mb-2 text-[11px] text-red-500">
          {deleteDisabled ? '系统知识库受保护，不能删除。' : '删除知识库将移除其所有文件、索引与图谱引用，不可恢复。'}
        </p>
        <Button
          variant="danger"
          size="sm"
          onClick={() => setConfirmDelete(true)}
          disabled={deleteDisabled}
          title={deleteDisabled ? '系统知识库不能删除' : '删除知识库'}
        >
          <Trash2 size={14} /> 删除知识库
        </Button>
      </section>

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title="删除知识库" width="sm">
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600">确认删除「{kb?.name}」？此操作不可恢复。</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>取消</Button>
            <Button variant="danger" onClick={remove} disabled={deleteDisabled}><Trash2 size={14} /> 确认删除</Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
