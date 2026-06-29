# Entity Graph Projection Claude Code Handoff

> **For Claude Code / next agent:** continue from the isolated worktree and branch below. Use a task-by-task workflow with tests first where possible. Do not restart from the main workspace.

**Worktree:** `H:\Agent\Project\Prism\prism\.worktrees\entity-graph-projection`  
**Branch:** `feature/entity-graph-projection`  
**Current HEAD at handoff:** `b7f6198 fix: return entity graph source evidence`  
**Original plan stub in this worktree:** `docs/superpowers/plans/2026-06-29-entity-graph-projection.md`  
**This handoff file:** `docs/superpowers/plans/2026-06-29-entity-graph-projection-claude-handoff.md`

## Current Status

The entity graph migration branch has implemented the lower knowledge-layer entity extraction, MySQL audit tables, Neo4j graph projection, backfill CLI, and the first working engine-side `entity_graph_search` service.

The implementation is not finished. The current in-progress task is Task 11, `entity_graph_search` Neo4j service. It was implemented and then fixed after code review to return evidence from `MENTIONED_IN` relationships. After that fix, local focused tests passed, but the final spec/code-quality re-review has not yet been rerun because this handoff was requested.

Last local verification before this handoff:

```powershell
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py -q
```

Result:

```text
18 passed
```

Important environment note: backend tests currently need `DATABASE_URL` set because `backend/tests/conftest.py` imports `backend.app.database` at collection time. Use this pattern for backend-focused tests:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest <paths> -q
```

## Architectural Decisions Already Locked In

MySQL remains the source of truth. Neo4j is a derived projection/index.

CKP is not duplicated as a generic `Entity`. CKP remains its own graph node label. Entity nodes represent concrete named objects such as people, organizations, papers, emails, projects, datasets, venues, and products.

CKP hierarchy is represented in graph as:

```text
(:CKP)-[:HAS_CHILD]->(:CKP)
```

Existing CKP/PKU relationships are projected into graph:

```text
CKP -[:SUPPORTED_BY]-> PKU
CKP -[:RELATED_TO]-> CKP
PKU -[:RELATED_TO]-> PKU
PKU -[:EVIDENCED_BY]-> Source
```

Entity-layer relationships are projected into graph:

```text
Entity -[:MENTIONED_IN]-> Source
Alias -[:ALIAS_OF]-> Entity
Entity -[:AUTHORED]-> Entity
Entity -[:AFFILIATED_WITH]-> Entity
Entity -[:EDUCATED_AT]-> Entity
Entity -[:HAS_EMAIL]-> Entity
Entity -[:CO_AUTHOR]-> Entity
Entity -[:RELATED_TO]-> Entity
```

The `yanchaotan -> Yanchao Tan` badcase is addressed at multiple layers:

1. bottom source-layer extraction from chunks,
2. normalized alias keys,
3. entity audit rows in MySQL,
4. entity/alias graph projection,
5. engine `entity_graph_search` query normalization.

## Implemented Commits

These are the key commits on `feature/entity-graph-projection`:

```text
b7f6198 fix: return entity graph source evidence
ca7780c Implement Neo4j entity graph search
f810480 Add entity graph search tool shell
c1d67b3 fix: clarify entity graph backfill summary
26b50e2 Add entity graph backfill CLI
9b4872d fix: harden entity graph projection contract
3785626 Project audit entities into graph
d2b28a5 fix: project ckp hierarchy accurately
a6e1b28 Project CKP graph to Neo4j
7635265 fix: align alias graph identity
036fd89 Add Neo4j graph client
c74c307 fix: strengthen entity extraction idempotency
7ddbe8d feat: add rule-first entity extraction
75fe250 fix: tighten entity alias generation
a9b6379 Add entity resolution aliases
07872ef fix: use mysql-safe entity relation key
0135ff1 Add entity audit models
fcb07d6 fix: use neo4j initial database setting
42dd285 fix: align prod neo4j compose defaults
7c8adbf Add Neo4j configuration wiring
5631485 docs: add entity graph projection plan
```

## File Responsibility Map

### Configuration And Docker

`requirements.txt`

- Adds Neo4j Python driver dependency.

`.env.prod.example`

- Documents `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `ENTITY_GRAPH_ENABLED`.

