import { useEffect, useState } from 'react'
import { Plus, RefreshCw, Settings } from 'lucide-react'
import type { ModelProvider, ModelStatus } from '@/features/modelConfig/api/modelConfig'
import { modelConfigApi } from '@/features/modelConfig/api/modelConfig'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { Dialog } from '@/components/ui/Dialog'
import { ApiProblem } from '@/features/knowledge/api/client'

export function ModelConfigPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([])
  const [defaultSpec, setDefaultSpec] = useState<string | null>(null)
  const [models, setModels] = useState<{ spec: string; model_id: string; provider_id: string }[]>([])
  const [status, setStatus] = useState<ModelStatus | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [editing, setEditing] = useState<ModelProvider | null>(null)
  const [showNew, setShowNew] = useState(false)

  const reload = () => {
    modelConfigApi.listProviders().then(r => setProviders(r.items)).catch(setError)
    modelConfigApi.listModels().then(r => setModels(r.items)).catch(setError)
    modelConfigApi.getDefault().then(r => setDefaultSpec(r.spec)).catch(setError)
  }
  useEffect(() => { reload() }, [])

  useEffect(() => {
    if (!defaultSpec) return
    modelConfigApi.modelStatus(defaultSpec).then(setStatus).catch(() => setStatus({ status: 'error' }))
  }, [defaultSpec])

  const setDefault = (spec: string) => {
    modelConfigApi.setDefault(spec).then(() => setDefaultSpec(spec)).catch(setError)
  }

  return (
    <div data-testid="model-config-page" className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-base font-semibold text-slate-900">
          <Settings size={16} /> 模型配置
        </h2>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => { modelConfigApi.refreshCache().then(reload) }}>
            <RefreshCw size={14} /> 刷新缓存
          </Button>
          <Button variant="primary" size="sm" onClick={() => setShowNew(true)}>
            <Plus size={14} /> 新建供应商
          </Button>
        </div>
      </div>

      <section className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <h3 className="mb-1 text-sm font-semibold text-slate-800">当前默认模型</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <Badge tone="blue">{defaultSpec ?? '未设置'}</Badge>
          {status ? (
            <Badge tone={status.status === 'available' ? 'green' : 'red'}>
              {status.status === 'available' ? '可用' : status.status === 'error' ? '错误' : '不可用'}
            </Badge>
          ) : null}
        </div>
        <select
          className="mt-2 rounded-md border border-slate-200 px-2 py-1 text-sm"
          value={defaultSpec ?? ''}
          onChange={(e) => setDefault(e.target.value)}
        >
          <option value="">选择默认模型…</option>
          {models.map(m => (
            <option key={m.spec} value={m.spec}>{m.spec}</option>
          ))}
        </select>
      </section>

      <section className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-800">供应商</h3>
        <div className="flex flex-col gap-2">
          {providers.map(p => (
            <div key={p.provider_id} className="flex items-center gap-3 rounded-lg border border-slate-100 p-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                  {p.display_name}
                  {p.is_builtin ? <Badge tone="neutral">内置</Badge> : null}
                  {!p.is_enabled ? <Badge tone="red">已停用</Badge> : null}
                </div>
                <div className="truncate text-xs text-slate-500">{p.base_url} · {p.enabled_models.join(', ')}</div>
                <div className="text-xs text-slate-400">凭证：{p.has_api_key ? p.api_key_masked ?? p.api_key_env ?? '已配置' : '未配置'}</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setEditing(p)}>编辑</Button>
              <Button variant="ghost" size="sm" onClick={() => { modelConfigApi.deleteProvider(p.provider_id).then(reload).catch(setError) }}>删除</Button>
            </div>
          ))}
        </div>
      </section>

      {error ? <span className="text-xs text-red-500">{(error as ApiProblem).message}</span> : null}

      <Dialog open={showNew || editing != null} onClose={() => { setShowNew(false); setEditing(null) }} title={editing ? '编辑供应商' : '新建供应商'} width="md">
        <ProviderForm
          initial={editing}
          onDone={(data) => {
            const req = editing
              ? modelConfigApi.updateProvider(editing.provider_id, data)
              : modelConfigApi.createProvider(data as any)
            req.then(() => { setShowNew(false); setEditing(null); reload() }).catch(setError)
          }}
        />
      </Dialog>
    </div>
  )
}

function ProviderForm({ initial, onDone }: { initial: ModelProvider | null; onDone: (d: any) => void }) {
  const [providerId, setProviderId] = useState(initial?.provider_id ?? '')
  const [displayName, setDisplayName] = useState(initial?.display_name ?? '')
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [enabledModels, setEnabledModels] = useState(initial?.enabled_models.join(', ') ?? '')

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        Provider ID
        <Input value={providerId} disabled={initial != null} onChange={(e) => setProviderId(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        名称
        <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        Base URL
        <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        API Key（留空 = 不修改）
        <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
        启用模型（逗号分隔）
        <Input value={enabledModels} onChange={(e) => setEnabledModels(e.target.value)} />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="primary" size="sm" onClick={() => onDone({
          provider_id: providerId, display_name: displayName, base_url: baseUrl,
          api_key: apiKey || undefined, enabled_models: enabledModels.split(',').map(s => s.trim()).filter(Boolean),
        })}>保存</Button>
      </div>
    </div>
  )
}
