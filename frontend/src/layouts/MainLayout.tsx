import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { MessageSquare, BookOpen } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/chat', label: '对话', icon: MessageSquare },
  { to: '/knowledge', label: '知识库', icon: BookOpen },
]

export function MainLayout() {
  const location = useLocation()
  return (
    <div className="flex h-screen">
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 text-lg font-bold text-primary">🔮 Prism</div>
        <nav className="flex-1 px-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={cn(
                'flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors',
                location.pathname.startsWith(item.to)
                  ? 'bg-blue-50 text-primary'
                  : 'text-gray-600 hover:bg-gray-100'
              )}
            >
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
