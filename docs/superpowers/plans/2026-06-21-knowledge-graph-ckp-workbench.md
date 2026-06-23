# Knowledge Graph CKP Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CKP-focused graph workbench that makes CKP -> PKU -> source evidence relationships readable by default while keeping the existing global graph as a secondary view.

**Architecture:** Add a focused backend workbench endpoint that returns CKPs with grouped PKUs and source evidence, then add frontend API types and a new workbench UI. Keep the current `/knowledge-graph` endpoint and SVG network view for the `Global Network` tab.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React 18, TypeScript, Tailwind CSS, lucide-react, Vite.

---

## File Structure

- Modify `backend/app/api/knowledge_graph.py`: add a CKP workbench response builder and `GET /knowledge-graph/workbench`.
- Modify `backend/tests/test_knowledge_graph_api.py`: add focused tests for grouped CKP -> PKU -> source evidence and PKU relations.
- Modify `frontend/src/app/api.ts`: add workbench payload types and `knowledgeGraphApi.getWorkbench`.
- Create `frontend/src/pages/KnowledgeGraphWorkbench.tsx`: new three-column CKP workbench component.
- Modify `frontend/src/pages/KnowledgeGraphPage.tsx`: add top-level `CKP Workbench` / `Global Network` tabs and render the new workbench by default.

## Task 1: Backend CKP Workbench Endpoint

**Files:**
- Modify: `backend/app/api/knowledge_graph.py`
- Test: `backend/tests/test_knowledge_graph_api.py`

- [ ] **Step 1: Write failing test for grouped CKP workbench payload**

Append this test to `backend/tests/test_knowledge_graph_api.py`:

```python
def test_knowledge_graph_workbench_groups_ckp_pkus_sources_and_relations(client, db_session):
    from backend.app.models import (
        CanonicalKnowledgePoint,
        KnowledgeChunk,
        KnowledgeItem,
        PKUCanonicalLink,
        PKURelation,
        PersonalKnowledgeUnit,
    )

    item = KnowledgeItem(
        title="Hybrid retrieval notes",
        content="Metadata filters restrict retrieval before vector recall.",
        source_type="file",
        tags=["retrieval"],
        category="RAG",
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filters restrict retrieval before vector recall.",
        chunk_index=0,
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        title="Hybrid retrieval",
        canonical_statement="Hybrid retrieval combines metadata filters with vector recall.",
        canonical_type="method",
        confidence=0.91,
        keywords=["hybrid", "retrieval"],
    )
    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Metadata filters restrict retrieval before vector recall.",
        normalized_statement="Metadata filters restrict retrieval before vector recall.",
        normalized_statement_hash="workbench-pku-1",
        confidence=0.9,
        keywords=["metadata"],
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Vector recall retrieves semantically related chunks.",
        normalized_statement="Vector recall retrieves semantically related chunks.",
        normalized_statement_hash="workbench-pku-2",
        confidence=0.86,
        keywords=["vector"],
    )
    db_session.add_all([chunk, ckp, first, second])
    db_session.flush()
    db_session.add_all([
        PKUCanonicalLink(
            user_id="default-user",
            pku_id=first.id,
            canonical_id=ckp.id,
            relation_type="same_as",
            role="external_reference",
            confidence=0.93,
            reason="First PKU supports the CKP.",
        ),
        PKUCanonicalLink(
            user_id="default-user",
            pku_id=second.id,
            canonical_id=ckp.id,
            relation_type="same_as",
            role="external_reference",
            confidence=0.88,
            reason="Second PKU supports the CKP.",
        ),
        PKURelation(
            user_id="default-user",
            source_pku_id=first.id,
            target_pku_id=second.id,
            relation_type="prerequisite",
            confidence=0.77,
            reason="Filtering happens before recall.",
            source_kind="document_chunk",
            source_id=chunk.id,
        ),
    ])
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph/workbench?q=hybrid")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ckps"][0]["id"] == f"ckp:{ckp.id}"
    assert payload["ckps"][0]["pku_count"] == 2
    assert payload["ckps"][0]["source_count"] == 1
    group = payload["groups"][f"ckp:{ckp.id}"]
    assert [item["pku"]["id"] for item in group["pkus"]] == [f"pku:{first.id}", f"pku:{second.id}"]
    assert group["pkus"][0]["link"]["reason"] == "First PKU supports the CKP."
    assert group["pkus"][0]["sources"][0]["node"]["id"] == f"chunk:{chunk.id}"
    assert group["relations"][0]["type"] == "pku_relation"
    assert group["relations"][0]["label"] == "prerequisite"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_workbench_groups_ckp_pkus_sources_and_relations -q
```

