import { Network } from 'lucide-react'
import { useOutletContext } from 'react-router-dom'
import type { KnowledgeBase } from '@/features/knowledge/api/knowledgeBases'
import { EmptyState } from '@/components/ui/EmptyState'

type Ctx = { kb?: KnowledgeBase; reload: () => void }

// Graph page.
//
// IMPORTANT (Graph scope principle): only Graph Tasks 1–2 (data model + Outbox
// foundation) are complete in the backend. There is NO graph build/status/
// projection/re-extraction public endpoint, and the knowledge-scoped graph
// visualization is NOT a finished product. We therefore do NOT render a fake
// graph here.
//
// What IS available: the existing legacy global GraphRAG page at /graph stays
// intact and compatible (untouched). This scoped page only shows the real
// active_graph_generation status from the KB summary and an honest empty state.
export function KnowledgeGraphPage() {
  const { kb } = useOutletContext<Ctx>()
  return (
    <div data-testid="knowledge-graph-page" className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-900">图谱</h2>
        {kb?.active_graph_generation ? (
          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
            图谱 generation：{kb.active_graph_generation}
          </span>
        ) : null}
      </div>
      <EmptyState
        icon={Network}
        title="该知识库的图谱视图暂未启用"
        description="完整图谱产品能力（投影激活、图检索、治理）尚在建设中。如需查看全局图谱，请访问顶部导航的「图谱」页面。"
      />
    </div>
  )
}
