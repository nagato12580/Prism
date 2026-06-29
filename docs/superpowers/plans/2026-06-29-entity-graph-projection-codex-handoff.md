# Entity Graph Projection — Codex Handoff Report

> **For Codex / next agent:** continue the entity-graph projection work on branch `feature/entity-graph-projection`. This report supersedes `2026-06-29-entity-graph-projection-claude-handoff.md` and reflects the **actual current state** after Claude Code's pass on 2026-06-29. Follow it task-by-task, TDD-first. Do not restart from the main workspace.

**Branch:** `feature/entity-graph-projection`
**Current HEAD at handoff:** `d0d4595 test: cover yanchaotan entity graph badcase`
**Parent merge base on this session's work:** `93ac0c4 merge origin/dev into entity graph projection`
**Full plan:** `docs/superpowers/plans/2026-06-29-entity-graph-projection.md`
**Prior handoff (now superseded):** `docs/superpowers/plans/2026-06-29-entity-graph-projection-claude-handoff.md`

---

## 1. What Claude Code Did This Session

Three commits were added on top of `93ac0c4`:

```text
d0d4595 test: cover yanchaotan entity graph badcase
ebb8a2c docs: require entity graph lookup for named entities
22d903d feat: extract entities during document governance
```

These closed out plan Tasks 11 (final review), 12, 13, 14, and 15. Details:

- **Task 11 (entity_graph_search Neo4j service) — reviewed and confirmed complete.** No code change. Verified: Cypher uses parameterized `$keys` and `$limit`; `MENTIONED_IN` relationship evidence (evidence_span / snippet / confidence / extraction_method / source metadata) is projected into returned `sources`; tests cover evidence shaping, citation dedupe, query normalization, blank query, Chinese `谭谚超` passthrough, and fake Neo4j params.
- **Task 12 (governance wiring) — implemented.** `backend/app/services/knowledge_governance.py` now calls `extract_and_settle_entities(...)` at the top of the per-chunk loop in `settle_document_item_to_governance`, decoupled from PKU extraction so named entities are captured even when LLM PKU extraction returns nothing. Transaction control stays with the caller (flushes, no commit).
- **Task 13 (agent prompt) — implemented.** `engine/app/agent/prompts.py` (`AGENT_SYSTEM_PROMPT`) now documents `entity_graph_search` in the knowledge-tool boundary and adds a Chinese named-entity lookup rule requiring the agent to call `entity_graph_search` before declaring a person/org/paper/alias absent, then fall back to deeper knowledge tools.
- **Task 14 (badcase regression) — implemented.** Explicit named regression tests added at both layers.
- **Task 15 (verification) — run.** Focused suites green (see §4).

Files Claude changed this session (the complete diff `93ac0c4..HEAD`):

```text
 backend/app/services/knowledge_governance.py  |  13 ++++
 backend/tests/test_entity_extraction.py       | 100 ++++++++++++++++++++++++++
 engine/app/agent/prompts.py                   |   3 +
 engine/tests/test_agent_tools.py              |  16 +++++
 engine/tests/test_entity_graph_search_tool.py |  55 ++++++++++++++
```

## 2. Architectural Decisions Already Locked In

(Reproduced from the prior handoff — still authoritative.)

- **MySQL is the source of truth. Neo4j is a derived projection/index.**
- CKP is **not** duplicated as a generic `Entity`. CKP keeps its own node label; Entity covers concrete named objects (people, organizations, papers, emails, projects, datasets, venues, products).
- Graph relationships (locked contract):
  ```
  (:CKP)-[:HAS_CHILD]->(:CKP)
  CKP -[:SUPPORTED_BY]-> PKU
  CKP -[:RELATED_TO]-> CKP
  PKU -[:RELATED_TO]-> PKU
  PKU -[:EVIDENCED_BY]-> Source
  Entity -[:MENTIONED_IN]-> Source
  Alias -[:ALIAS_OF]-> Entity
  Entity -[:AUTHORED|AFFILIATED_WITH|EDUCATED_AT|HAS_EMAIL|CO_AUTHOR|RELATED_TO]-> Entity
  ```
- The `yanchaotan -> Yanchao Tan` badcase is addressed at: source-layer chunk extraction, normalized alias keys, MySQL entity audit rows, entity/alias graph projection, and engine `entity_graph_search` query normalization.

## 3. Known Scope Gap: Asset-Layer Entity Extraction (RECOMMENDED NEXT WORK)

