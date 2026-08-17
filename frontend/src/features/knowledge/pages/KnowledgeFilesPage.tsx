import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  Network,
  Archive,
} from 'lucide-react'
import { knowledgeBasesApi, type KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { filesApi, type KnowledgeFile, type FileListParams } from '@/features/knowledge/api/files'
import { jobsApi, isTerminalJobStatus } from '@/features/knowledge/api/jobs'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'
import { FileUploadPanel } from '@/features/knowledge/components/FileUploadPanel'
import { DocumentDrawer } from '@/features/knowledge/components/DocumentDrawer'
import { updateFileStage } from '@/features/knowledge/pages/fileStageUpdates'
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
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [drawerFile, setDrawerFile] = useState<KnowledgeFile | null>(null)
  const [selectedFileUids, setSelectedFileUids] = useState<string[]>([])
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const [archiveFiles, setArchiveFiles] = useState<KnowledgeFile[] | null>(null)
  const pollTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const kbUid = kb?.kb_uid ?? ''
  const statusFilter = searchParams.get('status') ?? ''
  const isPersonalInboxKb = kb?.system_type === 'personal_inbox'

  const listFiles = useCallback(
    (cursor?: string, limit = 100) => {
      const params: FileListParams = { limit }
      if (cursor) params.cursor = cursor
      if (statusFilter) {
        // Map UI filter to parse/index status filters the backend accepts.
        if (statusFilter === 'succeeded') params.index_status = 'succeeded'
        else if (statusFilter === 'failed') params.index_status = 'failed'
        else params.index_status = 'running'
      }
      return filesApi.list(kbUid, params)
    },
    [kbUid, statusFilter],
  )

  const load = useCallback(() => {
    if (!kbUid) return
    setLoading(true)
    setError(null)
    listFiles()
      .then((res) => {
        setItems(res.items)
        setNextCursor(res.next_cursor)
      })
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }, [kbUid, listFiles])

  useEffect(load, [load])

  useEffect(() => {
    const visibleFileUids = new Set(items.map((item) => item.file_uid))
    setSelectedFileUids((current) => current.filter((fileUid) => visibleFileUids.has(fileUid)))
  }, [items])

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
              if (snap.status === 'failed') {
                setError(new Error(snap.error_message || snap.error_code || 'Knowledge job failed'))
              }
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
    setItems((current) => updateFileStage(current, file.file_uid, 'parse_status', 'running'))
    filesApi
      .parse(kbUid, file.file_uid)
      .then((job) => watchJob(job.id))
      .catch((e) => {
        setItems((current) => updateFileStage(current, file.file_uid, 'parse_status', 'failed'))
        setError(e)
      })
  }

  const triggerIndex = (file: KnowledgeFile) => {
    if (!kbUid) return
    setItems((current) => updateFileStage(current, file.file_uid, 'index_status', 'running'))
    filesApi
      .index(kbUid, file.file_uid)
      .then((job) => watchJob(job.id))
      .catch((e) => {
        setItems((current) => updateFileStage(current, file.file_uid, 'index_status', 'failed'))
        setError(e)
      })
  }

  const triggerGraph = (file: KnowledgeFile) => {
    if (!kbUid) return
    setItems((current) => updateFileStage(current, file.file_uid, 'graph_status', 'running'))
    filesApi
      .graph(kbUid, file.file_uid)
      .then((job) => watchJob(job.id))
      .catch((e) => {
        setItems((current) => updateFileStage(current, file.file_uid, 'graph_status', 'failed'))
        setError(e)
      })
  }

  const selectedFiles = useMemo(() => {
    const selected = new Set(selectedFileUids)
    return items.filter((file) => selected.has(file.file_uid))
  }, [items, selectedFileUids])

  const selectedIndexableFiles = selectedFiles.filter(canIndexFile)
  const selectedGraphableFiles = selectedFiles.filter(canGraphFile)
  const allVisibleSelected = items.length > 0 && !nextCursor && selectedFileUids.length === items.length

  const loadAllFiles = async () => {
    if (!nextCursor) return items
    const allFiles = [...items]
    let cursor: string | null = nextCursor
    while (cursor) {
      const res = await listFiles(cursor, 500)
      allFiles.push(...res.items)
      cursor = res.next_cursor
    }
    setItems(allFiles)
    setNextCursor(null)
    return allFiles
  }

  const toggleSelectAll = async () => {
    if (allVisibleSelected) {
      setSelectedFileUids([])
      return
    }
    setError(null)
    try {
      const allFiles = await loadAllFiles()
      setSelectedFileUids(allFiles.map((file) => file.file_uid))
    } catch (e) {
      setError(e)
    }
  }

  const toggleSelectFile = (fileUid: string) => {
    setSelectedFileUids((current) =>
      current.includes(fileUid)
        ? current.filter((selectedFileUid) => selectedFileUid !== fileUid)
        : [...current, fileUid],
    )
  }

  const triggerBulkIndex = () => {
    if (!kbUid || selectedIndexableFiles.length === 0) return
    const targets = selectedIndexableFiles
    const triggerFile = targets[0]
    setItems((current) =>
      targets.reduce(
        (next, file) => updateFileStage(next, file.file_uid, 'index_status', 'running'),
        current,
      ),
    )
    // The backend index job rebuilds the whole KB generation. One trigger file
    // is enough; submitting per file creates duplicate full-KB rebuild jobs.
    filesApi
      .index(kbUid, triggerFile.file_uid)
      .then((job) => watchJob(job.id))
      .catch((e) => {
        setItems((current) =>
          targets.reduce(
            (next, file) => updateFileStage(next, file.file_uid, 'index_status', 'failed'),
            current,
          ),
        )
        setError(e)
      })
  }

  const triggerBulkGraph = () => {
    if (!kbUid || selectedGraphableFiles.length === 0) return
    const targets = selectedGraphableFiles
    setItems((current) =>
      targets.reduce(
        (next, file) => updateFileStage(next, file.file_uid, 'graph_status', 'running'),
        current,
      ),
    )
    Promise.allSettled(
      targets.map((file) =>
        filesApi.graph(kbUid, file.file_uid).then((job) => {
          watchJob(job.id)
          return job
        }),
      ),
    ).then((results) => {
      const failed = results.filter((result) => result.status === 'rejected')
      if (failed.length > 0) {
        setItems((current) =>
          targets.reduce(
            (next, file) => updateFileStage(next, file.file_uid, 'graph_status', 'failed'),
            current,
          ),
        )
        setError(new Error(`${failed.length} 个文件图抽取任务提交失败`))
      }
    })
  }

  const openBulkArchive = () => {
    if (!isPersonalInboxKb || selectedFiles.length === 0) return
    setArchiveFiles(selectedFiles)
  }

  const onArchiveDone = () => {
    setArchiveFiles(null)
    setSelectedFileUids([])
    load()
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

  const deleteSelectedFiles = () => {
    if (!kbUid || selectedFiles.length === 0) return
    const targets = selectedFiles
    Promise.allSettled(
      targets.map((file) =>
        filesApi.remove(kbUid, file.file_uid).then((job) => {
          watchJob(job.id)
          return job
        }),
      ),
    ).then((results) => {
      setConfirmBulkDelete(false)
      setSelectedFileUids([])
      const failed = results.filter((result) => result.status === 'rejected')
      if (failed.length > 0) {
        setError(new Error(`${failed.length} 个文件删除任务提交失败`))
      }
      load()
    })
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
          <Button
            variant="primary"
            size="sm"
            onClick={() => setUploadOpen(true)}
            disabled={!kb?.can_contribute}
            title={!kb?.can_contribute ? '需要贡献者以上权限' : '上传文件'}
          >
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

      {selectedFiles.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
          <span className="text-xs font-medium text-slate-500">
            已选择 {selectedFiles.length} 个文档
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={triggerBulkIndex}
              disabled={!kb?.can_contribute || selectedIndexableFiles.length === 0}
              title={!kb?.can_contribute ? '需要贡献者以上权限' : '对已解析文档批量向量化'}
            >
              <Zap size={14} /> 批量向量化
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={triggerBulkGraph}
              disabled={!kb?.can_edit || selectedGraphableFiles.length === 0}
              title={!kb?.can_edit ? '需要编辑权限' : '对已解析文档批量图抽取'}
            >
              <Network size={14} /> 批量图抽取
            </Button>
            {isPersonalInboxKb ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={openBulkArchive}
                disabled={!kb?.can_edit}
                title={!kb?.can_edit ? '需要编辑权限' : '整理到知识库'}
              >
                <Archive size={14} /> 整理到知识库
              </Button>
            ) : null}
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmBulkDelete(true)}
              disabled={!kb?.can_edit}
              title={!kb?.can_edit ? '需要编辑权限' : '删除已选择文档'}
            >
              <Trash2 size={14} /> 批量删除
            </Button>
          </div>
        </div>
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
            <Button
              variant="primary"
              size="sm"
              onClick={() => setUploadOpen(true)}
              disabled={!kb?.can_contribute}
              title={!kb?.can_contribute ? '需要贡献者以上权限' : '上传文件'}
            >
              <Upload size={14} /> 上传文件
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--prism-line)] bg-white">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b border-[var(--prism-line)] bg-slate-50/60 text-xs text-slate-500">
                <tr>
                  <th className="w-10 px-4 py-2.5 font-medium">
                    <input
                      type="checkbox"
                      aria-label="选择所有文档"
                      checked={allVisibleSelected}
                      onChange={() => void toggleSelectAll()}
                      className="h-4 w-4 rounded border-slate-300 text-[var(--prism-blue)] focus:ring-[var(--prism-blue)]"
                    />
                  </th>
                  <th className="px-4 py-2.5 font-medium">文件名</th>
                  <th className="px-3 py-2.5 font-medium">类型</th>
                  <th className="px-3 py-2.5 font-medium">大小</th>
                  <th className="px-3 py-2.5 font-medium">解析</th>
                  <th className="px-3 py-2.5 font-medium">索引</th>
                  <th className="px-3 py-2.5 font-medium">图谱</th>
                  <th className="px-3 py-2.5 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((file) => (
                  <FileRow
                    key={file.file_uid}
                    file={file}
                    selected={selectedFileUids.includes(file.file_uid)}
                    canContribute={!!kb?.can_contribute}
                    canEdit={!!kb?.can_edit}
                    canArchive={isPersonalInboxKb && !!kb?.can_edit}
                    onSelect={() => toggleSelectFile(file.file_uid)}
                    onPreview={() => setDrawerFile(file)}
                    onDownload={() => downloadFile(file)}
                    onParse={() => triggerParse(file)}
                    onIndex={() => triggerIndex(file)}
                    onGraph={() => triggerGraph(file)}
                    onArchive={() => setArchiveFiles([file])}
                    onDelete={() => setConfirmDelete(file)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {drawerFile ? (
        <DocumentDrawer kbUid={kbUid} file={drawerFile} onClose={() => setDrawerFile(null)} />
      ) : null}

      {confirmDelete ? (
        <DeleteConfirm
          file={confirmDelete}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={deleteFile}
        />
      ) : null}

      {confirmBulkDelete ? (
        <BulkDeleteConfirm
          files={selectedFiles}
          onCancel={() => setConfirmBulkDelete(false)}
          onConfirm={deleteSelectedFiles}
        />
      ) : null}

      {archiveFiles ? (
        <ArchiveFilesDialog
          sourceKbUid={kbUid}
          files={archiveFiles}
          onClose={() => setArchiveFiles(null)}
          onDone={onArchiveDone}
          onError={setError}
        />
      ) : null}
    </div>
  )
}

