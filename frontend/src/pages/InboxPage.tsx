import { useEffect, useMemo, useState } from 'react'
import {
  assetApi,
  inboxApi,
  type AssetDraft,
  type PersonalAsset,
  type MemoryEntry,
} from '@/app/api'
import {
  Archive,
  BookmarkCheck,
  Check,
  Clock3,
  FileText,
  Inbox,
  Lightbulb,
  Loader2,
  MessageCircle,
  RefreshCw,
  Send,
  Sparkles,
  Tag,
  Trash2,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const KIND_META: Record<string, { label: string; icon: typeof Lightbulb; tone: string }> = {
  knowledge: { label: '知识点', icon: FileText, tone: 'bg-blue-50 text-blue-700 border-blue-100' },
  opinion: { label: '观点', icon: MessageCircle, tone: 'bg-violet-50 text-violet-700 border-violet-100' },
  resource: { label: '资源', icon: BookmarkCheck, tone: 'bg-cyan-50 text-cyan-700 border-cyan-100' },
  task: { label: '稍后处理', icon: Clock3, tone: 'bg-amber-50 text-amber-700 border-amber-100' },
  memory: { label: '记忆', icon: Sparkles, tone: 'bg-emerald-50 text-emerald-700 border-emerald-100' },
  idea: { label: '灵感', icon: Lightbulb, tone: 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-100' },
  chat: { label: '闲聊', icon: MessageCircle, tone: 'bg-slate-100 text-slate-700 border-slate-200' },
}

const FILTERS: Array<{ value: string; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'knowledge', label: '知识' },
  { value: 'opinion', label: '观点' },
  { value: 'resource', label: '资源' },
  { value: 'memory', label: '记忆' },
  { value: 'idea', label: '灵感' },
]

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function InboxPage() {
  const [content, setContent] = useState('')
  const [title, setTitle] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [sourcePlatform, setSourcePlatform] = useState('')
  const [filter, setFilter] = useState<string>('all')
  const [drafts, setDrafts] = useState<AssetDraft[]>([])
  const [assets, setAssets] = useState<PersonalAsset[]>([])
  const [memories, setMemories] = useState<MemoryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [busyDraftId, setBusyDraftId] = useState<string | null>(null)
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const visibleDrafts = useMemo(() => {
    if (filter === 'all') return drafts
    return drafts.filter((draft) => draft.asset_kind === filter)
  }, [filter, drafts])

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextReviews, nextNotes, nextMemories] = await Promise.all([
        assetApi.listDrafts({ status: 'pending' }),
        assetApi.listAssets(),
        inboxApi.listMemories(),
      ])
      setDrafts(nextReviews)
      setAssets(nextNotes)
      setMemories(nextMemories)
    } catch (err) {
      setError(`加载 Inbox 失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const submit = async () => {
    const text = content.trim()
    if (!text || submitting) {
      setError('先粘贴一段想保存的内容。')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const result = await assetApi.createDraft({
        content: text,
        title: title.trim() || undefined,
        source_url: sourceUrl.trim() || undefined,
        source_platform: sourcePlatform.trim() || undefined,
        source_type: sourceUrl.trim() ? 'web' : 'manual',
      })
      setDrafts((current) => [result, ...current])
      setContent('')
      setTitle('')
      setSourceUrl('')
      setSourcePlatform('')
    } catch (err) {
      setError(`采集失败：${getErrorMessage(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const approve = async (draft: AssetDraft) => {
    setBusyDraftId(draft.id)
    setError(null)
    try {
      await assetApi.confirmDraft(draft.id)
      setDrafts((current) => current.filter((item) => item.id !== draft.id))
      const [nextAssets, nextMemories] = await Promise.all([assetApi.listAssets(), inboxApi.listMemories()])
      setAssets(nextAssets)
      setMemories(nextMemories)
    } catch (err) {
      setError(`沉淀失败：${getErrorMessage(err)}`)
    } finally {
      setBusyDraftId(null)
    }
  }

  const saveDraft = async (draft: AssetDraft, patch: Partial<AssetDraft>) => {
    setBusyDraftId(draft.id)
    setError(null)
    try {
      const next = await assetApi.updateDraft(draft.id, patch)
      setDrafts((current) => current.map((item) => (item.id === draft.id ? next : item)))
      setEditingDraftId(null)
    } catch (err) {
      setError(`更新草稿失败：${getErrorMessage(err)}`)
    } finally {
      setBusyDraftId(null)
    }
  }

  return (
    <div className="grid h-[calc(100vh-8rem)] min-h-[40rem] gap-4 overflow-hidden xl:grid-cols-[23rem_minmax(0,1fr)_22rem]">
      <section className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
        <div className="mb-4 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-950 text-white">
            <Inbox size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-slate-950">收件箱</h1>
            <p className="text-xs text-slate-500">把看到的东西先放进来</p>
          </div>
        </div>

        <div className="space-y-3">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="标题，可不填"
            className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="粘贴评论、文章片段、视频链接、自己的想法..."
            className="min-h-56 w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-3 py-3 text-sm leading-6 outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
          <input
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
            placeholder="来源链接"
            className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
          <input
            value={sourcePlatform}
            onChange={(event) => setSourcePlatform(event.target.value)}
            placeholder="平台，例如微信、B站、即刻"
            className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
          <button
            type="button"
            disabled={submitting}
            onClick={submit}
            className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            采集并分类
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">
            {error}
          </div>
        )}
      </section>

      <main className="min-h-0 overflow-hidden">
        <section className="prism-panel flex h-full min-h-0 flex-col rounded-lg p-4">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">待审阅</h2>
              <p className="text-xs text-slate-500">{drafts.length} 条 AI 草稿等待确认</p>
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

          <div className="mb-4 flex flex-wrap gap-2">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setFilter(item.value)}
                className={cn(
                  'min-h-9 rounded-lg px-3 text-sm font-medium transition',
                  filter === item.value ? 'bg-slate-950 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {loading ? (
              <StateBlock icon={<Loader2 className="animate-spin" size={24} />} title="正在整理收件箱" text="稍等一下，审阅卡片马上回来。" />
            ) : visibleDrafts.length === 0 ? (
              <StateBlock icon={<Archive size={24} />} title="没有待审阅内容" text="新的材料会在分类后出现在这里。" />
            ) : (
              <div className="space-y-3">
                {visibleDrafts.map((draft) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    busy={busyDraftId === draft.id}
                    editing={editingDraftId === draft.id}
                    onEdit={() => setEditingDraftId(draft.id)}
                    onCancelEdit={() => setEditingDraftId(null)}
                    onSave={(patch) => saveDraft(draft, patch)}
                    onApprove={() => approve(draft)}
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      </main>

      <aside className="grid min-h-0 gap-4 overflow-hidden xl:grid-rows-2">
        <SettledPanel title="最近资产" items={assets} empty="确认后的知识资产会沉淀到这里。" />
        <SettledPanel title="轻量记忆" items={memories} empty="关于你的偏好、目标和约束会放在这里。" />
      </aside>
    </div>
  )
}

function DraftCard({
  draft,
  busy,
  editing,
  onEdit,
  onCancelEdit,
  onSave,
  onApprove,
}: {
  draft: AssetDraft
  busy: boolean
  editing: boolean
  onEdit: () => void
  onCancelEdit: () => void
  onSave: (patch: Partial<AssetDraft>) => void
  onApprove: () => void
}) {
  const meta = KIND_META[draft.asset_kind] ?? KIND_META.idea
  const Icon = meta.icon
  const confidence = typeof draft.confidence?.overall === 'number' ? draft.confidence.overall : undefined
  return (
    <article className="rounded-lg border border-[var(--prism-line)] bg-white p-4 shadow-[0_12px_32px_-28px_rgba(15,23,42,0.45)]">
      {editing ? (
        <DraftEditor draft={draft} busy={busy} onCancel={onCancelEdit} onSave={onSave} />
      ) : (
        <>
          <div className="flex items-start gap-3">
            <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border', meta.tone)}>
              <Icon size={17} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="break-words text-sm font-semibold text-slate-950">{draft.title}</h3>
                <span className={cn('rounded-md border px-2 py-1 text-xs font-medium', meta.tone)}>{meta.label}</span>
                {confidence !== undefined && (
                  <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                    {Math.round(confidence * 100)}%
                  </span>
                )}
              </div>
              {draft.summary && <p className="mt-2 text-sm leading-6 text-slate-600">{draft.summary}</p>}
              {draft.extracts?.length > 0 && (
                <div className="mt-3 rounded-lg border-l-2 border-slate-300 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">
                  {draft.extracts.slice(0, 2).map((item, index) => (
                    <p key={index}>{String(item.content ?? '')}</p>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {draft.category && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
                    <Tag size={12} />
                    {draft.category}
                  </span>
                )}
                {draft.tags?.map((tag) => (
                  <span key={tag} className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
                    #{tag}
                  </span>
                ))}
              </div>
              {draft.suggested_extensions?.length > 0 && (
                <p className="mt-3 text-xs leading-5 text-slate-400">
                  拓展建议：{draft.suggested_extensions.slice(0, 2).map((item) => String(item.title ?? '')).filter(Boolean).join('、')}
                </p>
              )}
              {draft.rationale && <p className="mt-3 text-xs leading-5 text-slate-400">{draft.rationale}</p>}
            </div>
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onEdit}
              className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-600 transition hover:border-blue-200 hover:text-[var(--prism-blue)] disabled:opacity-50"
            >
              <FileText size={15} />
              编辑
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onApprove}
              className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              确认入库
            </button>
          </div>
        </>
      )}
    </article>
  )
}

function DraftEditor({
  draft,
  busy,
  onCancel,
  onSave,
}: {
  draft: AssetDraft
  busy: boolean
  onCancel: () => void
  onSave: (patch: Partial<AssetDraft>) => void
}) {
  const [title, setTitle] = useState(draft.title)
  const [summary, setSummary] = useState(draft.summary ?? '')
  const [assetKind, setAssetKind] = useState(draft.asset_kind)
  const [category, setCategory] = useState(draft.category)
  const [sourceType, setSourceType] = useState(draft.source_type)
  const [sourcePlatform, setSourcePlatform] = useState(draft.source_platform)
  const [tags, setTags] = useState((draft.tags ?? []).join(', '))

  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2">
        <input value={title} onChange={(event) => setTitle(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
        <input value={assetKind} onChange={(event) => setAssetKind(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
        <input value={category} onChange={(event) => setCategory(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
        <input value={sourceType} onChange={(event) => setSourceType(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
        <input value={sourcePlatform} onChange={(event) => setSourcePlatform(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
        <input value={tags} onChange={(event) => setTags(event.target.value)} className="min-h-10 rounded-lg border border-[var(--prism-line)] px-3 text-sm outline-none focus:border-[var(--prism-blue)]" />
      </div>
      <textarea value={summary} onChange={(event) => setSummary(event.target.value)} className="min-h-24 w-full resize-none rounded-lg border border-[var(--prism-line)] px-3 py-2 text-sm leading-6 outline-none focus:border-[var(--prism-blue)]" />
      <div className="flex justify-end gap-2">
        <button type="button" disabled={busy} onClick={onCancel} className="min-h-9 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm font-medium text-slate-600 disabled:opacity-50">
          取消
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            onSave({
              title,
              summary,
              asset_kind: assetKind,
              category,
              source_type: sourceType,
              source_platform: sourcePlatform,
              tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean),
            })
          }
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
          保存
        </button>
      </div>
    </div>
  )
}

function SettledPanel({
  title,
  items,
  empty,
}: {
  title: string
  items: Array<PersonalAsset | MemoryEntry>
  empty: string
}) {
  const itemContent = (item: PersonalAsset | MemoryEntry) =>
    'content' in item ? item.content : (item.summary || item.body || '')
  return (
    <section className="prism-panel flex min-h-0 flex-col rounded-lg p-4">
      <h2 className="mb-3 text-base font-semibold text-slate-950">{title}</h2>
      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        {items.length === 0 ? (
          <div className="flex h-full min-h-32 items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-4 text-center text-sm leading-6 text-slate-500">
            {empty}
          </div>
        ) : (
          <div className="space-y-2">
            {items.slice(0, 8).map((item) => (
              <article key={item.id} className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-3">
                <div className="break-words text-sm font-semibold text-slate-950">{item.title}</div>
                <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-500">{itemContent(item)}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                  <span>{item.category || 'Inbox'}</span>
                  <span>{formatDate(item.created_at)}</span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function StateBlock({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-6 text-center">
      <div className="mb-3 text-slate-400">{icon}</div>
      <h3 className="text-base font-semibold text-slate-950">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-500">{text}</p>
    </div>
  )
}
