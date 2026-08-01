import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { renderGraphPage } from './support/render-graph-page.mjs'

const loadedPayload = {
  nodes: [
    { id: 'entity-1', type: 'entity', label: 'Alpha Entity', confidence: 0.91 },
    { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One', confidence: 0.72 },
    { id: 'asset-1', type: 'personal_asset_unit', label: 'Asset One', confidence: 0.66 },
  ],
  edges: [
    { id: 'edge-1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '閺夈儲绨拠浣瑰祦' },
    { id: 'edge-2', source: 'entity-1', target: 'asset-1', type: 'shares_entity_with', label: '閸忓彉闊╃€圭偘缍?' },
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
}
const root = resolve(import.meta.dirname, '..')
const pageSource = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')
const sourceFocusedPayload = {
  view: 'source',
  nodes: [
    { id: 'entity-1', type: 'entity', label: 'Alpha Entity', confidence: 0.91 },
    { id: 'entity-2', type: 'entity', label: 'Beta Entity', confidence: 0.84 },
    { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One', confidence: 0.72 },
    { id: 'asset-1', type: 'personal_asset_unit', label: 'Asset One', confidence: 0.66 },
  ],
  edges: [
    { id: 'edge-1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '来源证据' },
    { id: 'edge-2', source: 'entity-2', target: 'asset-1', type: 'shares_entity_with', label: '共享实体' },
    { id: 'edge-3', source: 'entity-1', target: 'entity-2', type: 'related_to', label: '语义关联' },
  ],
  stats: {
    node_count: 4,
    edge_count: 3,
    node_counts: {
      entity: 2,
      document_chunk: 1,
      personal_asset_unit: 1,
    },
    edge_counts: {
      mentioned_in: 1,
      shares_entity_with: 1,
      related_to: 1,
    },
  },
  focus: {
    view: 'source',
    query: 'Recovered query',
    entity_ids: ['entity-1'],
  },
}

const html = await renderGraphPage()
const loadedHtml = await renderGraphPage({ initialPayload: loadedPayload })
const openHtml = await renderGraphPage({ initialPayload: loadedPayload, initialSelectedId: 'entity-1' })
const sourceFocusedHtml = await renderGraphPage({ initialPayload: sourceFocusedPayload })
const seededPayload = {
  view: 'entity',
  nodes: [
    { id: 'hub-1', type: 'entity', label: 'Hub One', confidence: 0.95 },
    { id: 'hub-2', type: 'entity', label: 'Hub Two', confidence: 0.93 },
    { id: 'near-1', type: 'document_chunk', label: 'Near One', confidence: 0.7 },
    { id: 'near-2', type: 'document_chunk', label: 'Near Two', confidence: 0.7 },
    { id: 'near-3', type: 'document_chunk', label: 'Near Three', confidence: 0.7 },
    { id: 'near-4', type: 'document_chunk', label: 'Near Four', confidence: 0.7 },
    { id: 'near-5', type: 'document_chunk', label: 'Near Five', confidence: 0.7 },
    { id: 'near-6', type: 'document_chunk', label: 'Near Six', confidence: 0.7 },
    { id: 'isolated-1', type: 'entity', label: 'Isolated One', confidence: 0.4 },
    { id: 'isolated-2', type: 'entity', label: 'Isolated Two', confidence: 0.4 },
    { id: 'isolated-3', type: 'entity', label: 'Isolated Three', confidence: 0.4 },
    { id: 'isolated-4', type: 'entity', label: 'Isolated Four', confidence: 0.4 },
    { id: 'isolated-5', type: 'entity', label: 'Isolated Five', confidence: 0.4 },
  ],
  edges: [
    { id: 'edge-1', source: 'hub-1', target: 'near-1', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-2', source: 'hub-1', target: 'near-2', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-3', source: 'hub-1', target: 'near-3', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-4', source: 'hub-1', target: 'near-4', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-5', source: 'hub-2', target: 'near-5', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-6', source: 'hub-2', target: 'near-6', type: 'mentioned_in', label: 'linked' },
    { id: 'edge-7', source: 'hub-1', target: 'hub-2', type: 'related_to', label: 'related' },
  ],
  stats: {
    node_count: 13,
    edge_count: 7,
    node_counts: {
      entity: 7,
      document_chunk: 6,
      personal_asset_unit: 0,
    },
    edge_counts: {
      mentioned_in: 6,
      related_to: 1,
    },
  },
  focus: {
    view: 'entity',
    query: '',
    entity_ids: [],
  },
}
const seededHtml = await renderGraphPage({ initialPayload: seededPayload })

assert.match(html, /data-testid="graph-floating-controls"/, 'Graph page should render dedicated floating controls for the explorer shell.')
assert.doesNotMatch(
  html,
  /grid-cols-\[minmax\(0,1fr\)_23rem\]/,
  'Graph page should not keep the old fixed two-column inspector grid.',
)
assert.match(
  html,
  /<[^>]*data-testid="graph-inspector-overlay"[^>]*data-state="closed"[^>]*>|<[^>]*data-state="closed"[^>]*data-testid="graph-inspector-overlay"[^>]*>/,
  'Graph page should render the inspector overlay element in a hidden-by-default closed state.',
)
assert.match(
  loadedHtml,
  /<[^>]*data-testid="graph-inspector-overlay"[^>]*data-state="closed"[^>]*>|<[^>]*data-state="closed"[^>]*data-testid="graph-inspector-overlay"[^>]*>/,
  'Loaded graph markup should keep the inspector overlay closed until the user selects a node.',
)
assert.doesNotMatch(
  loadedHtml,
  /\u5f53\u524d\u7126\u70b9/,
  'Loaded graph markup should not assign an implicit focus root while the drawer is closed.',
)
assert.doesNotMatch(
  loadedHtml,
  /data-testid="graph-inspector-close"/,
  'Closed overlay markup should not render the inspector close control before a node is selected.',
)
assert.doesNotMatch(
  loadedHtml,
  /\u5b9e\u4f53\u7f51\u7edc/,
  'Loaded graph markup should not foreground the entity lane heading once free scatter becomes the main layout.',
)
assert.doesNotMatch(
  loadedHtml,
  /\u6587\u6863\u8bc1\u636e/,
  'Loaded graph markup should not foreground the document-evidence lane heading once free scatter becomes the main layout.',
)
assert.doesNotMatch(
  loadedHtml,
  /\u4e2a\u4eba\u8d44\u4ea7\u8bc1\u636e/,
  'Loaded graph markup should not foreground the asset-evidence lane heading once free scatter becomes the main layout.',
)
assert.match(
  openHtml,
  /<[^>]*data-testid="graph-inspector-overlay"[^>]*data-state="open"[^>]*>|<[^>]*data-state="open"[^>]*data-testid="graph-inspector-overlay"[^>]*>/,
  'Injected selected-node state should render the inspector overlay open.',
)
assert.match(openHtml, /data-testid="graph-inspector-close"/, 'Open inspector markup should expose an explicit close control.')
assert.match(openHtml, /Alpha Entity/, 'Open inspector markup should render the selected node details.')
assert.match(
  pageSource,
  /data-testid="graph-inspector-overlay"[\s\S]*items-stretch[\s\S]*overflow-hidden[\s\S]*<GraphInspector/,
  'Inspector overlay should stretch the drawer within the available graph viewport and clip overflow.',
)
assert.match(
  pageSource,
  /data-testid="graph-inspector-scroll"[\s\S]*min-h-0 flex-1[\s\S]*overflow-y-auto/,
  'Inspector details should own a vertical scroll region so long node content remains reachable.',
)
assert.match(html, /\u91cd\u65b0\u805a\u7126/, 'Graph page should expose a refocus action at runtime.')
assert.match(html, /\u5c55\u5f00\u66f4\u591a\u5173\u8054/, 'Graph page should expose an expand-more action at runtime.')
assert.match(
  sourceFocusedHtml,
  /value="Recovered query"/,
  'Preloaded graph markup should preserve the query from initialPayload focus instead of resetting to an empty search.',
)
assert.match(
  sourceFocusedHtml,
  /<button[^>]*text-slate-600[^>]*>实体视图<\/button><button[^>]*bg-slate-950 text-white shadow-sm[^>]*>来源视图<\/button>/,
  'Preloaded graph markup should preserve a source-focused initial view instead of falling back to entity view.',
)
assert.match(
  sourceFocusedHtml,
  /Search document or asset sources/,
  'Preloaded source-view markup should keep the source-view search semantics on first paint.',
)
assert.match(
  sourceFocusedHtml,
  /transform="translate\((?!590 360\) scale\()/,
  'Preloaded graph markup should solve initial node positions instead of rendering every node at the canvas center first.',
)
assert.match(
  seededHtml,
  /Hub One/,
  'Large graph markup should show high-degree seed nodes on first paint.',
)
assert.match(
  seededHtml,
  /Near One/,
  'Large graph markup should include one-hop neighbors of the default seed set on first paint.',
)
assert.doesNotMatch(
  seededHtml,
  /Isolated One/,
  'Large graph markup should hide isolated low-degree nodes until the user explores further.',
)
assert.match(
  pageSource,
  /const \[positions, setPositions\] = useState<PositionMap>\(\(\) =>[\s\S]*mergeSolvedPositions\(initialPayload\.nodes, initialPayload\.edges, \{\}, \{\}, initialView\)/,
  'Knowledge graph page should derive solved initial positions from initialPayload during state initialization.',
)
assert.match(
  pageSource,
  /const \[query, setQuery\] = useState\(\(\) => initialPayload\?\.focus\?\.query \?\? ''\)/,
  'Knowledge graph page should initialize query state from initialPayload focus when present.',
)
assert.match(
  pageSource,
  /const \[view, setView\] = useState<UnifiedGraphView>\(\(\) => initialPayload\?\.focus\?\.view \?\? initialPayload\?\.view \?\? 'entity'\)/,
  'Knowledge graph page should initialize view state from initialPayload focus when present.',
)
assert.match(
  pageSource,
  /const skipInitialLoadRef = useRef\(Boolean\(initialPayload\)\)[\s\S]*if \(skipInitialLoadRef\.current\) \{[\s\S]*skipInitialLoadRef\.current = false[\s\S]*return[\s\S]*void loadGraph\(view\)/,
  'Knowledge graph page should skip the first mount-triggered reload when initialPayload already seeded the page state.',
)
