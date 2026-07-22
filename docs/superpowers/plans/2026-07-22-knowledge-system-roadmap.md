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

After each plan, append its commit hash and verification summary here in a follow-up docs-only commit. Do not mark a stage complete based only on code review or mocked tests.
