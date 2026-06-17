import { useEffect, useMemo, useState } from 'react'
import { assetApi, type KnowledgeDraft, type PersonalAsset } from '@/app/api'
import { BookOpenCheck, Check, FileStack, Loader2, RefreshCw, Search, Sparkles, Tags } from 'lucide-react'
import { cn } from '@/lib/utils'

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function splitTags(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function AssetsPage() {
  const [assets, setAssets] = useState<PersonalAsset[]>([])
  const [knowledgeDrafts, setKnowledgeDrafts] = useState<KnowledgeDraft[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeDraft, setActiveDraft] = useState<KnowledgeDraft | null>(null)
  const [query, setQuery] = useState('')
  const [title, setTitle] = useState('')
  const [instruction, setInstruction] = useState('')
  const [loading, setLoading] = useState(false)
  const [synthesizing, setSynthesizing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const filteredAssets = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return assets
    return assets.filter((asset) => {
      const text = [asset.title, asset.summary, asset.body, asset.category, asset.asset_kind, ...(asset.tags ?? [])]
        .join(' ')
        .toLowerCase()
      return text.includes(q)
    })
  }, [assets, query])

  const selectedAssets = useMemo(
    () => assets.filter((asset) => selectedIds.includes(asset.id)),
    [assets, selectedIds],
  )

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextAssets, nextDrafts] = await Promise.all([
        assetApi.listAssets(),
        assetApi.listKnowledgeDrafts({ status: 'pending' }),
      ])
      setAssets(nextAssets)
      setKnowledgeDrafts(nextDrafts)
      setActiveDraft((current) => current ?? nextDrafts[0] ?? null)
    } catch (err) {
      setError(`加载资产失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  const createKnowledgeDraft = async () => {
    if (selectedIds.length === 0 || synthesizing) {
      setError('请先选择要整理的资产。')
      return
    }
    setSynthesizing(true)
    setError(null)
    try {
      const draft = await assetApi.createKnowledgeDraft({
        asset_ids: selectedIds,
        title: title.trim() || undefined,
        instruction: instruction.trim() || undefined,
      })
      setKnowledgeDrafts((current) => [draft, ...current])
      setActiveDraft(draft)
      setSelectedIds([])
      setTitle('')
      setInstruction('')
    } catch (err) {
      setError(`生成知识草稿失败：${getErrorMessage(err)}`)
    } finally {
      setSynthesizing(false)
    }
  }

  const updateActiveDraft = async (patch: Partial<KnowledgeDraft>) => {
    if (!activeDraft || saving) return
    setSaving(true)
    setError(null)
    try {
      const next = await assetApi.updateKnowledgeDraft(activeDraft.id, patch)
      setActiveDraft(next)
      setKnowledgeDrafts((current) => current.map((draft) => (draft.id === next.id ? next : draft)))
    } catch (err) {
      setError(`保存知识草稿失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const confirmActiveDraft = async () => {
    if (!activeDraft || saving) return
    setSaving(true)
    setError(null)
    try {
      const result = await assetApi.confirmKnowledgeDraft(activeDraft.id, { ingest: false })
      setKnowledgeDrafts((current) => current.filter((draft) => draft.id !== activeDraft.id))
      setActiveDraft(result.draft)
    } catch (err) {
      setError(`确认进入知识库失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid min-h-[calc(100vh-9rem)] gap-4 xl:grid-cols-[24rem_minmax(0,1fr)]">
      <section className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-950">知识资产</h1>
            <p className="mt-1 text-xs text-slate-500">从已确认碎片中整理稳定知识</p>
          </div>
          <button
            type="button"
            onClick={loadAll}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)]"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>
        </div>

        <div className="relative mb-3">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、标签、来源或正文"
            className="h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-9 pr-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
        </div>

        <div className="mb-3 rounded-lg border border-[var(--prism-line)] bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-slate-800">{selectedIds.length} 个资产已选择</span>
            <button
              type="button"
              disabled={selectedIds.length === 0}
              onClick={() => setSelectedIds([])}
              className="text-xs font-medium text-slate-500 transition hover:text-slate-900 disabled:opacity-40"
            >
              清空
            </button>
          </div>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="知识草稿标题，可不填"
            className="mb-2 h-9 w-full rounded-md border border-[var(--prism-line)] bg-white px-3 text-xs outline-none focus:border-[var(--prism-blue)]"
          />
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="整理要求，可不填"
            className="mb-2 h-20 w-full resize-none rounded-md border border-[var(--prism-line)] bg-white px-3 py-2 text-xs leading-5 outline-none focus:border-[var(--prism-blue)]"
          />
          <button
            type="button"
            disabled={selectedIds.length === 0 || synthesizing}
            onClick={createKnowledgeDraft}
            className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {synthesizing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            整理为知识草稿
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
            {error}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {loading ? (
            <StateBlock text="正在加载资产池" />
          ) : filteredAssets.length === 0 ? (
            <StateBlock text="还没有可整理的已确认资产" />
          ) : (
            <div className="space-y-2">
              {filteredAssets.map((asset) => {
                const selected = selectedIds.includes(asset.id)
                return (
                  <button
                    key={asset.id}
                    type="button"
                    onClick={() => toggleSelected(asset.id)}
                    className={cn(
                      'w-full rounded-lg border bg-white p-3 text-left transition',
                      selected
                        ? 'border-[var(--prism-blue)] ring-2 ring-blue-100'
                        : 'border-[var(--prism-line)] hover:border-blue-200',
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <span
                        className={cn(
                          'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border',
                          selected ? 'border-[var(--prism-blue)] bg-[var(--prism-blue)] text-white' : 'border-slate-300',
                        )}
                      >
                        {selected ? <Check size={13} /> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="block break-words text-sm font-semibold text-slate-950">{asset.title}</span>
                        <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500">
                          {asset.summary || asset.body || '无摘要'}
                        </span>
                        <span className="mt-2 flex flex-wrap gap-1.5">
                          <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                            {asset.category || asset.asset_kind}
                          </span>
                          {(asset.tags ?? []).slice(0, 3).map((tag) => (
                            <span key={tag} className="rounded-md bg-blue-50 px-2 py-1 text-[11px] text-blue-700">
                              #{tag}
                            </span>
                          ))}
                        </span>
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </section>

      <main className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <KnowledgeDraftEditor
          draft={activeDraft}
          saving={saving}
          selectedAssets={selectedAssets}
          onSave={updateActiveDraft}
          onConfirm={confirmActiveDraft}
        />
        <section className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
          <h2 className="mb-3 text-base font-semibold text-slate-950">待确认草稿</h2>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {knowledgeDrafts.length === 0 ? (
              <StateBlock text="从左侧选择资产后生成草稿" compact />
            ) : (
              <div className="space-y-2">
                {knowledgeDrafts.map((draft) => (
                  <button
                    key={draft.id}
                    type="button"
                    onClick={() => setActiveDraft(draft)}
                    className={cn(
                      'w-full rounded-lg border bg-white px-3 py-3 text-left transition',
                      activeDraft?.id === draft.id
                        ? 'border-[var(--prism-blue)] ring-2 ring-blue-100'
                        : 'border-[var(--prism-line)] hover:border-blue-200',
                    )}
                  >
                    <div className="text-sm font-semibold text-slate-950">{draft.title}</div>
                    <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-500">{draft.summary}</p>
                    <div className="mt-2 text-[11px] text-slate-400">{draft.source_asset_ids.length} 个来源资产</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

function KnowledgeDraftEditor({
  draft,
  saving,
  selectedAssets,
  onSave,
  onConfirm,
}: {
  draft: KnowledgeDraft | null
  saving: boolean
  selectedAssets: PersonalAsset[]
  onSave: (patch: Partial<KnowledgeDraft>) => void
  onConfirm: () => void
}) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [category, setCategory] = useState('')
  const [tags, setTags] = useState('')
  const [content, setContent] = useState('')

  useEffect(() => {
    setTitle(draft?.title ?? '')
    setSummary(draft?.summary ?? '')
    setCategory(draft?.category ?? '')
    setTags((draft?.tags ?? []).join(', '))
    setContent(draft?.content ?? '')
  }, [draft?.id])

  if (!draft) {
    return (
      <section className="prism-panel flex min-h-[34rem] flex-col items-center justify-center rounded-lg p-6 text-center">
        <FileStack size={32} className="mb-3 text-slate-300" />
        <h2 className="text-base font-semibold text-slate-950">选择资产生成知识草稿</h2>
        <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
          已确认资产仍然保持碎片形态，只有经过整理和确认后才进入正式知识库。
        </p>
      </section>
    )
  }

  const sourceCount = draft.source_asset_ids.length || selectedAssets.length

  return (
    <section className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <BookOpenCheck size={15} />
            <span>{sourceCount} 个资产整理而来</span>
          </div>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">知识草稿</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={saving || draft.status !== 'pending'}
            onClick={() => onSave({ title, summary, category, tags: splitTags(tags), content })}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            保存
          </button>
          <button
            type="button"
            disabled={saving || draft.status !== 'pending'}
            onClick={onConfirm}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-3 text-sm font-medium text-white transition hover:brightness-95 disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            确认入知识库
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]"
        />
        <input
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          className="h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]"
        />
      </div>
      <textarea
        value={summary}
        onChange={(event) => setSummary(event.target.value)}
        className="mt-3 h-20 resize-none rounded-lg border border-[var(--prism-line)] px-3 py-2 text-sm leading-6 outline-none focus:border-[var(--prism-blue)]"
      />
      <div className="relative mt-3">
        <Tags size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          placeholder="标签，用英文逗号分隔"
          className="h-10 w-full rounded-lg border border-[var(--prism-line)] px-9 text-sm outline-none focus:border-[var(--prism-blue)]"
        />
      </div>
      <textarea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        className="mt-3 min-h-0 flex-1 resize-none rounded-lg border border-[var(--prism-line)] bg-white px-4 py-3 font-mono text-sm leading-6 outline-none focus:border-[var(--prism-blue)]"
      />
    </section>
  )
}

function StateBlock({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-4 text-center text-sm leading-6 text-slate-500',
        compact ? 'min-h-32' : 'min-h-64',
      )}
    >
      {text}
    </div>
  )
}
