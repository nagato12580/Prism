import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { knowledgeApi, type KnowledgeItem } from '@/app/api'
import { FileText, Link as LinkIcon, Loader2, Plus, Trash2, Upload } from 'lucide-react'

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

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const nextItems = await knowledgeApi.list()
      setItems(nextItems)
    } catch (err) {
      setError(`知识库加载失败：${getErrorMessage(err)}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || busy) return

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadFile(file)
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
    if (!url || busy) return

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setError('请输入以 http:// 或 https:// 开头的 URL。')
      return
    }

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadUrl(url)
      setUrlInput('')
      await load()
    } catch (err) {
      setError(`URL 导入失败：${getErrorMessage(err)}`)
    } finally {
      setBusy(false)
    }
  }

  const handleCreate = async () => {
    const title = newTitle.trim()
    if (!title) {
      setError('请先填写笔记标题。')
      return
    }
    if (busy) return

    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.create({
        title,
        content: newContent,
        source_type: 'manual',
      })
      setNewTitle('')
      setNewContent('')
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(`笔记保存失败：${getErrorMessage(err)}`)
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

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-normal text-slate-950">知识库</h1>
            <span className="rounded-full border border-[var(--prism-line)] bg-white px-3 py-1 text-xs font-medium text-slate-600">
              {items.length} 条
            </span>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-slate-600">
            管理 Prism 用来检索和回答的资料。当前 {items.length} 条知识。
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={handleUpload}
            accept=".pdf,.docx,.xlsx,.md,.txt"
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
          <button
            type="button"
            disabled={busy}
            onClick={() => setShowCreate((value) => !value)}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-55"
          >
            <Plus size={16} />
            新建笔记
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
              value={urlInput}
              disabled={busy}
              onChange={(event) => setUrlInput(event.target.value)}
              placeholder="粘贴网页 URL，导入为知识条目"
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

      {error && (
        <div className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:flex-row sm:items-start sm:justify-between">
          <p className="min-w-0 break-words">{error}</p>
          <button
            type="button"
            onClick={() => setError(null)}
            className="self-start rounded-md px-2 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100"
          >
            关闭
          </button>
        </div>
      )}

      {showCreate && (
        <section className="prism-panel space-y-3 p-4">
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-[var(--prism-blue)]" />
            <h2 className="text-base font-semibold text-slate-950">新建笔记</h2>
          </div>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-600">标题</span>
            <input
              value={newTitle}
              disabled={busy}
              onChange={(event) => setNewTitle(event.target.value)}
              placeholder="笔记标题"
              className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-slate-600">内容</span>
            <textarea
              value={newContent}
              disabled={busy}
              onChange={(event) => setNewContent(event.target.value)}
              placeholder="笔记内容，支持 Markdown"
              className="min-h-36 w-full resize-y rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
            />
          </label>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowCreate(false)}
              className="inline-flex min-h-10 items-center justify-center rounded-lg px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-55"
            >
              取消
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={handleCreate}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
            >
              {busy && <Loader2 size={16} className="animate-spin" />}
              保存笔记
            </button>
          </div>
        </section>
      )}

      {loading ? (
        <div className="flex min-h-44 items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 text-sm text-slate-500">
          <Loader2 size={18} className="mr-2 animate-spin text-[var(--prism-blue)]" />
          正在加载知识库...
        </div>
      ) : items.length === 0 ? (
        <div className="flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-6 py-12 text-center">
          <FileText size={28} className="mb-3 text-slate-400" />
          <h2 className="text-base font-semibold text-slate-950">还没有知识条目</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
            上传文件、导入网页，或写一条笔记开始构建 Prism 的知识来源。
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => {
            const createdDate = formatDate(item.created_at)
            const summary = item.summary || item.content

            return (
              <article key={item.id} className="prism-panel flex min-h-48 flex-col p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-[var(--prism-blue)]">
                    <FileText size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h2 className="break-words text-sm font-semibold leading-5 text-slate-950">
                      {item.title}
                    </h2>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">
                        {item.source_type}
                      </span>
                      {item.status && (
                        <span className="rounded-md bg-emerald-50 px-2 py-1 font-medium text-emerald-700">
                          {item.status}
                        </span>
                      )}
                      {createdDate && <span>{createdDate}</span>}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => handleDelete(item.id)}
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

                {(item.category || item.tags?.length) && (
                  <div className="mt-auto flex flex-wrap gap-2 pt-4">
                    {item.category && (
                      <span className="rounded-md border border-[var(--prism-line)] px-2 py-1 text-xs font-medium text-slate-600">
                        {item.category}
                      </span>
                    )}
                    {item.tags?.map((tag) => (
                      <span
                        key={tag}
                        className="max-w-full truncate rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700"
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
