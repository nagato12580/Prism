import { useEffect, useMemo, useState } from 'react'
import { Download, FileText, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { filesApi, type KnowledgeFile } from '@/features/knowledge/api/files'
import { knowledgeBaseGraphApi } from '@/features/knowledge/api/graph'
import { KnowledgeGraphPage as UnifiedGraphBrowser } from '@/pages/KnowledgeGraphPage'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Dialog } from '@/components/ui/Dialog'
import { Tabs } from '@/components/ui/Tabs'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { LoadingState, ErrorState } from '@/components/ui/StateView'
import {
  clampPreviewContent,
  type PreviewContent,
} from '@/features/knowledge/components/previewContent'

export function DocumentDrawer({
  kbUid,
  file,
  onClose,
}: {
  kbUid: string
  file: KnowledgeFile
  onClose: () => void
}) {
  const [view, setView] = useState<'original' | 'markdown' | 'chunks' | 'history' | 'graph'>('markdown')
  const [preview, setPreview] = useState<PreviewContent | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setPreview(null)
    // The backend exposes a single `preview` endpoint returning the stored text
    // content (parsed text). There is no separate markdown/original/chunks
    // variant in the current API; "original" triggers a binary download.
    filesApi
      .preview(kbUid, file.file_uid)
      .then((res) => setPreview(clampPreviewContent(res.content)))
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }, [kbUid, file.file_uid])

  const download = () => {
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

  // Graph scoped to this single document: the backend subgraph query filters
  // ScopedSource rows by file_uid and returns only the entities mentioned in
  // this document plus the edges among them. This is the "meta 过滤" the drawer
  // graph relies on — the current document's file_uid as the graph filter key.
  const graphLoader = useMemo(
    () => (params: { view: 'entity' | 'source'; q?: string; limit?: number }) =>
      knowledgeBaseGraphApi.get(kbUid, {
        view: params.view,
        limit: params.limit,
        file_uids: [file.file_uid],
      }),
    [kbUid, file.file_uid],
  )

  return (
    <Dialog
      open
      onClose={onClose}
      width="xl"
      title={
        <div className="flex items-center gap-2">
          <FileText size={16} className="text-slate-400" />
          <span className="truncate">{file.original_filename}</span>
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{file.media_type}</Badge>
        <Badge tone={file.parse_status === 'succeeded' ? 'green' : 'amber'}>解析：{file.parse_status}</Badge>
        <Badge tone={file.index_status === 'succeeded' ? 'green' : 'amber'}>索引：{file.index_status}</Badge>
        <div className="ml-auto">
          <Button size="sm" variant="secondary" onClick={download}>
            <Download size={14} /> 下载原文件
          </Button>
        </div>
      </div>

      <Tabs
        items={[
          { key: 'markdown', label: '正文' },
          { key: 'original', label: '原文件' },
          { key: 'chunks', label: '分块' },
          { key: 'graph', label: '图谱' },
          { key: 'history', label: '处理历史' },
        ]}
        active={view}
        onChange={(k) => setView(k as typeof view)}
      />

      {view === 'graph' ? (
        <div className="mt-3 h-[55vh] min-h-0 overflow-hidden rounded-lg border border-[var(--prism-line)]">
          <UnifiedGraphBrowser
            key={file.file_uid}
            loader={graphLoader}
            className="h-[55vh]"
          />
        </div>
      ) : (
      <div className="mt-3 max-h-[60vh] overflow-y-auto rounded-lg border border-[var(--prism-line)] bg-slate-50/40 p-4">
        {view === 'original' ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-sm text-slate-500">
            <FileText size={28} className="text-slate-300" />
            <p>原文件需下载查看，点击右上角「下载原文件」</p>
            <Button size="sm" variant="secondary" onClick={download}>
              <Download size={14} /> 下载
            </Button>
          </div>
        ) : view === 'chunks' ? (
          <div className="text-xs text-slate-500">
            当前后端预览接口返回完整正文，暂未提供独立分块视图。可在下方正文内容中查看。
            {preview?.content ? <pre className="mt-2 whitespace-pre-wrap break-words text-slate-700">{preview.content}</pre> : null}
          </div>
        ) : view === 'history' ? (
          <div className="text-xs text-slate-500">
            <p>解析状态：{file.parse_status}</p>
            <p>索引状态：{file.index_status}</p>
            <p>图谱状态：{file.graph_status}</p>
            <p>大小：{Math.max(1, Math.round(file.size_bytes / 1024))} KB</p>
            <p className="mt-2 text-slate-400">当前后端文件行未携带逐 Job 历史，详细任务历史请通过后端管理界面查看。</p>
          </div>
        ) : loading ? (
          <LoadingState label="加载正文…" />
        ) : error ? (
          <ErrorState problem={error} />
        ) : (
          <div>
            {preview?.truncated ? (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                正文共 {preview.totalCharacters.toLocaleString()} 个字符，为避免页面卡顿仅显示前{' '}
                {preview.content.length.toLocaleString()} 个字符。完整内容请下载原文件查看。
              </div>
            ) : null}
            <div className="markdown-body text-sm leading-relaxed">
              {preview?.content ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown>
              ) : (
                <span className="text-slate-400">（空内容）</span>
              )}
            </div>
          </div>
        )}
      </div>
      )}
    </Dialog>
  )
}

export { Loader2, ApiProblem }
