import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon
  title: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--prism-line)] bg-slate-50/50 px-6 py-12 text-center',
        className,
      )}
    >
      <Icon size={28} className="text-slate-300" />
      <div className="text-sm font-medium text-slate-700">{title}</div>
      {description ? <div className="max-w-sm text-xs text-slate-400">{description}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}
