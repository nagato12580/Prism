import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, ExternalLink, Loader2, AlertCircle } from 'lucide-react'
import type { Source } from '@/app/chatStore'
import { filesApi } from '@/features/knowledge/api/files'
import { ApiProblem } from '@/features/knowledge/api/client'
import { Dialog } from '@/components/ui/Dialog'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { LoadingState, ErrorState } from '@/components/ui/StateView'

// Chat citation -> document loop.
//
// The chat stream carries legacy source objects (the backend emits legacy NDJSON
// today; no CitationRegistry / K1.. registry exists server-side). We render the
// real sources as a validated citation list: clicking a source opens this
// drawer showing the evidence snippet, and offers to open the source document
// in the knowledge workspace via the public route (kb_uid/file_uid). We never
// fabricate a citation that the backend did not emit, and we never expose a
// private storage path or Engine URL.
export function EvidenceDrawer({
  source,
  onClose,
}: {
  source: Source | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    setContent(null)
    setError(null)
    if (!source) return
    // Resolve the public file preview only if we have a kb_uid + file_uid pair.
    const kbUid = (source as Source & { kb_uid?: string }).kb_uid
    const fileUid = (source as Source & { file_uid?: string }).file_uid
    if (!kbUid || !fileUid) return
    setLoading(true)
    filesApi
      .preview(kbUid, fileUid)
      .then((res) => setContent(res.content))
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }, [source])

  if (!source) return null

  const kbUid = (source as Source & { kb_uid?: string }).kb_uid
  const fileUid = (source as Source & { file_uid?: string }).file_uid
  const title =
    source.display_title || source.doc_name || source.title || source.item_id || source.display_id || '来源'

  return (
    <Dialog
      open
      onClose={onClose}
      width="lg"
      title={
        <div className="flex items-center gap-2">
          <FileText size={16} className="text-slate-400" />
          <span className="truncate">{title}</span>
        </div>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
        <Badge tone="neutral">{source.source_kind ?? '来源'}</Badge>
        {source.raw_score != null ? (
          <Badge tone="blue">原始分数 {source.raw_score.toFixed(4)}</Badge>
        ) : null}
        {source.score != null ? (
          <Badge tone="violet">相关度 {source.score.toFixed(4)}</Badge>
        ) : null}
        {kbUid && fileUid ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              onClose()
              navigate(`/knowledge/${kbUid}/files`)
            }}
          >
            <ExternalLink size={13} /> 打开知识库文件
          </Button>
        ) : (
          <span className="flex items-center gap-1 text-slate-400">
            <AlertCircle size={12} /> 该来源未携带知识库定位信息，无法跳转
          </span>
        )}
      </div>

      <div className="max-h-[55vh] overflow-y-auto rounded-lg border border-[var(--prism-line)] bg-slate-50/40 p-4">
        {source.snippet || source.text ? (
          <pre className="mb-3 whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-700">
            {source.snippet || source.text}
          </pre>
        ) : null}

        {loading ? (
          <LoadingState label="加载正文…" />
        ) : error ? (
          <ErrorState problem={error} />
        ) : content ? (
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-700">
            {content}
          </pre>
        ) : null}
      </div>
    </Dialog>
  )
}

export { Loader2, ApiProblem }
