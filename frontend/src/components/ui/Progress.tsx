import { cn } from '@/lib/utils'

export function Progress({
  value,
  max,
  className,
  ariaLabel,
}: {
  value: number
  max?: number
  className?: string
  ariaLabel?: string
}) {
  const total = max ?? 100
  const pct = total > 0 ? Math.min(100, Math.max(0, Math.round((value / total) * 100))) : 0
  return (
    <div
      role="progressbar"
      aria-label={ariaLabel ?? '进度'}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={total}
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-slate-100', className)}
    >
      <div className="h-full rounded-full bg-[var(--prism-blue)] transition-all" style={{ width: `${pct}%` }} />
    </div>
  )
}
