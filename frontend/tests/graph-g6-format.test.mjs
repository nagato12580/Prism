import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { createServer } from 'vite'

const root = resolve(import.meta.dirname, '..')

async function loadFormatGraphData() {
  const server = await createServer({
    configFile: resolve(root, 'vite.config.ts'),
    root,
    logLevel: 'error',
    server: { middlewareMode: true },
    appType: 'custom',
  })
  try {
    const mod = await server.ssrLoadModule('/src/pages/graph/useG6Graph.ts')
    return mod.formatGraphData
  } finally {
    await server.close()
  }
}

const formatGraphData = await loadFormatGraphData()

const nodes = [
  { id: 'entity-1', type: 'entity', label: 'Alpha' },
  { id: 'chunk-1', type: 'document_chunk', label: 'Chunk One' },
  { id: 'asset-1', type: 'personal_asset_unit', label: 'Asset One' },
]
const edges = [
  { id: 'e1', source: 'entity-1', target: 'chunk-1', type: 'mentioned_in', label: '来源证据' },
  { id: 'e2', source: 'entity-1', target: 'asset-1', type: 'shares_entity_with' },
]

const graphData = formatGraphData(nodes, edges, new Set(['entity', 'document_chunk']))

assert.equal(graphData.nodes.length, 2, 'formatGraphData should drop nodes outside the type filter.')
assert.deepEqual(
  graphData.nodes.map((node) => node.id),
  ['entity-1', 'chunk-1'],
  'formatGraphData should preserve source node order for visible nodes.',
)

const entityNode = graphData.nodes.find((node) => node.id === 'entity-1')
assert.equal(entityNode.data.color, '#155eef', 'formatGraphData should map entity nodes to the blue accent.')
assert.equal(entityNode.data.label, 'Alpha', 'formatGraphData should carry the node label into G6 data.')
assert.equal(entityNode.data.degree, 2, 'formatGraphData should compute node degree from the full edge set.')

const chunkNode = graphData.nodes.find((node) => node.id === 'chunk-1')
assert.equal(chunkNode.data.color, '#0f766e', 'formatGraphData should map chunk nodes to the teal accent.')
assert.equal(chunkNode.data.degree, 1, 'formatGraphData should compute one-hop degree for the chunk node.')

assert.equal(graphData.edges.length, 1, 'formatGraphData should drop edges whose endpoints are filtered out.')
assert.equal(graphData.edges[0].id, 'e1', 'formatGraphData should preserve the edge id.')
assert.equal(graphData.edges[0].source, 'entity-1', 'formatGraphData should preserve the edge source.')
assert.equal(graphData.edges[0].target, 'chunk-1', 'formatGraphData should preserve the edge target.')
assert.equal(graphData.edges[0].data.label, '来源证据', 'formatGraphData should carry the edge label into G6 data.')
