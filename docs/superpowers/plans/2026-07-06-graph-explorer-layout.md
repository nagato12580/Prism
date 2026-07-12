# Unified `/graph` Explorer Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `/graph` into a weakly convergent unified knowledge explorer with anti-overlap layout, focus-based readability, and clearer visual structure.

**Architecture:** Keep the current unified graph API and route intact, but replace the page's static lane spacing with a lane-constrained frontend layout pass. Add focus-tier derivation and explorer actions in the page layer, then refine the canvas rendering with lane fields, distance-based hierarchy, and deterministic layout behavior.

**Tech Stack:** React, TypeScript, Vite, existing `KnowledgeGraphPage.tsx`, Node-based frontend smoke tests

---

## File Structure

- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
  - Main integration point for the explorer behavior, layout solver, canvas rendering, focus hierarchy, and action controls.
- Create: `frontend/src/pages/__tests__/graph-layout-fixture.ts` only if extraction becomes necessary during implementation
  - Optional helper fixture for deterministic layout validation if the page file becomes too large.
- Create: `frontend/tests/unified-graph-explorer-layout.test.mjs`
  - Static contract smoke test for new explorer controls, layout helpers, and copy.
- Modify: `frontend/tests/unified-graph-page.test.mjs`
  - Extend existing smoke checks so the previous unified graph migration assertions still hold.

This plan intentionally keeps the change frontend-only. No backend files should be modified.

## Task 1: Add Explorer Layout Contract Tests

**Files:**
- Create: `frontend/tests/unified-graph-explorer-layout.test.mjs`
- Modify: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Write the failing explorer smoke test**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')

