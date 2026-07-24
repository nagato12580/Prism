// Citations against the real Backend `/citations` routes.
//
// The backend persists citations and returns public IDs. We use this to persist
// a chat-run evidence reference so a citation can be reopened later. We do NOT
// invent a client-side CitationRegistry: the backend is the source of truth.

import { requestJSON } from './client'

export interface CitationCreate {
  kb_uid: string
  file_uid?: string | null
  chunk_uid?: string | null
  citation_text?: string | null
}

export interface Citation {
  id: string
  kb_uid: string
  file_uid: string | null
  chunk_uid: string | null
  citation_text: string | null
  created_at?: string | null
}

export const citationsApi = {
  create(data: CitationCreate): Promise<Citation> {
    return requestJSON<Citation>('/citations', { method: 'POST', body: JSON.stringify(data) })
  },

  get(citationId: string): Promise<Citation> {
    return requestJSON<Citation>(`/citations/${encodeURIComponent(citationId)}`)
  },
}
