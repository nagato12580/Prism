import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const helperSource = 'src/app/graphrag.ts'
const tsc = resolve(root, 'node_modules/typescript/bin/tsc')

async function loadHelpers() {
  const outDir = mkdtempSync(join(tmpdir(), 'prism-graphrag-'))
  try {
    execFileSync(
      process.execPath,
      [
        tsc,
        helperSource,
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
    const moduleUrl = pathToFileURL(resolve(outDir, 'graphrag.js')).href
    return await import(moduleUrl)
  } finally {
    rmSync(outDir, { recursive: true, force: true })
  }
}

test('evidenceTypeLabel uses unified vocabulary', async () => {
  const { evidenceTypeLabel } = await loadHelpers()
  assert.equal(evidenceTypeLabel('INFERRED'), '图推断')
  assert.equal(evidenceTypeLabel('EXTRACTED'), '直接证据')
  assert.equal(evidenceTypeLabel('CUSTOM'), 'CUSTOM')
  assert.equal(evidenceTypeLabel(undefined), undefined)
})

test('graphPathLabels renders route and step labels', async () => {
  const { graphPathLabels } = await loadHelpers()
  const labels = graphPathLabels([
    {
      source_marker: 'route A',
      matched_entity_ids: ['alpha', 'beta'],
      steps: [
        { label: 'Alpha' },
        { edge_type: 'related_to' },
        { node_id: 'beta' },
      ],
    },
    { edge_type: 'supports' },
  ])

  assert.deepEqual(labels, [
    'route A: alpha -> beta',
    'Alpha',
    'related_to',
    'beta',
    'supports',
  ])
})

test('selectInspectorExplain prefers node explain, falls back to edge explain, and summarizes multiple edges', async () => {
  const { selectInspectorExplain } = await loadHelpers()

  const nodeExplain = selectInspectorExplain(
    {
      graph_rag: {
        explain: {
          why: 'node summary',
          evidence_type: 'EXTRACTED',
          source_marker: 'node-route',
        },
      },
    },
    [
      {
        id: 'edge-1',
        reason: 'edge reason',
        evidence_type: 'INFERRED',
      },
    ],
  )
  assert.deepEqual(nodeExplain, {
    why: 'node summary',
    evidence_type: 'EXTRACTED',
    source_marker: 'node-route',
  })

  const singleEdgeExplain = selectInspectorExplain({}, [
    {
      id: 'edge-1',
      reason: 'edge reason',
      evidence_type: 'EXTRACTED',
    },
  ])
  assert.deepEqual(singleEdgeExplain, {
    why: 'edge reason',
    evidence_type: 'EXTRACTED',
  })

  const multiEdgeExplain = selectInspectorExplain({}, [
    {
      id: 'edge-1',
      reason: 'edge one',
      evidence_type: 'EXTRACTED',
    },
    {
      id: 'edge-2',
      evidence_span: 'edge two',
      evidence_type: 'INFERRED',
      graph_rag: {
        explain: {
          why: 'edge two explain',
          evidence_type: 'INFERRED',
          source_marker: 'route-2',
        },
      },
    },
  ])
  assert.equal(multiEdgeExplain?.evidence_type, 'INFERRED')
  assert.match(multiEdgeExplain?.why ?? '', /2/)
  assert.match(multiEdgeExplain?.why ?? '', /relation details|one by one/i)
})
