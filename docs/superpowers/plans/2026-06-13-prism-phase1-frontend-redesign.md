# Prism Phase 1 Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Prism Phase 1 frontend into the approved Prism Lab design for the existing layout, chat page, and knowledge page.

**Architecture:** Keep the current React/Vite/Tailwind app and redesign only the existing frontend surfaces. Use shared CSS tokens in `index.css`, a stronger `MainLayout`, and focused page-level components inside `ChatPage.tsx` and `KnowledgePage.tsx`. Do not change backend contracts or add Ant Design.

**Tech Stack:** React 18, React Router 7, TypeScript, Vite 6, Tailwind CSS 4, Zustand, lucide-react, react-markdown.

---

## References

- Design spec: `docs/superpowers/specs/2026-06-13-prism-phase1-frontend-redesign-design.md`
- Tailwind v4 CSS import and directives: `https://tailwindcss.com/docs/functions-and-directives`
- React Router `NavLink`: `https://reactrouter.com/api/components/NavLink`

## File Structure

- Modify: `frontend/src/index.css`
  - Owns Prism Lab tokens, base page styling, scrollbars, reusable Markdown styling, and small shared animation utilities.
- Modify: `frontend/src/layouts/MainLayout.tsx`
  - Owns the product shell, dark sidebar, mobile navigation drawer, brand mark, and route navigation.
- Modify: `frontend/src/pages/ChatPage.tsx`
  - Owns local chat UI, empty state, streaming state, source expansion, clear conversation action, and input card.
- Modify: `frontend/src/pages/KnowledgePage.tsx`
  - Owns the knowledge workbench UI, upload/import/create flows, item cards, empty/loading/error states.
- Keep unchanged: `frontend/src/app/api.ts`
  - Existing API contract already supplies all data used by the redesign.
- Keep unchanged: `frontend/src/app/chatStore.ts`
  - Existing `clear()` action already supports the planned clear conversation control.

## Task 1: Add Prism Lab Global Styling

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Replace global CSS with Prism Lab tokens**

Replace the contents of `frontend/src/index.css` with:

```css
@import "tailwindcss";

:root {
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #172033;
  background: #f7f9fc;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  --prism-ink: #111827;
  --prism-blue: #155eef;
  --prism-cyan: #22d3ee;
  --prism-violet: #8b5cf6;
  --prism-surface: #f7f9fc;
  --prism-line: #e6eaf2;
}

html,
body,
#root {
  height: 100%;
}

body {
  margin: 0;
  background:
    radial-gradient(circle at 20% 0%, rgba(34, 211, 238, 0.12), transparent 32rem),
    linear-gradient(180deg, #f7f9fc 0%, #eef3fb 100%);
}

button,
input,
textarea {
  font: inherit;
}

button {
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-thumb {
  background: rgba(17, 24, 39, 0.18);
  border-radius: 999px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(17, 24, 39, 0.32);
}

.prism-mark {
  background: conic-gradient(from 35deg, var(--prism-blue), var(--prism-cyan), var(--prism-violet), var(--prism-blue));
  box-shadow: 0 0 24px rgba(34, 211, 238, 0.34);
}

.prism-panel {
  border: 1px solid var(--prism-line);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 14px 38px -30px rgba(16, 24, 40, 0.55);
}

.markdown-body {
  color: #1f2937;
  font-size: 16px;
  line-height: 1.75;
  word-break: break-word;
}

.markdown-body > *:first-child {
  margin-top: 0;
}

.markdown-body > *:last-child {
  margin-bottom: 0;
}

.markdown-body p {
  margin: 0.5rem 0;
}

.markdown-body ul,
.markdown-body ol {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.markdown-body li {
  margin: 0.25rem 0;
}

.markdown-body h1,
.markdown-body h2,
.markdown-body h3 {
  margin: 1rem 0 0.5rem;
  font-weight: 700;
  line-height: 1.35;
}

.markdown-body h1 {
  font-size: 1.35rem;
}

.markdown-body h2 {
  font-size: 1.2rem;
}

.markdown-body h3 {
  font-size: 1.05rem;
}

.markdown-body blockquote {
  margin: 0.75rem 0;
  padding: 0.5rem 0.85rem;
  border-left: 3px solid var(--prism-cyan);
  border-radius: 0 8px 8px 0;
  background: #f4f8ff;
  color: #536174;
}

.markdown-body code {
  border-radius: 6px;
  background: #eef3fb;
  padding: 0.12rem 0.32rem;
  font-size: 0.9em;
}

.markdown-body pre {
  overflow-x: auto;
  border-radius: 10px;
  background: #111827;
  color: #e5e7eb;
  padding: 0.9rem 1rem;
}

.markdown-body pre code {
  background: transparent;
  padding: 0;
  color: inherit;
}

@keyframes prism-pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: translateY(0);
  }
  50% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
```

