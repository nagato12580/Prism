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
  ingestResource: (id: string) =>
    request<KnowledgeResource>(`/knowledge/resources/${id}/ingest`, { method: 'POST' }),
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

// ── Wiki types ────────────────────────────────────────────────

export interface WikiDocument {
  id: string
  file_id: string
  status: string
  extract_stage: string
  progress_current: number
  progress_total: number
  user_id: string
  created_at: string
  original_filename?: string | null
  mime_type?: string | null
  file_size?: number | null
}

export interface WikiDocumentDetail extends WikiDocument {
  logs: WikiExtractionLog[]
}

export interface WikiKnowledgePoint {
  id: string
  document_id: string
  title: string
  description?: string | null
  content?: string | null
  category: string
  tags: string
  aliases: string
  group_name: string
  status: string
  images?: string | null
  user_id: string
  created_at: string
}

export interface WikiKnowledgePointListItem {
  id: string
  document_id: string
  title: string
  description?: string | null
  category: string
  tags: string
  status: string
  created_at: string
}

export interface WikiKnowledgeRelation {
  id: string
  from_point_id: string
  to_point_id: string
  type: string
  confidence: number
  created_at: string
  from_title?: string | null
  to_title?: string | null
}

export interface WikiExtractionLog {
  id: string
  document_id: string
  stage: string
  message: string
  status: string
  progress_current: number
  progress_total: number
  created_at: string
}

// ── Wiki API functions ────────────────────────────────────────

export async function fetchWikiDocuments(): Promise<WikiDocument[]> {
  return request('/wiki/documents')
}

export async function fetchWikiDocument(id: string): Promise<WikiDocumentDetail> {
  return request(`/wiki/documents/${id}`)
}

export async function deleteWikiDocument(id: string): Promise<void> {
  await request(`/wiki/documents/${id}`, { method: 'DELETE' })
}

export async function fetchWikiPoints(docId?: string): Promise<WikiKnowledgePointListItem[]> {
  const params = docId ? `?doc_id=${encodeURIComponent(docId)}` : ''
  return request(`/wiki/points${params}`)
}

export async function fetchWikiPoint(id: string): Promise<WikiKnowledgePoint> {
  return request(`/wiki/points/${id}`)
}

export async function fetchWikiPointRelations(id: string): Promise<WikiKnowledgeRelation[]> {
  return request(`/wiki/points/${id}/relations`)
}

export async function uploadWikiFile(file: File): Promise<{ file_id: string; wiki_doc_id: string; status: string }> {
  const form = new FormData()
  form.append('file', file)
  return uploadRequest('/upload/wiki', form)
}

export async function triggerWikiExtraction(docId: string): Promise<{ doc_id: string; status: string }> {
  return request('/wiki/extract', {
    method: 'POST',
    body: JSON.stringify({ doc_id: docId }),
  })
}

// ── Inbox types ────────────────────────────────────────────────

export type InboxKind = 'knowledge' | 'opinion' | 'resource' | 'task' | 'memory' | 'idea' | 'chat'
export type InboxAction = 'make_wiki' | 'save_note' | 'save_resource' | 'remember' | 'review_later' | 'ignore'

export interface InboxRawItem {
  id: string
  user_id: string
  title: string
  content: string
  source_type: string
  source_url: string
  source_platform: string
  status: string
  created_at: string
  updated_at: string
}

export interface InboxReview {
  id: string
  raw_item_id: string
  user_id: string
  kind: InboxKind
  title: string
  summary?: string | null
  suggested_action: InboxAction
  category: string
  tags: string[]
  rationale?: string | null
  confidence: number
  status: string
  settled_type: string
  settled_ref_id: string
  created_at: string
  updated_at: string
  raw_item?: InboxRawItem | null
}

export interface NotebookNote {
  id: string
  user_id: string
  title: string
  content?: string | null
  note_type: string
  category: string
  tags: string[]
  source_raw_item_id: string
  source_review_id: string
  created_at: string
  updated_at: string
}

export interface MemoryEntry {
  id: string
  user_id: string
  title: string
  content: string
  memory_type: string
  category: string
  tags: string[]
  importance: number
  source_raw_item_id: string
  source_review_id: string
  created_at: string
  updated_at: string
}

export const inboxApi = {
  createItem: (data: {
    content: string
    title?: string
    source_type?: string
    source_url?: string
    source_platform?: string
    classify?: boolean
  }) =>
    request<{ item: InboxRawItem; review?: InboxReview | null }>('/inbox/items', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listReviews: (params?: { status?: string; kind?: string }) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<InboxReview[]>(`/inbox/reviews${qs}`)
  },
  approveReview: (id: string) =>
    request<{ review: InboxReview; settled_type: string; settled_ref_id: string }>(
      `/inbox/reviews/${id}/approve`,
      { method: 'POST' },
    ),
  rejectReview: (id: string) =>
    request<InboxReview>(`/inbox/reviews/${id}/reject`, { method: 'POST' }),
  listNotes: () => request<NotebookNote[]>('/inbox/notes'),
  listMemories: () => request<MemoryEntry[]>('/inbox/memories'),
}

// ── Personal Asset types ─────────────────────────────────────

