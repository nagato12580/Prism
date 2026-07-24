import { useCallback, useEffect, useRef, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import {
  FileText,
  Upload,
  Loader2,
  RefreshCw,
  Trash2,
  Download,
  Eye,
  Zap,
} from 'lucide-react'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { filesApi, type KnowledgeFile, type FileListParams } from '@/features/knowledge/api/files'
import { jobsApi, type KnowledgeJobSnapshot, isTerminalJobStatus } from '@/features/knowledge/api/jobs'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Progress } from '@/components/ui/Progress'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'
import { FileUploadPanel } from '@/features/knowledge/components/FileUploadPanel'
import { DocumentDrawer } from '@/features/knowledge/components/DocumentDrawer'
import { cn } from '@/lib/utils'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

const STATUS_FILTERS = [
  { key: '', label: '全部' },
  { key: 'pending', label: '处理中' },
  { key: 'succeeded', label: '完成' },
  { key: 'failed', label: '失败' },
]

export function fileStageStatus(file: KnowledgeFile): { parse: string; index: string } {
  return { parse: file.parse_status, index: file.index_status }
}

export function KnowledgeFilesPage() {
  const { kb } = useOutletContext<Ctx>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<KnowledgeFile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [drawerFile, setDrawerFile] = useState<KnowledgeFile | null>(null)
  const pollTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const kbUid = kb?.kb_uid ?? ''
  const statusFilter = searchParams.get('status') ?? ''

  const load = useCallback(() => {
    if (!kbUid) return
    setLoading(true)
    setError(null)
    const params: FileListParams = { limit: 100 }
    if (statusFilter) {
      // Map UI filter to parse/index status filters the backend accepts.
      if (statusFilter === 'succeeded') params.index_status = 'succeeded'
      else if (statusFilter === 'failed') params.index_status = 'failed'
      else params.index_status = 'running'
    }
    filesApi
      .list(kbUid, params)
      .then((res) => setItems(res.items))
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }, [kbUid, statusFilter])

  useEffect(load, [load])

  // After upload completes, refresh the list once (no aggressive polling).
  const onUploadDone = useCallback(() => {
    setUploadOpen(false)
    load()
  }, [load])

// Watch a job by polling the snapshot (the backend has no SSE). Capped
// exponential backoff, stops at terminal status. Used to refresh the file list
// after a UI-triggered parse/index/delete completes. NOTE: the current
// /files/jobs/{job_id} snapshot returns only {id,job_type,status,stage,attempt,
// error_code} — no progress_current/progress_total — so we do not render a
// progress bar from it (would be fabricated data). The file's own parse/index
// status columns reflect the authoritative state.
const watchJob = useCallback(
    (jobId: string) => {
      if (!kbUid || !jobId) return
      const clear = () => {
        if (pollTimers.current[jobId]) {
          clearTimeout(pollTimers.current[jobId])
          delete pollTimers.current[jobId]
        }
      }
      clear()
      let attempt = 0
      const tick = () => {
        jobsApi
          .snapshot(kbUid, jobId)
          .then((snap) => {
            if (isTerminalJobStatus(snap.status)) {
              clear()
              load()
              return
            }
            attempt += 1
            const delay = Math.min(15000, 1000 * Math.pow(1.6, attempt))
            pollTimers.current[jobId] = setTimeout(tick, delay)
          })
          .catch(() => {
            // On snapshot error, retry with backoff but cap retries.
            attempt += 1
            if (attempt > 8) {
              clear()
              return
            }
            const delay = Math.min(15000, 2000 * Math.pow(1.5, attempt))
            pollTimers.current[jobId] = setTimeout(tick, delay)
          })
      }
      tick()
    },
    [kbUid, load],
  )

  useEffect(() => {
    return () => {
      Object.values(pollTimers.current).forEach((t) => clearTimeout(t))
      pollTimers.current = {}
    }
  }, [])

  const triggerParse = (file: KnowledgeFile) => {
    if (!kbUid) return
    filesApi.parse(kbUid, file.file_uid).then((job) => watchJob(job.id)).catch((e) => setError(e))
  }
  const triggerIndex = (file: KnowledgeFile) => {
    if (!kbUid) return
    filesApi.index(kbUid, file.file_uid).then((job) => watchJob(job.id)).catch((e) => setError(e))
  }

  const [confirmDelete, setConfirmDelete] = useState<KnowledgeFile | null>(null)
  const deleteFile = () => {
    if (!kbUid || !confirmDelete) return
    filesApi
      .remove(kbUid, confirmDelete.file_uid)
      .then((job) => {
        watchJob(job.id)
        setConfirmDelete(null)
      })
      .catch((e) => setError(e))
  }

  const downloadFile = (file: KnowledgeFile) => {
    filesApi
      .download(kbUid, file.file_uid)
      .then(({ blob, filename }) => {
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename ?? file.original_filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      })
      .catch((e) => setError(e))
  }

  return (
    <div data-testid="knowledge-files-page" className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">文件</h2>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-[var(--prism-line)] bg-white p-0.5">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(searchParams)
                  if (f.key) next.set('status', f.key)
                  else next.delete('status')
                  setSearchParams(next)
                }}
                className={cn(
                  'rounded-md px-2.5 py-1 text-xs font-medium transition',
                  statusFilter === f.key
                    ? 'bg-[var(--prism-blue)] text-white'
                    : 'text-slate-500 hover:text-slate-800',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <Button variant="secondary" size="sm" onClick={load}>
            <RefreshCw size={14} /> 刷新
          </Button>
          <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
            <Upload size={14} /> 上传文件
          </Button>
        </div>
      </div>

      {uploadOpen ? (
        <FileUploadPanel
          kbUid={kbUid}
          onDone={onUploadDone}
          onClose={() => setUploadOpen(false)}
          onJobCreated={watchJob}
        />
      ) : null}

      {loading ? (
        <LoadingState label="加载文件…" />
      ) : error ? (
        <ErrorState problem={error} onRetry={load} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="还没有文件"
          description="上传 PDF、DOCX、XLSX、PPTX、MD、TXT 等文件，开始构建索引"
          action={
            <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
              <Upload size={14} /> 上传文件
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--prism-line)] bg-white">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b border-[var(--prism-line)] bg-slate-50/60 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">文件名</th>
                  <th className="px-3 py-2.5 font-medium">类型</th>
                  <th className="px-3 py-2.5 font-medium">大小</th>
                  <th className="px-3 py-2.5 font-medium">解析</th>
                  <th className="px-3 py-2.5 font-medium">索引</th>
                  <th className="px-3 py-2.5 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((file) => (
                  <FileRow
                    key={file.file_uid}
                    file={file}
                    onPreview={() => setDrawerFile(file)}
                    onDownload={() => downloadFile(file)}
                    onParse={() => triggerParse(file)}
                    onIndex={() => triggerIndex(file)}
                    onDelete={() => setConfirmDelete(file)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {drawerFile ? (
        <DocumentDrawer
          kbUid={kbUid}
          file={drawerFile}
          onClose={() => setDrawerFile(null)}
        />
      ) : null}

      {confirmDelete ? (
        <DeleteConfirm
          file={confirmDelete}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={deleteFile}
        />
      ) : null}
    </div>
  )
}

// Map a file to a tracked job id is not possible from the file row alone (the
// backend file row carries no job id). Standalone job snapshots are only
// tracked for UI-triggered operations to trigger a list refresh; they are not
// linked to a specific row for display.

function FileRow({
  file,
  onPreview,
  onDownload,
  onParse,
  onIndex,
  onDelete,
}: {
  file: KnowledgeFile
  onPreview: () => void
  onDownload: () => void
  onParse: () => void
  onIndex: () => void
  onDelete: () => void
}) {
  const sizeKb = Math.max(1, Math.round(file.size_bytes / 1024))
  return (
    <tr className="border-b border-[var(--prism-line)] last:border-0 hover:bg-slate-50/40">
      <td className="px-4 py-2.5">
        <button
          type="button"
          onClick={onPreview}
          className="flex items-center gap-2 text-left text-slate-800 hover:text-[var(--prism-blue)]"
        >
          <FileText size={15} className="shrink-0 text-slate-400" />
          <span className="max-w-[280px] truncate font-medium">{file.original_filename}</span>
        </button>
        {file.relative_path ? (
          <div className="mt-0.5 truncate pl-7 text-[11px] text-slate-400">{file.relative_path}</div>
        ) : null}
      </td>
      <td className="px-3 py-2.5">
        <Badge tone="neutral">{file.media_type}</Badge>
      </td>
      <td className="px-3 py-2.5 text-xs text-slate-500">{sizeKb} KB</td>
      <td className="px-3 py-2.5"><StageBadge status={file.parse_status} /></td>
      <td className="px-3 py-2.5">
        <StageBadge status={file.index_status} />
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1">
          <IconBtn label="预览" onClick={onPreview}><Eye size={14} /></IconBtn>
          <IconBtn label="下载" onClick={onDownload}><Download size={14} /></IconBtn>
          {file.index_status !== 'succeeded' ? (
            <IconBtn label="索引" onClick={onIndex}><Zap size={14} /></IconBtn>
          ) : null}
          {file.parse_status !== 'succeeded' ? (
            <IconBtn label="解析" onClick={onParse}><Loader2 size={14} /></IconBtn>
          ) : null}
          <IconBtn label="删除" danger onClick={onDelete}><Trash2 size={14} /></IconBtn>
        </div>
      </td>
    </tr>
  )
}

function StageBadge({ status }: { status: string }) {
  const tone =
    status === 'succeeded' ? 'green' : status === 'failed' ? 'red' : status === 'pending' ? 'neutral' : 'amber'
  const label =
    status === 'succeeded' ? '完成' : status === 'failed' ? '失败' : status === 'pending' ? '待处理' : status || '—'
  return <Badge tone={tone}>{label}</Badge>
}

function IconBtn({
  label,
  onClick,
  danger,
  children,
}: {
  label: string
  onClick: () => void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        'rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
        danger ? 'hover:bg-red-50 hover:text-red-500' : 'hover:text-slate-700',
      )}
    >
      {children}
    </button>
  )
}

function DeleteConfirm({
  file,
  onCancel,
  onConfirm,
}: {
  file: KnowledgeFile
  onCancel: () => void
  onConfirm: () => void
}) {
  const [busy, setBusy] = useState(false)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--prism-line)] bg-white p-5 shadow-2xl">
        <h3 className="text-sm font-semibold text-slate-900">删除文件</h3>
        <p className="mt-2 text-sm text-slate-600">
          确认删除「{file.original_filename}」？该操作会移除其分块、索引和图谱引用，不可恢复。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>取消</Button>
          <Button
            variant="danger"
            loading={busy}
            onClick={() => {
              setBusy(true)
              onConfirm()
            }}
          >
            <Trash2 size={14} /> 确认删除
          </Button>
        </div>
      </div>
    </div>
  )
}
