# Graph Free Scatter Circular Nodes Design

Date: 2026-07-10

## Goal

Refactor the `/graph` canvas from a lane-driven explorer into a full-canvas free scatter graph where as many nodes as possible remain visible at once, node overlap is aggressively reduced, and all graph nodes render as circles instead of elongated pill/ellipse cards.

This design keeps the current unified graph data source, floating controls, dual view toggle, and right-side inspector workflow. The change is about graph layout and node rendering, not about replacing the surrounding page shell.

## User Intent

The user wants three concrete outcomes:

1. All nodes should be visible together as much as possible.
2. Nodes should not stack on top of each other.
3. Nodes should be circular rather than elongated rounded rectangles.

The graph should feel like an actual graph visualization, not a lane-based workflow or swimlane board.

## Scope

In scope:

- Replace lane-dominant positioning with a full-canvas free scatter layout.
- Render nodes as circles.
- Rework node label strategy so labels no longer depend on wide node capsules.
- Reduce overlap through collision spacing and whole-canvas distribution.
- Preserve the existing floating graph controls and inspector workflow.

Out of scope:

- Backend API changes
- Replacing the current search / inspector product behavior
- Replacing the unified graph retrieval pipeline
- Major redesign of the surrounding `/graph` page shell

## Design Direction

### 1. Layout Model

The current graph is visually organized by fixed type lanes. That approach makes type grouping obvious, but it compresses many nodes into narrow vertical bands and creates persistent overlap pressure. For the new design, layout should shift to a free scatter model:

- The whole SVG canvas becomes one continuous placement surface.
- Nodes are seeded across the full width and height instead of fixed x-lanes.
- Type information is communicated by color and inspector metadata rather than hard spatial columns.
- The layout optimizer should prioritize non-overlap and readable spacing over lane purity.

The target result is a graph that reads as a network field instead of a categorized board.

### 2. Positioning Strategy

The implementation should use a deterministic free-scatter layout with collision avoidance. It does not need to be a full physics simulation, but it should behave like one visually.

Recommended strategy:

- Seed nodes from a deterministic radial or jittered scatter distribution across the canvas.
- Apply a lightweight iterative relaxation pass:
  - repel nodes from each other when they are inside a collision radius
  - mildly pull connected nodes toward each other
  - clamp results inside the canvas bounds
- Re-run the solver whenever payload/view changes, while preserving drag overrides if the user manually repositions nodes.

This gives us:

- far better node spread than the current lane layout
- reproducible output for tests and refreshes
- enough structure to keep related nodes visually near each other

The important constraint is that the graph should try to show the whole node set at once rather than collapsing into dense columns.

### 3. Node Shape and Visual System

Nodes should become circles, not pills.

Each node should render as:

- a circular hit area
- a circular visible body
- optional outer halo for focus / selection
- optional small icon or dot treatment inside the circle

Circle sizing should still communicate hierarchy:

- selected / focus node: largest
- near neighbors: medium
- background nodes: smaller

But all sizes remain circular.

Type differentiation should come from:

- fill color
- stroke color
- inner glyph / icon tint
- inspector metadata

This change deliberately removes the old assumption that long labels live inside the node body.

### 4. Label Strategy

Because nodes become circles, labels must detach from node shape.

Recommended rule set:

- Selected node: always show full label.
- Near / connected important nodes: show short visible labels.
- Background nodes: default to either no persistent label or a very minimal label.
- All nodes: preserve discoverability via SVG `<title>` and accessible `aria-label`.

Label placement should sit outside or adjacent to the node rather than inside it.

This keeps the graph readable while still letting the user identify important local structure. The design goal is not “every label always visible”; the goal is “every node visible, important labels readable, everything discoverable.”

## Interaction Model

The existing interaction model remains intact:

- floating top-left controls stay
- top-right status capsule stays
- bottom-left node/edge capsule stays
- bottom-right zoom controls stay
- selecting a node opens the right inspector overlay
- clicking empty space closes the inspector
- search and view switching continue to operate on the same unified graph pipeline

What changes is the visual graph behavior:

- no default lane reading expectation
- no pill-node text dependency
- local focus is expressed by highlight and neighbor emphasis, not by lane position

## Accessibility and Usability

The redesign must preserve:

- keyboard node selection
- reduced-motion safe inspector behavior
- discoverability for unlabeled nodes
- visible focus indicators for keyboard users

Additional accessibility rule:

- if a node label is visually hidden, the node must still expose its full label through `aria-label` and SVG `<title>`

## Testing Strategy

Tests should evolve with the new layout model:

- remove assumptions that lane layout is the main placement contract
- add source-level assertions for circular node rendering primitives
- add assertions that the old wide capsule rendering is gone
- keep existing overlay / shell tests intact
- where feasible, assert that nodes no longer rely on `nodeWidth/nodeHeight` pill text layout for their visible identity

The test suite should continue to protect:

- graph shell
- hidden-by-default inspector overlay
- calmer graph visual treatment
- accessibility fallbacks for hidden labels

## Implementation Notes

Likely implementation areas:

- `frontend/src/pages/KnowledgeGraphPage.tsx`
  - replace lane-based placement with free scatter solve
  - update edge anchoring from rectangle edge math to circle radius math
  - rewrite `GraphNode` rendering from pill to circle
  - rework label placement and visibility rules
- related graph tests in `frontend/tests/`
  - update or replace lane-specific expectations

No backend or API contract changes are required.

## Risks

### Risk 1: Whole-graph spread becomes visually noisy

Mitigation:

- keep edges light
- gate labels aggressively
- maintain clear selected/near/background hierarchy

### Risk 2: Related nodes drift too far apart

Mitigation:

- include soft edge-attraction in the layout relaxation pass
- preserve local neighbor emphasis after selection

### Risk 3: Too many nodes still collide in dense graphs

Mitigation:

- use a stronger collision radius
- allow smaller background nodes
- bias labels to important nodes only

## Recommended Approach

Implement the redesign in one focused frontend slice:

1. Replace lane placement with deterministic free scatter layout.
2. Convert node rendering to circles.
3. Adjust edge anchoring and label rules.
4. Update tests to reflect the new contract.
5. Re-run the current graph page verification suite and browser checks.

This gives the user the exact requested outcome without reopening the already-approved unified graph shell and inspector work.