**This is the main remaining functional gap.** Entity extraction is wired into the **document** governance path only:

- ✅ `settle_document_item_to_governance` — calls `extract_and_settle_entities` (Task 12).
- ❌ `backend/app/services/knowledge_governance.py :: settle_personal_asset_item_to_governance` (line ~1840) — does **not** call it.
- ❌ `backend/app/services/knowledge_governance.py :: settle_personal_asset_unit_to_governance` (line ~1874) — does **not** call it.

The plan's self-review explicitly defers asset-layer wiring as a follow-up. **Recommended approach for Codex — mirror the document wiring with its own tests:**

### Task A: Wire entity extraction into asset-item governance

**Purpose:** confirmed personal asset items should populate entity audit rows from their statement/title/summary text.

**TDD steps:**

1. Add a failing test to `backend/tests/test_entity_extraction.py`:

```python
def test_personal_asset_item_governance_extracts_entities(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend.app.database import Base
    from backend.app.models import KnowledgeEntity, PersonalAssetItem
    from backend.app.services import knowledge_governance as kg

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    asset = PersonalAssetItem(
        user_id="default-user",
        title="OpenViewer note",
        summary="Yanchao Tan authored OpenViewer at Fuzhou University.",
        status="confirmed",
        # ... fill any other non-nullable fields by reading the PersonalAssetItem model
    )
    db.add(asset)
    db.commit()

    kg.settle_personal_asset_item_to_governance(db, asset)

    entity = (
        db.query(KnowledgeEntity)
        .filter_by(user_id="default-user", entity_type="person", normalized_key="yanchaotan")
        .first()
    )
    assert entity is not None
```

2. Run red (set `DATABASE_URL`, see §6):
   ```bash
   DATABASE_URL='sqlite:///./_asset_red.db' python -m pytest "backend/tests/test_entity_extraction.py::test_personal_asset_item_governance_extracts_entities" -q
   ```
3. Implement: in `settle_personal_asset_item_to_governance`, call (note: only when `asset.status == "confirmed"`, which the function already guards):
   ```python
   extract_and_settle_entities(
       db,
       source_kind="personal_asset_item",
       source_id=asset.id,
       text=" ".join(filter(None, [asset.title, asset.summary, asset.content_or_statement_field])),
       item_id="",
       chunk_id="",
       user_id=asset.user_id or DEFAULT_USER_ID,
   )
   ```
   **Read the `PersonalAssetItem` model first** to use the correct text fields (title/summary/content/statement). Asset text is prose — see the prose caveat below.
4. Run green. Then run `backend/tests/test_entity_extraction.py backend/tests/test_knowledge_governance_models.py -q`.
5. Commit: `feat: extract entities during personal asset item governance`.

### Task B: Wire entity extraction into asset-unit governance

Same pattern for `settle_personal_asset_unit_to_governance` with `source_kind="personal_asset_unit"` and `source_id=unit.id`, extracting from `unit.title` / `unit.summary` / unit statement text. Add its own failing test first. Commit: `feat: extract entities during personal asset unit governance`.

### Task C (stretch): Project asset-source entities into the graph

`backend/app/services/graph_projection.py :: project_entity_graph` already projects `EntityMention` rows regardless of `source_kind`, so asset-sourced mentions should project automatically once Tasks A/B populate them. Add a `FakeGraph` test in `backend/tests/test_graph_projection.py` that seeds an asset-sourced `EntityMention` (source_kind `personal_asset_unit`) and asserts a `MENTIONED_IN` edge and a `Source` node are projected.

### ⚠️ Prose extraction caveat (important)

The rule-based extractor (`backend/app/services/entity_extraction.py`) is **line-oriented and weak on prose**. It splits author lines on `,`/`;`/`and`, so prose like `"include Yanchao Tan and Shiping Wang"` glues `Yanchao Tan` to preceding words and drops it. It works well on:
- Dedicated author/front-matter lines (`Shide Du, Zihan Fang, Yanchao Tan, ...`),
- First-line paper titles containing `:`,
- Emails,
- Organization lines (University/College/...),
- Author-bio `received the Ph.D. degree from ... with ...` patterns.

Asset text is often prose, so asset-layer extraction will have lower recall. **If higher recall is needed, the planned LLM entity extractor should land first.** Document this in test comments rather than over-tuning the rule extractor.

## 4. Test Results (Claude's verification run)

