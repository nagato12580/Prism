import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
function read(rel) {
  return readFileSync(resolve(root, rel), 'utf8')
}

test('FileUploadPanel bounds concurrent uploads and preserves relative paths', () => {
  const src = read('src/features/knowledge/components/FileUploadPanel.tsx')
  // Bounded concurrency (4 workers).
  assert.match(src, /MAX_CONCURRENT\s*=\s*4/)
  // One request per file with an AbortController.
  assert.match(src, /new AbortController/)
  assert.match(src, /filesApi\.upload\(/)
  // relative_path from webkitRelativePath is sent (directory upload).
  assert.match(src, /webkitRelativePath/)
  assert.match(src, /relative_path/)
})

test('DocumentDrawer is read-only and uses the single preview content endpoint', () => {
  const src = read('src/features/knowledge/components/DocumentDrawer.tsx')
  // Calls the real preview endpoint (single content field).
  assert.match(src, /filesApi[\s\S]*?\.preview\(/)
  // Chunk content has no edit action (read-only).
  assert.doesNotMatch(src, /contentEditable/)
  // Must never render storage paths / uploads_data.
  assert.doesNotMatch(src, /uploads_data/)
  assert.doesNotMatch(src, /storage_uri/)
})

test('KnowledgeFilesPage shows real stage status and avoids fabricated progress', () => {
  const src = read('src/features/knowledge/pages/KnowledgeFilesPage.tsx')
  // Polls the durable job snapshot (no SSE).
  assert.match(src, /jobsApi[\s\S]*?\.snapshot\(/)
  // Uses exponential backoff capped at 15s.
  assert.match(src, /Math\.min\(15000/)
  // Does NOT fabricate progress_current/progress_total from the reduced snapshot.
  assert.doesNotMatch(src, /job\.progress_current/)
  assert.doesNotMatch(src, /job\.progress_total/)
})
