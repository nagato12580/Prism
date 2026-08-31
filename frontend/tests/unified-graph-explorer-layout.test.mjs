import assert from 'node:assert/strict'
import { renderGraphPage } from './support/render-graph-page.mjs'

const loadedPayload = {
  nodes: [
    { id: 'entity-1', type: 'entity', label: 'Alpha Entity', confidence: 0.91 },
    { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One', confidence: 0.72 },
    { id: 'asset-1', type: 'personal_asset_unit', label: 'Asset One', confidence: 0.66 },
  ],
  edges: [
    { id: 'edge-1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '来源证据' },
    { id: 'edge-2', source: 'entity-1', target: 'asset-1', type: 'shares_entity_with', label: '共享实体' },
  ],
  stats: {
    node_count: 3,
    edge_count: 2,
    node_counts: { entity: 1, document_chunk: 1, personal_asset_unit: 1 },
    edge_counts: { mentioned_in: 1, shares_entity_with: 1 },
  },
  focus: { view: 'entity', query: 'Alpha', entity_ids: ['entity-1'] },
}

const sourceFocusedPayload = {
  view: 'source',
  nodes: [
    { id: 'entity-1', type: 'entity', label: 'Alpha Entity', confidence: 0.91 },
    { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One', confidence: 0.72 },
  ],
  edges: [{ id: 'edge-1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '来源证据' }],
  stats: {
    node_count: 2,
    edge_count: 1,
    node_counts: { entity: 1, document_chunk: 1 },
    edge_counts: { mentioned_in: 1 },
  },
  focus: { view: 'source', query: 'Recovered query', entity_ids: ['entity-1'] },
}

const html = await renderGraphPage()
const loadedHtml = await renderGraphPage({ initialPayload: loadedPayload })
const openHtml = await renderGraphPage({ initialPayload: loadedPayload, initialSelectedId: 'entity-1' })
const sourceFocusedHtml = await renderGraphPage({ initialPayload: sourceFocusedPayload })

assert.match(html, /data-testid="graph-floating-controls"/, 'Graph page should render dedicated floating controls for the explorer shell.')
assert.doesNotMatch(
  html,
  /grid-cols-\[minmax\(0,1fr\)_23rem\]/,
  'Graph page should not keep the old fixed two-column inspector grid.',
)
assert.match(
  html,
  /data-testid="graph-inspector-overlay" data-state="closed"/,
  'Graph page should render the inspector overlay element in a hidden-by-default closed state.',
)
assert.match(
  loadedHtml,
  /data-testid="graph-inspector-overlay" data-state="closed"/,
  'Loaded graph markup should keep the inspector overlay closed until the user selects a node.',
)
assert.doesNotMatch(
  loadedHtml,
  /data-testid="graph-inspector-close"/,
  'Closed overlay markup should not render the inspector close control before a node is selected.',
)
assert.match(
  openHtml,
  /data-testid="graph-inspector-overlay" data-state="open"/,
  'Injected selected-node state should render the inspector overlay open.',
)
assert.match(openHtml, /data-testid="graph-inspector-close"/, 'Open inspector markup should expose an explicit close control.')
assert.match(openHtml, /Alpha Entity/, 'Open inspector markup should render the selected node details.')

assert.match(loadedHtml, /节点 3/, 'Loaded graph markup should render the total node count from stats.')
assert.match(loadedHtml, /边 2/, 'Loaded graph markup should render the total edge count from stats.')
assert.match(loadedHtml, /实体 1/, 'Loaded graph markup should render the entity count from stats.')
assert.match(loadedHtml, /文档分块 1/, 'Loaded graph markup should render the chunk count from stats.')

assert.match(
  sourceFocusedHtml,
  /value="Recovered query"/,
  'Preloaded graph markup should preserve the query from initialPayload focus instead of resetting to an empty search.',
)
assert.match(
  sourceFocusedHtml,
  /搜索文档或资产来源/,
  'Preloaded source-view markup should keep the source-view search semantics on first paint.',
)
assert.match(
  sourceFocusedHtml,
  /<button[^>]*text-slate-600[^>]*>实体视图<\/button>/,
  'Preloaded source-view markup should render the entity toggle as inactive.',
)
assert.match(
  sourceFocusedHtml,
  /<button[^>]*bg-slate-950 text-white shadow-sm[^>]*>来源视图<\/button>/,
  'Preloaded source-view markup should render the source toggle as active.',
)
