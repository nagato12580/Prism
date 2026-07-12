# Graph Free Scatter Circular Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the `/graph` canvas into a full-canvas free scatter graph with circular nodes, reduced overlap, detached label strategy, and preserved unified graph inspector/shell behavior.

**Architecture:** Keep the current unified graph page shell, floating controls, and inspector overlay intact, but replace the lane-based graph placement and pill-node rendering with a deterministic free-scatter layout plus circular SVG nodes. Separate the work into test contract updates, layout solver replacement, circular node rendering, label/edge recalibration, and final verification so each slice can be reviewed independently.

**Tech Stack:** React, TypeScript, Vite SSR tests, Tailwind utility classes, SVG rendering in `KnowledgeGraphPage.tsx`.

---

## File Structure

### Primary files to modify

- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
  - Owns the graph layout solver, SVG node/edge rendering, selection logic, and overlay shell.
- Modify: `frontend/tests/unified-graph-page.test.mjs`
  - Source-level graph rendering contract checks.
- Modify: `frontend/tests/unified-graph-explorer-layout.test.mjs`
  - Runtime layout contract checks for closed/open inspector and graph-stage behavior.
- Modify: `frontend/tests/graph-workbench.test.mjs`
  - Runtime shell checks that should keep passing after the graph internals change.

### Secondary files to inspect while implementing

- Inspect: `frontend/src/index.css`
  - Only if circular node / label motion polish needs CSS hooks beyond what already exists.

No backend files or API contracts should change for this work.

---

### Task 1: Redefine the graph rendering contract around free scatter and circular nodes

**Files:**
- Modify: `frontend/tests/unified-graph-page.test.mjs`
- Modify: `frontend/tests/unified-graph-explorer-layout.test.mjs`
- Inspect: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Update the source-level graph contract test**

In `frontend/tests/unified-graph-page.test.mjs`, keep the existing shell assertions, then replace lane/pill-specific assumptions with free-scatter/circle-oriented assertions like:

```js
assert.match(page, /data-testid="unified-graph-page"/, 'Knowledge graph page should keep the unified graph shell.')
assert.match(page, /data-testid="graph-floating-controls"/, 'Knowledge graph page should keep the floating controls shell.')
assert.match(page, /function solveFreeScatterLayout\(/, 'Knowledge graph page should define a free scatter layout solver.')
assert.match(page, /function relaxScatterLayout\(/, 'Knowledge graph page should define a scatter relaxation pass.')
assert.match(page, /const nodeRadius = /, 'Knowledge graph page should define circular node radius rendering.')
assert.match(page, /<circle/, 'Knowledge graph page should render circular node primitives.')
assert.doesNotMatch(page, /width=\\{nodeWidth\\}[\\s\\S]*height=\\{nodeHeight\\}[\\s\\S]*rx=\\{nodeRadius\\}/, 'Knowledge graph page should no longer rely on pill-body rect rendering for visible nodes.')
assert.doesNotMatch(page, /function solveLaneLayout\\(/, 'Knowledge graph page should no longer use the old lane layout solver as the main graph layout contract.')
```

- [ ] **Step 2: Update the runtime layout contract test**

In `frontend/tests/unified-graph-explorer-layout.test.mjs`, keep the overlay open/closed checks and add a lightweight runtime assertion that the old fixed lane framing is gone:

```js
assert.doesNotMatch(
  loadedHtml,
  /实体网络|文档证据|个人资产证据/,
  'Loaded graph markup should no longer foreground lane headings as the main graph layout structure.',
)
assert.match(
  loadedHtml,
  /Entity graph explorer|Source graph explorer/,
  'Loaded graph markup should still expose the graph explorer surface after scatter layout refactor.',
)
```

Use the existing `loadedPayload` render path already present in that test file.

- [ ] **Step 3: Run the two updated tests to capture red state**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
node frontend/tests/unified-graph-explorer-layout.test.mjs
```

Expected:

- both fail because the page still uses lane-based layout and pill nodes

- [ ] **Step 4: Commit the test-only red state**

```bash
git add frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "test(graph): redefine graph contract around free scatter circles"
```

---

### Task 2: Replace lane-based placement with deterministic free scatter layout

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Write the failing layout target as a local checklist comment**

Use this target inside `KnowledgeGraphPage.tsx` before editing:

```ts
// Scatter layout target:
// - remove lane-based x positioning as the main layout strategy
// - seed nodes across the full canvas
// - iteratively repel overlapping nodes
// - softly attract connected nodes
// - keep user-pinned positions stable
```

- [ ] **Step 2: Replace lane layout helpers with free scatter helpers**

In `frontend/src/pages/KnowledgeGraphPage.tsx`, replace the current lane-first helper chain:

- `laneX(...)`
- `distributeLaneSegment(...)`
- `solveLaneLayout(...)`
- lane-based `mergeSolvedPositions(...)`

with a deterministic free-scatter set shaped like:

```ts
function seededScatterPoint(index: number, count: number) {
  const angle = index * 2.399963229728653
  const radius = Math.sqrt((index + 0.5) / Math.max(1, count))
  const usableWidth = graphWidth - 160
  const usableHeight = graphHeight - 160
  return {
    x: graphWidth / 2 + Math.cos(angle) * radius * (usableWidth / 2),
    y: graphHeight / 2 + Math.sin(angle) * radius * (usableHeight / 2),
  }
}

