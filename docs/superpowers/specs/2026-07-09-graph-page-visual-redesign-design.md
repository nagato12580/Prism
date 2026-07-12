# Graph Page Visual Redesign Design

Date: 2026-07-09
Owner: Codex
Status: Draft for review

## 1. Goal

Redesign the unified graph page at `/graph` so it feels like a graph-first exploration surface rather than a dashboard made of stacked cards.

The page should:

- make the graph canvas the primary visual object
- match the user's preferred direction: `dual-mode`
- keep the default state clean and quiet, similar to the provided reference
- show the right-side inspector only after a node is selected
- preserve existing graph functionality such as search, focus, expand, zoom, and source/entity mode switching

This redesign is visual and interaction-structural. It should not require changing the current backend graph payload contract.

## 2. Confirmed Direction

The user approved this design direction:

- interaction model: `dual-mode`
- inspector behavior: `show only when a node is selected`
- control style: `light white floating`
- reference alignment: closer to a full-canvas graph explorer than a classic workbench

## 3. Product Framing

Subject: a governed knowledge graph explorer for entity-source discovery across document chunks and personal asset units.

Audience:

- the primary user exploring their own knowledge graph
- future operators debugging graph ingestion and retrieval quality

Single job of the page:

- help the user see how entities connect to evidence sources, then drill into one selected node without losing the canvas context

## 4. High-Level UX Model

The page has two modes.

### 4.1 Explore Mode

Default state after entering `/graph`.

Characteristics:

- graph takes nearly the full page
- controls appear as small floating white surfaces
- no permanent right-side inspector
- the page feels calm, sparse, and spatial

Visible UI in this mode:

- top-left floating search bar
- compact mode switch embedded near search
- top-right small index/status capsule
- bottom-left node/edge counter capsule
- bottom-right zoom/fit controls

### 4.2 Inspect Mode

Entered after clicking a node.

Characteristics:

- graph remains visible
- a right-side sliding inspector appears
- selected node becomes the current visual focus
- nearby edges and neighbor nodes remain legible

Visible UI in this mode:

- same floating graph controls as Explore Mode
- right-side inspector drawer
- selected node highlighted strongly
- non-focus graph slightly softened, but not hidden

Exit behavior:

- clicking canvas empty space closes the inspector
- selecting another node swaps inspector content in place

## 5. Visual Direction

### 5.1 Design Thesis

The page should read like a quiet research surface: light paper background, floating instrumentation, and a graph that feels naturally spread across a canvas rather than boxed into dashboard lanes.

### 5.2 Token System

Recommended visual tokens:

- page background: `#F6F6F2`
- primary text: `#20252B`
- secondary text: `#6E7681`
- floating card: `rgba(255,255,255,0.92)`
- border line: `rgba(29,37,47,0.08)`
- shadow: soft wide blur, low contrast

Graph semantic palette:

- entity: warm yellow-gold
- document chunk: lake blue
- personal asset unit: soft mint green
- active path / focus relation: muted coral

### 5.3 Typography

The current generic admin feel should be reduced.

Typography direction:

- use clean sans-serif hierarchy
- stronger title contrast in inspector and floating counters
- lighter, quieter meta text
- avoid heavy uppercase dashboard labels except for small utility metadata

Typography should support:

- short node titles
- compact floating labels
- inspector summaries and evidence copy

### 5.4 Signature Move

The memorable element of the page is not a hero banner or decorative chrome. The signature is the contrast between:

- a nearly full-bleed, airy graph canvas
- very restrained floating white tools
- a precise, glass-light inspector that only appears on intent

This is the one deliberate aesthetic risk: most graph tools over-expose controls and analysis panels. This design hides structure until the user touches the graph.

## 6. Layout Structure

## 6.1 Remove Current Dashboard Framing

The following current structures should no longer dominate the page:

- large top textual header
- permanent workbench summary band
- fixed two-column layout with inspector always consuming space
- heavy lane framing as a primary visual scaffold

Some of their information can survive, but in compressed floating form.

## 6.2 New Page Shell

The page shell becomes:

1. full-height graph canvas container
2. floating controls above the canvas
3. conditional inspector drawer anchored right

Suggested spatial model:

- edge-to-edge canvas inside page padding
- rounded outer graph board
- internal graph background with subtle radial atmosphere, not a harsh grid

## 6.3 Floating Control Placement

Top-left:

- search input
- embedded entity/source mode switch
- refresh action icon

Top-right:

- small capsule for ingestion/index status
- quick count of pending indexed sources

Bottom-left:

- node count
- edge count

Bottom-right:

- zoom in
- zoom out
- fit/reset viewport

These controls must remain lightweight and never visually compete with the graph.

## 7. Graph Canvas Behavior

## 7.1 Graph as Primary Surface

The graph itself should feel more organic and less like rows of labeled zones.

Target changes:

- weaken the visible lane metaphor
- reduce strong table-like segmentation
- let clusters feel spatial rather than columnar
- preserve semantic grouping without obvious hard partitions