function isPersonalInboxDerivedFile(file: KnowledgeFile) {
  return file.system_type === 'personal_inbox' && file.source_kind === 'personal_asset_unit'
}

// Map a file to a tracked job id is not possible from the file row alone (the
// backend file row carries no job id). Standalone job snapshots are only
// tracked for UI-triggered operations to trigger a list refresh; they are not
// linked to a specific row for display.

function FileRow({
  file,
  selected,
  canContribute,
  canEdit,
  canArchive,
  onSelect,
  onPreview,
  onDownload,
  onParse,
  onIndex,
  onGraph,
  onArchive,
  onDelete,
}: {
  file: KnowledgeFile
  selected: boolean
  canContribute: boolean
  canEdit: boolean
  canArchive: boolean
  onSelect: () => void
  onPreview: () => void
  onDownload: () => void
  onParse: () => void
  onIndex: () => void
  onGraph: () => void
  onArchive: () => void
  onDelete: () => void
}) {
  const sizeKb = Math.max(1, Math.round(file.size_bytes / 1024))
  const canParse = !isRunningStage(file.parse_status)
  const canIndex = canIndexFile(file)
  const canGraph = canGraphFile(file)
  return (
    <tr className="border-b border-[var(--prism-line)] last:border-0 hover:bg-slate-50/40">
      <td className="px-4 py-2.5">
        <input
          type="checkbox"
          aria-label={`选择文档 ${file.original_filename}`}
          checked={selected}
          onChange={onSelect}
          className="h-4 w-4 rounded border-slate-300 text-[var(--prism-blue)] focus:ring-[var(--prism-blue)]"
        />
      </td>
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
      <td className="px-3 py-2.5">
        <StageBadge status={file.parse_status} />
        {file.parse_error?.message ? <StageErrorText message={file.parse_error.message} /> : null}
      </td>
      <td className="px-3 py-2.5">
        <StageBadge status={file.index_status} />
        {file.index_error?.message ? <StageErrorText message={file.index_error.message} /> : null}
      </td>
      <td className="px-3 py-2.5">
        <StageBadge status={file.graph_status} />
        {file.graph_error?.message ? <StageErrorText message={file.graph_error.message} /> : null}
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1">
          <IconBtn label="预览" onClick={onPreview}>
            <Eye size={14} />
          </IconBtn>
          <IconBtn label="下载" onClick={onDownload}>
            <Download size={14} />
          </IconBtn>
          <IconBtn label="解析" onClick={onParse} disabled={!canContribute || !canParse}>
            <Loader2 size={14} />
          </IconBtn>
          <IconBtn label="索引" onClick={onIndex} disabled={!canContribute || !canIndex}>
            <Zap size={14} />
          </IconBtn>
          <IconBtn label="图谱" onClick={onGraph} disabled={!canEdit || !canGraph}>
            <Network size={14} />
          </IconBtn>
          {canArchive ? (
            <IconBtn label="整理" onClick={onArchive}>
              <Archive size={14} />
            </IconBtn>
          ) : null}
          <IconBtn label="删除" danger onClick={onDelete} disabled={!canEdit}>
            <Trash2 size={14} />
          </IconBtn>
        </div>
      </td>
    </tr>
  )
}

