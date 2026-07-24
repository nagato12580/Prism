// Retrieval against the real Backend `/knowledge-bases/{kb_uid}/retrieval/query`.
//
// The backend accepts `mode: "fast" | "deep"` (NOT "standard"/"deep") and a
// `config` with only `top_k` and `graph_hops`. It returns status in
// {"ok","no_hits","degraded"}; "unavailable"/"invalid_request" are returned as
// an HTTP error envelope (ApiProblem) by the backend, not as a body status.

import { requestJSON, ApiProblem } from './client'
import {
  parseEvidence,
  type Evidence,
  type ChannelProblem,
  type RetrievalConfig,
  type RetrievalMode,
} from './contracts'

export interface RetrievalResultBody {
  status: 'ok' | 'no_hits' | 'degraded'
  evidence: Evidence[]
  warnings: ChannelProblem[]
}

export interface RetrievalQuery {
  query: string
  mode?: RetrievalMode
  filters?: { file_uids?: string[]; source_types?: string[] }
  config?: Partial<RetrievalConfig>
}

export interface RetrievalResult extends RetrievalResultBody {
  httpStatus: number
}

export const retrievalApi = {
  async query(kbUid: string, q: RetrievalQuery): Promise<RetrievalResult> {
    const body = {
      query: q.query,
      mode: q.mode ?? 'fast',
      filters: {
        file_uids: q.filters?.file_uids ?? [],
        source_types: q.filters?.source_types ?? [],
      },
      config: {
        top_k: q.config?.top_k ?? 10,
        graph_hops: q.config?.graph_hops ?? null,
      },
    }
    let resp: Response
    try {
      resp = await fetch(`/api/v1/knowledge-bases/${encodeURIComponent(kbUid)}/retrieval/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch (e) {
      throw new ApiProblem(0, 'NETWORK', '网络连接失败，请检查后端服务', true)
    }
    if (!resp.ok) {
      // Map the backend error envelope into ApiProblem. The backend returns
      // RETRIEVAL_UNAVAILABLE (503) etc., which the UI treats as "unavailable".
      throw await readRetrievalError(resp)
    }
    const json = (await resp.json()) as RetrievalResultBody
    return {
      status: json.status,
      evidence: parseEvidenceList(json.evidence),
      warnings: json.warnings ?? [],
      httpStatus: resp.status, // 200 normally, 206 for degraded
    }
  },
}

function parseEvidenceList(raw: unknown): Evidence[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => parseEvidence(item as Record<string, unknown>))
}

async function readRetrievalError(resp: Response): Promise<ApiProblem> {
  let code = `HTTP_${resp.status}`
  let message = resp.statusText || '检索请求失败'
  let retryable = resp.status >= 500
  let traceId = ''
  try {
    const body = (await resp.json()) as {
      error?: { code?: string; message?: string; retryable?: boolean; trace_id?: string }
    }
    if (body?.error) {
      if (body.error.code) code = body.error.code
      if (body.error.message) message = body.error.message
      if (typeof body.error.retryable === 'boolean') retryable = body.error.retryable
      if (body.error.trace_id) traceId = body.error.trace_id
    }
  } catch {
    // ignore
  }
  return new ApiProblem(resp.status, code, message, retryable, traceId)
}
