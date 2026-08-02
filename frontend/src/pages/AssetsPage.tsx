import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  BookOpenCheck,
  Boxes,
  Check,
  FileStack,
  GitBranch,
  Layers3,
  Loader2,
  Network,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Tags,
} from 'lucide-react'
import { assetApi, type PersonalAsset, type PersonalAssetUnit } from '@/app/api'
import { cn } from '@/lib/utils'

type ActiveTarget =
  | { type: 'asset'; id: string }
  | { type: 'knowledge'; id: string }
  | null

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

function shortDate(value?: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function unitStatusLabel(status: string) {
  if (status === 'pending' || status === 'pending_review') return '待确认'
  if (status === 'confirmed') return '已入库'
  if (status === 'rejected') return '已拒绝'
  return status || '-'
}

export function AssetsPage() {
  const [assets, setAssets] = useState<PersonalAsset[]>([])
  const [personalAssetUnits, setPersonalAssetUnits] = useState<PersonalAssetUnit[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [active, setActive] = useState<ActiveTarget>(null)
  const [query, setQuery] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [instruction, setInstruction] = useState('')
  const [loading, setLoading] = useState(false)
  const [synthesizing, setSynthesizing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const filteredAssets = useMemo(() => filterAssets(assets, query), [assets, query])
  const activeAsset = active?.type === 'asset' ? assets.find((item) => item.id === active.id) ?? null : null
  const activeKnowledge =
    active?.type === 'knowledge' ? personalAssetUnits.find((unit) => unit.id === active.id) ?? null : null
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
        assetApi.listPersonalAssetUnits(),
      ])
      setAssets(nextAssets)
      setPersonalAssetUnits(nextDrafts)
      setActive((current) => {
        if (current?.type === 'asset' && nextAssets.some((item) => item.id === current.id)) return current
        if (current?.type === 'knowledge' && nextDrafts.some((item) => item.id === current.id)) return current
        if (nextAssets[0]) return { type: 'asset', id: nextAssets[0].id }
        if (nextDrafts[0]) return { type: 'knowledge', id: nextDrafts[0].id }
        return null
      })
    } catch (err) {
      setError(`加载资产失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))
  }

  const createPersonalAssetUnit = async () => {
    if (selectedIds.length === 0) {
      setError('请先从左侧选择要整理的入库碎片。')
      return
    }
    setSynthesizing(true)
    setError(null)
    setNotice(null)
    try {
      const unit = await assetApi.createPersonalAssetUnit({
        asset_ids: selectedIds,
        title: draftTitle.trim() || undefined,
        instruction: instruction.trim() || undefined,
      })
      setPersonalAssetUnits((current) => [unit, ...current.filter((item) => item.id !== unit.id)])
      setActive({ type: 'knowledge', id: unit.id })
      setDraftTitle('')
      setInstruction('')
      setNotice('已基于所选碎片生成知识草稿，右侧可继续确认入库。')
    } catch (err) {
      setError(`生成知识草稿失败：${getErrorMessage(err)}`)
    } finally {
      setSynthesizing(false)
    }
  }

  const updatePersonalAssetUnit = async (unitId: string, patch: Partial<PersonalAssetUnit>) => {
    setSaving(true)
    setError(null)
    try {
      const next = await assetApi.updatePersonalAssetUnit(unitId, patch)
      setPersonalAssetUnits((current) => current.map((item) => (item.id === next.id ? next : item)))
      setActive({ type: 'knowledge', id: next.id })
      setNotice('知识草稿已保存，尚未进入正式知识库。')
    } catch (err) {
      setError(`保存知识草稿失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const updateAsset = async (assetId: string, patch: Partial<PersonalAsset>) => {
    setSaving(true)
    setError(null)
    try {
      const next = await assetApi.updateItem(assetId, patch)
      setAssets((current) => current.map((item) => (item.id === next.id ? next : item)))
      setActive({ type: 'asset', id: next.id })
      setNotice('资产已保存。')
    } catch (err) {
      setError(`保存资产失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  const confirmPersonalAssetUnit = async (unitId: string) => {
    setSaving(true)
    setError(null)
    try {
      const result = await assetApi.confirmPersonalAssetUnit(unitId)
      setPersonalAssetUnits((current) => current.map((item) => (item.id === result.unit.id ? result.unit : item)))
      setActive({ type: 'knowledge', id: result.unit.id })
      setNotice('确认入库成功，已生成正式知识条目。')
    } catch (err) {
      setError(`确认入库失败：${getErrorMessage(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid h-[calc(100vh-9rem)] min-h-0 overflow-hidden gap-3 text-[13px] xl:grid-cols-[21rem_minmax(0,1fr)_20rem]">
      <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
              <Boxes size={15} />
              <span>记录合并</span>
            </div>
            <h1 className="mt-1 text-base font-semibold text-slate-950">已入库碎片</h1>
          </div>
          <button
            type="button"
            onClick={loadAll}
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

        <div className="mt-3 rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-slate-700">已选择 {selectedIds.length} 条</span>
            <button
              type="button"
              disabled={selectedIds.length === 0}
              onClick={() => setSelectedIds([])}
              className="text-xs font-medium text-slate-500 transition hover:text-slate-900 disabled:opacity-40"
            >
              清空
            </button>
          </div>
        </div>

        {error ? (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">
            {error}
          </div>
        ) : null}

        <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
          {loading ? (
            <StateBlock text="正在加载已入库碎片" />
          ) : filteredAssets.length === 0 ? (
            <StateBlock text="这里不会采集原始内容。请先在收件箱确认碎片入库。" />
          ) : (
            <div className="space-y-2">
              {filteredAssets.map((asset) => (
                <AssetListItem
                  key={asset.id}
                  asset={asset}
                  active={active?.type === 'asset' && active.id === asset.id}
                  selected={selectedIds.includes(asset.id)}
                  onOpen={() => setActive({ type: 'asset', id: asset.id })}
                  onToggle={() => toggleSelected(asset.id)}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      <main className="min-h-0 overflow-hidden">
        {activeKnowledge ? (
          <KnowledgeWorkspace
            unit={activeKnowledge}
            assets={assets}
            saving={saving}
            onSave={updatePersonalAssetUnit}
            onConfirm={confirmPersonalAssetUnit}
          />
        ) : (
          <AssetWorkspace
            asset={activeAsset}
            selectedAssets={selectedAssets}
            saving={saving}
            draftTitle={draftTitle}
            instruction={instruction}
            synthesizing={synthesizing}
            onSaveAsset={updateAsset}
            onDraftTitleChange={setDraftTitle}
            onInstructionChange={setInstruction}
            onCreatePersonalAssetUnit={createPersonalAssetUnit}
          />
        )}
      </main>

      <aside className="prism-panel flex min-h-0 flex-col overflow-hidden rounded-lg p-3">
        <div className="mb-3 flex items-center gap-2">
          <BookOpenCheck size={16} className="text-[var(--prism-blue)]" />
          <h2 className="text-sm font-semibold text-slate-950">整理后的知识</h2>
        </div>
        {notice ? (
          <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
            {notice}
          </div>
        ) : null}
        <KnowledgeList
          units={personalAssetUnits}
          activeId={active?.type === 'knowledge' ? active.id : null}
          onOpen={(unit) => setActive({ type: 'knowledge', id: unit.id })}
        />
      </aside>
    </div>
  )
}

function filterAssets(items: PersonalAsset[], query: string) {
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
      item.source_platform,
      ...(item.tags ?? []),
    ]
      .join(' ')
      .toLowerCase()
      .includes(q),
  )
}

function AssetListItem({
  asset,
  active,
  selected,
  onOpen,
  onToggle,
}: {
  asset: PersonalAsset
  active: boolean
  selected: boolean
  onOpen: () => void
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'w-full rounded-lg border bg-white p-2.5 text-left transition',
        active ? 'border-[var(--prism-blue)] ring-2 ring-blue-100' : 'border-[var(--prism-line)] hover:border-blue-200',
      )}
    >
      <div className="flex items-start gap-3">
        <span
          role="checkbox"
          aria-checked={selected}
          tabIndex={0}
          onClick={(event) => {
            event.stopPropagation()
            onToggle()
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              event.stopPropagation()
              onToggle()
            }
          }}
          className={cn(
            'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border',
            selected ? 'border-[var(--prism-blue)] bg-[var(--prism-blue)] text-white' : 'border-slate-300',
          )}
        >
          {selected ? <Check size={13} /> : null}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-semibold text-slate-950">{asset.title}</span>
          <span className="mt-1 line-clamp-2 block text-[11px] leading-4 text-slate-500">
            {asset.summary || asset.raw_text || '无摘要'}
          </span>
          <span className="mt-2 flex flex-wrap gap-1.5">
            <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">已入库</span>
            {(asset.tags ?? []).slice(0, 2).map((tag) => (
              <span key={tag} className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">
                #{tag}
              </span>
            ))}
          </span>
        </span>
      </div>
    </button>
  )
}

function AssetWorkspace({
  asset,
  selectedAssets,
  saving,
  draftTitle,
  instruction,
  synthesizing,
  onSaveAsset,
  onDraftTitleChange,
  onInstructionChange,
  onCreatePersonalAssetUnit,
}: {
  asset: PersonalAsset | null
  selectedAssets: PersonalAsset[]
  saving: boolean
  draftTitle: string
  instruction: string
  synthesizing: boolean
  onSaveAsset: (assetId: string, patch: Partial<PersonalAsset>) => void
  onDraftTitleChange: (value: string) => void
  onInstructionChange: (value: string) => void
  onCreatePersonalAssetUnit: () => void
}) {
  const primary = asset ?? selectedAssets[0] ?? null
  const [assetTitle, setAssetTitle] = useState('')
  const [assetSummary, setAssetSummary] = useState('')
  const [assetRewrittenContent, setAssetRewrittenContent] = useState('')
  const [assetRawText, setAssetRawText] = useState('')

  useEffect(() => {
    setAssetTitle(primary?.title ?? '')
    setAssetSummary(primary?.summary ?? '')
    setAssetRewrittenContent(primary?.rewritten_content ?? '')
    setAssetRawText(primary?.raw_text || '')
  }, [primary?.id])

  if (!primary) {
    return (
      <section className="prism-panel flex h-full min-h-0 flex-col items-center justify-center rounded-lg p-5 text-center">
        <Layers3 size={34} className="mb-3 text-slate-300" />
        <h2 className="text-sm font-semibold text-slate-950">从左侧选择已入库碎片</h2>
        <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
          记录合并只治理已经确认入库的最小碎片单元。原始采集请在记录审核完成。
        </p>
      </section>
    )
  }

  const visibleAssets = selectedAssets.length ? selectedAssets : [primary]
  const tagCounts = countTags(visibleAssets)
  const categories = countBy(visibleAssets.map((item) => item.category || '未分类'))

  return (
    <section className="prism-panel flex h-full min-h-0 flex-col overflow-hidden rounded-lg p-3">
      <div className="mb-4 flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <Network size={15} />
            <span>{visibleAssets.length} 个碎片正在查看</span>
          </div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">碎片可视化结果</h2>
        </div>
        <button
          type="button"
          disabled={visibleAssets.length === 0 || synthesizing}
          onClick={onCreatePersonalAssetUnit}
          className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--prism-blue)] px-2.5 text-xs font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {synthesizing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          整理为知识草稿
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid gap-3 md:grid-cols-3">
          <MetricCard label="碎片数" value={visibleAssets.length} />
          <MetricCard label="分类数" value={categories.length} />
          <MetricCard label="标签数" value={tagCounts.length} />
        </div>

        <div className="mt-4 rounded-lg border border-[var(--prism-line)] bg-white p-3">
          <h3 className="text-[13px] font-semibold text-slate-950">整理设置</h3>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">知识草稿标题</span>
              <input
                value={draftTitle}
                onChange={(event) => onDraftTitleChange(event.target.value)}
                placeholder="可不填，由 AI 生成"
                className="h-8 w-full rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs outline-none focus:border-[var(--prism-blue)]"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">整理要求</span>
              <input
                value={instruction}
                onChange={(event) => onInstructionChange(event.target.value)}
                placeholder="例如：合并相同观点，保留争议点"
                className="h-8 w-full rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs outline-none focus:border-[var(--prism-blue)]"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tagCounts.slice(0, 10).map(([tag, count]) => (
              <span key={tag} className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">
                #{tag} {count}
              </span>
            ))}
            {tagCounts.length === 0 ? <span className="text-xs text-slate-400">暂无标签</span> : null}
          </div>
        </div>

        <div className="mt-3 rounded-lg border border-[var(--prism-line)] bg-slate-50 p-3">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-slate-950">
            <GitBranch size={16} className="text-[var(--prism-blue)]" />
            碎片聚合视图
          </div>
          <div className="space-y-3">
            {visibleAssets.slice(0, 8).map((item, index) => (
              <div key={item.id} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-[var(--prism-blue)]">
                    {index + 1}
                  </span>
                  {index < visibleAssets.length - 1 ? <span className="mt-1 h-full min-h-6 w-px bg-blue-100" /> : null}
                </div>
                <div className="min-w-0 flex-1 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2">
                  <div className="truncate text-[13px] font-semibold text-slate-950">{item.title}</div>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{item.summary || item.raw_text}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(item.tags ?? []).slice(0, 4).map((tag) => (
                      <span key={tag} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-3 rounded-lg border border-[var(--prism-line)] bg-white p-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-semibold text-slate-950">当前碎片详情</h3>
            <button
              type="button"
              disabled={saving}
              onClick={() =>
                onSaveAsset(primary.id, {
                  title: assetTitle,
                  summary: assetSummary,
                  rewritten_content: assetRewrittenContent,
                  raw_text: assetRawText,
                })
              }
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              保存
            </button>
          </div>
          <div className="mt-3 grid gap-3">
            <LabeledInput label="标题" value={assetTitle} readOnly={false} onChange={setAssetTitle} />
            <LabeledTextarea label="摘要" value={assetSummary} readOnly={false} rows={4} onChange={setAssetSummary} />
            <LabeledTextarea label="AI 改写内容" value={assetRewrittenContent} readOnly={false} rows={8} onChange={setAssetRewrittenContent} />
            <LabeledTextarea label="原始内容" value={assetRawText} readOnly={false} rows={10} onChange={setAssetRawText} />
            <ReadBlock label="来源" value={[primary.source_platform, primary.source_url].filter(Boolean).join(' · ') || '-'} />
          </div>
        </div>
      </div>
    </section>
  )
}

function KnowledgeWorkspace({
  unit,
  assets,
  saving,
  onSave,
  onConfirm,
}: {
  unit: PersonalAssetUnit
  assets: PersonalAsset[]
  saving: boolean
  onSave: (unitId: string, patch: Partial<PersonalAssetUnit>) => void
  onConfirm: (unitId: string) => void
}) {
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [category, setCategory] = useState('')
  const [tags, setTags] = useState('')
  const [content, setContent] = useState('')

  useEffect(() => {
    setTitle(unit.title ?? '')
    setSummary(unit.summary ?? '')
    setCategory(unit.category ?? '')
    setTags(joinTags(unit.tags))
    setContent(unit.content ?? '')
  }, [unit.id])

  const readonly = !['pending', 'pending_review'].includes(unit.status)
  const sources = assets.filter((asset) => unit.source_asset_ids.includes(asset.id))

  return (
    <section className="prism-panel flex h-full min-h-0 flex-col overflow-hidden rounded-lg p-3">
      <div className="mb-4 flex flex-col gap-3 border-b border-[var(--prism-line)] pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <FileStack size={15} />
            <span>{unitStatusLabel(unit.status)}</span>
            <span>·</span>
            <span>{sources.length} 个来源碎片</span>
          </div>
          <h2 className="mt-1 text-base font-semibold text-slate-950">知识草稿 / 已入库知识</h2>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={saving || readonly}
            onClick={() => onSave(unit.id, { title, summary, category, tags: splitTags(tags), content })}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            保存草稿
          </button>
          <button
            type="button"
            disabled={saving || readonly}
            onClick={() => onConfirm(unit.id)}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-[var(--prism-blue)] px-2.5 text-xs font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <BookOpenCheck size={15} />}
            确认入库
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="grid gap-3">
          <LabeledInput label="标题" value={title} readOnly={readonly} onChange={setTitle} />
          <div className="grid gap-3 2xl:grid-cols-2">
            <LabeledInput label="分类" value={category} readOnly={readonly} onChange={setCategory} />
            <LabeledInput label="标签" value={tags} readOnly={readonly} onChange={setTags} icon={<Tags size={15} />} />
          </div>
          <LabeledTextarea label="摘要" value={summary} readOnly={readonly} rows={4} onChange={setSummary} />
          <LabeledTextarea label="正文" value={content} readOnly={readonly} rows={16} onChange={setContent} />
        </div>

        <div className="mt-4 rounded-lg border border-[var(--prism-line)] bg-slate-50 p-3">
          <h3 className="text-[13px] font-semibold text-slate-950">来源碎片</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {sources.map((asset) => (
              <div key={asset.id} className="rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2">
                <div className="truncate text-[13px] font-semibold text-slate-950">{asset.title}</div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{asset.summary || asset.raw_text}</p>
              </div>
            ))}
            {sources.length === 0 ? <StateBlock text="暂无来源碎片" compact /> : null}
          </div>
        </div>
      </div>
    </section>
  )
}

function KnowledgeList({
  units,
  activeId,
  onOpen,
}: {
  units: PersonalAssetUnit[]
  activeId: string | null
  onOpen: (unit: PersonalAssetUnit) => void
}) {
  if (units.length === 0) {
    return <StateBlock text="从左侧选择碎片后，在中间整理生成知识草稿。" />
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      <div className="space-y-2">
        {units.map((unit) => (
          <button
            key={unit.id}
            type="button"
            onClick={() => onOpen(unit)}
            className={cn(
              'w-full rounded-lg border bg-white px-2.5 py-2.5 text-left transition',
              activeId === unit.id
                ? 'border-[var(--prism-blue)] ring-2 ring-blue-100'
                : 'border-[var(--prism-line)] hover:border-blue-200',
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="truncate text-[13px] font-semibold text-slate-950">{unit.title}</span>
              <span
                className={cn(
                  'shrink-0 rounded-md px-2 py-1 text-[11px]',
                  unit.status === 'confirmed' ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700',
                )}
              >
                {unitStatusLabel(unit.status)}
              </span>
            </div>
            <p className="mt-1.5 line-clamp-3 text-[11px] leading-4 text-slate-500">{unit.summary || unit.content}</p>
            <div className="mt-2 text-[11px] text-slate-400">{unit.source_asset_ids.length} 个来源碎片</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2.5">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  )
}

function ReadBlock({ label, value, multiline = false }: { label: string; value: string; multiline?: boolean }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{label}</div>
      <div
        className={cn(
          'rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2 text-xs leading-5 text-slate-700',
          multiline ? 'whitespace-pre-wrap' : 'truncate',
        )}
      >
        {value || '-'}
      </div>
    </div>
  )
}

function LabeledInput({
  label,
  value,
  readOnly,
  icon,
  onChange,
}: {
  label: string
  value: string
  readOnly: boolean
  icon?: React.ReactNode
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <span className="relative block">
        {icon ? <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">{icon}</span> : null}
        <input
          value={value}
          readOnly={readOnly}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            'h-8 w-full rounded-lg border border-[var(--prism-line)] bg-white px-2.5 text-xs outline-none transition focus:border-[var(--prism-blue)]',
            icon && 'pl-9',
            readOnly && 'bg-slate-50 text-slate-600',
          )}
        />
      </span>
    </label>
  )
}

function LabeledTextarea({
  label,
  value,
  readOnly,
  rows,
  onChange,
}: {
  label: string
  value: string
  readOnly: boolean
  rows: number
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      <textarea
        value={value}
        rows={rows}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          'w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-2.5 py-2 text-xs leading-5 outline-none transition focus:border-[var(--prism-blue)]',
          readOnly && 'bg-slate-50 text-slate-600',
        )}
      />
    </label>
  )
}

function StateBlock({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-3 text-center text-xs leading-5 text-slate-500',
        compact ? 'min-h-20' : 'min-h-48',
      )}
    >
      {text}
    </div>
  )
}

function countTags(items: PersonalAsset[]) {
  const counts = new Map<string, number>()
  items.forEach((item) => {
    ;(item.tags ?? []).forEach((tag) => counts.set(tag, (counts.get(tag) ?? 0) + 1))
  })
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
}

function countBy(values: string[]) {
  const counts = new Map<string, number>()
  values.forEach((value) => counts.set(value, (counts.get(value) ?? 0) + 1))
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
}