Expected: FAIL with status 404 or missing endpoint for `/knowledge-graph/workbench`.

- [ ] **Step 3: Add workbench serializers and endpoint**

In `backend/app/api/knowledge_graph.py`, add helper functions near the existing serializers:

```python
def _workbench_ckp_node(canonical: CanonicalKnowledgePoint, *, pku_count: int, source_count: int) -> dict[str, Any]:
    node = _serialize_canonical(canonical)
    node["pku_count"] = pku_count
    node["source_count"] = source_count
    return node


def _source_edge_for_pku(pku: PersonalKnowledgeUnit) -> dict[str, Any] | None:
    if not pku.source_id:
        return None
    if pku.source_kind == "document_chunk":
        return _edge(
            f"edge:source:{pku.id}:{pku.source_id}",
            f"pku:{pku.id}",
            f"chunk:{pku.source_id}",
            "pku_source",
            "evidence",
            source_kind=pku.source_kind,
        )
    if pku.source_kind == "personal_asset_unit":
        return _edge(
            f"edge:source:{pku.id}:{pku.source_id}",
            f"pku:{pku.id}",
            f"asset_unit:{pku.source_id}",
            "pku_source",
            "evidence",
            source_kind=pku.source_kind,
        )
    if pku.source_kind == "personal_asset_item":
        return _edge(
            f"edge:source:{pku.id}:{pku.source_id}",
            f"pku:{pku.id}",
            f"asset:{pku.source_id}",
            "pku_source",
            "evidence",
            source_kind=pku.source_kind,
        )
    return None
```

Then add the endpoint before `update_knowledge_graph_node`:

```python
@router.get("/workbench")
def get_knowledge_graph_workbench(
    q: Optional[str] = Query(None, description="Search CKPs by title, statement, or summary"),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(CanonicalKnowledgePoint).filter(
        CanonicalKnowledgePoint.user_id == DEFAULT_USER_ID,
        CanonicalKnowledgePoint.status != "deprecated",
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                CanonicalKnowledgePoint.title.like(like),
                CanonicalKnowledgePoint.canonical_statement.like(like),
                CanonicalKnowledgePoint.summary.like(like),
            )
        )

    canonicals = query.order_by(CanonicalKnowledgePoint.updated_at.desc()).limit(limit).all()
    canonical_ids = [canonical.id for canonical in canonicals]
    if not canonical_ids:
        return {"ckps": [], "groups": {}, "stats": {"ckp_count": 0, "pku_count": 0, "source_count": 0}}

    links = (
        db.query(PKUCanonicalLink)
        .filter(PKUCanonicalLink.canonical_id.in_(canonical_ids))
        .order_by(PKUCanonicalLink.confidence.desc(), PKUCanonicalLink.created_at.desc())
        .all()
    )

    links_by_ckp: dict[str, list[PKUCanonicalLink]] = {}
    pku_ids: set[str] = set()
    for link in links:
        if not link.pku:
            continue
        links_by_ckp.setdefault(link.canonical_id, []).append(link)
        pku_ids.add(link.pku_id)

    relations = []
    if pku_ids:
        relations = (
            db.query(PKURelation)
            .filter(
                PKURelation.user_id == DEFAULT_USER_ID,
                PKURelation.source_pku_id.in_(pku_ids),
                PKURelation.target_pku_id.in_(pku_ids),
            )
            .order_by(PKURelation.confidence.desc())
            .limit(limit * 8)
            .all()
        )

    relations_by_ckp: dict[str, list[dict[str, Any]]] = {}
    relation_nodes_by_ckp: dict[str, set[str]] = {}
    for relation in relations:
        edge = _edge(
            f"edge:pku_relation:{relation.id}",
            f"pku:{relation.source_pku_id}",
            f"pku:{relation.target_pku_id}",
            "pku_relation",
            relation.relation_type,
            confidence=relation.confidence,
            reason=relation.reason,
            source_kind=relation.source_kind,
            source_id=relation.source_id,
            llm_model=relation.llm_model,
        )
        for canonical_id, ckp_links in links_by_ckp.items():
            ckp_pku_ids = {link.pku_id for link in ckp_links}
            if relation.source_pku_id in ckp_pku_ids and relation.target_pku_id in ckp_pku_ids:
                relations_by_ckp.setdefault(canonical_id, []).append(edge)
                relation_nodes_by_ckp.setdefault(canonical_id, set()).update([edge["source"], edge["target"]])

    groups: dict[str, dict[str, Any]] = {}
    ckps: list[dict[str, Any]] = []
    total_sources: set[str] = set()
    for canonical in canonicals:
        ckp_links = links_by_ckp.get(canonical.id, [])
        pku_entries = []
        source_ids: set[str] = set()
        for link in ckp_links:
            pku = link.pku
            if not pku:
                continue
            source_node = _source_node_for_pku(db, pku)
            source_edge = _source_edge_for_pku(pku)
            sources = []
            if source_node and source_edge:
                source_ids.add(source_node["id"])
                total_sources.add(source_node["id"])
                sources.append({"node": source_node, "edge": source_edge})
            pku_entries.append({
                "pku": _serialize_pku(pku),
                "link": _edge(
                    f"edge:{link.id}",
                    f"ckp:{link.canonical_id}",
                    f"pku:{link.pku_id}",
                    "canonical_pku",
                    link.relation_type,
                    role=link.role,
                    confidence=link.confidence,
                    reason=link.reason,
                ),
                "sources": sources,
            })
        ckp_node = _workbench_ckp_node(canonical, pku_count=len(pku_entries), source_count=len(source_ids))
        ckps.append(ckp_node)
        groups[ckp_node["id"]] = {
            "ckp": ckp_node,
            "pkus": pku_entries,
            "relations": relations_by_ckp.get(canonical.id, []),
        }

    return {
        "ckps": ckps,
        "groups": groups,
        "stats": {
            "ckp_count": len(ckps),
            "pku_count": len(pku_ids),
            "source_count": len(total_sources),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_workbench_groups_ckp_pkus_sources_and_relations -q
```