**Focused entity-graph suites — ALL GREEN:**
- Backend: `test_entity_models test_entity_resolution test_entity_extraction test_graph_client test_graph_projection test_backfill_entity_graph test_config test_knowledge_governance_models` → **55 passed**
- Engine: `test_entity_graph_search_tool test_agent_tools test_config test_deep_search_executors` → **32 passed**

**Full suites — pre-existing failures classified (do NOT chase these as entity-graph bugs):**
- Backend full: `307 passed, 10 skipped, 8 failed`
- Engine full: `187 passed, 15 failed`

All ~23 full-suite failures are **pre-existing, introduced by the merged origin/dev commit `b3be6f2`** (which rewrote governance/ingestion/runner/milvus), **not by entity-graph work**. Proof: the entity-graph commits only touch the 5 files listed in §1; the diff against every failing source file is empty. Representative root causes:
- `engine/app/retrieval/hybrid.py` has no attribute `bm25_search` (restructured by origin/dev).
- `engine/app/agent/rag/agentic.py:107` `'str' object has no attribute 'get'` (RAG judge shape mismatch).
- `backend/tests/test_knowledge_graph_api.py` asserts node types but the API returns `node_types = set()` (empty graph). That test exercises `settle_personal_asset_unit_to_governance`, which the document-only Task 12 change does not touch — entity extraction only *adds* `KnowledgeEntity` rows, it cannot empty the CKP/PKU graph.

**Codex should re-run focused suites after each task; only treat entity-graph test files as in-scope failures.** If a broad-suite failure appears in code this branch didn't touch, classify it as pre-existing and move on.

## 5. Environment Notes

- **Backend tests require `DATABASE_URL`** because `backend/tests/conftest.py` imports `backend.app.database` at collection time. A throwaway SQLite URL works for most unit tests:
  ```bash
  export DATABASE_URL='sqlite:///./_test.db'
  ```
  Delete the temp db file after each run.
- **`neo4j` Python driver must be installed** (`pip install neo4j==5.28.1`) or `graph_client.py` / `graph_projection.py` tests fail at collection with `ModuleNotFoundError: No module named 'neo4j'`. It is already in `requirements.txt`.
- **Do not run backend and engine full suites concurrently** — the combined memory footprint triggered a pytest `MemoryError` during traceback rendering. Run suites sequentially.
- **Real Neo4j / real MySQL smoke (plan Task 16) was NOT run** — no running Neo4j or real MySQL available in this environment. Marked as not-run.

## 6. Working-Tree & Branch Hygiene Rules (important)

- The working tree currently has **uncommitted, unrelated changes** that pre-date this task and must be left alone: `requirements.txt` (adds `setuptools<81`, `apscheduler==3.10.4`) and untracked `start.bat` / `stop.bat`. **Do not commit these as part of entity-graph work.** Stage only the files your task actually changes (`git add <specific paths>`), never `git add .` / `git add -A`.
- **Do not** roll back or revert any existing commit.
- **Do not** force-push.
- **Do not** delete the worktree.
- Commit only the specific files your task modifies, with a clear conventional-commit message.

## 7. Suggested Codex Sequence

1. Confirm branch and clean-ish working tree: `git branch --show-current && git status --short`.
2. Re-run focused suites to establish green baseline (§4).
3. Task A (asset-item extraction) — TDD red → implement → green → commit.
4. Task B (asset-unit extraction) — TDD red → implement → green → commit.
5. Task C (graph projection test for asset-sourced mentions) — TDD red → green → commit.
6. Re-run focused suites; confirm no entity-graph regression.
7. Final commit only if needed; report results + any newly-surfaced (still pre-existing) broad failures.

## 8. Known Non-Blocking Follow-Ups (from prior handoff, still open)

1. `backend/app/services/entity_extraction.py` title detection can misclassify section headings like `Abstract:` in broad prose.
2. `backend/app/services/graph_projection.py` projects PKU with `status != "deprecated"`; add explicit filtering if `merged`/`rejected` become real statuses.
3. `engine/app/agent/tools/entity_graph_search.py` reverses any two Latin words in query alias generation — helps person lookup, broadens non-person queries.
4. Cross-script alias merge (`谭谚超 -> Yanchao Tan`) requires user confirmation or a future LLM resolver.
5. `neo4j` driver emits a DeprecationWarning about sessions not being closed explicitly (non-fatal).
