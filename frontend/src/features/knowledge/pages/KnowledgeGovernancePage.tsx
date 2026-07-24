import { AlertCircle } from 'lucide-react'
import { EmptyState } from '@/components/ui/EmptyState'

// Governance page.
//
// Graph governance actions (rebuild-projection / re-extract) do NOT exist as
// backend endpoints yet (Graph Tasks 3–8). We intentionally do not implement a
// fake governance workbench. This page is kept as an honest empty state so the
// route exists (deep-linkable) without presenting unavailable functionality
// as ready.
export function KnowledgeGovernancePage() {
  return (
    <div data-testid="knowledge-governance-page" className="flex h-full min-h-0 flex-col gap-3">
      <h2 className="text-base font-semibold text-slate-900">治理</h2>
      <EmptyState
        icon={AlertCircle}
        title="图谱治理能力尚未上线"
        description="投影重建、重新抽取等治理操作依赖后续图谱阶段，当前暂未提供。"
      />
    </div>
  )
}
