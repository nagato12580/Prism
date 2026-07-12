import assert from 'node:assert/strict'
import { renderGraphPage } from './support/render-graph-page.mjs'

const html = await renderGraphPage()
const loadedHtml = await renderGraphPage({
  initialPayload: {
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
      node_counts: {
        entity: 1,
        document_chunk: 1,
        personal_asset_unit: 1,
      },
      edge_counts: {
        mentioned_in: 1,
        shares_entity_with: 1,
      },
    },
    focus: {
      view: 'entity',
      query: 'Alpha',
      entity_ids: ['entity-1'],
    },
  },
})
const focusedHtml = await renderGraphPage({
  initialSelectedId: 'entity-1',
  initialPayload: {
    nodes: [
      { id: 'entity-1', type: 'entity', label: 'Alpha Entity', confidence: 0.91 },
      { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One', confidence: 0.72 },
      { id: 'asset-1', type: 'personal_asset_unit', label: 'Asset One', confidence: 0.66 },
    ],
    edges: [
      { id: 'edge-1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '鏉ユ簮璇佹嵁' },
      { id: 'edge-2', source: 'entity-1', target: 'asset-1', type: 'shares_entity_with', label: '鍏变韩瀹炰綋' },
    ],
    stats: {
      node_count: 3,
      edge_count: 2,
      node_counts: {
        entity: 1,
        document_chunk: 1,
        personal_asset_unit: 1,
      },
      edge_counts: {
        mentioned_in: 1,
        shares_entity_with: 1,
      },
    },
    focus: {
      view: 'entity',
      query: 'Alpha',
      entity_ids: ['entity-1'],
    },
  },
})

assert.match(html, /data-testid="graph-floating-controls"/, 'Knowledge graph page should render dedicated floating controls for the explorer shell.')
assert.match(html, /\u5b9e\u4f53\u89c6\u56fe/, 'Knowledge graph page should render the entity-view toggle at runtime.')
assert.match(html, /\u6765\u6e90\u89c6\u56fe/, 'Knowledge graph page should render the source-view toggle at runtime.')
assert.match(html, /\u5237\u65b0\u56fe\u8c31/, 'Knowledge graph page should render the refresh action at runtime.')
assert.match(html, /Pending index/, 'Knowledge graph page should render the top-right floating status capsule title at runtime.')
assert.match(html, /Status capsule/, 'Knowledge graph page should render the top-right floating status capsule subtitle at runtime.')
assert.match(html, /\u91cd\u65b0\u805a\u7126/, 'Knowledge graph page should render the refocus action at runtime.')
assert.match(html, /\u6587\u6863\u5206\u5757/, 'Knowledge graph page should render the document chunk label at runtime.')
assert.match(
  html,
  /\u9009\u62e9\u4e00\u4e2a\u8282\u70b9\uff0c\u67e5\u770b\u5b83\u5728 unified graph \u91cc\u7684\u7ed3\u6784\u3001\u6765\u6e90\u8bc1\u636e\u548c\u5173\u8054\u5173\u7cfb\u3002/,
  'Knowledge graph page should render the empty inspector guidance at runtime.',
)
assert.doesNotMatch(html, /Unified Graph|Unified knowledge graph workspace/, 'Knowledge graph page runtime should keep the floating controls shell free of a relocated headline block.')
assert.doesNotMatch(html, /Graph Workbench/, 'Knowledge graph page runtime should not foreground the old workbench shell.')
assert.doesNotMatch(html, /Community information/, 'Knowledge graph page runtime should not foreground old summary cards.')
assert.match(loadedHtml, /Pending index/, 'Knowledge graph page should keep the status capsule visible after the graph payload loads.')
assert.match(loadedHtml, />2</, 'Knowledge graph page should derive the pending index count from declared source node counts in the loaded payload.')
assert.match(loadedHtml, /Alpha Entity/, 'Knowledge graph page should render loaded graph content at runtime.')
assert.match(loadedHtml, /<title>Alpha Entity<\/title>/, 'Knowledge graph page should preserve title fallback text for hidden-label nodes at runtime.')
assert.match(
  loadedHtml,
  /<title>Alpha Entity<\/title><circle cx="0" cy="0" r="25" fill="transparent" pointer-events="all"><\/circle>/,
  'Knowledge graph page should keep hidden-label nodes clickable through the circle body even when detached labels are absent at runtime.',
)
assert.doesNotMatch(
  loadedHtml,
  /<title>Alpha Entity<\/title><rect/,
  'Knowledge graph page should not keep a detached-label ghost rect on hidden-label nodes at runtime.',
)
assert.match(
  focusedHtml,
  /<rect x="-73" y="-36" width="146" height="103" rx="36" fill="transparent" pointer-events="all"><\/rect>/,
  'Knowledge graph page should expand the focused detached-label hit rect far enough to cover the visible caption stack at runtime.',
)
assert.match(
  focusedHtml,
  /<text x="0" y="44" text-anchor="middle" class="fill-slate-900 font-medium text-\[10px\]" pointer-events="none">Alpha Entity<\/text>/,
  'Knowledge graph page should render the focused primary node label as a detached centered caption beneath the circle at runtime.',
)
assert.match(
  focusedHtml,
  /<text x="0" y="57" text-anchor="middle" class="text-\[8px\] font-medium fill-slate-600" pointer-events="none">实体<\/text>/,
  'Knowledge graph page should render the focused meta label as a detached centered caption beneath the circle at runtime.',
)
