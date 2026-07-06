# Unified `/graph` Explorer Layout Design

## 1. Goal

Optimize `http://localhost:5173/graph` so the unified graph is readable as node count grows.

This phase is focused on frontend presentation and interaction:

- reduce node overlap
- preserve the unified graph semantics already introduced
- make `/graph` behave like a knowledge explorer instead of a dense static graph dump
- keep both views:
  - `实体中心`
  - `来源中心`

The goal is not to change retrieval logic or backend graph meaning. The goal is to make the current unified graph explorable.

## 2. User Outcome

After this redesign:

- users can open `/graph` without immediately seeing stacked or unreadable nodes
- the graph still shows a relatively broad picture of the connected space
- selecting a node makes the nearby structure easier to read without collapsing the entire graph
- the page feels like a unified knowledge explorer, not a CKP/PKU governance screen and not a generic SVG debug view

## 3. Product Direction

The user explicitly chose:

- `/graph` should be an explorer-first page
- default behavior should be weakly convergent rather than heavily collapsed
- the page should still try to show a broad graph, but guide attention toward the active node and its near neighborhood

That means:

- do not default to a tiny local subgraph only
- do not keep the current static equal-spacing lane layout
- do not attempt a fully freeform all-node force graph that loses type structure

## 4. Current Problem

The current unified graph page still uses a mostly static lane layout:

- node types are assigned to fixed columns
- nodes in a column are distributed with simple vertical spacing
- positions are merged and preserved, but no true collision avoidance exists

This causes:

- overlapping or near-overlapping nodes as counts rise
- edge clutter around dense neighborhoods
- poor focus when a user selects a node
- a graph that technically renders but becomes hard to interpret

## 5. Design Principles

### 5.1 Preserve semantic structure

The graph should still communicate type structure at a glance.

The page should preserve the mental model of three semantic lanes:

- `entity`
- `document_chunk`
- `personal_asset_unit`

This should remain true in both `实体中心` and `来源中心`, though the lane emphasis may differ.

### 5.2 Prefer guided exploration over hard collapse

The user chose weak convergence.

So the graph should:

- show a meaningful amount of context by default
- avoid hiding most of the graph behind aggressive folding
- rely on visual hierarchy and focus behavior instead of heavy default pruning

### 5.3 Solve overlap at layout level first

Node overlap should not be treated as a styling issue alone.

The main fix must come from layout behavior:

- collision avoidance
- edge-length constraints
- lane-aware positioning
- local relaxation around active regions

Visual styling should support readability after layout improves, not replace it.

## 6. Recommended Approach

### 6.1 Chosen direction

Use a `lane-constrained collision layout`.

This keeps the current semantic lane model, but replaces the static per-lane equal spacing with a lightweight constrained layout pass in the frontend.

### 6.2 Why this approach

This is the best fit because it balances three needs:

- keep the unified graph understandable by type
- reduce overlap at the source
- avoid turning `/graph` into a generic force-directed graph tool

### 6.3 Rejected alternatives

#### A. Keep current layout and only add styling fixes

Not sufficient.

This might reduce pain temporarily using:

- transparency
- smaller nodes
- stronger hover
- curved edges

But it would not fix true overlap once density rises.

#### B. Fully freeform force-directed graph

Too much semantic loss.

This would likely reduce overlap well, but users would lose the immediate understanding of:

- what is an entity
- what is a document source
- what is a personal asset source

#### C. Strongly collapsed local-only explorer

Too restrictive for the requested behavior.

The user explicitly wants weak convergence, so the page should still expose a broader context by default.

## 7. Layout Design

### 7.1 Lane-constrained layout

Each node gets a target lane based on type:

- `entity`
- `document_chunk`
- `personal_asset_unit`

Each lane has a preferred horizontal band.

Nodes are then laid out using a constrained relaxation pass:

- nodes keep a strong preference for their lane x-position
- nodes repel nearby nodes to prevent overlap
- connected nodes attract each other with moderate strength
- all nodes remain bounded within the canvas

This produces a graph that is ordered, but not rigid.

### 7.2 View-specific lane emphasis

Both views use the same node types, but the visual emphasis changes.

In `实体中心`:

- the entity lane is treated as the visual backbone
- source lanes are secondary evidence lanes

In `来源中心`:

- source lanes become visually primary
- the entity lane becomes the connector lane

This is a weighting change, not a different graph renderer.

### 7.3 Initial layout and re-layout behavior

On first load:

- run a full automatic layout pass for the active view

On node drag:

- preserve the user-adjusted position
- keep it stable across light updates where possible

On explicit actions such as:

- switching view
- changing search query
- clicking `重新排布`

run a broader layout recomputation.

### 7.4 Local relaxation near focus

When a node is selected:

- the graph should not collapse into a tiny neighborhood
- instead, the selected node and its one-hop neighborhood should be given more spatial room

This means:

- nearby nodes can be slightly pushed apart
- unrelated distant nodes can yield visual priority and space
- the selected neighborhood becomes easier to inspect without hiding the rest of the graph

## 8. Interaction Design

