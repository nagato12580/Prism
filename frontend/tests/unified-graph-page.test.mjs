import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')
const graphNodeBlockMatch = page.match(/function GraphNode\([\s\S]*?function GraphInspector\(/)
const mergeSolvedPositionsBlockMatch = page.match(/function mergeSolvedPositions\([\s\S]*?function omitViewEntries/)
const renderedEdgeBlockMatch = page.match(/\{renderedEdges\.map\(\(\{ edge, tier \}\) => \{[\s\S]*?\}\)\}/)

assert.ok(graphNodeBlockMatch, 'Knowledge graph page should keep an inspectable GraphNode rendering block in source.')
assert.ok(
  mergeSolvedPositionsBlockMatch,
  'Knowledge graph page should keep an inspectable merged-position solver block in source.',
)
assert.ok(renderedEdgeBlockMatch, 'Knowledge graph page should keep an inspectable rendered-edge path block in source.')

const graphNodeBlock = graphNodeBlockMatch[0]
const mergeSolvedPositionsBlock = mergeSolvedPositionsBlockMatch[0]
const renderedEdgeBlock = renderedEdgeBlockMatch[0]

assert.match(page, /data-testid="unified-graph-page"/, 'Knowledge graph page should keep the unified graph page shell.')
assert.match(page, /data-testid="graph-floating-controls"/, 'Knowledge graph page should render a dedicated floating controls shell.')
assert.match(page, /\u5b9e\u4f53\u89c6\u56fe/, 'Knowledge graph page should keep the entity-view toggle readable.')
assert.match(page, /\u6765\u6e90\u89c6\u56fe/, 'Knowledge graph page should keep the source-view toggle readable.')
assert.match(page, /\u5237\u65b0\u56fe\u8c31/, 'Knowledge graph page should keep the refresh action readable.')
assert.match(
  page,
  /countFor\(payload, 'document_chunk'\) \+ countFor\(payload, 'personal_asset_unit'\)/,
  'Knowledge graph page should derive the pending index count from declared source node counts.',
)
assert.match(
  page,
  /\u9009\u62e9\u4e00\u4e2a\u8282\u70b9\uff0c\u67e5\u770b\u5b83\u5728 unified graph \u91cc\u7684\u7ed3\u6784\u3001\u6765\u6e90\u8bc1\u636e\u548c\u5173\u8054\u5173\u7cfb\u3002/,
  'Knowledge graph page should keep the empty inspector guidance.',
)
assert.match(page, /\u91cd\u65b0\u805a\u7126/, 'Knowledge graph page should keep the refocus action readable.')
assert.match(page, /\u6587\u6863\u5206\u5757/, 'Knowledge graph page should keep the document chunk label readable.')
assert.match(
  page,
  /node\.type === 'entity' && tier === 'mid'/,
  'Knowledge graph page should keep the extra entity-label branch limited to the intended mid-tier hierarchy.',
)
assert.doesNotMatch(
  page,
  /node\.type === 'entity' && tier !== 'far'/,
  'Knowledge graph page should not let dim nodes slip into the extra entity-label branch.',
)
assert.match(
  page,
  /!showPrimaryLabel && !showMetaLabel \? \(\s*<title>\{node\.label\}<\/title>/s,
  'Knowledge graph page should keep a visible discoverability fallback for nodes whose text labels are hidden.',
)
assert.match(
  page,
  /graph-drift/,
  'Knowledge graph page should define a calmer drift field treatment for the graph surface.',
)
assert.match(
  page,
  /ref=\{graphContainerRef\}[\s\S]*bg-\[radial-gradient\(circle_at_50%_42%/,
  'Graph canvas frame should own a full-frame surface background so SVG aspect-ratio letterboxing does not expose blank bands.',
)
assert.match(
  page,
  /function solveFreeScatterLayout\(/,
  'Knowledge graph page should promote solveFreeScatterLayout as the main graph layout contract.',
)
assert.match(
  page,
  /function relaxScatterLayout\(/,
  'Knowledge graph page should keep a dedicated scatter relaxation pass for free-node layout.',
)
assert.match(
  mergeSolvedPositionsBlock,
  /const solved = solveFreeScatterLayout\(/,
  'Knowledge graph page should route merged graph positions through solveFreeScatterLayout as the main layout contract.',
)
assert.match(
  page,
  /const graphNodeClampPadding = /,
  'Knowledge graph page should define a single circle-based drag clamp padding for graph nodes.',
)
assert.match(
  page,
  /function nodeVisualRadiusForTier\(/,
  'Knowledge graph page should expose a shared circle-radius helper for node rendering and edge anchoring.',
)
assert.match(
  page,
  /function edgeAnchorRadius\(/,
  'Knowledge graph page should expose a shared edge-anchor radius helper for circular nodes.',
)
assert.match(
  page,
  /function nodeDetachedLabelHitArea\(/,
  'Knowledge graph page should expose a shared label-aware hit-area helper for detached circular-node labels.',
)
assert.match(
  page,
  /function nodeDetachedLabelHitArea\([\s\S]*showPrimaryLabel[\s\S]*showMetaLabel[\s\S]*primaryLabelY[\s\S]*metaLabelY[\s\S]*if \(!showPrimaryLabel && !showMetaLabel\)[\s\S]*enabled: false[\s\S]*x: -nodeHitRadius[\s\S]*y: -nodeHitRadius[\s\S]*width: nodeHitRadius \* 2[\s\S]*height: nodeHitRadius \* 2/s,
  'Knowledge graph page should bind detached label hit-area geometry to actual label visibility and collapse hidden-label nodes to the circle body only.',
)
assert.match(
  page,
  /function nodeDetachedLabelHitArea\([\s\S]*const top = Math\.min\(-nodeHitRadius[\s\S]*const bottom = Math\.max\(nodeHitRadius[\s\S]*return \{[\s\S]*enabled: true[\s\S]*x: -width \/ 2[\s\S]*y: top[\s\S]*width,[\s\S]*height: bottom - top/s,
  'Knowledge graph page should return full detached-label rect geometry that spans from the top edge through the rendered label stack.',
)
assert.match(
  page,
  /function edgeAnchorRadius\([\s\S]*nodeVisualRadiusForTier\(tier, active, focusRoot\) \* nodeScale\(tier, active, focusRoot\)/s,
  'Knowledge graph page should scale edge anchors to the same visible circle radius used by the rendered node transform.',
)
assert.doesNotMatch(
  page,
  /function edgeAnchorRadius\([\s\S]*return nodeVisualRadiusForTier\(tier, active, focusRoot\)\s*\}/s,
  'Knowledge graph page should not keep edge anchors tied to the unscaled base circle radius.',
)
assert.match(
  graphNodeBlock,
  /const nodeVisualRadius = nodeVisualRadiusForTier\(/,
  'Knowledge graph page should derive GraphNode visible size from the shared circular radius helper.',
)
assert.match(
  graphNodeBlock,
  /const nodeHitRadius = /,
  'Knowledge graph page should keep a separate hit radius around the circular node body.',
)
assert.match(
  graphNodeBlock,
  /<circle\b[\s\S]*pointerEvents="all"/s,
  'Knowledge graph page should keep an explicit circular GraphNode hit area while the circular-node contract lands.',
)
assert.doesNotMatch(
  graphNodeBlock,
  /translate\(\$\{node\.x\} \$\{node\.y\}\) scale\(\$\{scale\}\) translate\(\$\{-nodeWidth \/ 2\} \$\{-nodeHeight \/ 2\}\)/,
  'Knowledge graph page should not keep GraphNode anchored around a top-left pill box once the circle-centered contract lands.',
)
assert.match(
  graphNodeBlock,
  /<circle\b[\s\S]*cx="0"[\s\S]*cy="0"[\s\S]*pointerEvents="none"/s,
  'Knowledge graph page should render visible node circles centered on the node origin.',
)
assert.match(
  graphNodeBlock,
  /const showPrimaryLabel = active \|\| focusRoot \|\| tier === 'near' \|\| \(node\.type === 'entity' && tier === 'mid'\)/,
  'Knowledge graph page should derive primary detached-label visibility from the intended circle-node focus hierarchy.',
)
assert.match(
  graphNodeBlock,
  /const showMetaLabel = active \|\| focusRoot \|\| tier === 'near'/,
  'Knowledge graph page should derive meta detached-label visibility from the intended circle-node focus hierarchy.',
)
assert.match(
  graphNodeBlock,
  /const nodeLabelHitArea = nodeDetachedLabelHitArea\(\{[\s\S]*nodeHitRadius,[\s\S]*showPrimaryLabel,[\s\S]*showMetaLabel,[\s\S]*primaryLabelY,[\s\S]*metaLabelY/s,
  'Knowledge graph page should derive GraphNode detached-label hit-area geometry from actual label visibility and positions.',
)
assert.match(
  graphNodeBlock,
  /const nodeHitWidth = nodeLabelHitArea\.width/,
  'Knowledge graph page should source GraphNode hit width from the shared detached-label hit-area helper.',
)
assert.match(
  graphNodeBlock,
  /const nodeHitHeight = nodeLabelHitArea\.height/,
  'Knowledge graph page should source GraphNode hit height from the shared detached-label hit-area helper.',
)
assert.match(
  graphNodeBlock,
  /const nodeHitX = nodeLabelHitArea\.x/,
  'Knowledge graph page should source GraphNode hit x from the detached-label geometry helper.',
)
assert.match(
  graphNodeBlock,
  /const nodeHitY = nodeLabelHitArea\.y/,
  'Knowledge graph page should source GraphNode hit y from the detached-label geometry helper.',
)
assert.match(
  graphNodeBlock,
  /nodeLabelHitArea\.enabled \? \(\s*<rect\b[\s\S]*x=\{nodeHitX\}[\s\S]*y=\{nodeHitY\}[\s\S]*width=\{nodeHitWidth\}[\s\S]*height=\{nodeHitHeight\}/s,
  'Knowledge graph page should render an extra detached-label hit rect only when labels are actually visible.',
)
assert.match(
  graphNodeBlock,
  /const primaryLabelY = nodeVisualRadius \+ 18/,
  'Knowledge graph page should position the primary label below the circle body once labels detach.',
)
assert.match(
  graphNodeBlock,
  /const metaLabelY = nodeVisualRadius \+ 31/,
  'Knowledge graph page should position the meta label below the circle body once labels detach.',
)
assert.match(
  graphNodeBlock,
  /<text\b[\s\S]*y=\{primaryLabelY\}[\s\S]*textAnchor="middle"/s,
  'Knowledge graph page should center detached primary labels under each circle node.',
)
assert.match(
  graphNodeBlock,
  /<text\b[\s\S]*y=\{metaLabelY\}[\s\S]*textAnchor="middle"/s,
  'Knowledge graph page should center detached meta labels under each circle node.',
)
assert.doesNotMatch(
  graphNodeBlock,
  /const primaryLabelY = showMetaLabel \? -1 : 3|const metaLabelY = 11/,
  'Knowledge graph page should not keep the old inline label y-offsets once labels detach from the circle body.',
)
assert.doesNotMatch(
  graphNodeBlock,
  /cy=\{showPrimaryLabel \|\| showMetaLabel \? -nodeVisualRadius \+ 8 : 0\}/,
  'Knowledge graph page should not move the internal glyph upward to make room for inline text once labels are detached.',
)
assert.match(
  renderedEdgeBlock,
  /const sourceRadius = edgeAnchorRadius\(sourceTier, sourceActive, sourceFocusRoot\)/,
  'Knowledge graph page should derive rendered source edge anchors from the shared scale-aware circle radius helper.',
)
assert.match(
  renderedEdgeBlock,
  /const targetRadius = edgeAnchorRadius\(targetTier, targetActive, targetFocusRoot\)/,
  'Knowledge graph page should derive rendered target edge anchors from the shared scale-aware circle radius helper.',
)
assert.match(
  renderedEdgeBlock,
  /const sy = source\.y \+ \(dy \/ distance\) \* sourceRadius/,
  'Knowledge graph page should anchor the rendered edge start point from the scaled source circle perimeter.',
)
assert.match(
  renderedEdgeBlock,
  /const ty = target\.y - \(dy \/ distance\) \* targetRadius/,
  'Knowledge graph page should anchor the rendered edge end point from the scaled target circle perimeter.',
)
assert.match(
  renderedEdgeBlock,
  /d=\{`M \$\{sx\} \$\{sy\} C \$\{cx1\} \$\{cy1\}, \$\{cx2\} \$\{cy2\}, \$\{tx\} \$\{ty\}`\}/,
  'Knowledge graph page should render the edge path from circle-adjusted start and end coordinates.',
)
assert.doesNotMatch(
  page,
  /showMetaLabel \? 96 : 84|showMetaLabel \? 44 : 38/,
  'Knowledge graph page should not keep the old fixed 84/96 and 38/44 hit-area contracts anywhere in source.',
)
assert.doesNotMatch(
  graphNodeBlock,
  /<rect\b[^>]*fill=\{bodyFill\}/s,
  'Knowledge graph page should drop the old rect-based visible node body once circular nodes land.',
)
assert.doesNotMatch(
  page,
  /const graphNodeClampPaddingX = nodeWidth \/ 2 \+ 16|const graphNodeClampPaddingY = nodeHeight \/ 2 \+ 16/,
  'Knowledge graph page should not derive drag clamps from the old pill width and height.',
)
assert.match(
  page,
  /const x = clamp\(point\.x - dragging\.dx, graphNodeClampPadding, graphWidth - graphNodeClampPadding\)/,
  'Knowledge graph page should clamp dragged nodes horizontally using the circle-based padding.',
)
assert.match(
  page,
  /const y = clamp\(point\.y - dragging\.dy, graphNodeClampPadding, graphHeight - graphNodeClampPadding\)/,
  'Knowledge graph page should clamp dragged nodes vertically using the circle-based padding.',
)
assert.match(
  renderedEdgeBlock,
  /Math\.hypot\(dx, dy\)/,
  'Knowledge graph page should derive rendered edge geometry from circle-aware source and target vectors.',
)
assert.match(
  renderedEdgeBlock,
  /edgeAnchorRadius\(/,
  'Knowledge graph page should route rendered edge endpoints through a circular edge-anchor helper.',
)
assert.doesNotMatch(
  renderedEdgeBlock,
  /nodeWidth \/ 2/,
  'Knowledge graph page should not keep the old pill-width edge anchoring contract in the main edge path block.',
)
assert.doesNotMatch(
  mergeSolvedPositionsBlock,
  /const solved = solveLaneLayout\(/,
  'Knowledge graph page should not keep mergeSolvedPositions wired to solveLaneLayout as the main graph layout path.',
)
assert.doesNotMatch(
  page,
  /id="graph-grid"/,
  'Knowledge graph page should not keep the old high-contrast graph grid field.',
)
assert.doesNotMatch(page, /stats\.source_count/, 'Knowledge graph page should not read an undeclared source_count field from unified graph stats.')
assert.doesNotMatch(page, /Unified Graph|Unified knowledge graph workspace/, 'Knowledge graph page should not relocate the page headline into the floating controls shell.')
assert.doesNotMatch(page, /Graph Workbench/, 'Knowledge graph page should not keep the old workbench-first frame copy.')
