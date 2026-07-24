// Durable knowledge jobs.
//
// IMPORTANT: the current backend exposes NO Job SSE / events stream and NO
// KB-level job list or retry route. The only job access is a single pollable
// snapshot:
//   GET /knowledge-bases/{kb_uid}/files/jobs/{job_id}
// returning { id, job_type, status, stage, attempt, error_code }.
// (And the enrichment cancel route for mindmap/sample-question jobs only.)
//
// This module models exactly that real surface. No SSE, no retry endpoint.

import { requestJSON } from './client'

export interface KnowledgeJobSnapshot {
  id: string
  job_type: string
  status: string // queued | claimed | running | succeeded | failed | canceled
  stage: string
  attempt: number
  error_code: string | null
}

export interface EnrichmentJobDto {
  id: string
  job_type: 'mindmap_generation' | 'sample_questions_generation'
  status: string
  stage: string
}

export function isTerminalJobStatus(status: string): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'canceled'
}

export const jobsApi = {
  // Pollable snapshot. Path is /files/jobs/{job_id} (note the /files segment).
  snapshot(kbUid: string, jobId: string): Promise<KnowledgeJobSnapshot> {
    return requestJSON<KnowledgeJobSnapshot>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/jobs/${encodeURIComponent(jobId)}`,
    )
  },
}