`docker-compose.yml`

- Adds dev Neo4j service with browser/Bolt ports and `neo4j_data` volume.

`docker-compose.prod.yml`

- Adds prod Neo4j service, `neo4j_data`, healthcheck, and backend/engine Neo4j envs.
- Uses `NEO4J_initial_dbms_default__database`, not the obsolete/wrong `NEO4J_dbms_default__database`.

`backend/app/config.py`

- Backend Neo4j config and feature flag.

`engine/app/config.py`

- Engine Neo4j config and feature flag.

`backend/tests/test_config.py`

- Backend settings env/default tests.

`engine/tests/test_config.py`

- Engine settings env/default tests.

### MySQL Entity Audit Layer

`backend/app/models/entity.py`

- Defines `KnowledgeEntity`, `EntityAlias`, `EntityMention`, `EntityRelation`.
- `EntityRelation` uses `relation_key` SHA-256 as the MySQL-safe unique key. Do not reintroduce a unique constraint over `object_literal Text`.
- Event listeners recompute `relation_key` before insert/update.

`backend/app/models/__init__.py`

- Exports the four entity audit models.

`backend/app/utils/auto_migrate.py`

- Adds entity unique constraint names to `KNOWN_UNIQUE_CONSTRAINTS`.

`backend/tests/test_entity_models.py`

- Verifies persistence, MySQL DDL safety for `relation_key`, and duplicate relation uniqueness.

### Entity Normalization

`backend/app/services/entity_resolution.py`

- Pure helper module.
- `normalize_entity_key(text)` compacts Latin/digits/Chinese and preserves Chinese-only keys.
- `alias_keys_for_surface(surface, entity_type)` generates ordered deduped alias keys.
- For `person` and whole-surface two Latin words, generates both orders: `Yanchao Tan -> yanchaotan, tanyanchao`.

`backend/tests/test_entity_resolution.py`

- Tests Latin names, email-like token normalization, two-word person aliases, Chinese `谭谚超`, non-person no-swap, punctuation no-swap.

### Source-Layer Entity Extraction

`backend/app/services/entity_extraction.py`

- Rule-first extraction from text.
- Produces `EntityCandidate` rows for paper titles, people, emails, organizations, authored relations, and affiliation relations.
- `extract_and_settle_entities(...)` persists `KnowledgeEntity`, `EntityAlias`, `EntityMention`, and `EntityRelation`.
- Leaves transaction control to caller; it flushes but does not commit.
- Important known limitation: `_extract_paper_title` scans all lines for first colon line; this can over-detect section headers such as `Abstract:` in broad prose. It is acceptable for current rollout but should be tightened if false positives appear.

`backend/tests/test_entity_extraction.py`

- Covers OpenViewer front matter:
  - paper title,
  - `Yanchao Tan`,
  - `Shiping Wang`,
  - `Fuzhou University`,
  - `yctan@fzu.edu.cn`,
  - authored relation,
  - affiliation relation to Fuzhou University,
  - idempotent persistence,
  - pre-seeded alias/mention/relation idempotency.

### Neo4j Client And Projection

`backend/app/services/graph_client.py`

- Thin Neo4j wrapper with injected driver support.
- Node upserts:
  - `upsert_ckp`
  - `upsert_pku`
  - `upsert_source`
  - `upsert_entity`
  - `upsert_alias`
- `relate(...)` validates labels and relationship types against allowlists before Cypher interpolation.
- Alias identity is `id` based. If no alias id is passed and `entity_id/key` exist, `upsert_alias` derives `id = "{entity_id}:{key}"`.

