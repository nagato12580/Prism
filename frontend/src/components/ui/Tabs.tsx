import { cn } from '@/lib/utils'

export interface TabItem {
  key: string
  label: string
}

export function Tabs({
  items,
  active,
  onChange,
  className,
}: {
  items: TabItem[]
  active: string
  onChange: (key: string) => void
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1 border-b border-[var(--prism-line)]', className)}>
      {items.map((item) => {
        const isActive = item.key === active
        return (
          <button
            key={item.key}
            type="button"
            aria-current={isActive ? 'page' : undefined}
            onClick={() => onChange(item.key)}
            className={cn(
              'relative h-9 px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
              isActive ? 'text-[var(--prism-blue)]' : 'text-slate-500 hover:text-slate-800',
            )}
          >
            {item.label}
            {isActive ? (
              <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--prism-blue)]" />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
