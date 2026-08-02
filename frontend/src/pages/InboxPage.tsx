import { useEffect, useMemo, useState } from 'react'
import { Check, Inbox, Loader2, RefreshCw, Save, Search, Sparkles, Tags, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
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
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null)
  const [regenerationKey, setRegenerationKey] = useState(0)

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

  const confirmActive = async (opts: { create_memory: boolean }) => {
    if (!active) return
    setSaving(true)
    setError(null)
    try {
      await assetApi.confirmItem(active.id, { create_memory: opts.create_memory })
      removeItemFromList(active.id)
      setNotice(
        opts.create_memory
          ? '已确认入库，记录已进入资产层、知识治理层并沉淀为长期记忆。'
          : '已确认入库，记录已进入资产层和知识治理层。',
      )
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
      setNotice('已拒绝该记录。')
    } catch (err) {
      setError(`拒绝失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const regenerateItem = async (itemId: string, rawText?: string, title?: string) => {
    setRegeneratingId(itemId)
    setError(null)
    try {
      const next = await assetApi.regenerateItem(itemId, { raw_text: rawText, title })
      setItems((current) => current.map((item) => (item.id === next.id ? next : item)))
      setRegenerationKey((k) => k + 1)
      setNotice('已重新生成 AI 改写内容和摘要。')
    } catch (err) {
      setError(`重新生成失败：${getErrorMessage(err)}`)
    } finally {
      setRegeneratingId(null)
    }
  }

  return (
    <div className="grid h-[calc(100vh-9rem)] min-h-0 gap-3 overflow-hidden text-[13px] xl:grid-cols-[21rem_minmax(0,1fr)]">
      <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
              <Inbox size={15} />
              <span>记录审核</span>
            </div>
            <h1 className="mt-1 text-base font-semibold text-slate-950">待确认记录</h1>
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
            <StateBlock text="正在加载待确认记录" />
          ) : filtered.length === 0 ? (
            <StateBlock text="暂无待确认记录。在对话页说「帮我记一下…」即可采集想法，稍后来这里确认入库。" />
          ) : (
            <div className="space-y-2">
              {filtered.map((item) => (
                <div
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveId(item.id)}
                  onKeyDown={(e) => { if (e.key === 'Enter') setActiveId(item.id) }}
                  className={cn(
                    'group relative w-full cursor-pointer rounded-lg border bg-white p-2.5 text-left transition',
                    activeId === item.id
                      ? 'border-[var(--prism-blue)] ring-2 ring-blue-100'
                      : 'border-[var(--prism-line)] hover:border-blue-200',
                  )}
                >
                  <button
                    type="button"
                    disabled={regeneratingId === item.id}
                    onClick={(e) => { e.stopPropagation(); regenerateItem(item.id) }}
                    title="重新生成 AI 改写内容和摘要"
                    className={cn(
                      'absolute right-2 top-2 inline-flex h-6 w-6 items-center justify-center rounded-md transition',
                      regeneratingId === item.id
                        ? 'bg-blue-50 text-[var(--prism-blue)]'
                        : 'text-slate-300 opacity-0 group-hover:opacity-100 hover:bg-blue-50 hover:text-[var(--prism-blue)]',
                    )}
                  >
                    {regeneratingId === item.id ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <Sparkles size={13} />
                    )}
                  </button>
                  <div className="truncate pr-8 text-[13px] font-semibold text-slate-950">{item.title}</div>
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
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <main className="min-h-0 overflow-hidden">
        <EditorPanel
          item={active}
          saving={saving}
          regenerating={regeneratingId === active?.id}
          regenerationKey={regenerationKey}
          onSave={updateActive}
          onRegenerate={(rawText, title) => active && regenerateItem(active.id, rawText, title)}
          onConfirm={confirmActive}
          onReject={rejectActive}
        />
      </main>
    </div>
  )
}

function EditorPanel({
  item,
  saving,
  regenerating,
  regenerationKey,
  onSave,
  onRegenerate,
  onConfirm,
  onReject,
}: {
  item: AssetDraft | null
  saving: boolean
  regenerating: boolean
  regenerationKey: number
  onSave: (patch: Partial<AssetDraft>) => void
  onRegenerate: (rawText: string, title: string) => void
  onConfirm: (opts: { create_memory: boolean }) => void
  onReject: () => void
}) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [rawText, setRawText] = useState('')
  const [rewrittenContent, setRewrittenContent] = useState('')
  const [rewrittenMode, setRewrittenMode] = useState<'preview' | 'edit'>('preview')
  const [category, setCategory] = useState('')
  const [assetKind, setAssetKind] = useState('')
  const [tags, setTags] = useState('')
  const [createMemory, setCreateMemory] = useState(false)

  useEffect(() => {
    setTitle(item?.title ?? '')
    setSummary(item?.summary ?? '')
    setRawText(item?.raw_text || '')
    setRewrittenContent(item?.rewritten_content ?? '')
    setRewrittenMode('preview')
    setCategory(item?.category ?? '')
    setAssetKind(item?.asset_kind ?? '')
    setTags(joinTags(item?.tags))
    setCreateMemory((item?.asset_kind ?? '').trim().toLowerCase() === 'memory')
  }, [item?.id, regenerationKey])

  if (!item) {
    return (
      <section className="prism-panel flex h-full min-h-0 flex-col items-center justify-center rounded-lg p-5 text-center">
        <Inbox size={34} className="mb-3 text-slate-300" />
        <h2 className="text-sm font-semibold text-slate-950">选择或添加一个记录</h2>
        <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
          想法从对话页采集，在这里确认后进入资产层。
        </p>
      </section>
    )
  }

  return (
    <section className="prism-panel flex h-full min-h-0 flex-col overflow-hidden rounded-lg p-3">
      <div className="flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-xs font-medium text-slate-500">编辑待确认记录</div>
          <h2 className="mt-1 truncate text-base font-semibold text-slate-950">{item.title}</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={saving || regenerating}
            onClick={() => onRegenerate(rawText, title)}
            title="基于当前原始内容重新生成 AI 改写内容和摘要"
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-purple-200 bg-white px-2.5 text-xs font-medium text-purple-600 transition hover:bg-purple-50 disabled:opacity-50"
          >
            {regenerating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            重新生成
          </button>
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
            onClick={() => onConfirm({ create_memory: createMemory })}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--prism-blue)] px-2.5 text-xs font-medium text-white transition hover:brightness-95 disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            确认入库
          </button>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-2 border-b border-[var(--prism-line)] pb-4">
        <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={createMemory}
            onChange={(event) => setCreateMemory(event.target.checked)}
            className="h-3.5 w-3.5 rounded border-[var(--prism-line)] text-[var(--prism-blue)] focus:ring-blue-100"
          />
          同时沉淀为长期记忆
        </label>
        {createMemory ? (
          <span className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">
            确认后写入用户画像记忆
          </span>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid gap-3 2xl:grid-cols-2">
          <LabeledInput label="标题" value={title} onChange={setTitle} />
          <LabeledInput
            label="类型"
            value={assetKind}
            onChange={setAssetKind}
            placeholder="idea/opinion/knowledge/resource/memory"
          />
          <LabeledInput label="分类" value={category} onChange={setCategory} />
          <LabeledInput label="标签" value={tags} onChange={setTags} icon={<Tags size={15} />} />
        </div>
        <div className="mt-3 grid gap-3">
          <LabeledTextarea label="摘要" value={summary} onChange={setSummary} rows={4} />
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500">AI 改写内容（Markdown）</span>
              <div className="flex items-center gap-1 rounded-lg border border-[var(--prism-line)] bg-white p-0.5 text-[10px]">
                {(['preview', 'edit'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setRewrittenMode(mode)}
                    className={cn(
                      'rounded-md px-2 py-0.5 transition',
                      rewrittenMode === mode ? 'bg-[var(--prism-blue)] text-white' : 'text-slate-500 hover:text-slate-700',
                    )}
                  >
                    {mode === 'preview' ? 'Markdown 预览' : '编辑'}
                  </button>
                ))}
              </div>
            </div>
            {rewrittenMode === 'preview' ? (
              <div className="markdown-body max-h-80 overflow-y-auto rounded-lg border border-[var(--prism-line)] bg-slate-50 px-2.5 py-2 text-xs leading-5">
                {rewrittenContent.trim() ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{rewrittenContent}</ReactMarkdown>
                ) : (
                  <span className="text-slate-400">暂无改写内容</span>
                )}
              </div>
            ) : (
              <textarea
                value={rewrittenContent}
                rows={8}
                onChange={(event) => setRewrittenContent(event.target.value)}
                className="w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2 text-xs leading-5 outline-none transition focus:border-[var(--prism-blue)]"
              />
            )}
          </div>
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
