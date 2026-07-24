// Public knowledge system API contracts.
//
// Every type below mirrors the REAL backend response field names produced by:
//   backend/app/schemas/knowledge.py   (KnowledgeRetrievalResponse / PublicEvidence)
//   backend/app/api/knowledge_bases.py (KnowledgeBaseResponse)
//   backend/app/api/knowledge_files.py (_public_file dict)
//   backend/app/api/knowledge_enrichment.py (mindmap / sample questions / evaluation / export)
//
// `parseEvidence` constructs a new object from an allow-list of public keys and
// never spreads server data, so private fields (storage_uri, tenant_id, ...) can
// never leak into the UI even if a future backend change adds them.

export type RetrievalStatus =
  | 'ok'
  | 'no_hits'
  | 'degraded'
  | 'unavailable'
  | 'invalid_request'

export type StageStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'stale'
  | 'skipped'

export type RetrievalChannel = 'dense' | 'bm25' | 'graph'

export interface ChannelScore {
  raw_score: number
  raw_rank: number
}

export interface ChannelProblem {
  code: string
  message: string
  retryable: boolean
}

// The retrieval query uses `mode: "fast" | "deep"` (backend schema).
export type RetrievalMode = 'fast' | 'deep'

export interface RetrievalFilters {
  file_uids: string[]
  source_types: string[]
}

export interface RetrievalConfig {
  top_k: number
  graph_hops: number | null
}

// Public Evidence DTO. `evidence_id` is `null` in the current backend response
// (PublicEvidence sets it to None), so it is optional here.
export interface Evidence {
  evidence_id?: string | null
  kb_uid: string
  file_uid: string
  item_id?: string | null
  chunk_uid: string
  parent_chunk_uid?: string | null
  display_title: string
  original_filename?: string | null
  excerpt: string
  page_start?: number | null
  page_end?: number | null
  char_start?: number | null
  char_end?: number | null
  channel_scores: Record<string, ChannelScore>
  rrf_score: number
  rerank_score?: number | null
  rerank_model?: string | null
  retrieval_channels: RetrievalChannel[]
  graph_path: Record<string, unknown>[]
  graph_explanation?: string | null
  evidence_type: 'chunk' | 'graph_path' | 'entity'
  index_generation: string
  degradation_flags: string[]
}

export interface RetrievalResponse {
  status: 'ok' | 'no_hits' | 'degraded'
  evidence: Evidence[]
  warnings: ChannelProblem[]
}

const EVIDENCE_KEYS: ReadonlyArray<keyof Evidence> = [
  'evidence_id',
  'kb_uid',
  'file_uid',
  'item_id',
  'chunk_uid',
  'parent_chunk_uid',
  'display_title',
  'original_filename',
  'excerpt',
  'page_start',
  'page_end',
  'char_start',
  'char_end',
  'channel_scores',
  'rrf_score',
  'rerank_score',
  'rerank_model',
  'retrieval_channels',
  'graph_path',
  'graph_explanation',
  'evidence_type',
  'index_generation',
  'degradation_flags',
]

// Build a clean Evidence from raw server data using an allow-list. Unknown/
// private keys (storage_uri, tenant_id, file_path, ...) are dropped.
export function parseEvidence(raw: Record<string, unknown>): Evidence {
  const out = {} as Record<string, unknown>
  for (const key of EVIDENCE_KEYS) {
    if (key in raw) {
      out[key] = raw[key]
    }
  }
  return out as unknown as Evidence
}

export function parseEvidenceList(raw: unknown): Evidence[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => parseEvidence(item as Record<string, unknown>))
}

const RETRIEVAL_STATUS_LABEL: Record<RetrievalStatus, string> = {
  ok: '检索完成',
  no_hits: '未找到证据',
  degraded: '部分检索通道不可用',
  unavailable: '检索服务不可用',
  invalid_request: '检索请求无效',
}

export function retrievalStatusLabel(status: RetrievalStatus): string {
  return RETRIEVAL_STATUS_LABEL[status] ?? status
}

const CHANNEL_SCORE_LABEL: Record<string, string> = {
  dense: 'Dense 原始分数',
  bm25: 'BM25 原始分数',
  graph: 'Graph 原始分数',
  rerank: 'Rerank 分数',
}

// Label a channel score by its native retrieval meaning; never wrap the raw
// number as a synthetic "match percentage".
export function channelScoreLabel(channel: string): string {
  return CHANNEL_SCORE_LABEL[channel] ?? `${channel} 原始分数`
}