`backend/tests/test_graph_client.py`

- Fake-driver tests for Cypher shape, params, allowlist rejection, alias identity, close behavior.

`backend/app/services/graph_projection.py`

- Contains `GraphProjectionResult`.
- `project_ckp_graph(db, graph, user_id="default-user")`
  - Projects CKP, PKU, Source nodes.
  - Projects `HAS_CHILD`, `SUPPORTED_BY`, `RELATED_TO`, `EVIDENCED_BY`.
  - Handles real governance hierarchy `subtopic_of` as child-to-parent: `parent -[:HAS_CHILD]-> child`.
  - Dedupes Source nodes by source id.
  - Avoids wrong-user KnowledgeItem title leakage for source title lookup.
- `project_entity_graph(db, graph, user_id="default-user")`
  - Projects active `KnowledgeEntity`.
  - Projects `EntityAlias` via `upsert_alias`.
  - Projects mention Source nodes and `MENTIONED_IN`.
  - Projects entity-to-entity relations with predicate mapping.
  - Skips deprecated/literal-only/dangling relations.
  - Counts alias `ALIAS_OF` as a relation in `relation_count`.

`backend/tests/test_graph_projection.py`

- FakeGraph tests for CKP/PKU/Source graph projection.
- Tests `subtopic_of` hierarchy.
- Tests entity graph projection, relationship type contract vs `GraphClient.ALLOWED_RELATIONSHIP_TYPES`, source title scoping, source dedupe, and skip cases.

### Backfill CLI

`backend/scripts/backfill_entity_graph.py`

- CLI entrypoint:
  - `--limit`
  - `--dry-run`
- Queries `KnowledgeChunk` ordered by `created_at`, `id`.
- Runs `extract_and_settle_entities` for chunks.
- Dry-run rolls back and skips graph.
- Non-dry-run commits extraction, then calls `project_ckp_graph` and `project_entity_graph`.
- Closes graph and DB sessions in `finally`.
- Prints split source counts:
  - `ckp_source_count`
  - `entity_source_count`
  - `ckp_relation_count`
  - `entity_relation_count`
  - `total_relation_count`

`backend/tests/test_backfill_entity_graph.py`

- Fake-only tests for dry-run, success, projection-error cleanup, and parse args.

### Engine Entity Graph Search Tool

`engine/app/agent/tools/entity_graph_search.py`

- Registers `entity_graph_search` tool.
- `EntityGraphSearchInput` has `query` and `limit`.
- `_normalize_entity_key` and `_alias_keys` mirror backend normalization enough for the badcase.
- `Neo4jEntityQueryClient`
  - injected driver support,
  - settings fallback,
  - parameterized Cypher,
  - shapes entities, sources, paths.
- Current HEAD includes fix to return evidence from `MENTIONED_IN` relationship:
  - `evidence_span`,
  - `snippet`,
  - `confidence`,
  - `extraction_method`,
  - source metadata.
- `EntityGraphSearchService`
  - returns `success`, `insufficient`, or `error`,
  - includes `normalized_keys`,
  - catches client exceptions for agent stability.
- `build(ctx, graph_search=None)`
  - returns `StructuredTool`,
  - dedupes citations by `(source_kind, source_id, snippet)`,
  - updates `ctx.stats_holder["entity_graph_search"]`.

`engine/app/agent/tools/__init__.py`

- Imports `entity_graph_search` so it registers in `BUILTIN_REGISTRY`.

`engine/tests/test_entity_graph_search_tool.py`

- Tests fake service invocation.
- Tests registry.
- Tests service normalization.
- Tests blank query.
- Tests citation dedupe.
- Tests Chinese query `谭谚超`.
- Tests fake Neo4j params.
- Tests fake Neo4j result shaping with evidence-rich sources.

## Current Open Item: Finish Task 11 Review

Task 11 was implemented in:

```text
ca7780c Implement Neo4j entity graph search
```

Then code review found an important issue:

