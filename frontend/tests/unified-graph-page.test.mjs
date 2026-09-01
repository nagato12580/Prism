import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')
const hook = readFileSync(resolve(root, 'src/pages/graph/useG6Graph.ts'), 'utf8')

// —— 外壳仍保留 ——
assert.match(page, /data-testid="unified-graph-page"/, 'Knowledge graph page keeps the unified graph shell.')
assert.match(page, /data-testid="graph-floating-controls"/, 'Knowledge graph page keeps the dedicated floating controls shell.')
assert.match(page, /实体视图/, 'Knowledge graph page keeps the entity-view toggle readable.')
assert.match(page, /来源视图/, 'Knowledge graph page keeps the source-view toggle readable.')
assert.match(page, /刷新图谱/, 'Knowledge graph page keeps the refresh action readable.')
assert.match(page, /类型过滤/, 'Knowledge graph page keeps the type filter control readable.')

// —— 画布交给 G6，取代手写 SVG ——
assert.match(page, /from '\.\/graph\/useG6Graph'/, 'Knowledge graph page imports the G6 hook and data mapper.')
assert.match(page, /const canvasRef = useRef<HTMLDivElement \| null>\(null\)/, 'Knowledge graph page owns a G6 container ref.')
assert.match(
  page,
  /useG6Graph\(\{[\s\S]*containerRef: canvasRef[\s\S]*data: graphData[\s\S]*onNodeClick: inspectNode[\s\S]*onCanvasClick: closeInspector/,
  'Knowledge graph page wires the G6 hook to the canvas, graph data, and click handlers.',
)
assert.match(
  page,
  /<div ref=\{canvasRef\} className="absolute inset-0" \/>/,
  'Knowledge graph page hands the canvas surface to G6 instead of an inline SVG tree.',
)

// —— 保留 Prism 双色配色 ——
assert.match(page, /entity: \{\s*label: '实体',\s*color: '#155eef'/, 'Knowledge graph page keeps the entity blue accent.')
assert.match(
  page,
  /document_chunk: \{\s*label: '文档分块',\s*color: '#0f766e'/,
  'Knowledge graph page keeps the chunk teal accent.',
)

// —— 默认类型过滤仅实体与文档分块 ——
assert.match(
  page,
  /useState<Set<UnifiedGraphNodeType>>\([\s\S]*new Set<UnifiedGraphNodeType>\(\['entity', 'document_chunk'\]\)/,
  'Knowledge graph page defaults the type filter to entity and document chunk.',
)

// —— 移除手写 SVG 渲染与物理布局 ——
assert.doesNotMatch(page, /function GraphNode\(/, 'Knowledge graph page no longer keeps the hand-rolled GraphNode SVG component.')
assert.doesNotMatch(
  page,
  /solveFreeScatterLayout|relaxScatterLayout|mergeSolvedPositions|seededScatterPoint/,
  'Knowledge graph page no longer keeps the hand-rolled physics layout solvers.',
)
assert.doesNotMatch(
  page,
  /nodeVisualRadiusForTier|edgeAnchorRadius|nodeDetachedLabelHitArea|graphNodeClampPadding/,
  'Knowledge graph page no longer keeps the hand-rolled node/edge geometry helpers.',
)
assert.doesNotMatch(
  page,
  /buildSeedDistanceMap|selectDefaultVisibleNodeIds|distanceTier/,
  'Knowledge graph page no longer keeps the seed-based default visibility pruning.',
)
assert.doesNotMatch(page, /id="graph-grid"/, 'Knowledge graph page no longer keeps the old high-contrast graph grid.')

// —— G6 配置对齐 Yuxi ——
assert.match(hook, /type: 'd3-force'/, 'G6 hook uses the d3-force layout aligned with Yuxi.')
assert.match(hook, /type: 'click-select',[\s\S]*degree: 1/, 'G6 hook uses single-hop click-select highlighting.')
assert.match(hook, /ENTITY_COLOR = '#155eef'/, 'G6 hook maps entity nodes to the blue accent.')
assert.match(hook, /CHUNK_COLOR = '#0f766e'/, 'G6 hook maps chunk nodes to the teal accent.')
assert.match(hook, /export function formatGraphData/, 'G6 hook exposes a pure data mapper from UnifiedGraph to G6 data.')

// —— 性能优化：控制数据量、省去低价值标签渲染 ——
assert.match(
  hook,
  /d\.data\.type === 'entity' \|\| d\.data\.degree >= 2/,
  'G6 hook shows node labels only for entities or bridge chunks.',
)
assert.doesNotMatch(hook, /labelBackground/, 'G6 hook drops per-edge text labels to cut render cost.')
assert.match(hook, /iterations: 60/, 'G6 hook lowers d3-force iterations for large graphs.')
assert.match(hook, /type: node\.type/, 'G6 hook carries node type into G6 data for label gating.')
assert.match(page, /limit: 120/, 'Knowledge graph page caps the backend entity limit.')