Expected: PASS.

- [ ] **Step 5: Run graph API regression tests**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit backend workbench endpoint**

```powershell
git add backend/app/api/knowledge_graph.py backend/tests/test_knowledge_graph_api.py
git commit -m "feat: add CKP graph workbench endpoint"
```

## Task 2: Frontend API Types

**Files:**
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: Add workbench TypeScript types**

In `frontend/src/app/api.ts`, near existing knowledge graph types, add:

```ts
export interface KnowledgeGraphSourceEvidence {
  node: KnowledgeGraphNode
  edge: KnowledgeGraphEdge
}

export interface KnowledgeGraphWorkbenchPKU {
  pku: KnowledgeGraphNode
  link: KnowledgeGraphEdge
  sources: KnowledgeGraphSourceEvidence[]
}

export interface KnowledgeGraphWorkbenchGroup {
  ckp: KnowledgeGraphNode & {
    pku_count?: number
    source_count?: number
  }
  pkus: KnowledgeGraphWorkbenchPKU[]
  relations: KnowledgeGraphEdge[]
}

export interface KnowledgeGraphWorkbenchPayload {
  ckps: Array<KnowledgeGraphNode & {
    pku_count?: number
    source_count?: number
  }>
  groups: Record<string, KnowledgeGraphWorkbenchGroup>
  stats: {
    ckp_count: number
    pku_count: number
    source_count: number
  }
}
```

- [ ] **Step 2: Add API method**

In `knowledgeGraphApi`, add:

```ts
  getWorkbench: (params?: { q?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.q) qs.set('q', params.q)
    if (params?.limit) qs.set('limit', String(params.limit))
    const query = qs.toString()
    return request<KnowledgeGraphWorkbenchPayload>(`/knowledge-graph/workbench${query ? `?${query}` : ''}`)
  },
```

- [ ] **Step 3: Run frontend typecheck/build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: TypeScript compiles. Vite may show the existing chunk-size warning.

- [ ] **Step 4: Commit frontend API types**

```powershell
git add frontend/src/app/api.ts
git commit -m "feat: add CKP graph workbench API types"
```

## Task 3: CKP Workbench Component