- [ ] **Step 2: Verify CSS compiles**

Run:

```powershell
pnpm.cmd build
```

Expected: the command reaches Vite build output. If TypeScript fails because later tasks are not applied yet, stop and confirm Task 1 was run in isolation from a clean frontend state.

- [ ] **Step 3: Commit Task 1**

```powershell
git add frontend/src/index.css
git commit -m "style: add Prism Lab design tokens"
```

## Task 2: Redesign the Main Application Layout

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`

- [ ] **Step 1: Replace `MainLayout.tsx`**

Replace the file with:

```tsx
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { BookOpen, Menu, MessageSquare, Sparkles, X } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/chat', label: '对话', description: '知识问答', icon: MessageSquare },
  { to: '/knowledge', label: '知识库', description: '资料工作台', icon: BookOpen },
]

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="prism-mark flex h-10 w-10 items-center justify-center rounded-xl text-white">
        <Sparkles size={20} />
      </div>
      <div className="min-w-0">
        <div className="text-base font-semibold tracking-normal text-white">Prism</div>
        <div className="text-xs text-slate-400">Personal knowledge lab</div>
      </div>
    </div>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="mt-8 flex flex-col gap-2">
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'group flex items-center gap-3 rounded-xl border px-3 py-3 text-sm transition',
              isActive
                ? 'border-cyan-400/30 bg-white/10 text-white shadow-[inset_3px_0_0_var(--prism-cyan)]'
                : 'border-transparent text-slate-300 hover:border-white/10 hover:bg-white/[0.06] hover:text-white',
            )
          }
        >
          <item.icon size={18} className="shrink-0" />
          <span className="min-w-0">
            <span className="block font-medium">{item.label}</span>
            <span className="block truncate text-xs text-slate-500 group-hover:text-slate-400">
              {item.description}
            </span>
          </span>
        </NavLink>
      ))}
    </nav>
  )
}

export function MainLayout() {
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--prism-surface)]">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/10 bg-[var(--prism-ink)] px-4 py-5 lg:flex">
        <Brand />
        <NavList />
        <div className="mt-auto rounded-xl border border-white/10 bg-white/5 p-3 text-xs leading-6 text-slate-400">
          <div className="mb-1 font-medium text-slate-200">Prism Lab</div>
          <div>把资料、检索和回答收束在一个清晰的工作台里。</div>
        </div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="关闭导航"
            className="absolute inset-0 bg-slate-950/50"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative flex h-full w-72 flex-col bg-[var(--prism-ink)] px-4 py-5 shadow-2xl">
            <div className="flex items-center justify-between">
              <Brand />
              <button
                aria-label="关闭导航"
                className="rounded-lg p-2 text-slate-300 hover:bg-white/10 hover:text-white"
                onClick={() => setMobileOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <NavList onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--prism-line)] bg-white/80 px-4 backdrop-blur lg:px-6">
          <button
            aria-label="打开导航"
            className="rounded-lg border border-[var(--prism-line)] bg-white p-2 text-slate-700 shadow-sm lg:hidden"
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
```

- [ ] **Step 2: Run the frontend build**

Run:

```powershell
pnpm.cmd build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 3: Commit Task 2**

