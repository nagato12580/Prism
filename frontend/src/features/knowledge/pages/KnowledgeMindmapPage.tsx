import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Network, Sparkles, RefreshCw, AlertCircle } from 'lucide-react'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { enrichmentApi, type MindmapResponse } from '@/features/knowledge/api/enrichment'
import { genId } from '@/lib/utils'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/StateView'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

interface MindmapNode {
  id?: string
  title?: string
  file_uid?: string
  relative_path?: string
  children?: MindmapNode[]
}

export function KnowledgeMindmapPage() {
  const { kb } = useOutletContext<Ctx>()
  const kbUid = kb?.kb_uid ?? ''
  const [data, setData] = useState<MindmapResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [generating, setGenerating] = useState(false)

  const load = () => {
    if (!kbUid) return
    setLoading(true)
    setError(null)
    enrichmentApi
      .getMindmap(kbUid)
      .then(setData)
      .catch((e) => setError(e))
      .finally(() => setLoading(false))
  }

  useEffect(load, [kbUid])

  const generate = () => {
    if (!kbUid) return
    setGenerating(true)
    enrichmentApi
      .generateMindmap(kbUid, { idempotency_key: genId() })
      .then(() => load())
      .catch((e) => setError(e))
      .finally(() => setGenerating(false))
  }

  const mindmap = (data?.mindmap ?? {}) as Record<string, unknown>
  const status = String(mindmap.status ?? '')
  const version = Number(mindmap.version ?? 0)
  const nodes = (mindmap.nodes as MindmapNode[]) ?? []

  return (
    <div data-testid="knowledge-mindmap-page" className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">知识导图</h2>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={load}><RefreshCw size={14} /> 刷新</Button>
          <Button size="sm" variant="primary" onClick={generate} loading={generating}>
            <Sparkles size={14} /> 生成导图
          </Button>
        </div>
      </div>

      {status ? (
        <div className="flex items-center gap-2">
          <Badge tone={status === 'ready' ? 'green' : status === 'stale' ? 'amber' : 'blue'}>{status}</Badge>
          {version ? <span className="text-xs text-slate-400">版本 {version}</span> : null}
        </div>
      ) : null}

      {loading ? (
        <LoadingState label="加载导图…" />
      ) : error ? (
        <ErrorState problem={error} onRetry={load} />
      ) : nodes.length === 0 ? (
        <EmptyState
          icon={Network}
          title="尚未生成知识导图"
          description="基于文件结构生成可折叠的知识导图，点击「生成导图」开始"
        />
      ) : (
        <div className="overflow-auto rounded-xl border border-[var(--prism-line)] bg-white p-4">
          <MindmapTree nodes={nodes} />
        </div>
      )}
    </div>
  )
}

function MindmapTree({ nodes, depth = 0 }: { nodes: MindmapNode[]; depth?: number }) {
  return (
    <ul className={depth > 0 ? 'ml-4 border-l border-[var(--prism-line)] pl-3' : 'space-y-1'}>
      {nodes.map((node, i) => (
        <li key={node.id ?? node.title ?? i} className="py-1">
          <div className="flex items-center gap-2 text-sm text-slate-700">
            {depth === 0 ? <Network size={13} className="text-[var(--prism-blue)]" /> : <AlertCircle size={11} className="text-slate-300" />}
            <span className="font-medium">{node.title ?? node.id ?? '未命名'}</span>
            {node.relative_path ? <span className="text-[11px] text-slate-400">{node.relative_path}</span> : null}
          </div>
          {node.children?.length ? <MindmapTree nodes={node.children} depth={depth + 1} /> : null}
        </li>
      ))}
    </ul>
  )
}