**Files:**
- Create: `frontend/src/pages/KnowledgeGraphWorkbench.tsx`
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Create the workbench component**

Create `frontend/src/pages/KnowledgeGraphWorkbench.tsx` with:

```tsx
import { Search, Sparkles, Boxes, FileText, BookOpen, GitBranch, Loader2 } from 'lucide-react'
import {
  knowledgeGraphApi,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeUpdate,
  type KnowledgeGraphWorkbenchGroup,
  type KnowledgeGraphWorkbenchPayload,
  type KnowledgeGraphWorkbenchPKU,
} from '@/app/api'
import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'

type Selection =
  | { kind: 'ckp'; node: KnowledgeGraphNode }
  | { kind: 'pku'; node: KnowledgeGraphNode; edge?: KnowledgeGraphEdge }
  | { kind: 'source'; node: KnowledgeGraphNode; edge?: KnowledgeGraphEdge }
  | { kind: 'relation'; edge: KnowledgeGraphEdge }

const sourceColors: Record<string, string> = {
  document_chunk: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  personal_asset_unit: 'border-rose-200 bg-rose-50 text-rose-800',
  personal_asset_item: 'border-amber-200 bg-amber-50 text-amber-800',
}

function contentForNode(node: KnowledgeGraphNode) {
  return node.statement || node.summary || node.text || ''
}

function truncate(text: string | undefined | null, max = 180) {
  const value = (text || '').trim()
  if (value.length <= max) return value
  return `${value.slice(0, max)}...`
}

function nodeKindLabel(node: KnowledgeGraphNode) {
  if (node.type === 'canonical') return 'CKP'
  if (node.type === 'pku') return 'PKU'
  if (node.type === 'document_chunk') return 'Document'
  if (node.type === 'personal_asset_unit') return 'Asset unit'
  if (node.type === 'asset') return 'Fragment'
  return node.type
}

export function KnowledgeGraphWorkbench({
  onSaveNode,
}: {
  onSaveNode: (nodeId: string, data: KnowledgeGraphNodeUpdate) => Promise<KnowledgeGraphNode>
}) {
  const [query, setQuery] = useState('')
  const [payload, setPayload] = useState<KnowledgeGraphWorkbenchPayload | null>(null)
  const [selectedCkpId, setSelectedCkpId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [subMode, setSubMode] = useState<'evidence' | 'relations'>('evidence')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedGroup = selectedCkpId && payload ? payload.groups[selectedCkpId] : null

  async function load(nextQuery = query) {
    setLoading(true)
    setError(null)
    try {
      const data = await knowledgeGraphApi.getWorkbench({ q: nextQuery.trim() || undefined, limit: 60 })
      setPayload(data)
      const nextCkpId = data.ckps.some((ckp) => ckp.id === selectedCkpId)
        ? selectedCkpId
        : data.ckps[0]?.id ?? null
      setSelectedCkpId(nextCkpId)
      setSelection(nextCkpId ? { kind: 'ckp', node: data.groups[nextCkpId].ckp } : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load('')
  }, [])

  const pkuCount = selectedGroup?.pkus.length ?? 0
  const sourceCount = useMemo(() => {
    const ids = new Set<string>()
    selectedGroup?.pkus.forEach((pku) => pku.sources.forEach((source) => ids.add(source.node.id)))
    return ids.size
  }, [selectedGroup])

  return (
    <div className="grid min-h-[calc(100vh-13rem)] gap-4 xl:grid-cols-[18rem_minmax(0,1fr)_23rem]">
      <aside className="prism-panel rounded-lg p-4">
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void load()
            }}
            placeholder="Search CKP"
            className="h-10 w-full rounded-lg border border-[var(--prism-line)] bg-white pl-9 pr-3 text-sm outline-none focus:border-[var(--prism-blue)] focus:ring-2 focus:ring-blue-100"
          />
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>{payload?.stats.ckp_count ?? 0} CKPs</span>
          {loading ? <Loader2 size={14} className="animate-spin" /> : null}
        </div>
        <div className="mt-3 space-y-2 overflow-y-auto pr-1">
          {(payload?.ckps ?? []).map((ckp) => (
            <button
              key={ckp.id}
              type="button"
              onClick={() => {
                setSelectedCkpId(ckp.id)
                setSelection({ kind: 'ckp', node: payload!.groups[ckp.id].ckp })
              }}
              className={cn(
                'w-full rounded-lg border px-3 py-2 text-left transition',
                selectedCkpId === ckp.id
                  ? 'border-blue-300 bg-blue-50'
                  : 'border-[var(--prism-line)] bg-white hover:bg-slate-50',
              )}
            >
              <div className="line-clamp-2 text-sm font-semibold text-slate-950">{ckp.label}</div>
              <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
                <span>{ckp.canonical_type || 'canonical'}</span>
                <span>{ckp.pku_count ?? 0} PKU</span>
                <span>{ckp.source_count ?? 0} sources</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <main className="prism-panel min-h-0 rounded-lg p-4">
        {error ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        ) : null}
        {!selectedGroup ? (
          <div className="flex min-h-[32rem] items-center justify-center text-center text-sm leading-6 text-slate-500">
            No CKP found. Confirm fragments or vectorized documents to generate PKU and CKP.
          </div>
        ) : (
          <>
            <section className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
              <div className="flex items-start gap-3">
                <span className="mt-1 inline-flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white">
                  <Sparkles size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold uppercase text-blue-700">Selected CKP</div>
                  <h2 className="mt-1 break-words text-lg font-semibold text-slate-950">{selectedGroup.ckp.label}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{truncate(contentForNode(selectedGroup.ckp), 260)}</p>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-md bg-white px-2 py-1 text-blue-700">{pkuCount} PKUs</span>
                    <span className="rounded-md bg-white px-2 py-1 text-blue-700">{sourceCount} sources</span>
                    {typeof selectedGroup.ckp.confidence === 'number' ? (
                      <span className="rounded-md bg-white px-2 py-1 text-blue-700">
                        {selectedGroup.ckp.confidence.toFixed(2)}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>

            <div className="mt-4 inline-flex rounded-lg border border-[var(--prism-line)] bg-white p-1">
              <button
                type="button"
                onClick={() => setSubMode('evidence')}
                className={cn('rounded-md px-3 py-1.5 text-sm font-medium', subMode === 'evidence' ? 'bg-slate-950 text-white' : 'text-slate-600')}
              >
                Evidence Chain
              </button>
              <button
                type="button"
                onClick={() => setSubMode('relations')}
                className={cn('rounded-md px-3 py-1.5 text-sm font-medium', subMode === 'relations' ? 'bg-slate-950 text-white' : 'text-slate-600')}
              >
                PKU Relations
              </button>
            </div>

            {subMode === 'evidence' ? (
              <div className="mt-4 space-y-3">
                {selectedGroup.pkus.map((entry) => (
                  <PKUCard key={entry.pku.id} entry={entry} onSelect={setSelection} />
                ))}
              </div>
            ) : (
              <PKURelationList group={selectedGroup} onSelect={setSelection} />
            )}
          </>
        )}
      </main>

      <WorkbenchInspector selection={selection} onSaveNode={onSaveNode} />
    </div>
  )
}

function PKUCard({ entry, onSelect }: { entry: KnowledgeGraphWorkbenchPKU; onSelect: (selection: Selection) => void }) {
  return (
    <article className="rounded-lg border border-violet-200 bg-white px-4 py-3">
      <button type="button" className="block w-full text-left" onClick={() => onSelect({ kind: 'pku', node: entry.pku, edge: entry.link })}>
        <div className="flex items-center gap-2 text-xs font-semibold text-violet-700">
          <Boxes size={14} />
          PKU
          {typeof entry.pku.confidence === 'number' ? <span className="ml-auto">{entry.pku.confidence.toFixed(2)}</span> : null}
        </div>
        <p className="mt-2 text-sm font-medium leading-6 text-slate-950">{entry.pku.statement || entry.pku.label}</p>
        {entry.link.reason ? <p className="mt-1 text-xs leading-5 text-slate-500">{entry.link.reason}</p> : null}
      </button>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {entry.sources.map(({ node, edge }) => (
          <button
            key={node.id}
            type="button"
            onClick={() => onSelect({ kind: 'source', node, edge })}
            className={cn('rounded-lg border px-3 py-2 text-left text-xs', sourceColors[node.source_kind || node.type] ?? 'border-slate-200 bg-slate-50 text-slate-700')}
          >
            <div className="flex items-center gap-2 font-semibold">
              {node.type === 'document_chunk' ? <FileText size={13} /> : <BookOpen size={13} />}
              {nodeKindLabel(node)}
            </div>
            <div className="mt-1 line-clamp-2 leading-5">{truncate(contentForNode(node), 120)}</div>
          </button>
        ))}
      </div>
    </article>
  )
}

function PKURelationList({ group, onSelect }: { group: KnowledgeGraphWorkbenchGroup; onSelect: (selection: Selection) => void }) {
  const pkuById = new Map(group.pkus.map((entry) => [entry.pku.id, entry.pku]))
  return (
    <div className="mt-4 space-y-2">
      {group.relations.length === 0 ? (
        <p className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-4 text-sm text-slate-500">No PKU relations for this CKP.</p>
      ) : (
        group.relations.map((edge) => (
          <button
            key={edge.id}
            type="button"
            onClick={() => onSelect({ kind: 'relation', edge })}
            className="w-full rounded-lg border border-pink-200 bg-white px-4 py-3 text-left"
          >
            <div className="flex items-center gap-2 text-xs font-semibold text-pink-700">
              <GitBranch size={14} />
              {edge.label}
              {typeof edge.confidence === 'number' ? <span className="ml-auto">{edge.confidence.toFixed(2)}</span> : null}
            </div>
            <div className="mt-2 grid gap-2 text-sm text-slate-700 md:grid-cols-[1fr_auto_1fr]">
              <span>{pkuById.get(edge.source)?.label ?? edge.source}</span>
              <span className="text-slate-400">-></span>
              <span>{pkuById.get(edge.target)?.label ?? edge.target}</span>
            </div>
            {edge.reason ? <p className="mt-2 text-xs leading-5 text-slate-500">{edge.reason}</p> : null}
          </button>
        ))
      )}
    </div>
  )
}

function WorkbenchInspector({
  selection,
}: {
  selection: Selection | null
  onSaveNode: (nodeId: string, data: KnowledgeGraphNodeUpdate) => Promise<KnowledgeGraphNode>
}) {
  if (!selection) {
    return (
      <aside className="prism-panel flex min-h-[24rem] items-center justify-center rounded-lg p-5 text-center text-sm text-slate-500">
        Select a CKP, PKU, or source to inspect details.
      </aside>
    )
  }
  if (selection.kind === 'relation') {
    return (
      <aside className="prism-panel rounded-lg p-5">
        <div className="text-xs font-semibold text-pink-700">PKU Relation</div>
        <h2 className="mt-1 text-base font-semibold text-slate-950">{selection.edge.label}</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">{selection.edge.reason || 'No relation reason recorded.'}</p>
        {selection.edge.llm_model ? <div className="mt-3 text-xs text-slate-500">{selection.edge.llm_model}</div> : null}
      </aside>
    )
  }
  return (
    <aside className="prism-panel rounded-lg p-5">
      <div className="text-xs font-semibold text-slate-500">{nodeKindLabel(selection.node)}</div>
      <h2 className="mt-1 break-words text-base font-semibold leading-6 text-slate-950">{selection.node.label}</h2>
      <p className="mt-4 whitespace-pre-wrap rounded-lg border border-[var(--prism-line)] bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
        {contentForNode(selection.node) || 'No content.'}
      </p>
      {selection.edge?.reason ? (
        <div className="mt-4 rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
          <div className="text-xs font-semibold text-slate-500">Relationship reason</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">{selection.edge.reason}</p>
        </div>
      ) : null}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
          <div className="text-[11px] text-slate-500">Type</div>
          <div className="mt-1 truncate text-sm font-semibold text-slate-950">
            {selection.node.canonical_type || selection.node.unit_type || selection.node.source_kind || selection.node.type}
          </div>
        </div>
        <div className="rounded-lg border border-[var(--prism-line)] bg-white px-3 py-2">
          <div className="text-[11px] text-slate-500">Confidence</div>
          <div className="mt-1 text-sm font-semibold text-slate-950">
            {typeof selection.node.confidence === 'number' ? selection.node.confidence.toFixed(2) : '-'}
          </div>
        </div>
      </div>
    </aside>
  )
}
```

