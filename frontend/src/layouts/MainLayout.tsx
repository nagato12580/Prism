import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BookOpen,
  CircleUserRound,
  Fingerprint,
  Inbox,
  Menu,
  MessageSquare,
  Moon,
  Network,
  Search,
  Sun,
  Waypoints,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { memoryApi } from '@/app/api'

const navItems = [
  { to: '/chat', label: '对话', icon: MessageSquare },
  { to: '/review', label: '审核台', icon: Inbox },
  { to: '/assets', label: '资产', icon: BookOpen },
  { to: '/knowledge', label: '知识库', icon: BookOpen },
  { to: '/graph', label: '图谱', icon: Network },
  { to: '/memory/inbox', label: '记忆审核', icon: Inbox },
  { to: '/memory/profile', label: '用户画像', icon: Fingerprint },
  { to: '/memory/graph', label: '记忆图谱', icon: Waypoints },
]

const mobileNavId = 'prism-mobile-navigation'

function Brand({ isDark = false }: { isDark?: boolean }) {
  return (
    <div className="flex h-14 items-center gap-3 px-3">
      <div
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[10px] font-black tracking-tight shadow-[0_0_24px_rgba(59,130,246,0.25)]',
          isDark ? 'bg-white text-slate-950' : 'bg-slate-950 text-white',
        )}
      >
        PR
      </div>
      <div className="min-w-0">
        <div className={cn('truncate text-[15px] font-semibold tracking-normal', isDark ? 'text-white' : 'text-slate-950')}>
          棱镜 Prism
        </div>
        <div className="truncate text-[11px] text-slate-500">Personal knowledge lab</div>
      </div>
    </div>
  )
}

function NavList({ onNavigate, isDark = false, draftCount = 0 }: { onNavigate?: () => void; isDark?: boolean; draftCount?: number }) {
  const location = useLocation()

  return (
    <nav className="mt-5 space-y-6 px-2">
      <div className="px-2 text-[11px] font-medium text-slate-500">对话</div>
      <div className="space-y-1">
        <NavItem
          to="/chat"
          label="对话"
          icon={MessageSquare}
          active={location.pathname === '/chat' || location.pathname.startsWith('/chat/') || location.pathname === '/'}
          isDark={isDark}
          onNavigate={onNavigate}
        />
      </div>

      <div className="px-2 text-[11px] font-medium text-slate-500">工作台</div>
      <div className="space-y-1">
        <NavItem
          to="/review"
          label="审核台"
          icon={Inbox}
          active={location.pathname === '/review' || location.pathname.startsWith('/review/')}
          isDark={isDark}
          onNavigate={onNavigate}
        />
        <NavItem
          to="/assets"
          label="资产"
          icon={BookOpen}
          active={location.pathname === '/assets' || location.pathname.startsWith('/assets/')}
          isDark={isDark}
          onNavigate={onNavigate}
        />
        <NavItem
          to="/knowledge"
          label="知识库"
          icon={BookOpen}
          active={location.pathname === '/knowledge' || location.pathname.startsWith('/knowledge/')}
          isDark={isDark}
          onNavigate={onNavigate}
        />
        <NavItem
          to="/graph"
          label="图谱"
          icon={Network}
          active={location.pathname === '/graph' || location.pathname.startsWith('/graph/')}
          isDark={isDark}
          onNavigate={onNavigate}
        />
      </div>

      <div className="px-2 text-[11px] font-medium text-slate-500">用户记忆</div>
      <div className="space-y-1">
        <NavItem
          to="/memory/inbox"
          label="记忆审核"
          icon={Inbox}
          active={location.pathname === '/memory/inbox'}
          isDark={isDark}
          onNavigate={onNavigate}
          badge={draftCount}
        />
        <NavItem
          to="/memory/profile"
          label="用户画像"
          icon={Fingerprint}
          active={location.pathname === '/memory/profile'}
          isDark={isDark}
          onNavigate={onNavigate}
        />
        <NavItem
          to="/memory/graph"
          label="记忆图谱"
          icon={Waypoints}
          active={location.pathname === '/memory/graph'}
          isDark={isDark}
          onNavigate={onNavigate}
        />
      </div>
    </nav>
  )
}

function NavItem({
  to,
  label,
  icon: Icon,
  active,
  isDark = false,
  onNavigate,
  badge,
}: {
  to: string
  label: string
  icon: typeof MessageSquare
  active: boolean
  isDark?: boolean
  onNavigate?: () => void
  badge?: number
}) {
  return (
    <NavLink
      to={to}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
      className={cn(
        'group flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/80',
        active
          ? 'bg-[var(--prism-blue)] text-white shadow-[0_10px_24px_-16px_rgba(37,99,235,0.9)]'
          : isDark
            ? 'text-slate-400 hover:bg-white/[0.06] hover:text-slate-100'
            : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950',
      )}
    >
      <Icon size={16} className="shrink-0" />
      <span>{label}</span>
      {badge != null && badge > 0 ? (
        <span className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
          {badge > 99 ? '99+' : badge}
        </span>
      ) : null}
    </NavLink>
  )
}