- sources returned by graph search did not include evidence from `MENTIONED_IN` relationships.

The fix is:

```text
b7f6198 fix: return entity graph source evidence
```

After that fix, local focused tests passed:

```powershell
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py -q
```

Expected:

```text
18 passed
```

What Claude Code should do first:

1. Review `engine/app/agent/tools/entity_graph_search.py`.
2. Confirm Cypher uses `$keys` and `$limit` params.
3. Confirm `MENTIONED_IN` relationship evidence is included in returned `sources`.
4. Confirm `engine/tests/test_entity_graph_search_tool.py` includes fake result shaping with `evidence_span` and derived `snippet`.
5. Re-run:

```powershell
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py -q
```

6. If clean, consider Task 11 complete.
7. Commit only if changes are needed. Current HEAD already contains the Task 11 fix.

## Remaining Work Plan

### Task 12: Wire Entity Extraction Into Governance Flow

**Purpose:** new ingested/governed document chunks should automatically create/update entity audit rows. Without this, backfill works but fresh documents will not populate entity graph inputs.

**Files:**

- Modify: `backend/app/services/knowledge_governance.py`
- Modify: `backend/tests/test_entity_extraction.py` or `backend/tests/test_knowledge_governance_models.py`

**Where to look:**

- Search in `backend/app/services/knowledge_governance.py`:

```powershell
rg "settle_document_item_to_governance|document_chunk|KnowledgeChunk|_extract_document_chunk" backend\app\services\knowledge_governance.py -n
```

Likely integration point is inside the loop that processes document chunks and settles PKUs.

**Implementation steps:**

1. Add failing test.

Recommended test location: `backend/tests/test_entity_extraction.py`.

Add a test like:

```python
def test_document_governance_extracts_entities_from_chunks(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import KnowledgeChunk, KnowledgeEntity, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    item = KnowledgeItem(
        user_id="default-user",
        title="OpenViewer",
        content="Yanchao Tan authored OpenViewer.",
        source_type="document",
    )
    db.add(item)
    db.flush()
    db.add(
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="OpenViewer authors include Yanchao Tan and Shiping Wang.",
            chunk_type="parent",
        )
    )
    db.commit()

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda *args, **kwargs: kg.AssetUnitPKUExtraction([], []),
    )

    kg.settle_document_item_to_governance(db, item.id)

    assert (
        db.query(KnowledgeEntity)
        .filter_by(user_id="default-user", entity_type="person", normalized_key="yanchaotan")
        .first()
    )
```

Adjust helper names if the exact governance extraction class differs. Read existing tests in:

```text
backend/tests/test_knowledge_governance_models.py
backend/tests/test_asset_unit_pku_extraction.py
```

2. Run red:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests\test_entity_extraction.py::test_document_governance_extracts_entities_from_chunks -q
```

Expected: fail because governance does not call entity extraction yet.

3. Implement.

In `backend/app/services/knowledge_governance.py`, import:

```python
from backend.app.services.entity_extraction import extract_and_settle_entities
```

Inside document chunk governance loop, after the chunk text is available and before final commit, call:

```python
extract_and_settle_entities(
    db,
    source_kind="document_chunk",
    source_id=chunk.id,
    item_id=item.id,
    chunk_id=chunk.id,
    text=chunk.chunk_text or "",
    user_id=item.user_id or DEFAULT_USER_ID,
)
```

4. Run green:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests\test_entity_extraction.py::test_document_governance_extracts_entities_from_chunks -q
```

5. Run focused backend suite:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests\test_entity_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_graph_projection.py backend\tests\test_backfill_entity_graph.py -q
```

6. Commit:

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_entity_extraction.py
git commit -m "feat: extract entities during document governance"
```

### Task 13: Update Agent Prompt For Entity Graph Usage

**Purpose:** instruct the agent to use `entity_graph_search` before declaring named people/objects absent.

**Files:**