```powershell
git add frontend/src/layouts/MainLayout.tsx
git commit -m "feat: redesign Prism app shell"
```

## Task 3: Redesign Chat Page and Source Details

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Replace `ChatPage.tsx`**

Replace the file with:

```tsx
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  Loader2,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useChatStore, type Message, type Source } from '@/app/chatStore'
import { cn } from '@/lib/utils'

const starterPrompts = [
  '总结我上传资料里的核心观点',
  '基于知识库帮我列一个行动清单',
  '哪些资料可以回答这个问题？',
]

export function ChatPage() {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const messages = useChatStore((s) => s.messages)
  const addMessage = useChatStore((s) => s.addMessage)
  const appendToLast = useChatStore((s) => s.appendToLast)
  const setLastSources = useChatStore((s) => s.setLastSources)
  const finishLast = useChatStore((s) => s.finishLast)
  const clear = useChatStore((s) => s.clear)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (value = input) => {
    if (!value.trim() || sending) return
    const query = value.trim()
    setInput('')
    setSending(true)

    const history = messages
      .filter((m) => !m.streaming)
      .map((m) => ({ role: m.role, content: m.content }))

    addMessage({ id: crypto.randomUUID(), role: 'user', content: query })
    addMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true })

    try {
      const resp = await fetch('/api/v1/chat/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, history }),
      })

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('响应没有可读取的内容流')

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value: chunk } = await reader.read()
        if (done) break
        buffer += decoder.decode(chunk, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const msg = JSON.parse(line)
            if (msg.type === 'sources') setLastSources(msg.data)
            else if (msg.type === 'token') appendToLast(msg.data)
            else if (msg.type === 'done') finishLast()
            else if (msg.type === 'error') appendToLast(`\n\n回答失败：${msg.data}`)
          } catch {
            appendToLast('\n\n收到了一段无法解析的流式响应。')
          }
        }
      }
      finishLast()
    } catch (e) {
      appendToLast('请求失败：' + (e as Error).message)
      finishLast()
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col">
      <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-950">对话</h1>
          <p className="mt-1 text-sm text-slate-500">基于你的知识库进行可追溯问答。</p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clear}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2 text-sm text-slate-600 shadow-sm hover:bg-slate-50"
          >
            <Trash2 size={16} />
            清空对话
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-[var(--prism-line)] bg-white/60 p-4 lg:p-6">
        {messages.length === 0 ? <EmptyChat onPrompt={send} /> : null}
        <div className="space-y-5">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
        </div>
        <div ref={endRef} />
      </div>

      <div className="mt-4 shrink-0 rounded-2xl border border-[var(--prism-line)] bg-white p-3 shadow-[0_16px_40px_-30px_rgba(16,24,40,0.7)]">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            placeholder="输入问题，Prism 会检索知识库后回答"
            disabled={sending}
            rows={2}
            className="max-h-36 min-h-12 flex-1 resize-none rounded-xl border-0 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-900 outline-none ring-1 ring-slate-200 transition focus:bg-white focus:ring-[var(--prism-blue)] disabled:opacity-60"
          />
          <button
            onClick={() => send()}
            disabled={sending || !input.trim()}
            className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[var(--prism-blue)] text-white shadow-lg shadow-blue-600/20 transition hover:brightness-105 disabled:bg-slate-300 disabled:shadow-none"
            aria-label="发送"
          >
            {sending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  )
}

function EmptyChat({ onPrompt }: { onPrompt: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center py-16 text-center">
      <div className="prism-mark mb-5 flex h-14 w-14 items-center justify-center rounded-2xl text-white">
        <Sparkles size={26} />
      </div>
      <h2 className="text-2xl font-semibold text-slate-950">Prism 知识问答工作台</h2>
      <p className="mt-3 max-w-xl text-sm leading-7 text-slate-500">
        先上传资料，再让 Prism 从你的知识库里检索、组织并给出可追溯回答。
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {starterPrompts.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onPrompt(prompt)}
            className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-100"
          >
            {prompt}
          </button>
        ))}
      </div>
      <Link
        to="/knowledge"
        className="mt-6 inline-flex items-center gap-2 rounded-xl border border-[var(--prism-line)] bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
      >
        <BookOpen size={16} />
        去知识库添加资料
      </Link>
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  const [openSources, setOpenSources] = useState(false)
  const isUser = msg.role === 'user'
  const isError = !isUser && msg.content.startsWith('请求失败')

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn('max-w-[86%] lg:max-w-[78%]', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-7 shadow-sm',
            isUser
              ? 'rounded-br-md bg-[var(--prism-blue)] text-white shadow-blue-600/20'
              : 'rounded-bl-md border border-[var(--prism-line)] bg-white text-slate-900',
            isError && 'border-red-200 bg-red-50 text-red-700',
          )}
        >
          {msg.content ? (
            isUser ? (
              <p className="whitespace-pre-wrap">{msg.content}</p>
            ) : isError ? (
              <div className="flex gap-2">
                <AlertTriangle size={18} className="mt-1 shrink-0" />
                <p className="whitespace-pre-wrap">{msg.content}</p>
              </div>
            ) : (
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              </div>
            )
          ) : (
            <StreamingState />
          )}
        </div>

        {!isUser && msg.sources && msg.sources.length > 0 && !msg.streaming && (
          <SourceList
            sources={msg.sources}
            open={openSources}
            onToggle={() => setOpenSources((v) => !v)}
          />
        )}
      </div>
    </div>
  )
}

function StreamingState() {
  return (
    <div className="flex items-center gap-2 text-slate-500">
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-[var(--prism-cyan)]"
            style={{ animation: `prism-pulse 1s ease-in-out ${i * 120}ms infinite` }}
          />
        ))}
      </span>
      正在检索知识库...
    </div>
  )
}

function SourceList({
  sources,
  open,
  onToggle,
}: {
  sources: Source[]
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="mt-2">
      <button
        onClick={onToggle}
        className="inline-flex items-center gap-1 rounded-full border border-cyan-100 bg-cyan-50 px-3 py-1 text-xs font-medium text-cyan-700 hover:bg-cyan-100"
      >
        来源 {sources.length}
        <ChevronDown size={14} className={cn('transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="mt-2 grid gap-2">
          {sources.map((source, index) => (
            <div
              key={`${source.chunk_id}-${index}`}
              className="rounded-xl border border-[var(--prism-line)] bg-white px-3 py-2 text-xs leading-6 text-slate-600"
            >
              <div className="font-medium text-slate-900">来源 {index + 1}</div>
              <div>chunk: {source.chunk_id}</div>
              <div>item: {source.item_id}</div>
              <div>score: {source.score.toFixed(4)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run the frontend build**

Run:

```powershell
pnpm.cmd build
```

Expected: TypeScript and Vite build pass.

- [ ] **Step 3: Commit Task 3**

```powershell
git add frontend/src/pages/ChatPage.tsx
git commit -m "feat: redesign Prism chat workspace"
```

## Task 4: Redesign Knowledge Page Workbench

**Files:**
- Modify: `frontend/src/pages/KnowledgePage.tsx`

- [ ] **Step 1: Replace `KnowledgePage.tsx`**

Replace the file with:

```tsx
import { useEffect, useRef, useState } from 'react'
import { knowledgeApi, type KnowledgeItem } from '@/app/api'
import {
  AlertCircle,
  FileText,
  Link as LinkIcon,
  Loader2,
  Plus,
  Trash2,
  Upload,
} from 'lucide-react'

