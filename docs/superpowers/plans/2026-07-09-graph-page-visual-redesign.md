# Graph Page Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `/graph` page into a graph-first dual-mode explorer with floating controls, a hidden-by-default inspector drawer, and a calmer visual graph surface that stays compatible with the existing unified graph API.

**Architecture:** Keep all backend contracts and most interaction logic in `frontend/src/pages/KnowledgeGraphPage.tsx`, but reshape the page shell from a dashboard layout into a full-canvas explorer. Preserve the current graph behavior and helper functions, while replacing the top workbench-heavy frame with floating overlays and a conditional inspector. Update focused frontend tests first so the redesign is protected by TDD and so the existing mojibake assertions stop fighting the new UI.

**Tech Stack:** React, TypeScript, Vite SSR tests, Tailwind utility classes, existing `lucide-react` icons, existing unified graph API payloads.

---

## File Structure

### Primary files to modify

- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
  - Owns the graph page shell, graph SVG rendering, floating controls, zoom actions, node selection, and inspector rendering.
- Modify: `frontend/tests/unified-graph-page.test.mjs`
  - Source-level assertions for shell, labels, and anti-regression copy.
- Modify: `frontend/tests/graph-workbench.test.mjs`
  - Runtime render assertions; should stop expecting the old workbench-first framing.
- Modify: `frontend/tests/unified-graph-explorer-layout.test.mjs`
  - Layout contract assertions; should be updated away from lane-heavy visuals and toward dual-mode explorer behaviors.

### Secondary files to inspect while implementing

- Inspect: `frontend/src/app/api.ts`
  - Confirms the graph view and payload types stay unchanged.

No new backend files are required for this redesign.

---

### Task 1: Fix the test contract so it matches the approved redesign direction

**Files:**
- Modify: `frontend/tests/unified-graph-page.test.mjs`
- Modify: `frontend/tests/graph-workbench.test.mjs`
- Modify: `frontend/tests/unified-graph-explorer-layout.test.mjs`
- Inspect: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Write the failing test updates for the new dual-mode shell**

Replace the core assertions in `frontend/tests/unified-graph-page.test.mjs` with:

```js
assert.match(page, /data-testid="unified-graph-page"/, 'Knowledge graph page should keep the unified graph page shell.')
assert.match(page, /实体视图/, 'Knowledge graph page should keep the entity-view toggle readable.')
assert.match(page, /来源视图/, 'Knowledge graph page should keep the source-view toggle readable.')
assert.match(page, /刷新图谱/, 'Knowledge graph page should keep the refresh action readable.')
assert.match(page, /选择一个节点，查看它在 unified graph 里的结构、来源证据和关联关系。/, 'Knowledge graph page should keep the empty inspector guidance.')
assert.match(page, /重新聚焦/, 'Knowledge graph page should keep the refocus action readable.')
assert.match(page, /文档分块/, 'Knowledge graph page should keep the document chunk label readable.')
assert.doesNotMatch(page, /Graph Workbench/, 'Knowledge graph page should not keep the old workbench-first frame copy.')
```

Replace the runtime assertions in `frontend/tests/graph-workbench.test.mjs` with:

```js
assert.match(html, /Unified knowledge graph workspace|统一图谱/, 'Knowledge graph page should render the graph page heading.')
assert.match(html, /刷新图谱/, 'Knowledge graph page should render the refresh action at runtime.')
assert.doesNotMatch(html, /Graph Workbench/, 'Knowledge graph page runtime should not foreground the old workbench shell.')
assert.doesNotMatch(html, /Community information/, 'Knowledge graph page runtime should not foreground old summary cards.')
```

Replace the layout assertions in `frontend/tests/unified-graph-explorer-layout.test.mjs` with:

```js
assert.match(page, /function solveLaneLayout\(/, 'Graph page should keep the layout solver until explicitly replaced.')
assert.match(page, /重新聚焦/, 'Graph page should expose a refocus action.')
assert.match(page, /展开更多关联/, 'Graph page should expose an expand-more action.')
assert.match(page, /floating|absolute/, 'Graph page should use floating overlay positioning for explorer controls.')
assert.match(page, /!selectedNode|selectedNode \\?/, 'Graph page should support a hidden-by-default inspector mode.')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/tests/unified-graph-page.test.mjs`

