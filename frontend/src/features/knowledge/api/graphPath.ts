export interface KnowledgeBaseGraphPathParams {
  view?: 'entity' | 'source'
  file_uids?: string[]
  limit?: number
}

export function buildKnowledgeBaseGraphPath(kbUid: string, params?: KnowledgeBaseGraphPathParams): string {
  const search = new URLSearchParams()
  if (params?.view) search.set('view', params.view)
  for (const fileUid of params?.file_uids ?? []) {
    if (fileUid) search.append('file_uids', fileUid)
  }
  if (params?.limit != null) search.set('limit', String(params.limit))
  const qs = search.toString() ? `?${search.toString()}` : ''
  return `/knowledge-bases/${encodeURIComponent(kbUid)}/graph${qs}`
}