function formatDate(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

export function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newContent, setNewContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      setItems(await knowledgeApi.list())
    } catch (e) {
      setError('知识库加载失败：' + (e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadFile(file)
      await load()
    } catch (e) {
      setError('文件上传失败：' + (e as Error).message)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleUrl = async () => {
    const url = urlInput.trim()
    if (!url) return
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setError('请输入以 http:// 或 https:// 开头的 URL。')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.uploadUrl(url)
      setUrlInput('')
      await load()
    } catch (e) {
      setError('URL 导入失败：' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleCreate = async () => {
    if (!newTitle.trim()) {
      setError('请先填写笔记标题。')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await knowledgeApi.create({
        title: newTitle.trim(),
        content: newContent,
        source_type: 'manual',
      })
      setNewTitle('')
      setNewContent('')
      setShowCreate(false)
      await load()
    } catch (e) {
      setError('笔记保存失败：' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确认删除这条知识吗？')) return
    setError(null)
    try {
      await knowledgeApi.delete(id)
      await load()
    } catch (e) {
      setError('删除失败：' + (e as Error).message)
    }
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-950">知识库</h1>
          <p className="mt-2 text-sm text-slate-500">
            管理 Prism 用来检索和回答的资料。当前 {items.length} 条知识。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={handleUpload}
            accept=".pdf,.docx,.xlsx,.md,.txt,.markdown"
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-xl bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white shadow-lg shadow-blue-600/20 hover:brightness-105 disabled:bg-slate-300"
          >
            <Upload size={16} />
            上传文件
          </button>
          <button
            onClick={() => setShowCreate((v) => !v)}
            className="inline-flex items-center gap-2 rounded-xl border border-[var(--prism-line)] bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <Plus size={16} />
            新建笔记
          </button>
        </div>
      </div>

      <div className="prism-panel mb-4 rounded-2xl p-3">
        <div className="flex flex-col gap-2 lg:flex-row">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl bg-slate-50 px-3 ring-1 ring-slate-200 focus-within:bg-white focus-within:ring-[var(--prism-blue)]">
            <LinkIcon size={16} className="shrink-0 text-slate-400" />
            <input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="粘贴网页 URL，导入为知识条目"
              className="h-11 min-w-0 flex-1 bg-transparent text-sm text-slate-900 outline-none"
            />
          </div>
          <button
            onClick={handleUrl}
            disabled={busy || !urlInput.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--prism-line)] bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:text-slate-300"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LinkIcon size={16} />}
            导入 URL
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            关闭
          </button>
        </div>
      )}

      {showCreate && (
        <div className="prism-panel mb-4 rounded-2xl p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-900">
            <FileText size={16} />
            新建笔记
          </div>
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="笔记标题"
            className="mb-3 w-full rounded-xl border border-[var(--prism-line)] px-3 py-2 text-sm outline-none focus:border-[var(--prism-blue)]"
          />
          <textarea
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="笔记内容，支持 Markdown"
            className="h-36 w-full resize-none rounded-xl border border-[var(--prism-line)] px-3 py-2 text-sm leading-6 outline-none focus:border-[var(--prism-blue)]"
          />
          <div className="mt-3 flex justify-end gap-2">
            <button
              onClick={() => setShowCreate(false)}
              className="rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100"
            >
              取消
            </button>
            <button
              onClick={handleCreate}
              disabled={busy}
              className="rounded-lg bg-[var(--prism-blue)] px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300"
            >
              保存笔记
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center rounded-2xl border border-[var(--prism-line)] bg-white py-20 text-slate-500">
          <Loader2 size={20} className="mr-2 animate-spin" />
          正在加载知识库...
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-blue-200 bg-blue-50/60 px-6 py-16 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-[var(--prism-blue)] shadow-sm">
            <BookOpenIcon />
          </div>
          <h2 className="text-lg font-semibold text-slate-950">还没有知识条目</h2>
          <p className="mt-2 text-sm text-slate-500">上传文件、导入网页，或写一条笔记开始构建 Prism 的知识来源。</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <KnowledgeCard key={item.id} item={item} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  )
}

function BookOpenIcon() {
  return <FileText size={22} />
}

function KnowledgeCard({
  item,
  onDelete,
}: {
  item: KnowledgeItem
  onDelete: (id: string) => void
}) {
  return (
    <article className="prism-panel rounded-2xl p-4 transition hover:-translate-y-0.5 hover:shadow-[0_18px_44px_-32px_rgba(16,24,40,0.75)]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-950" title={item.title}>
            {item.title}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="rounded-full bg-slate-100 px-2 py-0.5">{item.source_type}</span>
            {item.status && <span>{item.status}</span>}
            {formatDate(item.created_at) && <span>{formatDate(item.created_at)}</span>}
          </div>
        </div>
        <button
          onClick={() => onDelete(item.id)}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500"
          aria-label="删除知识条目"
        >
          <Trash2 size={15} />
        </button>
      </div>
      {item.summary ? (
        <p className="line-clamp-3 text-sm leading-6 text-slate-600">{item.summary}</p>
      ) : (
        <p className="text-sm leading-6 text-slate-400">这条知识暂时没有摘要。</p>
      )}
      {item.tags && item.tags.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {item.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-cyan-50 px-2 py-0.5 text-xs text-cyan-700">
              #{tag}
            </span>
          ))}
        </div>
      )}
    </article>
  )
}
```

- [ ] **Step 2: Run the frontend build**

Run:

```powershell
pnpm.cmd build
```

Expected: TypeScript and Vite build pass. If Tailwind does not include `line-clamp-3`, replace it with `max-h-[4.5rem] overflow-hidden` and rerun the command.

- [ ] **Step 3: Commit Task 4**

```powershell
git add frontend/src/pages/KnowledgePage.tsx
git commit -m "feat: redesign Prism knowledge workbench"
```

## Task 5: Verify the Frontend Redesign

**Files:**
- No planned source changes.
- Generated build files must stay uncommitted because `dist/` is ignored.

- [ ] **Step 1: Run the frontend production build**

Run:

```powershell
pnpm.cmd build
```

Expected: `tsc -b && vite build` completes with Vite asset output and no TypeScript errors.

- [ ] **Step 2: Run backend and engine regression tests**

Run from the repo root:

```powershell
python -m pytest backend engine
```

Expected: existing backend and engine tests pass. These tests are regression coverage only because this plan does not modify backend or engine behavior.

- [ ] **Step 3: Start the frontend dev server for visual review**

Run from `frontend`:

```powershell
pnpm.cmd dev -- --host 127.0.0.1
```

Expected: Vite prints a local URL, usually `http://127.0.0.1:5173/`.

- [ ] **Step 4: Manually check desktop layout**

Open the Vite URL at a desktop width and verify:

- Sidebar is dark and fixed-width.
- Chat and Knowledge navigation items are visible and active states work.
- Chat page empty state, prompt chips, input card, and clear button render without overlap.
- Knowledge page header, URL row, create-note form, and cards render without overlap.

- [ ] **Step 5: Manually check mobile layout**

Use the browser responsive viewport around `390x844` and verify:

- Mobile header is visible.
- Menu button opens the dark navigation panel.
- Chat input remains usable.
- Knowledge action buttons wrap without text overflow.
- Card grid collapses to one column.

- [ ] **Step 6: Final commit if verification required small fixes**

If verification required code changes, commit only those files:

```powershell
git add frontend/src/index.css frontend/src/layouts/MainLayout.tsx frontend/src/pages/ChatPage.tsx frontend/src/pages/KnowledgePage.tsx
git commit -m "fix: polish Prism frontend responsive states"
```

If verification required no code changes, do not create an empty commit.