- [ ] **Step 2: Wire the component into `KnowledgeGraphPage`**

In `frontend/src/pages/KnowledgeGraphPage.tsx`, import the component:

```tsx
import { KnowledgeGraphWorkbench } from '@/pages/KnowledgeGraphWorkbench'
```

Add view mode state near the existing state declarations:

```tsx
const [viewMode, setViewMode] = useState<'workbench' | 'network'>('workbench')
```

Add this tab control under the header and above the error banner:

```tsx
<div className="inline-flex w-fit rounded-lg border border-[var(--prism-line)] bg-white p-1">
  <button
    type="button"
    onClick={() => setViewMode('workbench')}
    className={cn('rounded-md px-3 py-1.5 text-sm font-medium', viewMode === 'workbench' ? 'bg-slate-950 text-white' : 'text-slate-600')}
  >
    CKP Workbench
  </button>
  <button
    type="button"
    onClick={() => setViewMode('network')}
    className={cn('rounded-md px-3 py-1.5 text-sm font-medium', viewMode === 'network' ? 'bg-slate-950 text-white' : 'text-slate-600')}
  >
    Global Network
  </button>
</div>
```

Then render the workbench before the existing network grid:

```tsx
{viewMode === 'workbench' ? (
  <KnowledgeGraphWorkbench
    onSaveNode={async (nodeId, data) => {
      const updated = await knowledgeGraphApi.updateNode(nodeId, data)
      setPayload((current) =>
        current
          ? {
              ...current,
              nodes: current.nodes.map((node) => (node.id === updated.id ? { ...node, ...updated } : node)),
            }
          : current,
      )
      return updated
    }}
  />
) : (
  <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_23rem]">
    {/* keep the existing global network section and GraphInspector here */}
  </div>
)}
```