function CompactNav({ onNavigate, isDark = false, draftCount = 0 }: { onNavigate?: () => void; isDark?: boolean; draftCount?: number }) {
  const location = useLocation()

  return (
    <nav className="mt-5 space-y-1 px-2">
      {navItems.map((item) => {
        const Icon = item.icon
        const active =
          location.pathname === item.to ||
          location.pathname.startsWith(`${item.to}/`) ||
          (item.to === '/chat' && location.pathname === '/')

        return (
          <NavLink
            key={item.to}
            to={item.to}
            aria-current={active ? 'page' : undefined}
            onClick={onNavigate}
            className={cn(
              'group flex h-10 items-center gap-3 rounded-lg px-3 text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/80',
              active
                ? 'bg-[var(--prism-blue)] text-white'
                : isDark
                  ? 'text-slate-400 hover:bg-white/[0.06] hover:text-slate-100'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950',
            )}
          >
            <Icon size={18} className="shrink-0" />
            <span>{item.label}</span>
            {item.to === '/memory/inbox' && draftCount > 0 ? (
              <span className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
                {draftCount > 99 ? '99+' : draftCount}
              </span>
            ) : null}
          </NavLink>
        )
      })}
    </nav>
  )
}

export function MainLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [draftCount, setDraftCount] = useState(0)
  const isDark = theme === 'dark'
  const location = useLocation()
  const isChatRoute = location.pathname === '/' || location.pathname === '/chat' || location.pathname.startsWith('/chat/')

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      memoryApi.countDrafts('draft')
        .then(res => { if (!cancelled) setDraftCount(res.count) })
        .catch(() => {})
    }
    poll()
    const id = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return (
    <div className={cn('fixed inset-0 flex overflow-hidden transition-colors', isDark ? 'bg-[#070917] text-slate-100' : 'bg-[#f4f7fb] text-slate-950')}>
      <aside className={cn('hidden w-[220px] shrink-0 flex-col border-r transition-colors lg:flex', isDark ? 'border-white/[0.07] bg-[#0c0f24]' : 'border-slate-200 bg-[#f8fbff]')}>
        <Brand isDark={isDark} />
        <NavList isDark={isDark} draftCount={draftCount} />
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            className="absolute inset-0 bg-slate-950/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside
            id={mobileNavId}
            className={cn(
              'relative flex h-full w-72 max-w-[86vw] flex-col border-r py-2 shadow-2xl',
              isDark ? 'border-white/[0.07] bg-[#0c0f24]' : 'border-slate-200 bg-white',
            )}
          >
            <div className="flex items-center justify-between gap-4">
              <Brand isDark={isDark} />
              <button
                type="button"
                aria-label="关闭导航"
                className="rounded-lg p-2 text-slate-300 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/80"
                onClick={() => setMobileOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <CompactNav isDark={isDark} onNavigate={() => setMobileOpen(false)} draftCount={draftCount} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className={cn('flex h-14 shrink-0 items-center gap-3 border-b px-4 backdrop-blur transition-colors lg:px-5', isDark ? 'border-white/[0.07] bg-[#0a0d1c]/95' : 'border-slate-200 bg-white/92')}>
          <button
            type="button"
            aria-label="打开导航"
            aria-controls={mobileNavId}
            aria-expanded={mobileOpen}
            className="rounded-lg border border-[var(--prism-line)] bg-white p-2 text-slate-700 shadow-sm transition hover:border-blue-200 hover:text-[var(--prism-blue)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu size={18} />
          </button>

          <div className="relative hidden w-full max-w-[440px] lg:block">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              aria-label="全局搜索"
              placeholder="搜索文档、知识、对话..."
              className={cn(
                'h-8 w-full rounded-md border px-9 text-xs outline-none transition',
                isDark
                  ? 'border-white/[0.08] bg-white/[0.07] text-slate-200 placeholder:text-slate-500 focus:border-blue-400/60 focus:bg-white/[0.1]'
                  : 'border-slate-200 bg-slate-50 text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:bg-white',
              )}
            />
          </div>

          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              aria-label={isDark ? '切换为亮色主题' : '切换为暗色主题'}
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              className={cn(
                'inline-flex h-8 items-center gap-1 rounded-md border px-2 text-xs font-medium transition',
                isDark
                  ? 'border-white/10 bg-white/[0.06] text-slate-200 hover:bg-white/[0.1]'
                  : 'border-slate-200 bg-white text-slate-600 shadow-sm hover:border-blue-200 hover:text-blue-600',
              )}
            >
              {isDark ? <Sun size={15} /> : <Moon size={15} />}
              <span className="hidden sm:inline">{isDark ? '亮色' : '暗色'}</span>
            </button>
            <div className={cn('hidden items-center gap-2 text-xs sm:flex', isDark ? 'text-slate-300' : 'text-slate-700')}>
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--prism-blue)] text-[11px] font-semibold text-white">A</span>
              <span>admin@example.com</span>
            </div>
            <CircleUserRound size={20} className="text-slate-400 sm:hidden" />
          </div>
        </header>

        <main className={cn('min-h-0 flex-1 p-4 transition-colors lg:p-6', isChatRoute ? 'overflow-hidden' : 'overflow-auto', isDark ? 'bg-[radial-gradient(circle_at_50%_0%,rgba(37,99,235,0.18),transparent_36rem),#070917]' : 'bg-[#f4f7fb]')}>
          <div
            className={cn(
              'mx-auto max-w-[1520px] rounded-2xl border p-3 shadow-[0_24px_80px_-56px_rgba(15,23,42,0.35)] backdrop-blur lg:p-4',
              isChatRoute && 'flex h-full min-h-0 flex-col overflow-hidden',
              !isChatRoute && 'min-h-full',
              isDark ? 'border-white/[0.07] bg-[#0d1024]/88' : 'border-slate-200 bg-white',
            )}
          >
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
