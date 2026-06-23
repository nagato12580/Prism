# Knowledge Graph CKP Workbench Design

Date: 2026-06-21

## Purpose

The current knowledge graph page shows CKP, PKU, and source evidence in one large network. It is visually interesting, but it makes the main review task hard: users cannot quickly understand which PKUs belong to a CKP, where those PKUs came from, and how the source evidence supports the governance result.

This design changes the default graph experience into a CKP-focused workbench. The page should make the CKP -> PKU -> source chain readable first. The existing global graph remains available as a secondary view.

Reference mockup: `docs/graph-layout-options.html`, option A.

## Primary User Task

The page optimizes for this workflow:

1. Select a CKP.
2. See the PKUs linked to that CKP.
3. For each PKU, inspect its source evidence from document chunks, personal asset units, or raw fragments.
4. Click CKP, PKU, or source evidence to inspect details and edit metadata where supported.

Global network exploration is still useful, but it is not the default entry point.

## Page Structure

The page uses a three-column layout.

### Left Column: CKP List

The left column is a navigable CKP list. It should support search and lightweight filtering.

Each CKP row/card shows:

- CKP title.
- Canonical type.
- PKU count.
- Source count.
- Status or confidence when available.
- Updated time if the API can provide it.

Selecting a CKP updates the middle workbench and right inspector.

### Middle Column: CKP Workbench

The middle column is the main reading surface.

At the top, show a selected CKP summary card:

- Title.
- Canonical statement or summary.
- Canonical type.
- Confidence.
- Keywords.

Below it, show associated PKUs as readable cards or rows. Each PKU item shows:

- PKU statement.
- Unit type.
- Confidence.
- Link role/relation to the CKP.
- Link reason when concise enough.

Each PKU item includes an evidence section listing sources:

- Document chunk.
- Personal asset unit.
- Raw personal asset item, if present in the graph payload.

Source evidence should show a short title, source type, and a short text snippet. Clicking the source selects it in the inspector.

### Right Column: Inspector

The inspector remains the place for details and editing.

It must support the same node types as the current graph:

- CKP.
- PKU.
- Personal asset item.
- Personal asset unit.
- Document chunk.

For a selected item, show:

- Full statement/content.
- Type/category/status.
- Confidence.
- Keywords/tags.
- Source metadata.
- Edge reason and role when selection is reached through a relationship.

The existing edit affordance can stay in the inspector. Editing should not interrupt the middle workbench.

## View Modes

The page should have two top-level tabs:

- `CKP Workbench`: the new default view.
- `Global Network`: the existing SVG graph view, retained as an exploration tool.

Inside `CKP Workbench`, the PKU area can have two sub-modes:

- `Evidence Chain`: default. Shows CKP -> PKU -> sources.
- `PKU Relations`: shows PKU-to-PKU relations such as prerequisite, supports, contradicts, or related_to.

PKU-to-PKU relations should not visually compete with the main CKP-to-PKU chain in the default view.

## Data Needs

The first implementation should reuse the existing `/knowledge-graph` payload where possible.

The frontend can derive the CKP workbench structure from:

- `canonical_pku` edges for CKP -> PKU.
- `pku_source` edges for PKU -> source.
- `pku_relation` edges for PKU -> PKU.
- Node metadata already serialized by `knowledge_graph.py`.

If the current payload is insufficient or inefficient, add a focused endpoint later, for example:

`GET /api/v1/knowledge-graph/ckp/{ckp_id}`

That endpoint would return one CKP, its linked PKUs, source evidence grouped by PKU, and PKU relations among that set.

For the first pass, avoid changing the backend unless the frontend cannot reliably group the current graph data.

## Interaction Rules

- Page load selects the first CKP from the filtered result set.
- Searching filters the CKP list and reloads the graph payload.
- Clicking a CKP changes the selected workbench context.
- Clicking a PKU highlights that PKU, its CKP link, and its source evidence.
- Clicking a source selects it and shows source details in the inspector.
- Clicking a PKU relation in the `PKU Relations` sub-mode selects the relation context and shows reason/confidence/model details in the inspector.
- Reset layout and drag behavior apply only to `Global Network`, not to `CKP Workbench`.

## Visual Direction

The CKP workbench should feel like a review surface, not a decorative graph.

Use restrained operational styling:

- CKP: blue.
- PKU: violet.
- Document source: teal/green.
- Asset unit: rose.
- Raw fragment: amber.

Cards should be compact and readable. The primary visual hierarchy is:

1. Selected CKP.
2. PKUs linked to the CKP.
3. Source evidence under each PKU.
4. Relationship metadata and edit controls.

## Error and Empty States

If no CKPs exist, show a direct empty state explaining that confirmed fragments or vectorized documents will generate PKU and CKP.

If search returns no CKPs, show an empty filtered state and keep the search box visible.

If a CKP has no visible PKUs, show a compact message in the workbench and keep the inspector available.

If graph loading fails, preserve the current error banner pattern.

## Testing Plan

Backend tests are only needed if a new endpoint is added. If reusing `/knowledge-graph`, frontend verification is enough for this design pass.

Frontend verification should cover:

- CKP list renders from graph payload.
- Selecting a CKP filters the middle workbench to related PKUs.
- PKU cards show source evidence grouped under the correct PKU.
- PKU relations appear in the PKU relations sub-mode.
- Inspector updates when selecting CKP, PKU, and source evidence.
- Existing global network view remains available.
- Build passes.

Manual browser verification should check:

- Desktop layout has no overlapping text.
- Long PKU statements wrap cleanly.
- Empty states are understandable.
- Switching between CKP Workbench and Global Network does not lose the loaded graph data.

## Out of Scope for First Pass

- Force-directed graph layout.
- Persisted custom node positions for CKP Workbench.
- Bulk editing PKUs or CKPs.
- Backend graph query optimization unless current payload is too slow.
- New graph algorithms for clustering or recommendation.

## Approved Direction

The selected direction is option A from the visual mockup: CKP Focus Workspace.

The agreed first-pass product shape is:

- Default to CKP Workbench.
- Keep Global Network as a secondary tab.
- Show CKP -> PKU -> source evidence as the primary chain.
- Keep PKU-to-PKU relations in a separate sub-mode.
- Use the inspector for details and editing.
