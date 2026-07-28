// Files against the real Backend `/knowledge-bases/{kb_uid}/files` routes.
//
// The public file projection is a plain dict from `_public_file()` with exactly
// these keys (verified verbatim from backend/app/api/knowledge_files.py).

import { requestJSON, requestUpload, requestBlob } from './client'
import type { KnowledgeJobSnapshot } from './jobs'

export interface StageError {
  code?: string
  message?: string
}

export interface KnowledgeFile {
  file_uid: string
  kb_uid: string
  original_filename: string
  relative_path: string
  media_type: string
  mime_type: string
  parse_status: string
  index_status: string
  graph_status: string
  parse_error: StageError | null
  index_error: StageError | null
  last_job_id: string | null
  content_sha256: string
  size_bytes: number
  preview_url: string
  download_url: string
  source_kind?: string | null
  source_id?: string | null
  system_type?: string | null
}

export interface KnowledgeFileListResponse {
  items: KnowledgeFile[]
  total: number
  next_cursor: string | null
}

export interface UploadFileResponse {
  file: KnowledgeFile
  job: Pick<KnowledgeJobSnapshot, 'id' | 'job_type' | 'status'>
}

export interface FilePreview {
  file_uid: string
  content: string
}

export interface FileMetadataUpdate {
  title?: string
  relative_path?: string
}

export interface FileListParams {
  cursor?: string
  limit?: number
  relative_path?: string
  media_type?: string
  parse_status?: string
  index_status?: string
  graph_status?: string
}

export const filesApi = {
  list(kbUid: string, params?: FileListParams): Promise<KnowledgeFileListResponse> {
    const qs = new URLSearchParams()
    if (params?.cursor) qs.set('cursor', params.cursor)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.relative_path) qs.set('relative_path', params.relative_path)
    if (params?.media_type) qs.set('media_type', params.media_type)
    if (params?.parse_status) qs.set('parse_status', params.parse_status)
    if (params?.index_status) qs.set('index_status', params.index_status)
    if (params?.graph_status) qs.set('graph_status', params.graph_status)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return requestJSON<KnowledgeFileListResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files${suffix}`,
    )
  },

  get(kbUid: string, fileUid: string): Promise<KnowledgeFile> {
    return requestJSON<KnowledgeFile>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}`,
    )
  },

  upload(
    kbUid: string,
    file: File,
    opts?: { relative_path?: string; auto_index?: boolean },
  ): Promise<UploadFileResponse> {
    const form = new FormData()
    form.append('file', file)
    if (opts?.relative_path) form.append('relative_path', opts.relative_path)
    // Backend expects a string "true"/"false" for auto_index.
    form.append('auto_index', opts?.auto_index ? 'true' : 'false')
    return requestUpload<UploadFileResponse>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files`,
      form,
    )
  },

  update(kbUid: string, fileUid: string, data: FileMetadataUpdate): Promise<KnowledgeFile> {
    return requestJSON<KnowledgeFile>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}`,
      { method: 'PATCH', body: JSON.stringify(data) },
    )
  },

  preview(kbUid: string, fileUid: string): Promise<FilePreview> {
    // Backend returns a single `content` field (raw stored text).
    return requestJSON<FilePreview>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}/preview`,
    )
  },

  download(kbUid: string, fileUid: string) {
    return requestBlob(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}/download`,
    )
  },

  parse(kbUid: string, fileUid: string): Promise<KnowledgeJobSnapshot> {
    return requestJSON<KnowledgeJobSnapshot>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}/parse`,
      { method: 'POST' },
    )
  },

  index(kbUid: string, fileUid: string): Promise<KnowledgeJobSnapshot> {
    return requestJSON<KnowledgeJobSnapshot>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}/index`,
      { method: 'POST' },
    )
  },

  remove(kbUid: string, fileUid: string): Promise<KnowledgeJobSnapshot> {
    return requestJSON<KnowledgeJobSnapshot>(
      `/knowledge-bases/${encodeURIComponent(kbUid)}/files/${encodeURIComponent(fileUid)}`,
      { method: 'DELETE' },
    )
  },
}
