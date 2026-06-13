const BASE = '/api/v1'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const detail = await resp.text()
    throw new Error(detail)
  }
  return resp.json()
}

export interface KnowledgeItem {
  id: string
  title: string
  content?: string
  summary?: string
  source_type: string
  tags?: string[]
  category?: string
  status: string
  created_at: string
}

export const knowledgeApi = {
  list: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<KnowledgeItem[]>(`/knowledge${qs}`)
  },
  get: (id: string) => request<KnowledgeItem>(`/knowledge/${id}`),
  create: (data: Partial<KnowledgeItem>) =>
    request<KnowledgeItem>('/knowledge', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<KnowledgeItem>) =>
    request<KnowledgeItem>(`/knowledge/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    request<{ detail: string }>(`/knowledge/${id}`, { method: 'DELETE' }),
  uploadFile: async (file: File, category?: string): Promise<KnowledgeItem> => {
    const form = new FormData()
    form.append('file', file)
    if (category) form.append('category', category)
    const resp = await fetch(`${BASE}/upload/file`, { method: 'POST', body: form })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
  uploadUrl: async (url: string, category?: string): Promise<KnowledgeItem> => {
    const form = new FormData()
    form.append('url', url)
    if (category) form.append('category', category)
    const resp = await fetch(`${BASE}/upload/url`, { method: 'POST', body: form })
    if (!resp.ok) throw new Error(await resp.text())
    return resp.json()
  },
}
