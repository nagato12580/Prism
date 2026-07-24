import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Dialog({
  open,
  onClose,
  title,
  children,
  className,
  width = 'md',
}: {
  open: boolean
  onClose: () => void
  title?: React.ReactNode
  children: React.ReactNode
  className?: string
  width?: 'sm' | 'md' | 'lg' | 'xl'
}) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      previouslyFocused?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  const widths = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl', xl: 'max-w-5xl' }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 sm:p-8">
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'relative my-8 w-full rounded-2xl border border-[var(--prism-line)] bg-white shadow-2xl',
          widths[width],
          className,
        )}
      >
        {title ? (
          <div className="flex items-center justify-between gap-3 border-b border-[var(--prism-line)] px-5 py-3">
            <div className="text-sm font-semibold text-slate-900">{title}</div>
            <button
              ref={closeRef}
              type="button"
              aria-label="关闭"
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/80"
            >
              <X size={16} />
            </button>
          </div>
        ) : null}
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}
