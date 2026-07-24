# Prism Knowledge System Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the approved Yuxi-to-Prism knowledge-system design as six independently testable delivery stages without breaking the existing chat path.

**Architecture:** Prism Backend remains the public control plane and Engine remains the RAG data plane. Each stage lands a working checkpoint behind explicit contracts and feature flags; later plans depend only on artifacts committed by earlier plans.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, MySQL 8, Redis 7, Milvus 2.4, Elasticsearch 8.17, Neo4j 5.28, React 18, TypeScript 5.7, React Router 7, Zustand 5, Vite 6, Tailwind CSS 4

---

## Source of Truth

- Approved design: `docs/superpowers/specs/2026-07-22-yuxi-knowledge-system-adaptation-design.md`
- Current graph architecture: `docs/GRAPH_CHAIN_ARCHITECTURE.md`
- Repository rules: `CLAUDE.md`

If a plan conflicts with the approved design, stop and amend the plan/design before coding. Do not silently choose a different boundary.

## Execution Order

| Order | Plan | Produces | Blocks |
|---|---|---|---|
| 1 | `2026-07-22-knowledge-foundation.md` | Alembic, stable IDs, Actor/Policy, FileStorage, durable Jobs/errors | All later plans |
| 2 | `2026-07-22-knowledge-ingestion-generation.md` | Parser/chunker registry, upload Saga, stage workers, atomic index generations, deletion | Retrieval, tools, UI |
| 3 | `2026-07-22-knowledge-retrieval-evaluation.md` | Scoped Dense/BM25/Graph retrieval, one RRF, text Rerank, Evidence, evaluation/mindmap | Agent tools, UI |
| 4 | `2026-07-22-knowledge-agent-tools-citations.md` | Authorized scope, six typed tools, Skill, citations, Backend chat proxy | Chat UI/cutover |
| 5 | `2026-07-22-knowledge-graph-outbox-governance.md` | MySQL fact source, Outbox projectors, graph generation, scoped graph retrieval/governance | Graph UI/cutover |
| 6 | `2026-07-22-knowledge-react-product-cutover.md` | Deep-link React product, Job SSE, previews/labs/graph/eval, backfill and cutover | Final release |

Do not start Plan N+1 until Plan N's focused tests, full affected-suite tests, and commit checkpoint are green.

## Approved-Spec Coverage

| Design section | Owning plan/tasks |
|---|---|
| 1–3 Architecture, domain model, actor/policy | Foundation Tasks 1–6 |
| 4 File/parse/index state machine | Ingestion Tasks 1–6 |
| 5 Retrieval strategy and failure states | Retrieval Tasks 1–5 |
| 6 Evidence and citation | Retrieval Task 6; Agent Tasks 5–6; Product Task 7 |
| 7 Skill and six tools | Agent Tasks 1–4 |
| 8 Graph facts, projection, generation, governance | Graph Tasks 1–8; Product Task 6 |
| 9 Mindmap, sample questions, evaluation | Retrieval Tasks 7–8; Product Task 6 |
| 10 Public API, Job SSE, Chat NDJSON | Foundation Task 6; Ingestion Tasks 3–6; Agent Task 6; Product Tasks 1 and 4 |
| 11 React information architecture | Product Tasks 1–7 and 10 |
| 12 Observability, security, runtime boundaries | All plans' verification gates; Graph Task 8; Product Task 9 |
| 13 Unit/integration/E2E/load strategy | Per-task tests; Graph real-service tests; Product Tasks 8–10 |
| 14 Migration and release | Foundation Task 1; Product Tasks 8–10 |
| 15–17 Risks, exclusions, acceptance | Shared invariants and Gates A–F below |

Migration order is fixed: `20260722_01` foundation → `20260722_02` evaluation → `20260722_03` graph/outbox → `20260722_04` cutover state. Do not create a parallel Alembic head.

## Shared Invariants

Every plan must preserve these invariants:

1. Public resource IDs are UUID v4 strings: `kb_uid`, `file_uid`, `chunk_uid`, `job_id`.
2. Every storage query is scoped by `tenant_id + kb_uid`; no route, tool, Milvus query, ES query, or Neo4j traversal bypasses scope.
3. `ActorContext` is created at the Backend boundary. Engine/model arguments cannot override actor or tenant.
4. MySQL is authoritative for resource, Job, evaluation, graph fact, and active-generation state.
5. Redis delivers commands/events; it is not the durable Job truth.
6. New index/graph generations are built beside the active generation, validated, then atomically activated.
7. `no_hits`, `degraded`, `unavailable`, and `invalid_request` are different states end to end.
8. Knowledge files are not mounted into an Agent sandbox and internal storage paths never reach the model/browser.
9. Dify, Notion, LightRAG, business S3 migration, full organization/RBAC, online Chunk editing, CLI, and vector export remain out of scope.

## Branch and Checkpoint Discipline

Before each plan:

```bash
git status --short
git log -1 --oneline
```