Expected: FAIL because the current page still contains the old workbench-heavy structure and old runtime copy.

- [ ] **Step 3: Run the other updated tests to capture current red state**

Run: `node frontend/tests/graph-workbench.test.mjs`

Expected: FAIL because runtime still surfaces `Graph Workbench` and summary cards.

Run: `node frontend/tests/unified-graph-explorer-layout.test.mjs`

Expected: FAIL because the page does not yet expose the new hidden-by-default inspector contract in code.

- [ ] **Step 4: Commit the test-only red state**

```bash
git add frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "test(graph): redefine graph page contract around dual-mode explorer shell"
```

---

### Task 2: Rebuild the page shell into a graph-first floating explorer

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Test: `frontend/tests/graph-workbench.test.mjs`

- [ ] **Step 1: Write the failing shell expectation in code comments or a local scratch note before editing**

Use this shell target as the implementation checklist:

```ts
// Shell target:
// - remove the heavyweight top header + Graph Workbench summary section
// - keep one canvas-first board
// - render top-left floating search/toggle/refresh
// - render top-right pending index capsule
// - render bottom-left node/edge capsule
// - render bottom-right zoom stack
```

- [ ] **Step 2: Replace the current header and summary sections with a single canvas-first shell**

In `frontend/src/pages/KnowledgeGraphPage.tsx`, replace the current outer layout beginning near:

```tsx
<div className="flex h-[calc(100vh-9rem)] min-h-0 flex-col gap-4 overflow-hidden" data-testid="unified-graph-page">
```

with a shell shaped like:

```tsx
<div className="flex h-[calc(100vh-9rem)] min-h-0 flex-col overflow-hidden" data-testid="unified-graph-page">
  {error ? (
    <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {error}
    </div>
  ) : null}

  <section className="relative min-h-0 flex-1 overflow-hidden rounded-[28px] border border-white/70 bg-[radial-gradient(circle_at_top_right,_rgba(242,185,40,0.12),_transparent_20%),radial-gradient(circle_at_bottom_left,_rgba(88,168,216,0.10),_transparent_22%),#f6f6f2] shadow-[0_24px_60px_rgba(15,23,42,0.08)]">
    {/* floating controls */}
    {/* graph canvas */}
    {/* conditional inspector */}
  </section>
</div>
```

- [ ] **Step 3: Implement floating controls instead of top dashboard bars**

Add floating control blocks like:

```tsx
<div className="absolute left-5 top-5 z-20 flex items-center gap-2 rounded-[18px] border border-slate-200/70 bg-white/90 px-3 py-2 shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur">
  <div className="inline-flex rounded-full bg-slate-100 p-1">
    {/* entity/source toggle buttons */}
  </div>
  <div className="relative w-[22rem] max-w-[42vw]">
    {/* search input */}
  </div>
  <button type="button" onClick={() => void loadGraph()}>{loading ? <Loader2 ... /> : <RefreshCw ... />}</button>
</div>
```

And add:

```tsx
<div className="absolute right-5 top-5 z-20 rounded-[18px] border border-slate-200/70 bg-white/90 px-4 py-3 text-sm shadow-[0_16px_40px_rgba(15,23,42,0.08)] backdrop-blur">
  <div className="flex items-center gap-2 text-slate-700">
    <Boxes size={15} />
    <span>{pendingIndexCount} 待索引</span>
  </div>
</div>
```

Where `pendingIndexCount` is derived from existing payload or fallback `0` if not available:

```ts
const pendingIndexCount = payload?.stats.source_count ?? 0
```

- [ ] **Step 4: Run the two shell-focused tests**

Run: `node frontend/tests/unified-graph-page.test.mjs`

Expected: PASS

