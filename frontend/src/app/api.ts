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

async function uploadRequest<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'POST', body: form })
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

export type ResourceMediaType = 'document' | 'image' | 'audio' | 'video'
export type ResourceFilterType = 'all' | ResourceMediaType

export interface KnowledgeTopic {
  id: string
  user_id: string
  name: string
  description?: string | null
  created_at: string
  updated_at: string
  resource_count: number
}

export interface KnowledgeResource {
  id: string
  user_id: string
  topic_id?: string | null
  item_id?: string | null
  title: string
  original_filename: string
  media_type: ResourceMediaType
  mime_type?: string | null
  file_ext: string
  file_size: number
  md5: string
  storage_path: string
  processing_status: string
  description?: string | null
  tags?: string[] | null
  source_type: string
  page_count?: number | null
  content_text?: string | null
  uploaded_at: string
  last_modified_at: string
  created_at: string
  updated_at: string
  error_message?: string | null
}

// ── Chat types ────────────────────────────────────────────────

export interface ChatSessionOut {
  id: string
  title: string
  user_id: string
  topic_id?: string | null
  source_types?: ResourceMediaType[] | null
  created_at: string
  updated_at: string
}

export interface ChatMessageOut {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string | null
  sources: any[] | null
  clarify: any | null
  created_at: string
}

export interface ChatSessionCreate {
  title?: string
  topic_id?: string | null
  source_types?: string[] | null
}

export interface ChatSessionUpdate {
  title?: string
  topic_id?: string | null
  source_types?: string[] | null
}

export interface ChatMessageCreate {
  role: 'user' | 'assistant'
  content: string
  sources?: any[] | null
  clarify?: any | null
}

export const chatApi = {
  listSessions: () =>
    request<ChatSessionOut[]>('/chat/sessions'),

  createSession: (data: ChatSessionCreate) =>
    request<ChatSessionOut>('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateSession: (id: string, data: ChatSessionUpdate) =>
    request<ChatSessionOut>(`/chat/sessions/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteSession: (id: string) =>
    request<{ detail: string }>(`/chat/sessions/${id}`, { method: 'DELETE' }),

  generateTitle: (id: string) =>
    request<ChatSessionOut>(`/chat/sessions/${id}/generate-title`, {
      method: 'POST',
    }),

  listMessages: (sessionId: string) =>
    request<ChatMessageOut[]>(`/chat/sessions/${sessionId}/messages`),

  addMessage: (sessionId: string, data: ChatMessageCreate) =>
    request<ChatMessageOut>(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
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
  listTopics: () => request<KnowledgeTopic[]>('/knowledge/topics'),
  createTopic: (data: Pick<KnowledgeTopic, 'name'> & { description?: string }) =>
    request<KnowledgeTopic>('/knowledge/topics', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateTopic: (id: string, data: Partial<Pick<KnowledgeTopic, 'name' | 'description'>>) =>
    request<KnowledgeTopic>(`/knowledge/topics/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteTopic: (id: string) =>
    request<{ detail: string }>(`/knowledge/topics/${id}`, { method: 'DELETE' }),
  listResources: (topicId: string, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<KnowledgeResource[]>(`/knowledge/topics/${topicId}/resources${qs}`)
  },
  uploadResource: async (
    topicId: string,
    file: File,
    options?: { description?: string; tags?: string[] },
  ): Promise<KnowledgeResource> => {
    const form = new FormData()
    form.append('file', file)
    if (options?.description) form.append('description', options.description)
    if (options?.tags?.length) form.append('tags', options.tags.join(','))
    return uploadRequest<KnowledgeResource>(`/knowledge/topics/${topicId}/resources`, form)
  },
  updateResource: (id: string, data: Partial<Pick<KnowledgeResource, 'title'>>) =>
    request<KnowledgeResource>(`/knowledge/resources/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteResource: (id: string) =>
    request<{ detail: string }>(`/knowledge/resources/${id}`, { method: 'DELETE' }),
  uploadFile: async (file: File, category?: string): Promise<KnowledgeItem> => {
    const form = new FormData()
    form.append('file', file)
    if (category) form.append('category', category)
    return uploadRequest<KnowledgeItem>('/upload/file', form)
  },
  uploadUrl: async (url: string, category?: string): Promise<KnowledgeItem> => {
    const form = new FormData()
    form.append('url', url)
    if (category) form.append('category', category)
    return uploadRequest<KnowledgeItem>('/upload/url', form)
  },
}