export interface AssetDraft {
  id: string
  raw_item_id?: string | null
  user_id: string
  title: string
  summary?: string | null
  asset_kind: string
  source_type: string
  source_platform: string
  source_url: string
  media_type: string
  category: string
  tags: string[]
  extracts: Array<Record<string, unknown>>
  suggested_relations: Array<Record<string, unknown>>
  suggested_extensions: Array<Record<string, unknown>>
  confidence: Record<string, unknown>
  rationale?: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface PersonalAsset {
  id: string
  user_id: string
  asset_kind: string
  title: string
  body?: string | null
  summary?: string | null
  category: string
  tags: string[]
  source_type: string
  source_platform: string
  source_url: string
  media_type: string
  extra_meta: Record<string, unknown>
  capabilities: string[]
  source_raw_item_id: string
  source_draft_id: string
  source_ref_type: string
  source_ref_id: string
  importance: number
  status: string
  created_at: string
  updated_at: string
}

export interface AssetSearchResult {
  asset_id: string
  asset_kind: string
  title: string
  summary?: string | null
  source_type: string
  source_platform: string
  tags: string[]
  category: string
  score: number
}

export interface AssetOverview {
  summary: string
  categories: Array<Record<string, unknown>>
  tags: Array<Record<string, unknown>>
  representative_assets: AssetSearchResult[]
}

export interface KnowledgeDraft {
  id: string
  user_id: string
  title: string
  content?: string | null
  summary?: string | null
  category: string
  tags: string[]
  source_asset_ids: string[]
  outline: Array<Record<string, unknown>>
  confidence: Record<string, unknown>
  rationale?: string | null
  status: string
  knowledge_item_id: string
  created_at: string
  updated_at: string
}

export const assetApi = {
  createDraft: (data: {
    raw_item_id?: string
    content?: string
    title?: string
    source_type?: string
    source_platform?: string
    source_url?: string
  }) =>
    request<AssetDraft>('/assets/drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listDrafts: (params?: { status?: string }) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<AssetDraft[]>(`/assets/drafts${qs}`)
  },
  updateDraft: (id: string, data: Partial<AssetDraft>) =>
    request<AssetDraft>(`/assets/drafts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  confirmDraft: (
    id: string,
    data?: {
      confirm_relations?: Array<Record<string, unknown>>
      confirm_extensions?: Array<Record<string, unknown>>
      create_memory?: boolean
    },
  ) =>
    request<{ draft: AssetDraft; asset: PersonalAsset; relation_count: number; extension_count: number }>(
      `/assets/drafts/${id}/confirm`,
      {
        method: 'POST',
        body: JSON.stringify(data ?? {}),
      },
    ),
  listAssets: () => request<PersonalAsset[]>('/assets'),
  search: (q: string, limit?: number) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (limit) params.set('limit', String(limit))
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request<AssetSearchResult[]>(`/assets/search${qs}`)
  },
  overview: (q: string, limit?: number) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (limit) params.set('limit', String(limit))
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request<AssetOverview>(`/assets/overview${qs}`)
  },
  createKnowledgeDraft: (data: { asset_ids: string[]; title?: string; instruction?: string }) =>
    request<KnowledgeDraft>('/assets/knowledge-drafts', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  listKnowledgeDrafts: (params?: { status?: string }) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return request<KnowledgeDraft[]>(`/assets/knowledge-drafts${qs}`)
  },
  getKnowledgeDraft: (id: string) =>
    request<KnowledgeDraft>(`/assets/knowledge-drafts/${id}`),
  updateKnowledgeDraft: (id: string, data: Partial<KnowledgeDraft>) =>
    request<KnowledgeDraft>(`/assets/knowledge-drafts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  confirmKnowledgeDraft: (id: string, data?: { ingest?: boolean }) =>
    request<{ draft: KnowledgeDraft; knowledge_item_id: string }>(`/assets/knowledge-drafts/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify(data ?? {}),
    }),
}

// ── Knowledge governance graph ───────────────────────────────

export type KnowledgeGraphNodeType = 'canonical' | 'pku' | 'asset' | 'document_chunk'
export type KnowledgeGraphEdgeType = 'canonical_pku' | 'pku_source'

export interface KnowledgeGraphNode {
  id: string
  type: KnowledgeGraphNodeType
  label: string
  ref_id?: string
  statement?: string
  summary?: string | null
  text?: string | null
  source_kind?: string
  source_id?: string
  canonical_type?: string
  unit_type?: string
  modality?: string
  role?: string
  confidence?: number
  category?: string | null
  tags?: string[]
  keywords?: string[]
  source_platform?: string
}

export interface KnowledgeGraphEdge {
  id: string
  source: string
  target: string
  type: KnowledgeGraphEdgeType
  label: string
  role?: string
  confidence?: number
  source_kind?: string
}

export interface KnowledgeGraphPayload {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  stats: {
    node_count: number
    edge_count: number
    node_counts: Record<string, number>
    edge_counts: Record<string, number>
  }
}

export const knowledgeGraphApi = {
  get: (params?: { q?: string; limit?: number }) => {
    const search = new URLSearchParams()
    if (params?.q) search.set('q', params.q)
    if (params?.limit) search.set('limit', String(params.limit))
    const qs = search.toString() ? `?${search.toString()}` : ''
    return request<KnowledgeGraphPayload>(`/knowledge-graph${qs}`)
  },
}
