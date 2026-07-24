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
  const outDir = mkdtempSync(join(tmpdir(), 'prism-kb-contracts-'))
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

test('parseEvidence keeps only public fields and strips storage/tenant secrets', async () => {
  const { parseEvidence } = await loadModule('src/features/knowledge/api/contracts.ts', 'contracts.js')
  const evidence = parseEvidence({
    evidence_id: null,
    kb_uid: 'kb-a',
    tenant_id: 'secret-tenant',
    file_uid: 'file-a',
    item_id: 'item-1',
    chunk_uid: 'chunk-a',
    parent_chunk_uid: null,
    display_title: 'A',
    original_filename: 'a.pdf',
    excerpt: 'text',
    page_start: 1,
    page_end: 1,
    char_start: 0,
    char_end: 4,
    channel_scores: { dense: { raw_score: 0.9, raw_rank: 1 } },
    rrf_score: 0.02,
    rerank_score: 0.8,
    rerank_model: 'ce',
    retrieval_channels: ['dense'],
    graph_path: [{ step: 'x' }],
    graph_explanation: 'exp',
    evidence_type: 'chunk',
    index_generation: 'g1',
    degradation_flags: [],
    storage_uri: 'private/path',
  })
  assert.equal(evidence.chunk_uid, 'chunk-a')
  assert.equal(evidence.display_title, 'A')
  assert.equal(evidence.index_generation, 'g1')
  assert.equal('storage_uri' in evidence, false)
  assert.equal('tenant_id' in evidence, false)
})

test('retrievalStatusLabel maps the real backend statuses to distinct Chinese', async () => {
  const { retrievalStatusLabel } = await loadModule('src/features/knowledge/api/contracts.ts', 'contracts.js')
  assert.equal(retrievalStatusLabel('ok'), '检索完成')
  assert.equal(retrievalStatusLabel('no_hits'), '未找到证据')
  assert.equal(retrievalStatusLabel('degraded'), '部分检索通道不可用')
  assert.equal(retrievalStatusLabel('unavailable'), '检索服务不可用')
  assert.equal(retrievalStatusLabel('invalid_request'), '检索请求无效')
})

test('channelScoreLabel labels native channel meaning without wrapping as percent', async () => {
  const { channelScoreLabel } = await loadModule('src/features/knowledge/api/contracts.ts', 'contracts.js')
  assert.equal(channelScoreLabel('dense'), 'Dense 原始分数')
  assert.equal(channelScoreLabel('bm25'), 'BM25 原始分数')
  assert.equal(channelScoreLabel('graph'), 'Graph 原始分数')
  assert.equal(channelScoreLabel('rerank'), 'Rerank 分数')
})