function relaxScatterLayout(
  points: Array<{ id: string; x: number; y: number; pinned: boolean }>,
  edges: UnifiedGraphEdge[],
) {
  // apply a few deterministic repel + attract passes
}

function solveFreeScatterLayout(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  view: UnifiedGraphView,
  pinned: PinnedState,
  current: PositionMap,
) {
  // seed across canvas, preserve pinned nodes, then relax
}
```

The actual implementation should:

- preserve pinned positions for dragged nodes
- clamp final positions inside the canvas bounds
- use deterministic iteration order
- keep enough attraction that related nodes do not fly completely apart

- [ ] **Step 3: Rewire merged position calculation to the new solver**

Replace the old `mergeSolvedPositions(...)` body so it uses `solveFreeScatterLayout(...)` and produces fallback points from the scatter solver rather than lane centers:

```ts
const solved = solveFreeScatterLayout(nodes, edges, view, pinned, current)
return nodes.reduce((acc, node) => {
  const key = positionKey(view, node.id)
  acc[key] = solved[key] ?? current[key] ?? { x: graphWidth / 2, y: graphHeight / 2 }
  return acc
}, {} as PositionMap)
```

- [ ] **Step 4: Remove lane heading rendering from the SVG stage**

Delete the SVG lane heading block and the lane field group that visually encodes fixed columns. Keep the calmer background field from the previous redesign, but do not render lane labels like:

```tsx
<text ...>实体网络</text>
<text ...>文档证据</text>
<text ...>个人资产证据</text>
```

- [ ] **Step 5: Run the two scatter-layout contract tests**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
node frontend/tests/unified-graph-explorer-layout.test.mjs
```

Expected:

