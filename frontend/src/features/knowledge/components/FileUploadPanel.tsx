import { useRef, useState } from 'react'
import { Upload, X, FileText, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { filesApi } from '@/features/knowledge/api/files'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'

const MAX_CONCURRENT = 4

type UploadState = 'queued' | 'uploading' | 'registered' | 'failed' | 'canceled'

interface PendingUpload {
  localId: string
  file: File
  relativePath: string
  state: UploadState
  fileUid?: string
  jobId?: string
  error?: ApiProblem
}

export function FileUploadPanel({
  kbUid,
  onDone,
  onClose,
  onJobCreated,
}: {
  kbUid: string
  onDone: () => void
  onClose: () => void
  onJobCreated?: (jobId: string) => void
}) {
  const [pending, setPending] = useState<PendingUpload[]>([])
  const [autoIndex, setAutoIndex] = useState(true)
  const inputRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const controllers = useRef<Record<string, AbortController>>({})
  const running = useRef(0)

  const addFiles = (fileList: FileList | null, relativePathOf?: (f: File) => string) => {
    if (!fileList) return
    const next: PendingUpload[] = Array.from(fileList).map((file) => ({
      localId: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      relativePath: relativePathOf?.(file) ?? file.webkitRelativePath ?? '',
      state: 'queued' as UploadState,
    }))
    setPending((prev) => [...prev, ...next])
    void drain()
  }

  const drain = () => {
    setPending((prev) => {
      const queue = [...prev]
      const toStart = queue.filter((p) => p.state === 'queued')
      for (const item of toStart) {
        if (running.current >= MAX_CONCURRENT) break
        running.current += 1
        item.state = 'uploading'
        void runUpload(item)
      }
      return [...queue]
    })
  }

  const runUpload = async (item: PendingUpload) => {
    const controller = new AbortController()
    controllers.current[item.localId] = controller
    try {
      const res = await filesApi.upload(kbUid, item.file, {
        relative_path: item.relativePath || undefined,
        auto_index: autoIndex,
      })
      setPending((prev) =>
        prev.map((p) =>
          p.localId === item.localId
            ? { ...p, state: 'registered', fileUid: res.file.file_uid, jobId: res.job.id }
            : p,
        ),
      )
      if (res.job?.id) onJobCreated?.(res.job.id)
    } catch (e) {
      const err = e as ApiProblem
      setPending((prev) =>
        prev.map((p) => (p.localId === item.localId ? { ...p, state: 'failed', error: err } : p)),
      )
    } finally {
      running.current = Math.max(0, running.current - 1)
      delete controllers.current[item.localId]
      drain()
    }
  }

  const cancel = (localId: string) => {
    controllers.current[localId]?.abort()
    setPending((prev) =>
      prev.map((p) => (p.localId === localId ? { ...p, state: 'canceled' as UploadState } : p)),
    )
  }

  const remaining = pending.filter((p) => p.state === 'queued' || p.state === 'uploading').length
  const allDone = pending.length > 0 && remaining === 0

  return (
    <div className="rounded-xl border border-[var(--prism-line)] bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Upload size={16} className="text-[var(--prism-blue)]" />
          <span className="text-sm font-semibold text-slate-900">上传文件</span>
          {pending.length ? (
            <Badge tone={allDone ? 'green' : 'blue'}>
              {allDone ? '全部完成' : `进行中 ${remaining}/${pending.length}`}
            </Badge>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={autoIndex}
              onChange={(e) => setAutoIndex(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            上传后自动索引
          </label>
          {allDone ? (
            <Button size="sm" variant="primary" onClick={onDone}>
              完成
            </Button>
          ) : null}
          <button
            type="button"
            aria-label="收起上传"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={15} />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => inputRef.current?.click()}
        >
          <Upload size={14} /> 选择文件
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => folderRef.current?.click()}
        >
          <Upload size={14} /> 选择文件夹
        </Button>
        <span className="self-center text-[11px] text-slate-400">支持 PDF / DOCX / XLSX / PPTX / MD / TXT</span>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        aria-label="选择文件"
        className="hidden"
        onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={folderRef}
        type="file"
        multiple
        aria-label="选择文件夹"
        // @ts-expect-error webkitdirectory is a non-standard but widely supported attribute
        webkitdirectory=""
        directory=""
        className="hidden"
        onChange={(e) => {
          addFiles(e.target.files, (f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? '')
          e.target.value = ''
        }}
      />

      {pending.length ? (
        <ul className="mt-3 max-h-64 space-y-1.5 overflow-y-auto">
          {pending.map((p) => (
            <li
              key={p.localId}
              className="flex items-center gap-2 rounded-lg border border-[var(--prism-line)] bg-slate-50/40 px-3 py-2"
            >
              <FileText size={15} className="shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-slate-700">{p.file.name}</div>
                {p.relativePath ? (
                  <div className="truncate text-[11px] text-slate-400">{p.relativePath}</div>
                ) : null}
                {p.error ? (
                  <div className="text-[11px] text-red-500">
                    {p.error.message}
                    {p.error.code ? <span className="ml-1 font-mono">({p.error.code})</span> : null}
                  </div>
                ) : null}
              </div>
              <UploadStateBadge state={p.state} />
              {p.state === 'uploading' ? (
                <button
                  type="button"
                  aria-label="取消上传"
                  onClick={() => cancel(p.localId)}
                  className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                >
                  <X size={13} />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function UploadStateBadge({ state }: { state: UploadState }) {
  if (state === 'registered')
    return (
      <Badge tone="green">
        <CheckCircle2 size={11} /> 已上传
      </Badge>
    )
  if (state === 'failed')
    return (
      <Badge tone="red">
        <AlertCircle size={11} /> 失败
      </Badge>
    )
  if (state === 'canceled') return <Badge tone="neutral">已取消</Badge>
  return (
    <Badge tone="blue">
      <Loader2 size={11} className="animate-spin" /> {state === 'uploading' ? '上传中' : '排队中'}
    </Badge>
  )
}
