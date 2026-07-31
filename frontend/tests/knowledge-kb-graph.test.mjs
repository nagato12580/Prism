import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const tsc = resolve(root, 'node_modules/typescript/bin/tsc')

async function loadModule(sourceRel, outName) {
  const outDir = mkdtempSync(join(tmpdir(), 'prism-kb-graph-'))
  try {
    execFileSync(
      process.execPath,
      [
        tsc,
        sourceRel,
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
    const moduleUrl = pathToFileURL(resolve(outDir, outName)).href
    return await import(moduleUrl)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
}

test('buildKnowledgeBaseGraphPath repeats file_uids and keeps view', async () => {
  const { buildKnowledgeBaseGraphPath } = await loadModule(
    'src/features/knowledge/api/graphPath.ts',
    'graphPath.js',
  )

  assert.equal(
    buildKnowledgeBaseGraphPath('kb-a', {
      view: 'source',
      file_uids: ['file-a', 'file-b'],
      limit: 50,
    }),
    '/knowledge-bases/kb-a/graph?view=source&file_uids=file-a&file_uids=file-b&limit=50',
  )
})

test('graphFilterParamsFromWorkspaceSelection keeps only selected files for current kb', async () => {
  const { graphFilterParamsFromWorkspaceSelection } = await loadModule(
    'src/features/knowledge/pages/knowledgeGraphState.ts',
    'knowledgeGraphState.js',
  )

  assert.deepEqual(
    graphFilterParamsFromWorkspaceSelection(
      {
        'kb-a': ['file-a', 'file-b'],
        'kb-b': ['file-c'],
      },
      'kb-a',
    ),
    { file_uids: ['file-a', 'file-b'] },
  )
  assert.deepEqual(
    graphFilterParamsFromWorkspaceSelection(
      {
        'kb-a': [],
      },
      'kb-a',
    ),
    {},
  )
})