Run: `node frontend/tests/graph-workbench.test.mjs`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs
git commit -m "feat(graph): replace dashboard shell with floating explorer frame"
```

---

### Task 3: Convert the inspector into a hidden-by-default right overlay drawer

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Write the failing inspector-mode assertion**

Use this assertion target in the page structure:

```tsx
{selectedNode ? (
  <GraphInspector ... />
) : null}
```

and keep the empty-state guidance inside the canvas itself instead of a permanently reserved right column.

- [ ] **Step 2: Refactor the page body to remove the fixed two-column grid**

Replace the current two-column frame:

```tsx
<div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
```

with a single relative stage:

```tsx
<div className="relative h-full w-full">
  {/* canvas */}
  {selectedNode ? (
    <div className="absolute inset-y-4 right-4 z-30 w-[24rem] max-w-[calc(100%-2rem)]">
      <GraphInspector ... />
    </div>
  ) : null}
</div>
```

- [ ] **Step 3: Update `GraphInspector` to work as an overlay card rather than a full column**

Change its root container from:

```tsx
<aside className="prism-panel flex min-h-0 flex-col rounded-lg p-5">
```

to something shaped like:

```tsx
<aside className="flex h-full min-h-0 flex-col rounded-[24px] border border-slate-200/70 bg-white/95 p-5 shadow-[0_30px_60px_rgba(15,23,42,0.12)] backdrop-blur">
```

And remove the old fallback aside branch from `GraphInspector`; render the empty-state message in the graph shell instead:

```tsx
{!selectedNode ? (
  <div className="pointer-events-none absolute inset-x-0 bottom-24 z-10 flex justify-center">
    <div className="rounded-full border border-slate-200/70 bg-white/88 px-4 py-2 text-sm text-slate-500 shadow-sm backdrop-blur">
      选择一个节点，查看它在 unified graph 里的结构、来源证据和关联关系。
    </div>
  </div>
) : null}
```

- [ ] **Step 4: Run layout test**

Run: `node frontend/tests/unified-graph-explorer-layout.test.mjs`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "feat(graph): make inspector a conditional overlay drawer"
```

---