function StageBadge({ status }: { status: string }) {
  const tone =
    status === 'succeeded'
      ? 'green'
      : status === 'failed'
        ? 'red'
        : status === 'pending'
          ? 'neutral'
          : 'amber'
  const label =
    status === 'succeeded'
      ? '完成'
      : status === 'failed'
        ? '失败'
        : status === 'pending'
          ? '待处理'
          : status || '—'
  return <Badge tone={tone}>{label}</Badge>
}

function isRunningStage(status: string) {
  return status === 'running' || status === 'queued' || status === 'claimed'
}

function canIndexFile(file: KnowledgeFile) {
  return file.parse_status === 'succeeded' && !isRunningStage(file.index_status)
}

function canGraphFile(file: KnowledgeFile) {
  return file.parse_status === 'succeeded' && !isRunningStage(file.graph_status)
}

function StageErrorText({ message }: { message: string }) {
  return (
    <div
      className="mt-1 max-w-[240px] truncate text-[11px] leading-4 text-red-600"
      title={message}
    >
      {message}
    </div>
  )
}

function IconBtn({
  label,
  onClick,
  danger,
  disabled,
  children,
}: {
  label: string
  onClick: () => void
  danger?: boolean
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
        danger ? 'hover:bg-red-50 hover:text-red-500' : 'hover:text-slate-700',
        disabled ? 'cursor-not-allowed opacity-40 hover:bg-transparent hover:text-slate-400' : '',
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
  const cascadesToPersonalAssetUnit = isPersonalInboxDerivedFile(file)
  // Render through a portal: the MainLayout content wrapper has `backdrop-blur`,
  // whose backdrop-filter makes `position: fixed` relative to that wrapper instead
  // of the viewport. Without the portal, the overlay centers against the whole
  // (tall, scrollable) file list and the dialog can be pushed below the fold.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--prism-line)] bg-white p-5 shadow-2xl">
        <h3 className="text-sm font-semibold text-slate-900">删除文件</h3>
        <p className="mt-2 text-sm text-slate-600">
          确认删除「{file.original_filename}」？该操作会移除其分块、索引和图谱引用，不可恢复。
        </p>
        {cascadesToPersonalAssetUnit ? (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            这是未归档知识派生文件。删除该文件也会删除对应的个人知识单元，并清理不再被引用的来源碎片。
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
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
    </div>,
    document.body,
  )
}

function BulkDeleteConfirm({
  files,
  onCancel,
  onConfirm,
}: {
  files: KnowledgeFile[]
  onCancel: () => void
  onConfirm: () => void
}) {
  const [busy, setBusy] = useState(false)
  const derivedCount = files.filter(isPersonalInboxDerivedFile).length
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--prism-line)] bg-white p-5 shadow-2xl">
        <h3 className="text-sm font-semibold text-slate-900">批量删除文件</h3>
        <p className="mt-2 text-sm text-slate-600">
          确认删除已选择的 {files.length} 个文档？该操作会移除对应分块、索引和图谱引用，不可恢复。
        </p>
        {derivedCount > 0 ? (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            其中 {derivedCount} 个是未归档知识派生文件。删除这些文件也会删除对应的个人知识单元，并清理不再被引用的来源碎片。
          </div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            取消
          </Button>
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
    </div>,
    document.body,
  )
}

function ArchiveFilesDialog({
  sourceKbUid,
  files,
  onClose,
  onDone,
  onError,
}: {
  sourceKbUid: string
  files: KnowledgeFile[]
  onClose: () => void
  onDone: () => void
  onError: (error: unknown) => void
}) {
  const [targets, setTargets] = useState<KnowledgeBase[]>([])
  const [targetKbUid, setTargetKbUid] = useState('')
  const [loadingTargets, setLoadingTargets] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    setLoadingTargets(true)
    knowledgeBasesApi.list({ limit: 200 })
      .then((res) => {
        if (!active) return
        const options = res.items.filter(
          (item) => item.kb_uid !== sourceKbUid && !item.is_system && item.system_type !== 'personal_inbox' && item.can_contribute,
        )
        setTargets(options)
        setTargetKbUid(options[0]?.kb_uid ?? '')
      })
      .catch(onError)
      .finally(() => {
        if (active) setLoadingTargets(false)
      })
    return () => {
      active = false
    }
  }, [sourceKbUid, onError])

  const submit = () => {
    if (!targetKbUid || files.length === 0) return
    setBusy(true)
    filesApi.archive(sourceKbUid, files.map((file) => file.file_uid), targetKbUid)
      .then(onDone)
      .catch(onError)
      .finally(() => setBusy(false))
  }

  return (
    <Dialog open onClose={onClose} title="整理到知识库" width="sm">
      <div className="flex flex-col gap-3">
        <div className="text-sm text-slate-600">
          将已选择的 {files.length} 个文档移动到目标知识库。
        </div>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          目标知识库
          <select
            value={targetKbUid}
            onChange={(event) => setTargetKbUid(event.target.value)}
            disabled={loadingTargets || busy || targets.length === 0}
            className="h-9 rounded-lg border border-[var(--prism-line)] bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-400"
          >
            {targets.map((target) => (
              <option key={target.kb_uid} value={target.kb_uid}>
                {target.name}
              </option>
            ))}
          </select>
        </label>
        {loadingTargets ? (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 size={13} className="animate-spin" /> 加载知识库…
          </div>
        ) : targets.length === 0 ? (
          <div className="text-xs text-amber-700">暂无可整理到的知识库。</div>
        ) : null}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} loading={busy} disabled={!targetKbUid || targets.length === 0}>
            <Archive size={14} /> 确认整理
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