Move the existing global network grid into the `else` branch without changing its internals.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: TypeScript compiles. Existing Vite chunk-size warning is acceptable.

- [ ] **Step 4: Commit workbench UI**

```powershell
git add frontend/src/pages/KnowledgeGraphWorkbench.tsx frontend/src/pages/KnowledgeGraphPage.tsx
git commit -m "feat: add CKP graph workbench UI"
```

## Task 4: Browser Verification and Polish

**Files:**
- Modify as needed: `frontend/src/pages/KnowledgeGraphWorkbench.tsx`
- Modify as needed: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Start or reuse frontend dev server**

If no Vite server is running:

```powershell
cd frontend
npm.cmd run dev
```

Expected: Vite serves the app, commonly at `http://localhost:5173`.

- [ ] **Step 2: Verify workbench manually**

Open `/graph` and verify:

- Default view is `CKP Workbench`.
- CKP list appears in the left column.
- Selecting a CKP updates the middle CKP summary and PKU list.
- PKU cards show grouped source evidence.
- Clicking CKP, PKU, source, and relation updates the right inspector.
- `PKU Relations` sub-mode shows relation rows without mixing them into the evidence chain.
- `Global Network` tab still shows the existing SVG graph.

- [ ] **Step 3: Fix any layout overlap found in browser**

