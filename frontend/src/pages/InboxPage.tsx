import { useEffect, useMemo, useState } from 'react'
import { Check, Inbox, Loader2, Plus, RefreshCw, Save, Search, Tags, X } from 'lucide-react'
import { assetApi, type AssetDraft } from '@/app/api'
import { cn } from '@/lib/utils'

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function splitTags(value: string) {
  return value
    .split(',')
    .map((item) => item.trim().replace(/^#/, ''))
    .filter(Boolean)
}

function joinTags(tags?: string[]) {
  return (tags ?? []).join(', ')
}

function sourceLabel(item: AssetDraft) {
  return [item.raw_source_type, item.raw_source_platform].filter(Boolean).join(' / ') || 'manual'
}

export function InboxPage() {
  const [items, setItems] = useState<AssetDraft[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [draftText, setDraftText] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [draftSourceType, setDraftSourceType] = useState('manual')
  const [draftSourcePlatform, setDraftSourcePlatform] = useState('')
  const [draftSourceUrl, setDraftSourceUrl] = useState('')
  const [draftTags, setDraftTags] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((item) =>
      [
        item.title,
        item.summary,
        item.rewritten_content,
        item.raw_text,
        item.category,
        item.asset_kind,
        item.raw_source_platform,
        item.raw_source_url,
        ...(item.tags ?? []),
      ]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [items, query])

  const active = activeId ? items.find((item) => item.id === activeId) ?? null : null

  const removeItemFromList = (itemId: string) => {
    setItems((current) => {
      const rest = current.filter((item) => item.id !== itemId)
      setActiveId((currentActiveId) => (currentActiveId === itemId ? rest[0]?.id ?? null : currentActiveId))
      return rest
    })
  }

  const loadItems = async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await assetApi.listItems({ status: 'pending_review' })
      setItems(next)
      setActiveId((current) => {
        if (current && next.some((item) => item.id === current)) return current
        return next[0]?.id ?? null
      })
    } catch (err) {
      setError(`加载收件箱失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadItems()
  }, [])

  const createItem = async () => {
    const text = draftText.trim()
    if (!text) {
      setError('请输入要收集的碎片内容。')
      return
    }
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const created = await assetApi.createItem({
        raw_text: text,
        raw_title: draftTitle.trim() || undefined,
        raw_source_type: draftSourceType.trim() || 'manual',
        raw_source_platform: draftSourcePlatform.trim() || undefined,
        raw_source_url: draftSourceUrl.trim() || undefined,
        raw_tags: splitTags(draftTags),
        raw_metadata: { entrypoint: 'inbox' },
      })
      setItems((current) => [created, ...current])
      setActiveId(created.id)
      setDraftText('')
      setDraftTitle('')
      setDraftSourceType('manual')
      setDraftSourcePlatform('')
      setDraftSourceUrl('')
      setDraftTags('')
      setNotice('已放入收件箱，等待确认入库。')
    } catch (err) {
      setError(`创建碎片失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const updateActive = async (patch: Partial<AssetDraft>) => {
    if (!active) return
    setSaving(true)
    setError(null)
    try {
      const next = await assetApi.updateItem(active.id, patch)
      setItems((current) => current.map((item) => (item.id === next.id ? next : item)))
      setNotice('已保存。')
    } catch (err) {
      setError(`保存失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const confirmActive = async () => {
    if (!active) return
    setSaving(true)
    setError(null)
    try {
      await assetApi.confirmItem(active.id)
      removeItemFromList(active.id)
      setNotice('已确认入库，碎片已进入资产层和知识治理层。')
    } catch (err) {
      setError(`确认失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const rejectActive = async () => {
    if (!active) return
    setSaving(true)
    setError(null)
    try {
      await assetApi.deleteItem(active.id)
      removeItemFromList(active.id)
      setNotice('已拒绝该碎片。')
    } catch (err) {
      setError(`拒绝失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid h-[calc(100vh-9rem)] min-h-0 gap-3 overflow-hidden text-[13px] xl:grid-cols-[21rem_minmax(0,1fr)]">
      <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
              <Inbox size={15} />
              <span>收件箱</span>
            </div>
            <h1 className="mt-1 text-base font-semibold text-slate-950">待确认碎片</h1>
          </div>
          <button
            type="button"
            onClick={loadItems}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)]"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>

        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、摘要、标签或来源"
            className="h-9 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-8 pr-3 text-xs outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
        </div>

        {error ? (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
            {notice}
          </div>
        ) : null}

        <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
          {loading ? (
            <StateBlock text="正在加载待确认碎片" />
          ) : filtered.length === 0 ? (
            <StateBlock text="暂无待确认碎片。可以在右侧添加新的碎片。" />
          ) : (
            <div className="space-y-2">
              {filtered.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveId(item.id)}
                  className={cn(
                    'w-full rounded-lg border bg-white p-2.5 text-left transition',
                    activeId === item.id
                      ? 'border-[var(--prism-blue)] ring-2 ring-blue-100'
                      : 'border-[var(--prism-line)] hover:border-blue-200',
                  )}
                >
                  <div className="truncate text-[13px] font-semibold text-slate-950">{item.title}</div>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">
                    {item.summary || item.raw_text}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">待确认</span>
                    <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                      {sourceLabel(item)}
                    </span>
                    {(item.tags ?? []).slice(0, 2).map((tag) => (
                      <span key={tag} className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <main className="grid min-h-0 gap-3 overflow-hidden lg:grid-cols-[minmax(0,1fr)_22rem]">
        <EditorPanel
          item={active}
          saving={saving}
          onSave={updateActive}
          onConfirm={confirmActive}
          onReject={rejectActive}
        />

        <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
          <div className="mb-3 flex items-center gap-2">
            <Plus size={16} className="text-[var(--prism-blue)]" />
            <h2 className="text-sm font-semibold text-slate-950">添加碎片</h2>
          </div>
          <div className="space-y-3">
            <LabeledInput label="标题" value={draftTitle} onChange={setDraftTitle} placeholder="可选" />
            <LabeledTextarea label="内容" value={draftText} onChange={setDraftText} rows={8} placeholder="粘贴想收集的知识碎片、想法、评论或资源摘录" />
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
              <LabeledInput label="来源类型" value={draftSourceType} onChange={setDraftSourceType} placeholder="manual/comment/web" />
              <LabeledInput label="来源平台" value={draftSourcePlatform} onChange={setDraftSourcePlatform} placeholder="知乎、网页、手动输入..." />
            </div>
            <LabeledInput label="来源链接" value={draftSourceUrl} onChange={setDraftSourceUrl} placeholder="可选" />
            <LabeledInput label="原始标签" value={draftTags} onChange={setDraftTags} placeholder="用逗号分隔" icon={<Tags size={15} />} />
            <button
              type="button"
              disabled={saving}
              onClick={createItem}
              className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-3 text-xs font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
              放入收件箱
            </button>
          </div>
        </section>
      </main>
    </div>
  )
}

function EditorPanel({
  item,
  saving,
  onSave,
  onConfirm,
  onReject,
}: {
  item: AssetDraft | null
  saving: boolean
  onSave: (patch: Partial<AssetDraft>) => void
  onConfirm: () => void
  onReject: () => void
}) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [rawText, setRawText] = useState('')
  const [rewrittenContent, setRewrittenContent] = useState('')
  const [category, setCategory] = useState('')
  const [assetKind, setAssetKind] = useState('')
  const [tags, setTags] = useState('')

  useEffect(() => {
    setTitle(item?.title ?? '')
    setSummary(item?.summary ?? '')
    setRawText(item?.raw_text || '')
    setRewrittenContent(item?.rewritten_content ?? '')
    setCategory(item?.category ?? '')
    setAssetKind(item?.asset_kind ?? '')
    setTags(joinTags(item?.tags))
  }, [item?.id])

  if (!item) {
    return (
      <section className="prism-panel flex h-full min-h-0 flex-col items-center justify-center rounded-lg p-5 text-center">
        <Inbox size={34} className="mb-3 text-slate-300" />
        <h2 className="text-sm font-semibold text-slate-950">选择或添加一个碎片</h2>
        <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
          收件箱现在直接操作 personal_asset_item。确认后，碎片会进入资产层并沉淀到 PKU/CKP。
        </p>
      </section>
    )
  }

  return (
    <section className="prism-panel flex min-h-0 flex-col overflow-hidden rounded-lg p-3">
      <div className="mb-4 flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-xs font-medium text-slate-500">编辑待确认碎片</div>
          <h2 className="mt-1 truncate text-base font-semibold text-slate-950">{item.title}</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() =>
              onSave({
                title,
                summary,
                raw_text: rawText,
                rewritten_content: rewrittenContent,
                category,
                asset_kind: assetKind,
                tags: splitTags(tags),
              })
            }
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            保存
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onReject}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-100 bg-white px-2.5 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50"
          >
            <X size={15} />
            拒绝
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={onConfirm}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--prism-blue)] px-2.5 text-xs font-medium text-white transition hover:brightness-95 disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            确认入库
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid gap-3 2xl:grid-cols-2">
          <LabeledInput label="标题" value={title} onChange={setTitle} />
          <LabeledInput label="类型" value={assetKind} onChange={setAssetKind} placeholder="idea/opinion/knowledge/resource" />
          <LabeledInput label="分类" value={category} onChange={setCategory} />
          <LabeledInput label="标签" value={tags} onChange={setTags} icon={<Tags size={15} />} />
        </div>
        <div className="mt-3 grid gap-3">
          <LabeledTextarea label="摘要" value={summary} onChange={setSummary} rows={4} />
          <LabeledTextarea label="AI 改写内容" value={rewrittenContent} onChange={setRewrittenContent} rows={8} />
          <LabeledTextarea label="原始内容" value={rawText} onChange={setRawText} rows={12} />
          <ReadBlock label="来源" value={[item.raw_source_type, item.raw_source_platform, item.raw_source_url].filter(Boolean).join(' / ') || '-'} />
        </div>
      </div>
    </section>
  )
}

function LabeledInput({
  label,
  value,
  icon,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  icon?: React.ReactNode
  placeholder?: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <span className="relative block">
        {icon ? <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">{icon}</span> : null}
        <input
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            'h-8 w-full rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs outline-none transition focus:border-[var(--prism-blue)]',
            icon && 'pl-9',
          )}
        />
      </span>
    </label>
  )
}

function LabeledTextarea({
  label,
  value,
  rows,
  placeholder,
  onChange,
}: {
  label: string
  value: string
  rows: number
  placeholder?: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2 text-xs leading-5 outline-none transition focus:border-[var(--prism-blue)]"
      />
    </label>
  )
}

function ReadBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{label}</div>
      <div className="whitespace-pre-wrap rounded-lg border border-[var(--prism-line)] bg-slate-50 px-2.5 py-2 text-xs leading-5 text-slate-600">
        {value || '-'}
      </div>
    </div>
  )
}

function StateBlock({ text }: { text: string }) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-3 text-center text-xs leading-5 text-slate-500">
      {text}
    </div>
  )
}
