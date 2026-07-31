import { Network } from 'lucide-react'
import { useMemo } from 'react'
import { useOutletContext } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { KnowledgeGraphPage as UnifiedKnowledgeGraphPage } from '@/pages/KnowledgeGraphPage'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { knowledgeBaseGraphApi } from '@/features/knowledge/api/graph'
import { useKnowledgeWorkspaceStore } from '@/features/knowledge/stores/knowledgeWorkspaceStore'
import { graphFilterParamsFromWorkspaceSelection } from '@/features/knowledge/pages/knowledgeGraphState'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

export function KnowledgeGraphPage() {
  const { kb } = useOutletContext<Ctx>()
  const selectedFileUidsByKb = useKnowledgeWorkspaceStore((state) => state.selectedFileUids)
  const kbUid = kb?.kb_uid ?? ''
  const selectedFileUids = useMemo(
    () => graphFilterParamsFromWorkspaceSelection(selectedFileUidsByKb, kbUid).file_uids ?? [],
    [kbUid, selectedFileUidsByKb],
  )

  const loader = useMemo(
    () => (params: { view: 'entity' | 'source'; q?: string; limit?: number }) =>
      knowledgeBaseGraphApi.get(kbUid, {
        view: params.view,
        limit: params.limit,
        file_uids: selectedFileUids,
      }),
    [kbUid, selectedFileUids],
  )

  if (!kb?.active_graph_generation) {
    return (
      <div data-testid="knowledge-graph-page" className="flex h-full min-h-0 flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-900">图谱</h2>
        </div>
        <EmptyState
          icon={Network}
          title="该知识库还没有可展示的图谱"
          description="先让文件完成解析、索引和图构建，然后再回来查看该知识库内所有文档的 scoped 子图。"
        />
      </div>
    )
  }

  return (
    <div data-testid="knowledge-graph-page" className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">图谱</h2>
          <p className="mt-1 text-xs text-slate-500">
            {selectedFileUids.length
              ? `当前按工作区已选文件过滤：${selectedFileUids.length} 个文件`
              : '当前显示该知识库全部文档的 scoped 子图'}
          </p>
        </div>
        <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
          图谱 generation：{kb.active_graph_generation}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-[var(--prism-line)] bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.96),_rgba(241,245,249,0.96)_55%,_rgba(226,232,240,0.96))]">
        <UnifiedKnowledgeGraphPage key={`${kbUid}:${selectedFileUids.join(',')}`} loader={loader} />
      </div>
    </div>
  )
}