If long PKU statements overflow, update `KnowledgeGraphWorkbench.tsx` with these class adjustments:

```tsx
<p className="mt-2 break-words text-sm font-medium leading-6 text-slate-950">
  {entry.pku.statement || entry.pku.label}
</p>
```

If the CKP list becomes too tall, ensure the left column list has:

```tsx
<div className="mt-3 max-h-[calc(100vh-18rem)] space-y-2 overflow-y-auto pr-1">
```

- [ ] **Step 4: Run final verification**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py -q
cd frontend
npm.cmd run build
```

Expected:

- Backend graph API tests pass.
- Frontend build passes.

- [ ] **Step 5: Commit browser polish**

If any polish changes were needed:

```powershell
git add frontend/src/pages/KnowledgeGraphWorkbench.tsx frontend/src/pages/KnowledgeGraphPage.tsx
git commit -m "polish: refine CKP graph workbench layout"
```

If no polish changes were needed, skip this commit.

## Self-Review Checklist

- The plan implements the approved option A: CKP Focus Workspace.
- The default page is CKP Workbench, not Global Network.
- CKP -> PKU -> source evidence is the primary chain.
- PKU-to-PKU relations are separated into a sub-mode.
- The existing global network remains available.
- The inspector remains available for detail review and editing context.
- Backend grouping is tested with pytest.
- Frontend compiles with Vite.