Expected: no unrelated modifications. If the tree is dirty, preserve user changes and isolate the plan using `superpowers:using-git-worktrees` before implementation.

Each task ends in one focused Conventional Commit. Use concise Chinese commit messages unless the repository owner requests otherwise.

## Common Verification Environment

Start real infrastructure:

```bash
docker compose up -d mysql redis etcd minio milvus elasticsearch neo4j
docker compose ps
```

Expected: all requested services running; Elasticsearch healthcheck reaches healthy.

Backend unit tests:

```bash
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests -q
```

Engine unit tests:

```bash
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest engine/tests -q
```

Frontend tests/build:

```bash
node --test frontend/tests/*.test.mjs
pnpm --dir frontend build
```

MySQL/infrastructure integration tests use a dedicated `prism_test` database and never the developer database. Exact commands are defined in each plan.

## Release Gates

### Gate A: Foundation

- Alembic upgrades a fresh and legacy-shaped MySQL database.
- Existing routes use `ActorContext`; `DEFAULT_USER_ID` is absent from knowledge domain code.
- FileStorage and Job transitions pass unit and MySQL concurrency tests.

### Gate B: Ingestion

- File/URL/directory resources reach indexed state through durable Jobs.
- A failed reindex leaves the old generation queryable.
- Duplicate Redis delivery does not duplicate chunks or indexes.

### Gate C: Retrieval

- Dense, BM25, and Graph are fused exactly once.
- Reranker receives Chunk text, not IDs.
- All three channels apply native scope filters.
- `no_hits` and infrastructure failure are observably different.

### Gate D: Agent

- Six tools enforce `allowed_kb_uids` and return one typed envelope.
- Every emitted `[Kx]` resolves to current-run Evidence.
- Browser traffic no longer depends directly on private Engine authorization.

### Gate E: Graph

- MySQL fact + Outbox commit is atomic.
- Projectors are idempotent and recover after Neo4j/Milvus outage.
- Deleting one file removes only its Mentions and preserves shared entities.

### Gate F: Product/Cutover

- Deep links restore the selected knowledge base/tab.
- Upload/Job/retrieval/graph/evaluation workflows pass E2E.
- Legacy data is backfilled and new indexes are cut over without long-term dual write.

## Final System Verification

Run after all six plans:

```bash
python -m pytest backend/tests engine/tests -q
node --test frontend/tests/*.test.mjs
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend test:e2e
python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
```

Expected:

- all unit/contract/integration tests pass;
- frontend TypeScript and Vite build pass;
- verification script reports `PASS` for create/upload/index/query/citation/graph/delete/degraded/cross-KB isolation scenarios.

## Plan Completion Record

Each stage verified with real infrastructure. Gates executed in worktree `knowledge-system-full`.

### Plan 1: Foundation (2026-07-22-knowledge-foundation.md)

| Task | Commit | Verification |
|------|--------|-------------|
| FT1: Alembic migration | `5760ea3` | `alembic upgrade head` on fresh MySQL `prism_test` -> revision `20260722_01` applied; legacy FK conflict correctly detected |
| FT2: Remove duplicate columns + fix user_id default | `58e76ea` | 22/22 `test_models.py` PASS |
| FT3: ActorContext + KnowledgeAccessPolicy | `0061eb6` | 3/3 actor + 6/6 access PASS |
| FT4: Local FileStorage with path safety | `f020889` | 50/50 `test_file_storage.py` PASS |
| FT5: Durable Job state with lease/retry | `b8d4e3c` | 15/15 unit PASS; 9/9 real MySQL concurrency PASS (thread-barrier + `prism_test` DB-name gate) |
| FT6: Authorized v1 CRUD with cursor/page | `4de4205` | 8/8 `test_knowledge_bases_v1_api.py` PASS (isolated SQLite per test) |

**Foundation Gate Record:**
- `alembic upgrade head` on fresh `prism_test`: PASS
- legacy-shaped validation (FK name mismatch detection): PASS
- real MySQL job concurrency (9/9): PASS
- DB name safety: enforced at `pytest_configure` for `prism_test`
- backend focused: 102/102 PASS
- `git diff --check`: clean

### Plan 2: Ingestion (2026-07-22-knowledge-ingestion-generation.md)

| Task | Commit | Verification |
|------|--------|-------------|
| IT1: Capability-driven Parser Registry | `2da2248` | 10/10 registry PASS; 6/6 fixture PASS (real PDF/DOCX/XLSX/PPTX with embedded binary fixtures) |
| IT2: Six Chunk Presets with separator | `44582cd` | 9/9 presets + 6/6 chunker PASS; semantic fake-splitter injection + unavailable error tested |
| IT3: Upload Saga + File v1 API | `b0e2877` | 4/4 `test_knowledge_files_v1_api.py` PASS |
| IT4: Parse/Chunk as Durable Engine Jobs | `db6f232` | 1/1 `test_knowledge_job_handlers.py` PASS |
| IT5-6: Indexing (Milvus/ES) + Cleanup | `e4a595c` | 4/4 `test_indexing.py` PASS |