- Modify: `engine/app/agent/prompts.py`
- Modify: `engine/tests/test_agent_tools.py` or create prompt-specific test if one exists

**Where to look:**

```powershell
rg "AGENT_SYSTEM_PROMPT|SYSTEM_PROMPT|before declaring|not found" engine\app\agent engine\tests -n
```

**Implementation steps:**

1. Add failing test.

In `engine/tests/test_agent_tools.py`, add:

```python
def test_agent_prompt_requires_entity_graph_before_named_entity_not_found():
    from engine.app.agent.prompts import AGENT_SYSTEM_PROMPT

    prompt = AGENT_SYSTEM_PROMPT.lower()
    assert "entity_graph_search" in AGENT_SYSTEM_PROMPT
    assert "named person" in prompt or "named entity" in prompt
    assert "before declaring" in prompt
```

If prompt constant name differs, adapt after reading `engine/app/agent/prompts.py`.

2. Run red:

```powershell
pytest engine\tests\test_agent_tools.py::test_agent_prompt_requires_entity_graph_before_named_entity_not_found -q
```

3. Update `engine/app/agent/prompts.py`.

Add a rule similar to:

```text
Named entity lookup rule:
When the user asks about a named person, organization, paper, project, email, or alias-like token, call `entity_graph_search` before saying the entity is absent. If entity graph search returns no result, then use raw document/deep knowledge fallback. If all paths are insufficient, say the entity was not found in the current indexed evidence rather than claiming it does not exist.
```

4. Run green:

```powershell
pytest engine\tests\test_agent_tools.py::test_agent_prompt_requires_entity_graph_before_named_entity_not_found -q
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py -q
```

5. Commit:

```powershell
git add engine/app/agent/prompts.py engine/tests/test_agent_tools.py
git commit -m "docs: require entity graph lookup for named entities"
```

### Task 14: Badcase Regression Tests

**Purpose:** lock the original `yanchaotan / 谭谚超查无此人` failure into tests.

**Files:**

- Modify: `backend/tests/test_entity_extraction.py`
- Modify: `engine/tests/test_entity_graph_search_tool.py`

**Backend extraction regression:**

Add to `backend/tests/test_entity_extraction.py`:

```python
def test_yanchaotan_badcase_extracts_person_paper_affiliation_and_email():
    from backend.app.services.entity_extraction import extract_entity_candidates_from_text

    text = (
        "OpenViewer: Openness-Aware Multi-View Learning\n"
        "Shide Du, Zihan Fang, Yanchao Tan, Changwei Wang, Shiping Wang\n"
        "College of Computer and Data Science, Fuzhou University\n"
        "yctan@fzu.edu.cn, shipingwangphd@163.com\n"
    )

    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")
    entities = {(item.entity_type, item.surface_text) for item in candidates if item.kind == "entity"}
    relations = {(item.subject_surface, item.predicate, item.object_surface) for item in candidates if item.kind == "relation"}

    assert ("person", "Yanchao Tan") in entities
    assert ("person", "Shiping Wang") in entities
    assert ("paper", "OpenViewer: Openness-Aware Multi-View Learning") in entities
    assert ("organization", "Fuzhou University") in entities
    assert ("email", "yctan@fzu.edu.cn") in entities
    assert ("Yanchao Tan", "authored", "OpenViewer: Openness-Aware Multi-View Learning") in relations
    assert ("Yanchao Tan", "affiliated_with", "Fuzhou University") in relations
```

**Engine query regression:**

Add to `engine/tests/test_entity_graph_search_tool.py`:

```python
def test_yanchaotan_query_resolves_to_yanchao_tan_entity_with_source():
    class BadcaseClient:
        def query_entity_context(self, normalized_keys, limit):
            assert "yanchaotan" in normalized_keys
            return {
                "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
                "sources": [{
                    "source_kind": "document_chunk",
                    "source_id": "chunk-1",
                    "snippet": "Yanchao Tan authored OpenViewer.",
                    "evidence_span": "Yanchao Tan authored OpenViewer.",
                }],
                "paths": [{"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"], "relation_type": "AUTHORED"}],
            }

    service = EntityGraphSearchService(client=BadcaseClient())
    payload = service.search_entity_context("yanchaotan", limit=5)

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
    assert payload["sources"][0]["snippet"] == "Yanchao Tan authored OpenViewer."
```

