import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
function read(rel) {
  return readFileSync(resolve(root, rel), 'utf8')
}

async function loadPreviewContent() {
  const outDir = mkdtempSync(join(tmpdir(), 'prism-preview-content-'))
  try {
    execFileSync(
      process.execPath,
      [
        resolve(root, 'node_modules/typescript/bin/tsc'),
        'src/features/knowledge/components/previewContent.ts',
        '--module',
        'ESNext',
        '--target',
        'ES2020',
        '--moduleResolution',
        'bundler',
        '--outDir',
        outDir,
      ],
      { cwd: root, stdio: 'pipe' },
    )
    return await import(pathToFileURL(resolve(outDir, 'previewContent.js')).href)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
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

test('document preview bounds rendered text and reports truncation', async () => {
  const { clampPreviewContent, MAX_PREVIEW_CHARACTERS } = await loadPreviewContent()
  const oversized = 'x'.repeat(MAX_PREVIEW_CHARACTERS + 5)

  assert.deepEqual(clampPreviewContent(oversized), {
    content: 'x'.repeat(MAX_PREVIEW_CHARACTERS),
    truncated: true,
    totalCharacters: MAX_PREVIEW_CHARACTERS + 5,
  })
  assert.deepEqual(clampPreviewContent('short'), {
    content: 'short',
    truncated: false,
    totalCharacters: 5,
  })
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

test('KnowledgeFilesPage surfaces terminal job failure reasons', () => {
  const page = read('src/features/knowledge/pages/KnowledgeFilesPage.tsx')
  const api = read('src/features/knowledge/api/jobs.ts')

  assert.match(api, /error_message:\s*string\s*\|\s*null/)
  assert.match(page, /snap\.status\s*===\s*'failed'/)
  assert.match(page, /snap\.error_message/)
  assert.match(page, /setError\(new Error/)
})

test('KnowledgeFilesPage renders persisted file stage failure details', () => {
  const page = read('src/features/knowledge/pages/KnowledgeFilesPage.tsx')
  const api = read('src/features/knowledge/api/files.ts')

  assert.match(api, /parse_error:\s*StageError\s*\|\s*null/)
  assert.match(api, /index_error:\s*StageError\s*\|\s*null/)
  assert.match(api, /last_job_id:\s*string\s*\|\s*null/)
  assert.match(page, /file\.index_error\?\.message/)
  assert.match(page, /title=\{file\.index_error\.message\}/)
})

test('KnowledgeFilesPage only offers indexing after parse succeeds', () => {
  const page = read('src/features/knowledge/pages/KnowledgeFilesPage.tsx')

  assert.match(page, /file\.parse_status\s*===\s*'succeeded'\s*&&\s*file\.index_status\s*!==\s*'succeeded'/)
})

test('KnowledgeShell includes a subdued back action near the knowledge title', () => {
  const shell = read('src/features/knowledge/components/KnowledgeShell.tsx')
  const page = read('src/features/knowledge/pages/KnowledgeFilesPage.tsx')

  assert.match(shell, /navigate\('\/knowledge'\)/)
  assert.match(shell, /text-\[11px\]/)
  assert.doesNotMatch(page, /navigate\('\/knowledge'\)/)
})
