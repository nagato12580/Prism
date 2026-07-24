// Mindmap, sample questions and export against the real Backend enrichment routes.
//
// `generate` requires an idempotency_key. Cancel is only available for
// mindmap_generation / sample_questions_generation jobs.

import { requestJSON, requestBlob, ApiProblem } from './client'
import type { EnrichmentJobDto } from './jobs'

export interface MindmapResponse {
  mindmap: Record<string, unknown>
}

export interface MindmapUpdateResponse {
  mindmap: Record<string, unknown> | null
  job: EnrichmentJobDto | null
}

export interface SampleQuestionsResponse {
  sample_questions: Record<string, unknown>
}

export interface GenerationRequest {
  model?: string | null
  prompt_version?: string
  idempotency_key: string
}

export interface GenerationResponse {
  job: EnrichmentJobDto
}

export const enrichmentApi = {
  getMindmap(kbUid: string): Promise<MindmapResponse> {
    return requestJSON<MindmapResponse>(`/knowledge-bases/${encodeURIComponent(kbUid)}/mindmap`)
  },

  generateMindmap(kbUid: string, req: GenerationRequest): Promise<GenerationResponse> {
    return requestJSON<GenerationResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/mindmap/generate`,
      { method: 'POST', body: JSON.stringify(req) },
    )
  },

  getSampleQuestions(kbUid: string): Promise<SampleQuestionsResponse> {
    return requestJSON<SampleQuestionsResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/sample-questions`,
    )
  },

  generateSampleQuestions(kbUid: string, req: GenerationRequest): Promise<GenerationResponse> {
    return requestJSON<GenerationResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/sample-questions/generate`,
      { method: 'POST', body: JSON.stringify(req) },
    )
  },

  cancelEnrichmentJob(kbUid: string, jobId: string): Promise<GenerationResponse> {
    return requestJSON<GenerationResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST' },
    )
  },

  // Safe export: a ZIP stream (config/manifest/markdown/eval/graph facts).
  // No vectors/secrets/absolute paths included.
  exportZip(kbUid: string) {
    return requestBlob(`/knowledge-bases/${encodeURIComponent(kbUid)}/export`)
  },
}

// Helper to trigger a browser download of the export ZIP without exposing the
// blob body in logs.
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export { ApiProblem }
