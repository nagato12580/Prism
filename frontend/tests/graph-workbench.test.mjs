import assert from 'node:assert/strict'
import { renderGraphPage } from './support/render-graph-page.mjs'

const html = await renderGraphPage()
const focusedHtml = await renderGraphPage({
  initialSelectedId: 'entity-1',
  initialPayload: {
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
    focus: { view: 'entity', query: 'Alpha', entity_ids: ['entity-1'] },
  },
})

assert.match(html, /data-testid="unified-graph-page"/, 'Knowledge graph page should render the unified graph shell.')
assert.match(html, /data-testid="graph-floating-controls"/, 'Knowledge graph page should render dedicated floating controls for the explorer shell.')
assert.match(html, /实体视图/, 'Knowledge graph page should render the entity-view toggle at runtime.')
assert.match(html, /来源视图/, 'Knowledge graph page should render the source-view toggle at runtime.')
assert.match(html, /刷新图谱/, 'Knowledge graph page should render the refresh action at runtime.')
assert.match(html, /类型过滤/, 'Knowledge graph page should render the type filter control at runtime.')
assert.match(html, /重新聚焦/, 'Knowledge graph page should render the refocus action at runtime.')
assert.match(html, /文档分块/, 'Knowledge graph page should render the document chunk label at runtime.')
assert.match(
  html,
  /选择一个节点，查看它在统一图谱里的结构、来源证据和关联关系。/,
  'Knowledge graph page should render the empty inspector guidance.',
)
assert.match(
  html,
  /<div class="absolute inset-0"><\/div>/,
  'Knowledge graph page should hand the canvas surface to G6 as an empty div in static markup.',
)

assert.match(
  html,
  /data-testid="graph-inspector-overlay" data-state="closed"/,
  'Knowledge graph page should render the inspector overlay hidden by default.',
)
assert.match(
  focusedHtml,
  /data-testid="graph-inspector-overlay" data-state="open"/,
  'Knowledge graph page should open the inspector overlay once a node is selected.',
)
assert.match(focusedHtml, /data-testid="graph-inspector-close"/, 'Open inspector markup should expose an explicit close control.')
assert.match(focusedHtml, /Alpha Entity/, 'Open inspector markup should render the selected node details.')
assert.match(focusedHtml, /data-testid="graph-inspector-scroll"/, 'Inspector details should own a vertical scroll region.')
assert.match(focusedHtml, /data-testid="graph-inspector-entity-search"/, 'Inspector should render the selected entity label in its own search box.')
assert.match(focusedHtml, /placeholder="搜索实体内容"/, 'Inspector entity search box should expose an inline search input.')
assert.match(
  focusedHtml,
  /aria-label="上一个匹配"[\s\S]*aria-label="下一个匹配"/,
  'Inspector entity search box should let users move through matches vertically.',
)

assert.doesNotMatch(html, /Graph Workbench/, 'Knowledge graph page should not foreground the old workbench shell.')
assert.doesNotMatch(html, /Community information/, 'Knowledge graph page should not foreground old summary cards.')