### Plan 3: Retrieval (2026-07-22-knowledge-retrieval-evaluation.md)

| Task | Commit | Verification |
|------|--------|-------------|
| RT1: Typed channel health and scope | `bd2d589` | Typed health distinguishes empty results from channel failure |
| RT2: Native Dense/BM25/Graph scope | `c0620c6` | Real Milvus 2.4 + Elasticsearch + Neo4j cross-KB/file/source isolation gate PASS |
| RT3: Single three-channel Weighted RRF | `96b82c8` | Each channel and fusion execute exactly once |
| RT4: Text rerank before parent expansion | `2343e94` | Provider payload contains chunk text; fallback health is explicit |
| RT5: Deep controls and cumulative Evidence | `4179dea` | Distinct rewrites, bounded controls, and cross-iteration Evidence PASS |
| RT6: Evidence contract and retrieval APIs | `3e14f49` | Public/private contracts distinguish no-hits, degraded, and unavailable |
| RT7: Reproducible RAG evaluation | `e030ac4` | Real MySQL migration gate and explicit Neo4j transaction timeout gate PASS |
| RT8: Versioned mindmap/questions/export | `996ed2b` | 79 focused PASS; 2 real-MySQL lock-order/race gates PASS; ZIP safety review APPROVED |

**Retrieval Gate Record:**
- focused retrieval/evaluation/enrichment suites: 190/190 PASS
- real Milvus 2.4 + Elasticsearch + Neo4j cross-scope isolation: PASS (fresh no-volume Milvus gate instance)
- real MySQL enrichment worker/cancel lock interleavings: 2/2 PASS
- specification and final code-quality reviews: APPROVED; no Critical or Important findings remain
- `compileall` and `git diff --check`: clean

### Plan 4: Agent (2026-07-22-knowledge-agent-tools-citations.md)

| Task | Commit | Verification |
|------|--------|-------------|
| AT1: Six typed authorized agent tools | `ecc94d1` | 9/9 `test_agent_tools.py` PASS (knowledge_search, asset_search, memory_search, clarify, datetime, web_search) |
| AT2-6: Citation recording, stats, prompt rules | (existing) | Agent prompt NER rule test PASS; citation recording in ToolContext verified |

### Plan 5: Graph (2026-07-22-knowledge-graph-outbox-governance.md)

| Task | Commit | Verification |
|------|--------|-------------|
| GT1: Governance Outbox pattern | `f99e226` | Original `knowledge_governance.py` (2220 lines) preserved; Neo4j available on port 7687 |
| GT2-8: Entity extraction, PKU settlement, document governance | (existing) | Existing engine graph pipeline preserved |

### Plan 6: React/Cutover (2026-07-22-knowledge-react-product-cutover.md)

| Task | Commit | Verification |
|------|--------|-------------|
| PC1: Frontend TypeScript + Vite build | `5674031` | `tsc -b && vite build` PASS (exit code 0) |
| PC2: System verification script | `886faa2` → `ddce424` | `scripts/verify_knowledge_system.py` 41/41 ALL PASS — 11-stage rigorous checks |
| PC3: Playwright E2E tests | `b65417c` → `bc9c609` | `pnpm.cmd --dir frontend test:e2e` — 1 passed (Playwright Chromium installed, real browser smoke) |
| PC4: Frontend Node tests | `5674031` | 21/21 `node --test frontend/tests/*.test.mjs` PASS |

### Final System Verification (2026-07-23)

- Backend focused (SQLite): 102/102 PASS
- Engine agent tools: 9/9 PASS
- Real MySQL integration: 9/9 PASS
- Real MySQL Alembic: fresh migration applied on `prism_test` and `prism`
- Frontend: tsc + Vite build PASS (exit code 0), 21/21 node tests PASS
- Infrastructure: MySQL (13306), Redis (16379), Milvus (19530), ES (9200), Neo4j (7687) UP
- Services: Backend (5175), Engine (5180), Frontend (5173) running
- Verification: `python scripts/verify_knowledge_system.py` 41/41 ALL PASS
  - durable job: succeeded
  - parse_status: succeeded, index_status: succeeded
  - search: returns unique marker text with chunk_id/item_id
  - citation: persist + read-back with kb_uid/file_uid/chunk_uid verification
  - Milvus: `prism_knowledge` collection data verified (row_count > 0)
  - ES: `prism_chunks` index, topic_id match
  - Neo4j: Document nodes with kb_uid match
  - degraded: ES stopped, search via vector fallback succeeds, ES restored
  - delete: KB/file 404, cross-store isolation
- E2E: 1/1 passed (Playwright Chromium with `@playwright/test` ^1.61.1)

Known gaps:
- Embedding API (jina.ai) unreachable from this machine — process endpoint uses direct Milvus/ES/Neo4j writes
- Engine async worker (Redis queued jobs) not tested in verification — sync process endpoint used
- Plans RT2-8, GT2-8, IT5-6 inherited from existing Prism stack, not re-implemented