### 8.1 Default state

The default graph should remain broad rather than narrow.

The page should still try to show:

- core matched nodes
- directly related nodes
- some surrounding graph context

But it should visually tier them.

### 8.2 Focus behavior

When a user selects a node:

- the node becomes the clear visual focus
- one-hop neighbors are highlighted
- two-hop context stays visible but softer
- unrelated nodes and edges recede visually

This is a focus enhancement, not a hard filter.

### 8.3 Explorer actions

Add two explorer-oriented actions:

- `重新聚焦`
  - recompute layout around the current node, giving its neighborhood more room
- `展开更多关联`
  - incrementally reveal more adjacent nodes for the active node

These actions support exploration without forcing the whole graph open all at once.

### 8.4 Reset behavior

Keep `重新排布` as the full-layout reset action.

This remains distinct from `重新聚焦`:

- `重新排布` resets the whole visible graph layout
- `重新聚焦` is local to the active node's neighborhood

## 9. Visual Design

### 9.1 Overall visual direction

The page should look like a unified knowledge explorer rather than a governance admin panel.

Recommended direction:

- light workspace base
- structured lanes
- restrained color coding
- strong focus hierarchy

The design should remain functional and technical, but more deliberate and legible.

### 9.2 Lane fields

Replace the plain neutral canvas feeling with very subtle lane fields.

Each semantic lane can have:

- a faint tinted background band
- or a soft atmospheric glow strip

This is not decorative.

It should help the user parse the graph from a distance and understand the three object classes before reading labels.

### 9.3 Node hierarchy

Node rendering should be tiered:

- active node: largest and highest contrast
- one-hop nodes: standard size and contrast
- more distant nodes: slightly smaller or softer

Each node should prioritize:

- readable title
- type badge
- minimal secondary information

Nodes should feel like compact readable objects, not generic pills.

### 9.4 Edge hierarchy

Edges should be tiered by relevance:

- focus edges: stronger opacity and width
- background edges: lighter, thinner
- edge type differences should be present but restrained

Recommended distinctions:

- `related_to`: stronger semantic relation treatment
- `mentioned_in` / `mentions_entity`: evidence-link treatment
- `shares_entity_with`: softer secondary relation treatment if present

### 9.5 Focus transition

Selection should cause a noticeable scene change:

- active node gains stronger outline/shadow
- adjacent nodes come forward
- unrelated content fades back

The key requirement is that focus must feel spatial, not just cosmetic.

## 10. Component-Level Scope

Primary file:

- `frontend/src/pages/KnowledgeGraphPage.tsx`

Likely additions within the same page or nearby extracted helpers:

- lane-constrained layout helper
- collision / relaxation utilities
- focus-state derivation
- lane background rendering
- local action controls such as `重新聚焦` and `展开更多关联`

No backend contract change is required for this phase.

## 11. Data and State Expectations

This redesign assumes the current unified graph payload remains the same:

- nodes
- edges
- stats
- focus

Frontend will derive additional presentation-only state such as:

- layout positions
- pinned nodes
- active neighborhood
- expansion state
- visual depth tier

These should remain frontend concerns.

## 12. Error Handling and Empty States

If the graph is empty:

- keep the current informative empty state
- explain that unified graph data is not yet available

If the layout solver fails or produces unstable output:

- fall back to deterministic lane placement
- keep the page usable

The page should never depend on a brittle animation-only layout phase to remain functional.

## 13. Testing Strategy

### 13.1 Functional verification

Verify that:

- graph renders in both views
- nodes no longer overlap in common medium-density cases
- dragging still works
- `重新排布` still works
- focus selection changes edge/node emphasis

### 13.2 Layout correctness checks

Add focused tests or deterministic checks for:

- lane assignment by type
- no identical positions for multiple nodes in the same visible graph
- preserved manually dragged positions when appropriate

### 13.3 Regression checks

Preserve:

- route continuity for `/graph`
- unified graph API usage
- right-side inspector behavior
- zoom and pan interactions

## 14. Risks and Mitigations

### Risk 1: Layout becomes visually unstable

Mitigation:

- use a deterministic seeded layout pass where possible
- constrain movement
- preserve dragged positions

### Risk 2: Weak convergence still feels noisy

Mitigation:

- rely on stronger focus hierarchy
- add local refocus and incremental expansion
- fade distant context more aggressively than primary context

### Risk 3: Too much motion makes the page feel artificial

Mitigation:

- keep animation subtle
- use movement mainly during layout transitions and focus changes
- respect reduced-motion preferences

### Risk 4: Implementation grows too large inside one page file

Mitigation:

- extract layout utilities and rendering helpers if the page becomes hard to reason about
- keep computation helpers separate from JSX rendering concerns

## 15. Final Recommendation

Implement `/graph` as a weakly convergent unified knowledge explorer using:

- lane-constrained collision layout
- broad default visibility
- focus-based local enhancement
- lane-field visual structure
- stronger node and edge hierarchy

This is the smallest change that addresses node overlap at the root while preserving the new unified graph mental model and the user's preferred exploration style.
