import { AlertTriangle, Loader2, ShieldAlert, FileQuestion } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ApiProblem } from '@/features/knowledge/api/client'
import { EmptyState } from './EmptyState'

export { EmptyState }

export function LoadingState({ label = '加载中…', className }: { label?: string; className?: string }) {
  return (
    <div className={cn('flex items-center justify-center gap-2 py-10 text-sm text-slate-400', className)}>
      <Loader2 size={16} className="animate-spin" />
      <span>{label}</span>
    </div>
  )
}

// Render a backend ApiProblem without leaking internal details: shows the safe
// code/message, retryability and trace id (trace id is a public correlation id,
// not a secret). Never prints stack traces or response bodies.
export function ErrorState({ problem, onRetry }: { problem: unknown; onRetry?: () => void }) {
  const err = problem as Partial<ApiProblem> & { message?: string }
  const code = err?.code ?? 'ERROR'
  const message = err?.message ?? '发生未知错误'
  const retryable = err?.retryable
  const traceId = err?.traceId
  const isAccess = err?.status === 403 || err?.status === 404

  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-amber-200 bg-amber-50/60 px-6 py-10 text-center">
      {isAccess ? <ShieldAlert size={26} className="text-amber-500" /> : <AlertTriangle size={26} className="text-amber-500" />}
      <div className="text-sm font-medium text-amber-800">{message}</div>
      <div className="flex items-center gap-2 text-[11px] text-amber-600">
        <span className="rounded bg-amber-100 px-1.5 py-0.5 font-mono">{code}</span>
        {retryable ? <span>可重试</span> : null}
        {traceId ? <span className="font-mono">trace: {traceId}</span> : null}
      </div>
      {retryable && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg border border-amber-300 bg-white px-3 py-1 text-xs font-medium text-amber-700 transition hover:bg-amber-50"
        >
          重试
        </button>
      ) : null}
    </div>
  )
}

export function NotFoundState({ title = '未找到该知识库', description }: { title?: string; description?: string }) {
  return (
    <EmptyState
      icon={FileQuestion}
      title={title}
      description={description ?? '该资源不存在或已被删除'}
    />
  )
}