- `unified-graph-page` should still fail because the graph nodes are not circular yet
- `unified-graph-explorer-layout` should pass or move closer to passing depending on implementation

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "feat(graph): replace lane layout with free scatter positioning"
```

---

### Task 3: Convert graph nodes from pill bodies to circular nodes

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Write the failing circular-node expectation**

Keep the source-level assertion that the visible node body is no longer a rounded rect pill and that circle rendering exists. If needed, add one more assertion like:

```js
assert.match(page, /const nodeVisualRadius = /, 'Knowledge graph page should define circular visual node radius.')
assert.match(page, /<circle[\\s\\S]*cx=\\\"0\\\"|<circle[\\s\\S]*cx=\\{0\\}/, 'Knowledge graph page should render node bodies as circles centered on the node origin.')
```

- [ ] **Step 2: Refactor `GraphNode` rendering around circle geometry**

In `frontend/src/pages/KnowledgeGraphPage.tsx`, replace the current `GraphNode` pill rendering model based on:

```tsx
<rect width={nodeWidth} height={nodeHeight} ... />
<text x="36" y="..." ... />
```

with a circle-centered model shaped like:

```tsx
const nodeVisualRadius = active || focusRoot ? 26 : tier === 'near' ? 20 : 15
const nodeHitRadius = Math.max(nodeVisualRadius + 10, 24)

<g transform={`translate(${node.x} ${node.y}) scale(${scale})`}>
  {!showPrimaryLabel && !showMetaLabel ? <title>{node.label}</title> : null}
  <circle r={nodeHitRadius} fill="transparent" pointerEvents="all" />
  <circle r={nodeVisualRadius + haloRadius} ... />
  <circle r={nodeVisualRadius} ... />
  <circle r={6} ... />
</g>
```

The node should remain keyboard-focusable and clickable via the outer `<g>`.

- [ ] **Step 3: Update drag clamping to circle-based bounds**

Change the drag clamps from `nodeWidth / 2` and `nodeHeight / 2` to circle-based margins such as:

```ts
const clampPadding = 44
const x = clamp(point.x - dragging.dx, clampPadding, graphWidth - clampPadding)
const y = clamp(point.y - dragging.dy, clampPadding, graphHeight - clampPadding)
```

This avoids carrying pill geometry assumptions into scatter dragging.

- [ ] **Step 4: Run the source-level contract test**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
```

Expected:

- closer to passing, but may still fail until edge anchoring and label strategy are updated

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): render graph nodes as circles"
```

---

### Task 4: Re-anchor edges and detach labels from node bodies

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Test: `frontend/tests/graph-workbench.test.mjs`

- [ ] **Step 1: Replace rectangle-based edge endpoints with circle-based endpoints**

In the SVG edge block of `KnowledgeGraphPage.tsx`, replace:

```ts
const sx = source.x + (target.x >= source.x ? nodeWidth / 2 : -nodeWidth / 2)
const tx = target.x + (target.x >= source.x ? -nodeWidth / 2 : nodeWidth / 2)
```

with circle anchoring:

```ts
const dx = target.x - source.x
const dy = target.y - source.y
const distance = Math.max(1, Math.hypot(dx, dy))
const sourceRadius = nodeRenderRadius(source, sourceTier)
const targetRadius = nodeRenderRadius(target, targetTier)
const sx = source.x + (dx / distance) * sourceRadius
const sy = source.y + (dy / distance) * sourceRadius
const tx = target.x - (dx / distance) * targetRadius
const ty = target.y - (dy / distance) * targetRadius
```

Update the path command to use `sy` and `ty` as well.

- [ ] **Step 2: Rewrite label strategy for circle nodes**

In `GraphNode`, move visible labels outside the circle rather than inside it. Use a rule like:

```ts
const showPrimaryLabel = active || focusRoot || tier === 'near' || (node.type === 'entity' && tier === 'mid')
const showMetaLabel = active || focusRoot || tier === 'near'
```

Render visible labels beneath or beside the node:

```tsx
{showPrimaryLabel ? (
  <text y={nodeVisualRadius + 18} textAnchor="middle" ...>
    {truncate(node.label, showMetaLabel ? 18 : 20)}
  </text>
) : null}
{showMetaLabel ? (
  <text y={nodeVisualRadius + 31} textAnchor="middle" ...>
    {meta.label}
  </text>
) : null}
```

Preserve `<title>{node.label}</title>` fallback for hidden-label nodes.

- [ ] **Step 3: Update the source-level contract test to reflect detached labels**

Replace any remaining pill-text assumptions in `frontend/tests/unified-graph-page.test.mjs` with assertions like:

```js
assert.match(page, /textAnchor=\\\"middle\\\"|textAnchor=\\{\\'middle\\'\\}|textAnchor=\\{\"middle\"\\}/, 'Knowledge graph page should center detached circular-node labels.')
assert.match(page, /<title>\\{node\\.label\\}<\\/title>/, 'Knowledge graph page should keep a discoverability fallback for hidden node labels.')
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
node frontend/tests/graph-workbench.test.mjs
```

Expected:

- both pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs
git commit -m "feat(graph): re-anchor edges and detach circular node labels"
```

---

### Task 5: Verify scatter readability and complete frontend validation

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx` only if verification exposes final fit/spacing issues
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Test: `frontend/tests/graph-workbench.test.mjs`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Inspect the final spacing heuristics**

Before changing code, review whether these properties are present and coherent in `KnowledgeGraphPage.tsx`:

```ts
const minNodeSpacing = ...
const relaxationPasses = ...
const attractionStrength = ...
```

If names differ, make sure there is still one clear place where scatter density can be tuned.

- [ ] **Step 2: Make the smallest necessary spacing tweak**

If the graph still bunches too tightly after Tasks 2-4, make one final small calibration in the scatter solver only, such as:

- increase collision radius
- slightly reduce background node radius
- slightly increase repel force

Do not redesign the solver again in this step.

- [ ] **Step 3: Run the full focused frontend verification suite**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
node frontend/tests/graph-workbench.test.mjs
node frontend/tests/unified-graph-explorer-layout.test.mjs
frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json --noEmit
```

Expected:

- all test scripts exit `0`
- `tsc` exits `0`

- [ ] **Step 4: Manual browser verification**

Run:

```bash
http://127.0.0.1:5173/graph
```

Check:

- graph opens in full-canvas scatter mode
- node pills are gone and nodes render as circles
- nodes are visibly more spread than before
- selecting a node still opens the right inspector
- closing the inspector returns to the full scatter view
- search, zoom, and view toggle remain usable

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "feat(graph): finish free scatter circular graph rendering"
```

---

## Self-Review

### Spec coverage

- free scatter full-canvas layout: covered by Task 2
- circular nodes: covered by Task 3
- detached label strategy: covered by Task 4
- preserved shell / overlay behavior: preserved across Tasks 2-5 and checked by runtime tests
- reduced overlap / whole-graph visibility: covered by Task 2 and final tuning in Task 5

No spec requirement is left without an implementing task.

### Placeholder scan

- No `TODO`, `TBD`, or “similar to above” placeholders remain.
- Each task includes exact file paths and exact verification commands.

### Type consistency

- The plan consistently refers to `solveFreeScatterLayout`, `relaxScatterLayout`, `GraphNode`, `PositionMap`, and the existing unified graph types.
- All geometry changes consistently move from pill-based width/height math to circle radius math.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-graph-free-scatter-circular-nodes.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
