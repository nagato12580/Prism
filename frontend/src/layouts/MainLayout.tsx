import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { BookOpen, Menu, MessageSquare, Sparkles, X } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/chat', label: '对话', description: '知识问答', icon: MessageSquare },
  { to: '/knowledge', label: '知识库', description: '资料工作台', icon: BookOpen },
]

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="prism-mark flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white">
        <Sparkles size={20} />
      </div>
      <div className="min-w-0">
        <div className="text-base font-semibold tracking-normal text-white">Prism</div>
        <div className="truncate text-xs text-slate-400">Personal knowledge lab</div>
      </div>
    </div>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()

  return (
    <nav className="mt-8 flex flex-col gap-2">
      {navItems.map((item) => {
        const Icon = item.icon
        const isRootChat = item.to === '/chat' && location.pathname === '/'

        return (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-xl border px-3 py-3 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/80',
                isActive || isRootChat
                  ? 'border-cyan-400/30 bg-white/10 text-white shadow-[inset_3px_0_0_var(--prism-cyan)]'
                  : 'border-transparent text-slate-300 hover:border-white/10 hover:bg-white/[0.06] hover:text-white'
              )
            }
          >
            <Icon size={18} className="shrink-0" />
            <span className="min-w-0">
              <span className="block font-medium">{item.label}</span>
              <span className="block truncate text-xs text-slate-500 group-hover:text-slate-400">
                {item.description}
              </span>
            </span>
          </NavLink>
        )
      })}
    </nav>
  )
}

export function MainLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="fixed inset-0 flex overflow-hidden bg-[var(--prism-surface)]">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/10 bg-[var(--prism-ink)] px-4 py-5 lg:flex">
        <Brand />
        <NavList />
        <div className="mt-auto rounded-xl border border-white/10 bg-white/5 p-3 text-xs leading-6 text-slate-400">
          <div className="mb-1 font-medium text-slate-200">Prism Lab</div>
          <div>把资料、检索和回答收束在一个清晰的工作台里。</div>
        </div>
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="关闭导航"
            className="absolute inset-0 bg-slate-950/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative flex h-full w-72 max-w-[86vw] flex-col bg-[var(--prism-ink)] px-4 py-5 shadow-2xl">
            <div className="flex items-center justify-between gap-4">
              <Brand />
              <button
                aria-label="关闭导航"
                className="rounded-lg p-2 text-slate-300 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/80"
                onClick={() => setMobileOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <NavList onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--prism-line)] bg-white/80 px-4 backdrop-blur lg:px-6">
          <button
            aria-label="打开导航"
            className="rounded-lg border border-[var(--prism-line)] bg-white p-2 text-slate-700 shadow-sm transition hover:border-blue-200 hover:text-[var(--prism-blue)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-cyan)] lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu size={18} />
          </button>
          <div className="hidden text-sm text-slate-500 lg:block">Phase 1 · Prism Lab</div>
          <div className="ml-auto rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
            RAG workspace
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
