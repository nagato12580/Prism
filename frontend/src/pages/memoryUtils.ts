import type { MemoryEntry } from '@/app/api'

export const memoryTypeMeta: Record<string, { label: string; tone: string; short: string }> = {
  preference: { label: '偏好', short: 'P', tone: 'border-blue-100 bg-blue-50 text-blue-700' },
  goal: { label: '目标', short: 'G', tone: 'border-emerald-100 bg-emerald-50 text-emerald-700' },
  fact: { label: '事实', short: 'F', tone: 'border-violet-100 bg-violet-50 text-violet-700' },
  context: { label: '上下文', short: 'C', tone: 'border-amber-100 bg-amber-50 text-amber-700' },
}

export function getMemoryMeta(type: string) {
  return memoryTypeMeta[type] ?? { label: type || '记忆', short: 'M', tone: 'border-slate-200 bg-slate-100 text-slate-600' }
}

export function groupMemories(items: MemoryEntry[]) {
  return items.reduce<Record<string, MemoryEntry[]>>((groups, item) => {
    const key = item.memory_type || 'context'
    groups[key] = [...(groups[key] ?? []), item]
    return groups
  }, {})
}

export function importantTags(items: MemoryEntry[], limit = 8) {
  const counts = new Map<string, number>()
  for (const item of items) {
    for (const tag of item.tags ?? []) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1)
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
}

export function formatDate(value: string) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value))
}
