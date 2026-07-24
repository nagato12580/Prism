import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

async function loadFileStageUpdates() {
  const outDir = mkdtempSync(join(tmpdir(), 'prism-file-stage-updates-'))
  try {
    execFileSync(
      process.execPath,
      [
        resolve(root, 'node_modules/typescript/bin/tsc'),
        'src/features/knowledge/pages/fileStageUpdates.ts',
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
    return await import(pathToFileURL(resolve(outDir, 'fileStageUpdates.js')).href)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
}

const baseFile = {
  file_uid: 'file-a',
  kb_uid: 'kb-a',
  original_filename: 'paper.pdf',
  relative_path: '',
  media_type: 'document',
  mime_type: 'application/pdf',
  parse_status: 'succeeded',
  index_status: 'pending',
  graph_status: 'pending',
  content_sha256: 'sha',
  size_bytes: 10,
  preview_url: '',
  download_url: '',
}

test('updateFileStage sets the clicked file index status immediately', async () => {
  const { updateFileStage } = await loadFileStageUpdates()
  const rows = [
    baseFile,
    { ...baseFile, file_uid: 'file-b', index_status: 'pending' },
  ]

  const updated = updateFileStage(rows, 'file-a', 'index_status', 'running')

  assert.equal(updated[0].index_status, 'running')
  assert.equal(updated[1].index_status, 'pending')
})

test('updateFileStage leaves rows unchanged when file uid is missing', async () => {
  const { updateFileStage } = await loadFileStageUpdates()
  const rows = [baseFile]

  const updated = updateFileStage(rows, 'missing', 'index_status', 'running')

  assert.deepEqual(updated, rows)
})