assert.match(page, /function solveLaneLayout\(/, 'Graph page should define a lane layout solver.')
assert.match(page, /重新聚焦/, 'Graph page should expose a refocus action.')
assert.match(page, /展开更多关联/, 'Graph page should expose an expand-more action.')
assert.match(page, /distanceTier/, 'Graph page should derive visual tiers from focus distance.')
assert.match(page, /lane-field/, 'Graph page should render lane field visuals.')
```

- [ ] **Step 2: Run the explorer smoke test to verify it fails**

Run: `node --test frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: FAIL because the solver, actions, and lane-field markers do not exist yet.

- [ ] **Step 3: Extend the existing unified graph smoke test to preserve current guarantees**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const api = readFileSync(resolve(root, 'src/app/api.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/KnowledgeGraphPage.tsx'), 'utf8')

assert.match(api, /export const unifiedGraphApi/, 'API client should expose unifiedGraphApi.')
assert.match(api, /\/unified-graph/, 'Unified graph client should point at \\/unified-graph.')
assert.match(page, /实体中心/, 'Knowledge graph page should expose the entity-centric view.')
assert.match(page, /来源中心/, 'Knowledge graph page should expose the source-centric view.')
assert.doesNotMatch(page, /CKP Workbench/, 'Knowledge graph page should not restore CKP Workbench.')
```

- [ ] **Step 4: Run both smoke tests**

Run: `node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: FAIL only on the new explorer assertions.

- [ ] **Step 5: Commit the failing-test checkpoint**

```bash
git add frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "test(graph): add explorer layout smoke tests"
```

## Task 2: Replace Static Lane Spacing With Lane-Constrained Layout

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Add a deterministic lane layout solver in the page file**

```tsx
type LayoutNode = UnifiedGraphNode & {
  neighbors: string[]
}

type LayoutResult = Record<string, { x: number; y: number }>

function laneCenter(type: UnifiedGraphNodeType, view: UnifiedGraphView) {
  if (view === 'entity') {
    if (type === 'entity') return 240
    if (type === 'document_chunk') return 650
    return 1030
  }
  if (type === 'document_chunk') return 220
  if (type === 'personal_asset_unit') return 640
  return 1020
}

function solveLaneLayout(nodes: UnifiedGraphNode[], edges: UnifiedGraphEdge[], view: UnifiedGraphView): LayoutResult {
  const byId = new Map(nodes.map((node) => [node.id, node] as const))
  const graphNodes: LayoutNode[] = nodes.map((node) => ({
    ...node,
    neighbors: edges.flatMap((edge) => {
      if (edge.source === node.id) return [edge.target]
      if (edge.target === node.id) return [edge.source]
      return []
    }),
  }))

  const positions: LayoutResult = Object.fromEntries(
    graphNodes.map((node, index) => [
      node.id,
      {
        x: laneCenter(node.type, view),
        y: 110 + index * 76,
      },
    ]),
  )

  for (let iteration = 0; iteration < 18; iteration += 1) {
    for (const node of graphNodes) {
      const current = positions[node.id]
      const idealX = laneCenter(node.type, view)
      let nextX = current.x + (idealX - current.x) * 0.22
      let nextY = current.y

      for (const other of graphNodes) {
        if (other.id === node.id) continue
        const otherPos = positions[other.id]
        const dx = current.x - otherPos.x
        const dy = current.y - otherPos.y
        const distance = Math.max(Math.hypot(dx, dy), 1)
        const minDistance = 76
        if (distance < minDistance) {
          const push = (minDistance - distance) * 0.18
          nextX += (dx / distance) * push
          nextY += (dy / distance) * push
        }
      }

      for (const neighborId of node.neighbors) {
        const neighbor = positions[neighborId]
        if (!neighbor) continue
        nextY += (neighbor.y - current.y) * 0.03
      }

      positions[node.id] = {
        x: clamp(nextX, 120, graphWidth - 120),
        y: clamp(nextY, 88, graphHeight - 88),
      }
    }
  }

  return positions
}
```

- [ ] **Step 2: Replace the old `createInitialPositions` / `mergePositions` flow with the solver**

```tsx
function mergeSolvedPositions(
  nodes: UnifiedGraphNode[],
  edges: UnifiedGraphEdge[],
  current: PositionMap,
  view: UnifiedGraphView,
  pinnedIds: Set<string>,
): PositionMap {
  const solved = solveLaneLayout(nodes, edges, view)
  const next: PositionMap = {}
  for (const node of nodes) {
    const key = positionKey(view, node.id)
    next[key] = pinnedIds.has(node.id) && current[key] ? current[key] : solved[node.id]
  }
  return next
}
```

- [ ] **Step 3: Track manually dragged nodes as pinned positions**

```tsx
const [pinnedNodeIds, setPinnedNodeIds] = useState<Record<UnifiedGraphView, string[]>>({
  entity: [],
  source: [],
})

const pinnedIdSet = useMemo(() => new Set(pinnedNodeIds[view]), [pinnedNodeIds, view])
```

And in pointer move completion logic:

```tsx
const stopDragging = () => {
  if (dragging?.id) {
    setPinnedNodeIds((current) => ({
      ...current,
      [view]: Array.from(new Set([...current[view], dragging.id])),
    }))
  }
  setDragging(null)
}
```

- [ ] **Step 4: Load data using solved positions instead of static positions**

```tsx
const data = await unifiedGraphApi.get({
  view: nextView,
  q: nextQuery.trim() || undefined,
  limit: 60,
})
setPayload(data)
setPositions((current) => ({
  ...current,
  ...mergeSolvedPositions(data.nodes, data.edges, current, nextView, new Set(pinnedNodeIds[nextView])),
}))
```

- [ ] **Step 5: Run the explorer smoke tests**

Run: `node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: FAIL only on the still-missing explorer actions and visual-tier assertions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-explorer-layout.test.mjs frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): add lane-constrained anti-overlap layout"
```

## Task 3: Add Weak-Convergence Focus Tiers and Explorer Actions

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Derive graph distance tiers from the selected node**

```tsx
type DistanceTier = 'focus' | 'near' | 'mid' | 'far'

function buildDistanceMap(selectedId: string | null, edges: UnifiedGraphEdge[]) {
  const adjacency = new Map<string, string[]>()
  for (const edge of edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target])
    adjacency.set(edge.target, [...(adjacency.get(edge.target) ?? []), edge.source])
  }
  const distances = new Map<string, number>()
  if (!selectedId) return distances
  const queue: Array<{ id: string; depth: number }> = [{ id: selectedId, depth: 0 }]
  while (queue.length) {
    const current = queue.shift()
    if (!current || distances.has(current.id)) continue
    distances.set(current.id, current.depth)
    for (const neighbor of adjacency.get(current.id) ?? []) {
      if (!distances.has(neighbor)) queue.push({ id: neighbor, depth: current.depth + 1 })
    }
  }
  return distances
}

function distanceTier(distance: number | undefined): DistanceTier {
  if (distance === 0) return 'focus'
  if (distance === 1) return 'near'
  if (distance === 2) return 'mid'
  return 'far'
}
```

- [ ] **Step 2: Add `重新聚焦` and `展开更多关联` actions**

```tsx
const [expandedNodeIds, setExpandedNodeIds] = useState<string[]>([])

const refocusSelection = () => {
  if (!selected) return
  const expanded = new Set(expandedNodeIds)
  expanded.add(selected.id)
  setExpandedNodeIds(Array.from(expanded))
  setPositions((current) => ({
    ...current,
    ...mergeSolvedPositions(payload?.nodes ?? [], payload?.edges ?? [], current, view, pinnedIdSet),
  }))
}

const expandMoreNeighbors = () => {
  if (!selected) return
  setExpandedNodeIds((current) => Array.from(new Set([...current, selected.id])))
}
```

- [ ] **Step 3: Use tier-aware filtering and emphasis instead of flat rendering**

```tsx
const distanceMap = useMemo(
  () => buildDistanceMap(selected?.id ?? null, payload?.edges ?? []),
  [payload?.edges, selected?.id],
)

function nodeOpacity(nodeId: string) {
  switch (distanceTier(distanceMap.get(nodeId))) {
    case 'focus':
      return 1
    case 'near':
      return 0.98
    case 'mid':
      return 0.72
    default:
      return 0.34
  }
}
```

- [ ] **Step 4: Add the new explorer action buttons to the canvas toolbar**

```tsx
<button
  type="button"
  onClick={refocusSelection}
  disabled={!selected}
  className="inline-flex h-8 items-center justify-center rounded-lg border border-[var(--prism-line)] px-3 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
>
  重新聚焦
</button>
<button
  type="button"
  onClick={expandMoreNeighbors}
  disabled={!selected}
  className="inline-flex h-8 items-center justify-center rounded-lg border border-[var(--prism-line)] px-3 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
>
  展开更多关联
</button>
```

- [ ] **Step 5: Run the smoke tests**

Run: `node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-explorer-layout.test.mjs frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): add explorer focus tiers and local actions"
```

## Task 4: Improve Visual Hierarchy With Lane Fields and Focus Styling

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Add semantic lane-field backgrounds to the SVG**

```tsx
<g aria-label="lane-field">
  {(['entity', 'document_chunk', 'personal_asset_unit'] as UnifiedGraphNodeType[]).map((type) => {
    const meta = getNodeMeta(type)
    const center = laneCenter(type, view)
    return (
      <rect
        key={type}
        x={center - 150}
        y={54}
        width={300}
        height={graphHeight - 108}
        rx={28}
        fill={meta.fill}
        opacity={0.35}
        pointerEvents="none"
      />
    )
  })}
</g>
```

- [ ] **Step 2: Make node rendering tier-aware**

```tsx
function tierScale(tier: DistanceTier) {
  if (tier === 'focus') return 1.08
  if (tier === 'near') return 1
  if (tier === 'mid') return 0.96
  return 0.92
}
```

And apply in `GraphNode`:

```tsx
transform={`translate(${node.x - nodeWidth / 2}, ${node.y - nodeHeight / 2}) scale(${tierScale(tier)})`}
opacity={nodeOpacity(node.id)}
```

- [ ] **Step 3: Make edge rendering tier-aware**

```tsx
function edgeOpacity(edge: UnifiedGraphEdge) {
  const sourceDistance = distanceMap.get(edge.source)
  const targetDistance = distanceMap.get(edge.target)
  const nearest = Math.min(sourceDistance ?? 9, targetDistance ?? 9)
  if (nearest === 0) return 0.98
  if (nearest === 1) return 0.82
  if (nearest === 2) return 0.5
  return 0.18
}
```

Use it in the `<path>`:

```tsx
opacity={edgeOpacity(edge)}
```

- [ ] **Step 4: Add clearer inspector copy for explorer focus**

```tsx
<p className="mt-1 text-xs leading-5 text-slate-500">
  {view === 'entity'
    ? '当前聚焦于实体网络，右侧优先展示与该节点最近的来源证据和语义连接。'
    : '当前聚焦于来源网络，右侧优先展示与该来源最近的实体和上下文连接。'}
</p>
```

- [ ] **Step 5: Run smoke tests again**

Run: `node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-explorer-layout.test.mjs frontend/tests/unified-graph-page.test.mjs
git commit -m "style(graph): add lane fields and focus hierarchy"
```

## Task 5: Verification and Regression Pass

**Files:**
- Verify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Verify: `frontend/tests/unified-graph-page.test.mjs`
- Verify: `frontend/tests/unified-graph-explorer-layout.test.mjs`
- Verify: `frontend/src/app/routes.tsx`

- [ ] **Step 1: Run explorer smoke tests**

Run: `node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs`
Expected: PASS

- [ ] **Step 2: Run frontend production build**

Run: `cmd /c npm run build`
Expected: Vite build succeeds without TypeScript errors.

- [ ] **Step 3: Verify the `/graph` route still points to the same page**

Run: `rg -n "path: 'graph'" frontend/src/app/routes.tsx`
Expected: one match pointing to `KnowledgeGraphPage`

- [ ] **Step 4: Verify old CKP/PKU primary copy did not reappear**

Run: `rg -n "CKP Workbench|查看 PKU 网络|全局 CKP 主题网络" frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests`
Expected: no matches in `KnowledgeGraphPage.tsx`; legacy references only remain in compatibility files or unrelated tests.

- [ ] **Step 5: Commit the verification checkpoint**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "test(graph): verify explorer layout regression coverage"
```

## Self-Review

**1. Spec coverage**

- Lane-constrained anti-overlap layout: covered by Task 2.
- Weakly convergent explorer behavior: covered by Task 3.
- Lane-field visual structure and node/edge hierarchy: covered by Task 4.
- Frontend-only scope with existing unified API preserved: enforced throughout file structure and tasks.
- Route continuity and regression coverage: covered by Task 5.

**2. Placeholder scan**

- No `TODO`, `TBD`, or “implement later” placeholders remain.
- Every code-changing task includes concrete snippets.
- Every test step has an exact command and expected result.

**3. Type consistency**

- `UnifiedGraphNode`, `UnifiedGraphEdge`, `UnifiedGraphView`, `PositionMap`, and the new `DistanceTier` names are consistent across tasks.
- Explorer action labels are consistently `重新聚焦` and `展开更多关联`.
- Layout helper naming consistently uses `solveLaneLayout` and `mergeSolvedPositions`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-06-graph-explorer-layout.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
