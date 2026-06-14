import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import {
  knowledgeApi,
  type KnowledgeResource,
  type KnowledgeTopic,
  type ResourceFilterType,
  type ResourceMediaType,
} from '@/app/api'
import {
  Check,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderPlus,
  Loader2,
  Pencil,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const ACCEPTED_RESOURCE_EXTENSIONS =
  '.pdf,.doc,.docx,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif,.mp3,.wav,.m4a,.aac,.flac,.ogg,.mp4,.mov,.avi,.mkv,.webm'

const FILTERS: Array<{ value: ResourceFilterType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'document', label: '文档' },
  { value: 'image', label: '图片' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
]

const MEDIA_LABEL: Record<ResourceMediaType, string> = {
  document: '文档',
  image: '图片',
  audio: '音频',
  video: '视频',
}

function formatDate(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date)
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function readApiError(error: unknown, fallback: string) {
  const raw = getErrorMessage(error)
  try {
    const parsed = JSON.parse(raw)
    const detail = parsed.detail
    if (detail?.code === 'duplicate_resource_in_topic') return '这个文件已经上传到当前主题了。'
    if (detail?.code === 'duplicate_topic_name') return '这个主题名称已经存在。'
    if (detail?.code === 'topic_not_empty') return '请先删除目录里的资源，再删除目录。'
    if (detail?.code === 'invalid_resource_title') return '资源名称不能为空。'
    if (detail?.message) return `${fallback}：${detail.message}`
  } catch {
    return `${fallback}：${raw}`
  }
  return `${fallback}：${raw}`
}

export function KnowledgePage() {
  const [topics, setTopics] = useState<KnowledgeTopic[]>([])
  const [activeTopicId, setActiveTopicId] = useState<string | null>(null)
  const [resources, setResources] = useState<KnowledgeResource[]>([])
  const [filter, setFilter] = useState<ResourceFilterType>('all')
  const [loadingTopics, setLoadingTopics] = useState(false)
  const [loadingResources, setLoadingResources] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showTopicForm, setShowTopicForm] = useState(false)
  const [newTopicName, setNewTopicName] = useState('')
  const [newTopicDescription, setNewTopicDescription] = useState('')
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null)
  const [editingTopicName, setEditingTopicName] = useState('')
  const [editingResourceId, setEditingResourceId] = useState<string | null>(null)
  const [editingResourceTitle, setEditingResourceTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const activeTopic = topics.find((topic) => topic.id === activeTopicId) || null

  const loadTopics = async () => {
    setLoadingTopics(true)
    try {
      const loaded = await knowledgeApi.listTopics()
      setTopics(loaded)
      setActiveTopicId((current) => current || loaded[0]?.id || null)
    } catch (err) {
      setError(`知识库主题加载失败：${getErrorMessage(err)}`)
    } finally {
      setLoadingTopics(false)
    }
  }

  const loadResources = async (topicId: string, nextFilter = filter) => {
    setLoadingResources(true)
    try {
      const params = nextFilter === 'all' ? undefined : { media_type: nextFilter }
      setResources(await knowledgeApi.listResources(topicId, params))
    } catch (err) {
      setError(`资源加载失败：${getErrorMessage(err)}`)
    } finally {
      setLoadingResources(false)
    }
  }

  useEffect(() => {
    loadTopics()
  }, [])

  useEffect(() => {
    if (activeTopicId) {
      loadResources(activeTopicId)
    } else {
      setResources([])
    }
  }, [activeTopicId, filter])

  const createTopic = async () => {
    const name = newTopicName.trim()
    if (!name || busy) {
      setError('请先填写主题名称。')
      return
    }

    setBusy(true)
    setError(null)
    try {
      const topic = await knowledgeApi.createTopic({
        name,
        description: newTopicDescription.trim() || undefined,
      })
      setTopics((current) => [topic, ...current])
      setActiveTopicId(topic.id)
      setNewTopicName('')
      setNewTopicDescription('')
      setShowTopicForm(false)
    } catch (err) {
      setError(readApiError(err, '主题创建失败'))
    } finally {
      setBusy(false)
    }
  }

  const startTopicEdit = (topic: KnowledgeTopic) => {
    setEditingTopicId(topic.id)
    setEditingTopicName(topic.name)
  }

  const saveTopicName = async () => {
    if (!editingTopicId || busy) return
    const name = editingTopicName.trim()
    if (!name) {
      setError('主题名称不能为空。')
      return
    }

    setBusy(true)
    setError(null)
    try {
      const topic = await knowledgeApi.updateTopic(editingTopicId, { name })
      setTopics((current) => current.map((item) => (item.id === topic.id ? topic : item)))
      setEditingTopicId(null)
      setEditingTopicName('')
    } catch (err) {
      setError(readApiError(err, '主题改名失败'))
    } finally {
      setBusy(false)
    }
  }

  const deleteTopic = async (topic: KnowledgeTopic) => {
    if (busy || !confirm(`确认删除目录「${topic.name}」吗？`)) return

    setBusy(true)
    setError(null)
    try {
      await knowledgeApi.deleteTopic(topic.id)
      setTopics((current) => current.filter((item) => item.id !== topic.id))
      if (activeTopicId === topic.id) {
        setActiveTopicId(topics.find((item) => item.id !== topic.id)?.id || null)
      }
    } catch (err) {
      setError(readApiError(err, '目录删除失败'))
    } finally {
      setBusy(false)
    }
  }

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || busy || !activeTopicId) return

    setBusy(true)
    setError(null)
    try {
      await knowledgeApi.uploadResource(activeTopicId, file)
      await Promise.all([loadTopics(), loadResources(activeTopicId)])
    } catch (err) {
      setError(readApiError(err, '资源上传失败'))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const startResourceEdit = (resource: KnowledgeResource) => {
    setEditingResourceId(resource.id)
    setEditingResourceTitle(resource.title || resource.original_filename)
  }

  const saveResourceTitle = async () => {
    if (!editingResourceId || busy) return
    const title = editingResourceTitle.trim()
    if (!title) {
      setError('资源名称不能为空。')
      return
    }

    setBusy(true)
    setError(null)
    try {
      const resource = await knowledgeApi.updateResource(editingResourceId, { title })
      setResources((current) => current.map((item) => (item.id === resource.id ? resource : item)))
      setEditingResourceId(null)
      setEditingResourceTitle('')
    } catch (err) {
      setError(readApiError(err, '资源改名失败'))
    } finally {
      setBusy(false)
    }
  }

  const handleDeleteResource = async (resourceId: string) => {
    if (busy || !activeTopicId || !confirm('确认删除这个资源吗？')) return

    setBusy(true)
    setError(null)
    try {
      await knowledgeApi.deleteResource(resourceId)
      await Promise.all([loadTopics(), loadResources(activeTopicId)])
    } catch (err) {
      setError(readApiError(err, '资源删除失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid h-[calc(100vh-8rem)] min-h-[34rem] gap-4 overflow-hidden lg:grid-cols-[18rem_minmax(0,1fr)]">
      <aside data-testid="knowledge-topic-sidebar" className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold text-slate-950">知识库</h1>
          <button
            type="button"
            onClick={() => setShowTopicForm((value) => !value)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--prism-blue)] text-white transition hover:brightness-95"
            aria-label="新建主题"
            title="新建主题"
          >
            <FolderPlus size={17} />
          </button>
        </div>

        {showTopicForm && (
          <div className="mb-3 space-y-2">
            <input
              value={newTopicName}
              onChange={(event) => setNewTopicName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') createTopic()
              }}
              placeholder="主题名称"
              className="min-h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
            />
            <textarea
              value={newTopicDescription}
              onChange={(event) => setNewTopicDescription(event.target.value)}
              placeholder="描述"
              rows={2}
              className="w-full resize-none rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm outline-none transition focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
            />
            <button
              type="button"
              disabled={busy}
              onClick={createTopic}
              className="inline-flex min-h-9 w-full items-center justify-center rounded-lg bg-[var(--prism-blue)] px-3 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
            >
              创建主题
            </button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {loadingTopics ? (
            <LoadingState text="正在加载主题..." compact />
          ) : topics.length === 0 ? (
            <EmptyState icon={<FolderPlus size={26} />} title="还没有主题" description="先新建一个主题，再上传资源。" compact />
          ) : (
            <div className="space-y-2">
              {topics.map((topic) => (
                <TopicRow
                  key={topic.id}
                  topic={topic}
                  active={activeTopicId === topic.id}
                  busy={busy}
                  editing={editingTopicId === topic.id}
                  editingName={editingTopicName}
                  onSelect={() => setActiveTopicId(topic.id)}
                  onStartEdit={() => startTopicEdit(topic)}
                  onChangeEdit={setEditingTopicName}
                  onSaveEdit={saveTopicName}
                  onCancelEdit={() => setEditingTopicId(null)}
                  onDelete={() => deleteTopic(topic)}
                />
              ))}
            </div>
          )}
        </div>
      </aside>

      <main className="min-h-0 min-w-0 overflow-y-auto pr-1">
        <div className="space-y-4">
          <ErrorMessage error={error} onClose={() => setError(null)} />
          {!activeTopic ? (
            <EmptyState icon={<FolderPlus size={28} />} title="请选择主题" description="主题里的资源会在这里显示。" />
          ) : (
            <>
              <section className="prism-panel rounded-lg p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <h2 className="break-words text-xl font-semibold text-slate-950">{activeTopic.name}</h2>
                    {activeTopic.description && <p className="mt-2 text-sm leading-6 text-slate-500">{activeTopic.description}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <input ref={fileRef} type="file" className="hidden" accept={ACCEPTED_RESOURCE_EXTENSIONS} onChange={handleUpload} />
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => fileRef.current?.click()}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
                    >
                      {busy ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                      上传资源
                    </button>
                  </div>
                </div>
              </section>

              <section className="prism-panel rounded-lg p-3">
                <div data-testid="knowledge-resource-filter" className="flex flex-wrap gap-2">
                  {FILTERS.map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setFilter(item.value)}
                      className={cn(
                        'min-h-9 rounded-lg px-3 text-sm font-medium transition',
                        filter === item.value ? 'bg-[var(--prism-blue)] text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </section>

              {loadingResources ? (
                <LoadingState text="正在加载资源..." />
              ) : resources.length === 0 ? (
                <EmptyState
                  icon={<Upload size={28} />}
                  title="当前主题还没有资源"
                  description="点击上传资源，文档会进入问答检索，图片、音频、视频会先保存元数据。"
                />
              ) : (
                <div className="grid gap-3 xl:grid-cols-2">
                  {resources.map((resource) => (
                    <ResourceCard
                      key={resource.id}
                      resource={resource}
                      busy={busy}
                      editing={editingResourceId === resource.id}
                      editingTitle={editingResourceTitle}
                      onStartEdit={() => startResourceEdit(resource)}
                      onChangeEdit={setEditingResourceTitle}
                      onSaveEdit={saveResourceTitle}
                      onCancelEdit={() => setEditingResourceId(null)}
                      onDelete={handleDeleteResource}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}

function iconButtonClass(extra = '') {
  return cn(
    'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40',
    extra,
  )
}

function TopicRow({
  topic,
  active,
  busy,
  editing,
  editingName,
  onSelect,
  onStartEdit,
  onChangeEdit,
  onSaveEdit,
  onCancelEdit,
  onDelete,
}: {
  topic: KnowledgeTopic
  active: boolean
  busy: boolean
  editing: boolean
  editingName: string
  onSelect: () => void
  onStartEdit: () => void
  onChangeEdit: (value: string) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onDelete: () => void
}) {
  const handleKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') onSaveEdit()
    if (event.key === 'Escape') onCancelEdit()
  }

  return (
    <div
      className={cn(
        'flex w-full items-start gap-2 rounded-lg border px-3 py-3 transition',
        active ? 'border-blue-200 bg-blue-50 text-[var(--prism-blue)]' : 'border-transparent bg-white text-slate-700 hover:border-[var(--prism-line)]',
      )}
    >
      <button type="button" onClick={onSelect} className="mt-0.5 shrink-0" aria-label={`选择 ${topic.name}`}>
        <Folder size={18} />
      </button>
      <div className="min-w-0 flex-1">
        {editing ? (
          <input
            value={editingName}
            onChange={(event) => onChangeEdit(event.target.value)}
            onKeyDown={handleKey}
            autoFocus
            className="min-h-8 w-full rounded-md border border-blue-200 bg-white px-2 text-sm font-semibold text-slate-950 outline-none focus:ring-2 focus:ring-blue-100"
          />
        ) : (
          <button type="button" onClick={onSelect} className="block w-full break-words text-left text-sm font-semibold">
            {topic.name}
          </button>
        )}
        <span className="mt-1 block text-xs text-slate-500">{topic.resource_count} 个资源</span>
      </div>
      <div className="flex shrink-0 gap-1">
        {editing ? (
          <>
            <button type="button" disabled={busy} onClick={onSaveEdit} className={iconButtonClass('hover:text-emerald-700')} aria-label="保存目录名称" title="保存">
              <Check size={15} />
            </button>
            <button type="button" disabled={busy} onClick={onCancelEdit} className={iconButtonClass()} aria-label="取消改名" title="取消">
              <X size={15} />
            </button>
          </>
        ) : (
          <>
            <button type="button" disabled={busy} onClick={onStartEdit} className={iconButtonClass()} aria-label={`改名 ${topic.name}`} title="改名">
              <Pencil size={15} />
            </button>
            <button type="button" disabled={busy} onClick={onDelete} className={iconButtonClass('hover:bg-red-50 hover:text-red-600')} aria-label={`删除 ${topic.name}`} title="删除目录">
              <Trash2 size={15} />
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function ErrorMessage({ error, onClose }: { error: string | null; onClose: () => void }) {
  if (!error) return null
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:flex-row sm:items-start sm:justify-between">
      <p className="min-w-0 break-words">{error}</p>
      <button type="button" onClick={onClose} className="self-start rounded-md px-2 py-1 text-xs font-medium text-red-700 transition hover:bg-red-100">
        关闭
      </button>
    </div>
  )
}

function LoadingState({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <div className={cn('flex items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 text-sm text-slate-500', compact ? 'min-h-32 px-3' : 'min-h-44')}>
      <Loader2 size={18} className="mr-2 animate-spin text-[var(--prism-blue)]" />
      {text}
    </div>
  )
}

function EmptyState({
  icon,
  title,
  description,
  compact = false,
}: {
  icon: React.ReactNode
  title: string
  description: string
  compact?: boolean
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center rounded-lg border border-dashed border-[var(--prism-line)] bg-white/70 px-6 text-center', compact ? 'min-h-32 py-6' : 'min-h-56 py-12')}>
      <div className="mb-3 text-slate-400">{icon}</div>
      <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
    </div>
  )
}

function ResourceIcon({ mediaType }: { mediaType: ResourceMediaType }) {
  if (mediaType === 'image') return <FileImage size={18} />
  if (mediaType === 'audio') return <FileAudio size={18} />
  if (mediaType === 'video') return <FileVideo size={18} />
  return <FileText size={18} />
}

function formatSize(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function ResourceCard({
  resource,
  busy,
  editing,
  editingTitle,
  onStartEdit,
  onChangeEdit,
  onSaveEdit,
  onCancelEdit,
  onDelete,
}: {
  resource: KnowledgeResource
  busy: boolean
  editing: boolean
  editingTitle: string
  onStartEdit: () => void
  onChangeEdit: (value: string) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onDelete: (id: string) => void
}) {
  const uploadedDate = formatDate(resource.uploaded_at)
  const displayTitle = resource.title || resource.original_filename
  const handleKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') onSaveEdit()
    if (event.key === 'Escape') onCancelEdit()
  }

  return (
    <article className="prism-panel flex min-h-44 flex-col rounded-lg p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-[var(--prism-blue)]">
          <ResourceIcon mediaType={resource.media_type} />
        </div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              value={editingTitle}
              onChange={(event) => onChangeEdit(event.target.value)}
              onKeyDown={handleKey}
              autoFocus
              className="min-h-8 w-full rounded-md border border-blue-200 bg-white px-2 text-sm font-semibold text-slate-950 outline-none focus:ring-2 focus:ring-blue-100"
            />
          ) : (
            <h3 className="break-words text-sm font-semibold leading-5 text-slate-950">{displayTitle}</h3>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600">{MEDIA_LABEL[resource.media_type]}</span>
            <span className={cn('rounded-md px-2 py-1 font-medium', resource.processing_status === 'failed' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700')}>
              {resource.processing_status}
            </span>
            <span>{formatSize(resource.file_size)}</span>
            {uploadedDate && <span>{uploadedDate}</span>}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          {editing ? (
            <>
              <button type="button" disabled={busy} onClick={onSaveEdit} className={iconButtonClass('hover:text-emerald-700')} aria-label="保存资源名称" title="保存">
                <Check size={16} />
              </button>
              <button type="button" disabled={busy} onClick={onCancelEdit} className={iconButtonClass()} aria-label="取消资源改名" title="取消">
                <X size={16} />
              </button>
            </>
          ) : (
            <>
              <button type="button" disabled={busy} onClick={onStartEdit} className={iconButtonClass()} aria-label={`改名 ${displayTitle}`} title="改名">
                <Pencil size={16} />
              </button>
              <button type="button" disabled={busy} onClick={() => onDelete(resource.id)} className={iconButtonClass('hover:bg-red-50 hover:text-red-600')} aria-label={`删除 ${displayTitle}`} title="删除资源">
                <Trash2 size={16} />
              </button>
            </>
          )}
        </div>
      </div>

      {resource.error_message && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm leading-6 text-red-700">{resource.error_message}</p>}

      {resource.tags?.length ? (
        <div className="mt-auto flex flex-wrap gap-2 pt-4">
          {resource.tags.map((tag) => (
            <span key={tag} className="rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
              #{tag}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  )
}