Run:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests\test_entity_extraction.py engine\tests\test_entity_graph_search_tool.py -q
```

Commit:

```powershell
git add backend/tests/test_entity_extraction.py engine/tests/test_entity_graph_search_tool.py
git commit -m "test: cover yanchaotan entity graph badcase"
```

### Task 15: End-To-End Verification

Run backend focused tests:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests\test_entity_models.py backend\tests\test_entity_resolution.py backend\tests\test_entity_extraction.py backend\tests\test_graph_client.py backend\tests\test_graph_projection.py backend\tests\test_backfill_entity_graph.py backend\tests\test_config.py -q
```

Run engine focused tests:

```powershell
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py engine\tests\test_config.py -q
```

Run broader backend/engine tests if time allows:

```powershell
$env:DATABASE_URL='mysql+pymysql://user:pass@127.0.0.1:3306/prism_test'
pytest backend\tests -q
pytest engine\tests -q
```

If broad suites fail, classify failures:

- caused by this branch,
- pre-existing environment issue,
- unrelated existing tests.

Do not claim full suite success unless verified.

### Task 16: Optional Local Neo4j Smoke

Only do this if Docker is available and the user wants runtime smoke.

```powershell
docker compose up -d neo4j
$env:DATABASE_URL='<real local database url>'
python -m backend.scripts.backfill_entity_graph --limit 20
```

Expected output includes:

```text
backfilled entity graph chunks=
```

If real DB is not available, skip and document as not run.

## Suggested Next Review Steps

Because Task 11 had a fix after quality review, Claude Code should first do a quick local review and then proceed:

1. Inspect Task 11 diff:

```powershell
git diff f810480..HEAD -- engine/app/agent/tools/entity_graph_search.py engine/tests/test_entity_graph_search_tool.py
```

2. Run:

```powershell
pytest engine\tests\test_entity_graph_search_tool.py engine\tests\test_agent_tools.py -q
```

3. If clean, continue Task 12.

## Known Non-Blocking Issues / Follow-Ups

1. `backend/tests/conftest.py` imports `backend.app.database` at collection time. Backend tests generally require `DATABASE_URL` to be set. This was pre-existing and intentionally not refactored in this branch.

2. `backend/app/services/entity_extraction.py` title detection can misclassify section headings like `Abstract:` in broad prose. It is acceptable for OpenViewer/front-matter rollout but should be tightened if false positives appear.

3. `backend/app/services/graph_projection.py` projects PKU statuses as `status != "deprecated"`. If `merged` or `rejected` become real statuses that should be excluded, add explicit status filtering and tests.

4. `engine/app/agent/tools/entity_graph_search.py` reverses any two Latin words in query alias generation. This helps person-name lookup but can broaden non-person queries. Consider query intent/entity-type detection later.

5. The earlier P0 query fallback work was done in the main workspace before this branch/worktree flow and is not part of this branch unless separately cherry-picked.

## Handoff Checklist For Claude Code

- [ ] Confirm worktree path and branch:

```powershell
cd H:\Agent\Project\Prism\prism\.worktrees\entity-graph-projection
git branch --show-current
git status --short
```

- [ ] Confirm current HEAD includes `b7f6198`.
- [ ] Re-run Task 11 focused tests.
- [ ] Finish Task 11 review.
- [ ] Implement Task 12 governance integration.
- [ ] Implement Task 13 prompt update.
- [ ] Implement Task 14 badcase regression.
- [ ] Run Task 15 focused verification.
- [ ] Prepare final branch summary / PR notes.