## 7.2 Node Styling

Nodes should carry visual hierarchy by graph importance.

Rules:

- central or high-degree nodes may be larger
- ordinary nodes remain small and light
- selected node gets a stronger halo or expanded ring
- semantic colors remain, but slightly desaturated from current harsh defaults

## 7.3 Edge Styling

Edges should become quieter.

Rules:

- thinner lines
- smaller arrowheads
- lower baseline opacity
- highlight only focus-related paths more strongly
- no heavy visual clutter from dense edge labeling

## 7.4 Label Strategy

The page should not try to fully label every node at equal strength.

Rules:

- highest-priority labels always visible
- peripheral labels truncated
- selected and near-focus labels fully readable
- distant labels lighter or omitted when density gets high

This is necessary to avoid the current overlapped, noisy graph look.

## 8. Inspector Drawer

## 8.1 Trigger

Open only when a node is selected.

## 8.2 Form

Right-side overlay drawer with:

- rounded corners
- very light translucency
- soft shadow
- fixed width around 360px to 420px on desktop

It should feel like a research card gliding over the graph, not a separate page column.

## 8.3 Content Order

Recommended content sequence:

1. node type and state
2. node title
3. short summary / content
4. actions: refocus, expand related
5. key metadata: type, confidence, category, status
6. tags / keywords
7. retrieval evidence or graph evidence
8. related nodes

## 8.4 Behavior

- opening the drawer should not re-layout the whole graph
- closing it returns to full exploration state
- swapping node selection updates content without closing animation reset

## 9. Mapping Existing Features Into New UI

Existing functionality should be preserved but relocated.

### 9.1 Search

Current search becomes the main floating control in the top-left.

### 9.2 Entity / Source View Toggle

Current toggle remains, but visually compressed into a pill inside or beside the search surface.

### 9.3 Refresh

Current refresh becomes a compact icon action rather than a large primary admin button.

### 9.4 Graph Workbench Metrics

Current workbench cards are too heavy for the new page shell.

Replacement:

- keep essential counts only
- move them into minimal capsules
- defer advanced diagnostics from the default page shell in the first pass

### 9.5 Zoom and Fit

Remain available, but live as a bottom-right floating micro-control stack.

### 9.6 Inspector

Current inspector logic remains useful, but its container and visual treatment must change to overlay mode.

## 10. Motion

Motion should be deliberate and limited.

Allowed motion:

- inspector slide-in from right
- subtle node halo growth on selection
- gentle opacity transitions for focus and de-focus

Avoid:

- flashy particle motion
- constant animated graph wobble
- excessive control hover theatrics

Reduced motion should be respected.

## 11. Mobile and Smaller Screens

The first priority is desktop quality, but the page must still work on smaller widths.

Responsive behavior:

- floating controls wrap or collapse
- inspector becomes wider relative to screen but still dismissible
- graph remains pannable and zoomable
- counters and status capsules may compress text before wrapping

The redesign should not assume very wide desktop only.

## 12. Implementation Scope

## 12.1 In Scope for First Pass

- redesign page shell to graph-first layout
- replace current top header/workbench dominance with floating controls
- convert inspector to conditional right-side overlay
- restyle nodes, edges, counters, controls, and graph background
- preserve current query/load/focus/expand behavior
- improve perceived density and label readability

## 12.2 Out of Scope for First Pass

- backend graph payload changes
- replacing the whole graph interaction model
- complex multi-filter analysis system
- deep graph algorithm rewrite
- complete layout engine replacement unless a small adjustment is enough

## 13. Risks

### 13.1 Density Risk

If the graph layout remains too collision-heavy, visual polish alone will not fully solve readability.

Mitigation:

- reduce always-on labels
- strengthen focus-based visibility rules
- make small layout adjustments without committing to a full engine rewrite in pass one

### 13.2 Hidden Capability Risk

If the page becomes too minimal, some existing functionality may become less discoverable.

Mitigation:

- keep mode switch, search, and refresh clearly available
- keep inspector actions obvious once opened
- use concise but direct labels

### 13.3 Overlay Conflict Risk

The inspector could obscure important graph regions.

Mitigation:

- soften graph underlay near drawer edge
- avoid reflow
- make deselection and reselection trivial

## 14. Acceptance Criteria

The redesign is successful if:

- the page visually reads as a graph explorer first, not a workbench dashboard
- the default state shows a clean full-canvas graph with floating controls
- the inspector is hidden by default and appears only after selecting a node
- the main graph remains visible during inspection
- entity/source switching, search, refresh, zoom, refocus, and expand still work
- the result feels materially closer to the provided reference image than the current page

## 15. Recommended Build Order

1. reshape page shell and remove heavyweight header/workbench framing
2. introduce floating control surfaces
3. convert inspector into right overlay drawer
4. restyle graph background, nodes, edges, and labels
5. tune focus-state emphasis and drawer interaction polish
