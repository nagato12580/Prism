import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
function read(rel) {
  return readFileSync(resolve(root, rel), 'utf8')
}

test('KnowledgeRetrievalPage keeps query/mode/filter in URL and uses real backend params', () => {
  const src = read('src/features/knowledge/pages/KnowledgeRetrievalPage.tsx')
  // Query, mode, top_k, graph_hops persist to search params (deep-linkable).
  assert.match(src, /searchParams\.get\(['"]q['"]\)/)
  assert.match(src, /searchParams\.get\(['"]mode['"]\)/)
  // Uses real backend mode values fast/deep (NOT standard/deep).
  assert.match(src, /<option value="fast">/)
  assert.match(src, /<option value="deep">/)
  // Sends overrides per-request via retrievalApi.query, not a settings PATCH.
  assert.match(src, /retrievalApi[\s\S]*?\.query\(/)
})

test('RetrievalPage maps backend error envelopes to unified status vocabulary', () => {
  const src = read('src/features/knowledge/pages/KnowledgeRetrievalPage.tsx')
  // RETRIEVAL_UNAVAILABLE -> unavailable; INVALID_RETRIEVAL_REQUEST -> invalid_request.
  assert.match(src, /RETRIEVAL_UNAVAILABLE/)
  assert.match(src, /INVALID_RETRIEVAL_REQUEST/)
  assert.match(src, /unavailable/)
  assert.match(src, /invalid_request/)
})

test('channel scores are labeled by native meaning, never as match percent', () => {
  const src = read('src/features/knowledge/pages/KnowledgeRetrievalPage.tsx')
  assert.match(src, /channelScoreLabel\(/)
  assert.doesNotMatch(src, /匹配百分比/)
})

test('retrieval result list exposes evidence fields without private data', () => {
  const src = read('src/features/knowledge/pages/KnowledgeRetrievalPage.tsx')
  assert.match(src, /channel_scores/)
  assert.match(src, /rrf_score/)
  assert.doesNotMatch(src, /storage_uri/)
  assert.doesNotMatch(src, /tenant_id/)
})
