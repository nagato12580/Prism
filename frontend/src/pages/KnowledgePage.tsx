import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { knowledgeApi, type KnowledgeItem } from '@/app/api'
import {
  ArrowLeft,
  BookOpen,
  FileText,
  Folder,
  FolderPlus,
  Link as LinkIcon,
  Loader2,
  Trash2,
  Upload,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const DEFAULT_DIRECTORY = '未分类'

function formatDate(value: string) {
  if (!value) return ''

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function getDirectoryName(item: KnowledgeItem) {
  return item.category?.trim() || DEFAULT_DIRECTORY
}

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [localDirectories, setLocalDirectories] = useState<string[]>([])
  const [activeDirectory, setActiveDirectory] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showDirectoryForm, setShowDirectoryForm] = useState(false)
  const [newDirectoryName, setNewDirectoryName] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await knowledgeApi.list())
    } catch (err) {
      setError(`知识库加载失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const directories = useMemo(() => {
    const map = new Map<string, KnowledgeItem[]>()
    for (const item of items) {
      const directory = getDirectoryName(item)
      map.set(directory, [...(map.get(directory) || []), item])
    }

    for (const directory of localDirectories) {
      if (!map.has(directory)) map.set(directory, [])
    }

    return Array.from(map.entries())
      .map(([name, directoryItems]) => ({
        name,
        items: directoryItems,
        updatedAt: directoryItems
          .map((item) => new Date(item.created_at).getTime())
          .filter((time) => Number.isFinite(time))
          .sort((a, b) => b - a)[0],
      }))
      .sort((a, b) => {
        if (a.name === DEFAULT_DIRECTORY) return 1
        if (b.name === DEFAULT_DIRECTORY) return -1
        return (b.updatedAt || 0) - (a.updatedAt || 0) || a.name.localeCompare(b.name, 'zh-CN')
      })
  }, [items, localDirectories])

  const activeItems = useMemo(
    () => items.filter((item) => getDirectoryName(item) === activeDirectory),
    [activeDirectory, items],
  )

  const createDirectory = () => {
    const name = newDirectoryName.trim()
    if (!name) {
      setError('请先填写目录名称。')
      return
    }
    if (directories.some((directory) => directory.name === name)) {
      setError('这个目录已经存在。')
      return
    }

    setLocalDirectories((current) => [...current, name])
    setActiveDirectory(name)
    setNewDirectoryName('')
    setShowDirectoryForm(false)
    setError(null)
  }

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || busy || !activeDirectory) return

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadFile(file, activeDirectory)
      await load()
    } catch (err) {
      setError(`文件上传失败：${getErrorMessage(err)}`)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleUrl = async () => {
    const url = urlInput.trim()
    if (!url || busy || !activeDirectory) return

    try {
      const parsed = new URL(url)
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        throw new Error('invalid protocol')
      }
    } catch {
      setError('请输入有效的 http:// 或 https:// URL。')
      return
    }

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadUrl(url, activeDirectory)
      setUrlInput('')
      await load()
    } catch (err) {
      setError(`URL 导入失败：${getErrorMessage(err)}`)
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (busy || !confirm('确认删除这条知识吗？')) return

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.delete(id)
      await load()
    } catch (err) {
      setError(`删除失败：${getErrorMessage(err)}`)
    } finally {
      setBusy(false)
    }
  }

  if (activeDirectory) {
    return (
      <div className="space-y-5">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 space-y-2">
            <button
              type="button"
              onClick={() => setActiveDirectory(null)}
              className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 transition hover:text-[var(--prism-blue)]"
            >
              <ArrowLeft size={16} />
              返回知识库
            </button>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-normal text-slate-950">
                {activeDirectory}
              </h1>
              <span className="rounded-full border border-[var(--prism-line)] bg-white px-3 py-1 text-xs font-medium text-slate-600">
                {activeItems.length} 条资料
              </span>
            </div>
            <p className="max-w-2xl text-sm leading-6 text-slate-500">
              在这个目录里上传文件或导入网页，Prism 会把它们作为问答检索来源。
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={handleUpload}
              accept=".pdf,.docx,.xlsx,.md,.txt,.markdown"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
              上传文件
            </button>
          </div>
        </header>

        <section className="prism-panel p-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <LinkIcon
                size={16}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                aria-label="导入网页 URL"
                value={urlInput}
                disabled={busy}
                onChange={(event) => setUrlInput(event.target.value)}
                placeholder="粘贴网页 URL，导入到当前目录"
                className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-9 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>
            <button
              type="button"
              disabled={busy || !urlInput.trim()}
              onClick={handleUrl}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-55"
            >
              <LinkIcon size={16} />
              导入 URL
            </button>
          </div>
        </section>

        <ErrorMessage error={error} onClose={() => setError(null)} />

        {loading ? (
          <LoadingState text="正在加载目录资料..." />
        ) : activeItems.length === 0 ? (
          <EmptyState
            icon={<Upload size={28} />}
            title="这个目录还没有资料"
            description="点击右上角上传文件，或粘贴网页 URL 导入第一条知识来源。"
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {activeItems.map((item) => (
              <KnowledgeCard key={item.id} item={item} busy={busy} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-normal text-slate-950">知识库</h1>
            <span className="rounded-full border border-[var(--prism-line)] bg-white px-3 py-1 text-xs font-medium text-slate-600">
              {directories.length} 个目录
            </span>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-slate-500">
            先按主题建立目录，再进入目录上传资料。知识库首页只负责组织资料结构。
          </p>
        </div>

        <button
          type="button"
          onClick={() => setShowDirectoryForm((value) => !value)}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95"
        >
          <FolderPlus size={16} />
          新建目录
        </button>
      </header>

      <ErrorMessage error={error} onClose={() => setError(null)} />

      {showDirectoryForm && (
        <section className="prism-panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <FolderPlus size={18} className="text-[var(--prism-blue)]" />
            <h2 className="text-base font-semibold text-slate-950">新建目录</h2>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              value={newDirectoryName}
              onChange={(event) => setNewDirectoryName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') createDirectory()
              }}
              placeholder="例如：产品文档、会议资料、研究笔记"
              className="min-h-10 flex-1 rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
            />
            <button
              type="button"
              onClick={createDirectory}
              className="inline-flex min-h-10 items-center justify-center rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white"
            >
              创建
            </button>
            <button
              type="button"
              onClick={() => setShowDirectoryForm(false)}
              className="inline-flex min-h-10 items-center justify-center rounded-lg px-4 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100"
            >
              取消
            </button>
          </div>
        </section>
      )}

      {loading ? (
        <LoadingState text="正在加载知识库目录..." />
      ) : directories.length === 0 ? (
        <EmptyState
          icon={<FolderPlus size={28} />}
          title="还没有目录"
          description="先新建一个目录，再进入目录上传文件。"
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {directories.map((directory) => (
            <button
              key={directory.name}
              type="button"
              onClick={() => setActiveDirectory(directory.name)}
              className="prism-panel group min-h-44 p-4 text-left transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-[0_22px_52px_-38px_rgba(21,94,239,0.5)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)]"
            >
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-[var(--prism-blue)] transition group-hover:bg-[var(--prism-blue)] group-hover:text-white">
                  <Folder size={22} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="break-words text-base font-semibold leading-6 text-slate-950">
                    {directory.name}
                  </h2>
                  <p className="mt-1 text-sm text-slate-500">{directory.items.length} 条资料</p>
                </div>
              </div>
              <div className="mt-5 flex items-center justify-between text-xs text-slate-400">
                <span>点击进入目录</span>
                <span>{directory.updatedAt ? formatDate(new Date(directory.updatedAt).toISOString()) : '空目录'}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ErrorMessage({ error, onClose }: { error: string | null; onClose: () => void }) {
  if (!error) return null

  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:flex-row sm:items-start sm:justify-between"
    >
      <p className="min-w-0 break-words">{error}</p>
      <button
        type="button"
        onClick={onClose}
        className="self-start rounded-md px-2 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100"
      >
        关闭
      </button>
    </div>
  )
}

function LoadingState({ text }: { text: string }) {
  return (
    <div className="flex min-h-44 items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 text-sm text-slate-500">
      <Loader2 size={18} className="mr-2 animate-spin text-[var(--prism-blue)]" />
      {text}
    </div>
  )
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-6 py-12 text-center">
      <div className="mb-3 text-slate-400">{icon}</div>
      <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
    </div>
  )
}

function KnowledgeCard({
  item,
  busy,
  onDelete,
}: {
  item: KnowledgeItem
  busy: boolean
  onDelete: (id: string) => void
}) {
  const createdDate = formatDate(item.created_at)
  const summary = item.summary || item.content

  return (
    <article className="prism-panel flex min-h-48 flex-col p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-[var(--prism-blue)]">
          <FileText size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="break-words text-sm font-semibold leading-5 text-slate-950">{item.title}</h2>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="max-w-full truncate rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
              {item.source_type}
            </span>
            {item.status && (
              <span className="max-w-full truncate rounded-md bg-emerald-50 px-2 py-1 font-medium text-emerald-700">
                {item.status}
              </span>
            )}
            {createdDate && <span>{createdDate}</span>}
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDelete(item.id)}
          className="rounded-md p-2 text-slate-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={`删除 ${item.title}`}
        >
          <Trash2 size={16} />
        </button>
      </div>

      {summary && (
        <p className="mt-4 max-h-[4.5rem] overflow-hidden text-sm leading-6 text-slate-600">
          {summary}
        </p>
      )}

      {item.tags?.length ? (
        <div className="mt-auto flex flex-wrap gap-2 pt-4">
          {item.tags.map((tag) => (
            <span
              key={tag}
              className="max-w-full truncate rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700"
            >
              #{tag}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  )
}
