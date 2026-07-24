// Shared fetch client for the public Backend knowledge API.
//
// All domain modules call only `/api/v1/...` Backend paths. The client parses
// the backend's shared error envelope and throws `ApiProblem`. It handles JSON,
// 204 No Content, and binary/ZIP responses without logging response bodies.

import type { Evidence } from './contracts'
import { parseEvidence } from './contracts'

const API_BASE = '/api/v1'

// Typed error for the backend's shared error envelope:
//   { error: { code, message, retryable, details, trace_id } }
export class ApiProblem extends Error {
  readonly status: number
  readonly code: string
  readonly retryable: boolean
  readonly traceId: string
  readonly details: Record<string, unknown>

  constructor(
    status: number,
    code: string,
    message: string,
    retryable = false,
    traceId = '',
    details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiProblem'
    this.status = status
    this.code = code
    this.retryable = retryable
    this.traceId = traceId
    this.details = details
  }

  // True for access errors (forbidden / not found) that should not be retried.
  isAccessError(): boolean {
    return this.status === 403 || this.status === 404
  }
}

// Merge caller headers with defaults into a plain record. We keep a single
// place for future auth-token injection; never hardcode default-user here.
function buildHeaders(
  defaults: Record<string, string>,
  init?: HeadersInit,
): Record<string, string> {
  const out: Record<string, string> = { ...defaults }
  if (!init) return out
  const list = init instanceof Headers ? Array.from(init.entries()) : (Array.isArray(init) ? init : Object.entries(init))
  for (const [k, v] of list) {
    out[k] = String(v)
  }
  return out
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
    retryable?: boolean
    details?: Record<string, unknown>
    trace_id?: string
  }
}

async function readErrorEnvelope(resp: Response): Promise<ApiProblem> {
  const status = resp.status
  let code = `HTTP_${status}`
  let message = resp.statusText || `请求失败 (${status})`
  let retryable = status >= 500
  let traceId = ''
  let details: Record<string, unknown> = {}

  try {
    const body = (await resp.json()) as ErrorEnvelope
    if (body?.error) {
      if (body.error.code) code = body.error.code
      if (body.error.message) message = body.error.message
      if (typeof body.error.retryable === 'boolean') retryable = body.error.retryable
      if (body.error.trace_id) traceId = body.error.trace_id
      if (body.error.details) details = body.error.details
    } else {
      // Some legacy endpoints return { detail: ... } (HTTPException).
      const legacy = body as { detail?: unknown }
      if (typeof legacy.detail === 'string') {
        message = legacy.detail
      } else if (legacy.detail && typeof legacy.detail === 'object') {
        const d = legacy.detail as { code?: string; message?: string }
        if (d.code) code = d.code
        if (d.message) message = d.message
      }
    }
  } catch {
    // Non-JSON body: keep the status-derived defaults.
  }

  const headerTrace = resp.headers.get('X-Trace-ID')
  if (!traceId && headerTrace) traceId = headerTrace

  return new ApiProblem(status, code, message, retryable, traceId, details)
}

// Perform a JSON request and return parsed JSON. Throws ApiProblem on !ok.
export async function requestJSON<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders({ 'Content-Type': 'application/json' }, options?.headers),
  })
  if (!resp.ok) {
    throw await readErrorEnvelope(resp)
  }
  if (resp.status === 204) {
    return undefined as T
  }
  return (await resp.json()) as T
}

// Perform a multipart upload. The caller builds the FormData (no JSON content
// type header, so the browser sets the boundary).
export async function requestUpload<T>(
  path: string,
  form: FormData,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    body: form,
    headers: buildHeaders({}, options?.headers),
    signal: options?.signal,
  })
  if (!resp.ok) {
    throw await readErrorEnvelope(resp)
  }
  return (await resp.json()) as T
}

// Fetch a binary/ZIP/ndjson response as a Blob. Throws ApiProblem on !ok.
export async function requestBlob(
  path: string,
  options?: RequestInit,
): Promise<{ blob: Blob; filename: string | null }> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders({}, options?.headers),
  })
  if (!resp.ok) {
    throw await readErrorEnvelope(resp)
  }
  const blob = await resp.blob()
  const disposition = resp.headers.get('Content-Disposition')
  let filename: string | null = null
  if (disposition) {
    const match = /filename="?([^";]+)"?/.exec(disposition)
    if (match) filename = match[1]
  }
  return { blob, filename }
}

// Convenience: parse a single Evidence object via the allow-list.
export function toEvidence(raw: unknown): Evidence {
  return parseEvidence(raw as Record<string, unknown>)
}

export { parseEvidence }