### Task 4: Restyle the graph surface, nodes, edges, and labels toward the approved reference

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`

- [ ] **Step 1: Write the failing visual-structure expectation**

Add an assertion in `frontend/tests/unified-graph-page.test.mjs`:

```js
assert.doesNotMatch(page, /Graph Workbench|Community information|Suspicious entity diagnostics/, 'Knowledge graph page should not keep the old card summary copy.')
assert.match(page, /rounded-\\[28px\\]|backdrop-blur|shadow-\\[0_24px_60px/, 'Knowledge graph page should use the floating explorer visual treatment.')
```

- [ ] **Step 2: Reduce lane dominance and soften the background field**

In the SVG container section, replace the hard grid and high-contrast lane field with softer field layers:

```tsx
<rect x="0" y="0" width={graphWidth} height={graphHeight} fill="url(#graph-paper)" />
```

and define:

```tsx
<radialGradient id="graph-glow-a" cx="78%" cy="14%" r="34%">
  <stop offset="0%" stopColor="#f2b928" stopOpacity="0.16" />
  <stop offset="100%" stopColor="#f2b928" stopOpacity="0" />
</radialGradient>
<radialGradient id="graph-glow-b" cx="20%" cy="78%" r="34%">
  <stop offset="0%" stopColor="#58a8d8" stopOpacity="0.12" />
  <stop offset="100%" stopColor="#58a8d8" stopOpacity="0" />
</radialGradient>
<pattern id="graph-paper" width="40" height="40" patternUnits="userSpaceOnUse">
  <rect width="40" height="40" fill="#f8f8f5" />
  <circle cx="20" cy="20" r="0.7" fill="#d9dee5" opacity="0.35" />
</pattern>
```

Keep lane positioning logic for now, but lower lane visual contrast by reducing `laneFieldStyle()` opacities and by avoiding strong filled lane bands.

- [ ] **Step 3: Restyle nodes and edges to be calmer and more hierarchical**

Update `edgeStyle()` so defaults are thinner and less saturated:

```ts
return {
  stroke: focused ? '#6b7280' : strong ? '#94a3b8' : medium ? '#cbd5e1' : faded ? '#e2e8f0' : '#eef2f7',
  strokeWidth: focused ? 2.2 : strong ? 1.7 : medium ? 1.2 : faded ? 0.95 : 0.8,
  opacity: focused ? 0.9 : strong ? 0.62 : medium ? 0.3 : faded ? 0.15 : 0.08,
}
```

Adjust node circles and halos inside the SVG node rendering block to:

```tsx
const radius = tier === 'focus' ? 24 : tier === 'near' ? 18 : 13
const haloOpacity = tier === 'focus' ? 0.18 : tier === 'near' ? 0.1 : 0
```

Also gate text labels more aggressively:

```ts
const showNodeLabel = tier === 'focus' || tier === 'near' || (tier === 'mid' && degree >= 3)
```

- [ ] **Step 4: Run the source-level contract test**

Run: `node frontend/tests/unified-graph-page.test.mjs`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs
git commit -m "feat(graph): restyle graph surface for calm full-canvas exploration"
```

---

### Task 5: Polish interaction states and verify the full frontend graph page

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Test: `frontend/tests/unified-graph-page.test.mjs`
- Test: `frontend/tests/graph-workbench.test.mjs`
- Test: `frontend/tests/unified-graph-explorer-layout.test.mjs`

- [ ] **Step 1: Add minimal motion and focus-state polish**

In `frontend/src/pages/KnowledgeGraphPage.tsx`, add transition classes to floating controls and inspector:

```tsx
className="... transition-[transform,opacity,box-shadow] duration-200 ease-out ..."
```

and for the inspector mount:

```tsx
className="absolute inset-y-4 right-4 z-30 w-[24rem] max-w-[calc(100%-2rem)] animate-[graphInspectorIn_180ms_ease-out]"
```

Add a local style block or existing CSS hook for:

```css
@keyframes graphInspectorIn {
  from { opacity: 0; transform: translateX(16px); }
  to { opacity: 1; transform: translateX(0); }
}
```

If the repo avoids inline CSS animation blocks, move this to `frontend/src/index.css` instead and update the file list accordingly.

- [ ] **Step 2: Verify keyboard/empty-state usability remains intact**

Check these code paths still exist:

```tsx
if (event.key === 'Enter') void loadGraph()
```

```tsx
onClick={() => onSelectNode(relatedNode.id)}
```

```tsx
onClick={onRefocus}
```

Do not remove them while polishing visual classes.

- [ ] **Step 3: Run the focused frontend verification suite**

Run:

```bash
node frontend/tests/unified-graph-page.test.mjs
node frontend/tests/graph-workbench.test.mjs
node frontend/tests/unified-graph-explorer-layout.test.mjs
frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json --noEmit
```

Expected:

- all three test scripts print no assertion failures
- `tsc` exits cleanly with code `0`

- [ ] **Step 4: Manual browser verification**

Run:

```bash
http://127.0.0.1:5173/graph
```

Check:

- default page opens in clean graph-first mode
- search and mode switch float top-left
- node/edge count floats bottom-left
- zoom controls float bottom-right
- selecting a node opens the right drawer
- clicking empty space closes the drawer
- graph remains visible during inspection

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs frontend/tests/unified-graph-explorer-layout.test.mjs
git commit -m "feat(graph): finish dual-mode visual redesign polish"
```

---

## Self-Review

### Spec coverage

- graph-first shell: covered by Task 2
- hidden-by-default inspector: covered by Task 3
- calmer graph aesthetics: covered by Task 4
- motion polish and validation: covered by Task 5
- test-first workflow: covered by Task 1 onward

No spec sections are left without at least one implementing task.

### Placeholder scan

- No `TBD`, `TODO`, or "write tests for the above" placeholders remain.
- Each task names exact files and exact commands.

### Type consistency

- Uses existing `selectedNode`, `loadGraph`, `GraphInspector`, `solveLaneLayout`, `edgeStyle`, and current tests.
- No new backend contracts or invented payload types are introduced.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-09-graph-page-visual-redesign.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
