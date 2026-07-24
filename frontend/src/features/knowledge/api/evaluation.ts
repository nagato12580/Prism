// Evaluation datasets and runs against the real Backend evaluation routes.

import { requestJSON, requestBlob } from './client'

export interface EvaluationDatasetSummary {
  id: number
  dataset_uid: string
  name: string
  source: string
  item_count: number
}

export interface EvaluationDatasetCreated {
  id: number
  dataset_uid: string
  name: string
  item_count: number
}

export interface EvaluationItemInput {
  query: string
  gold_chunk_uids?: string[]
  gold_answer?: string | null
}

export interface EvaluationRunConfig {
  mode?: 'fast' | 'deep'
  top_k?: number
  graph_hops?: number | null
  timeout_seconds?: number
}

export interface EvaluationRun {
  id: number
  run_uid: string
  dataset_id: number
  model: string | null
  config: EvaluationRunConfig
  retrieval_config: Record<string, unknown> | null
  embedding_profile: Record<string, unknown> | null
  graph_config: Record<string, unknown> | null
  index_generation: string | null
  graph_generation: string | null
  status: string
  progress_current: number
  progress_total: number
  metrics: Record<string, unknown> | null
}

export interface EvaluationRunItem {
  id: number
  ordinal: number
  query: string
  status: string
  evidence: unknown
  metrics: Record<string, unknown> | null
  error_message: string | null
}

export interface EvaluationRunDetail extends EvaluationRun {
  items: EvaluationRunItem[]
  items_total: number
  next_cursor: string | null
}

export const evaluationApi = {
  listDatasets(kbUid: string): Promise<EvaluationDatasetSummary[]> {
    return requestJSON<EvaluationDatasetSummary[]>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-datasets`,
    )
  },

  importDataset(kbUid: string, name: string, items: EvaluationItemInput[]): Promise<EvaluationDatasetCreated> {
    // Build NDJSON lines server-side expects as the `jsonl` string field.
    const jsonl = items.map((i) => JSON.stringify(i)).join('\n')
    return requestJSON<EvaluationDatasetCreated>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-datasets/import`,
      { method: 'POST', body: JSON.stringify({ name, jsonl }) },
    )
  },

  createGeneratedDataset(kbUid: string, name: string, items: EvaluationItemInput[]): Promise<EvaluationDatasetCreated> {
    return requestJSON<EvaluationDatasetCreated>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-datasets/generated`,
      { method: 'POST', body: JSON.stringify({ name, items }) },
    )
  },

  exportDataset(kbUid: string, datasetUid: string) {
    // NDJSON stream
    return requestBlob(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-datasets/${encodeURIComponent(datasetUid)}/export`,
    )
  },

  listRuns(kbUid: string): Promise<EvaluationRun[]> {
    return requestJSON<EvaluationRun[]>(`/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-runs`)
  },

  getRun(kbUid: string, runUid: string, params?: { cursor?: number; limit?: number }): Promise<EvaluationRunDetail> {
    const qs = new URLSearchParams()
    if (params?.cursor != null) qs.set('cursor', String(params.cursor))
    if (params?.limit != null) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return requestJSON<EvaluationRunDetail>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-runs/${encodeURIComponent(runUid)}${suffix}`,
    )
  },

  createRun(
    kbUid: string,
    datasetUid: string,
    config: EvaluationRunConfig,
    opts?: { model?: string | null; idempotency_key?: string },
  ): Promise<EvaluationRun> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (opts?.idempotency_key) headers['Idempotency-Key'] = opts.idempotency_key
    return requestJSON<EvaluationRun>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-runs`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          dataset_uid: datasetUid,
          model: opts?.model ?? null,
          idempotency_key: opts?.idempotency_key ?? null,
          config,
        }),
      },
    )
  },

  cancelRun(kbUid: string, runUid: string): Promise<EvaluationRun> {
    return requestJSON<EvaluationRun>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-runs/${encodeURIComponent(runUid)}/cancel`,
      { method: 'POST' },
    )
  },

  deleteRun(kbUid: string, runUid: string): Promise<void> {
    return requestJSON<void>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/evaluation-runs/${encodeURIComponent(runUid)}`,
      { method: 'DELETE' },
    )
  },
}
