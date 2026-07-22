# Prism Knowledge System Kilo Handoff

## Objective

Complete the approved Yuxi-to-Prism knowledge-system adaptation, verify every stage with real infrastructure, then start Backend, Engine, and Frontend for product acceptance.

This handoff is execution-oriented. Do not redesign the approved architecture or restart repository discovery unless current code contradicts the documents below.

## Canonical Documents

Read in this order:

1. `CLAUDE.md`
2. `docs/GRAPH_CHAIN_ARCHITECTURE.md`
3. `docs/superpowers/specs/2026-07-22-yuxi-knowledge-system-adaptation-design.md`
4. `docs/superpowers/plans/2026-07-22-knowledge-system-roadmap.md`
5. The six stage plans referenced by the roadmap.

The approved exclusions remain binding: no Dify, Notion, LightRAG, full organization/RBAC product, online Chunk editor, vector export, knowledge-to-sandbox mount, or long-term legacy/native dual write.

## Authoritative Workspace

Continue from the existing isolated worktree, not the parent checkout:

```powershell
cd H:\Agent\Project\Prism\prism\.worktrees\knowledge-system-full
git branch --show-current
git status --short
```

Expected branch: `codex/knowledge-system-full`.

The parent checkout `H:\Agent\Project\Prism\prism` remains on `feature/entity-graph-projection` and does not contain the implementation commits after `5d7f325`. Do not accidentally implement there or copy files between the two worktrees.

## Completed Work

### Foundation Task 1: Alembic and Knowledge Migration

Status: complete; spec review approved; code-quality review approved.

Implemented:

- Alembic configuration and revision `20260722_01`.
- Fresh, full-legacy, and partial-legacy MySQL migration paths.
- UUID v4 public-ID backfill and canonical KB scope propagation.
- Safe handling of ambiguous/orphan legacy rows.
- Precise upgrade/downgrade bookkeeping for columns, nullability, unique constraints, foreign keys, and indexes.
- Nullable active generations and KB-wide Job `file_uid`.
- Non-null legacy-safe idempotency keys.
- MySQL `MEDIUMTEXT` preservation.
- Removal/restoration of obsolete legacy uniqueness.
- No MD5-to-SHA256 fabrication.
- Four relationship foreign keys and four Job scheduling indexes.

Verification evidence:

- Latest real-MySQL migration suite: `23 passed` against the dedicated `prism_test` database.
- `git diff --check`: clean.
- Final migration alignment commit: `cdd9ea2`.

### Foundation Task 2: Explicit ORM IDs, Scope, and Status

Status: implementation committed; spec review approved; code-quality review has one open Important issue.

Implemented in `66e8895` and `101973e`:

- `knowledge_types.py` enums and UUID helper.
- Topic/File/Item/Chunk/Job stable IDs and scope fields.
- Generation, parsing/index/graph status, Job lease/cancel/retry fields.
- Chunk self-FK with `ON DELETE SET NULL`.
- One physical filename column plus bidirectional legacy synonym.
- ORM/migration columns, unique constraints, foreign keys, and indexes aligned.

Verification evidence:

- `backend/tests/test_models.py`: `21 passed`.
- Task 2 spec review: approved.

Open quality issue — fix this first:

- `backend/app/models/knowledge_item.py` still gives `KnowledgeItem.user_id` the Python default `"default-user"`.
- Remove that default while keeping the nullable legacy column.
- Add a model test asserting Topic, File, and Item legacy `user_id` columns have neither client nor server defaults.
- Run `backend/tests/test_models.py`, commit the fix, then repeat Task 2 spec and quality review before starting Task 3.

## Remaining Execution Order

Do not parallelize implementation agents against the shared worktree. For every task use:

```text
fresh implementer -> focused tests and commit -> spec review -> quality review -> fix/re-review until approved
```

Resume in this exact order:

1. Finish Foundation Task 2 open quality issue.
2. Foundation Task 3: ActorContext and KnowledgeAccessPolicy.
3. Foundation Task 4: local FileStorage abstraction.
4. Foundation Task 5: durable Job state, lease, cancellation, and idempotency.
5. Foundation Task 6: uniform errors and authorized v1 knowledge CRUD.
6. Run Foundation plan verification and record its commits/results in the roadmap.
7. Execute Ingestion/Generation Tasks 1–6.
8. Execute Retrieval/Evidence/Evaluation Tasks 1–8.
9. Execute Agent Tools/Citations Tasks 1–6.
10. Execute Graph Outbox/Governance Tasks 1–8.
11. Execute React Product/Cutover Tasks 1–10.
12. Run final real-service verification, start all three application processes, and perform browser acceptance.

Never start Plan N+1 while Plan N has an open Critical/Important review finding or a failed release gate.

## Environment and Test Infrastructure

The isolated worktree has its own MySQL compose project:

```powershell
docker compose up -d mysql
docker compose ps mysql
```

Port: `13306`; dedicated test database: `prism_test`.

Credentials must be read locally from existing configuration and injected only into the current process. Never add or print a database URL, password, API key, or provider token. Require `MYSQL_TEST_DATABASE_URL`/`PRISM_TEST_DATABASE_URL` to resolve exactly to the dedicated test database before destructive migration fixtures run.

For Python unit tests, set an explicit SQLite URL so a malformed ambient root URL cannot affect collection:

```powershell
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests/test_models.py -v
```

Use Python 3.11 for final verification. The prior local baseline used Python 3.14, which exposed compatibility noise not representative of the declared runtime.

## Pre-existing Baseline Failures

These existed before the knowledge-system implementation and must not be misreported as new regressions:

- Frontend Node tests: `21/21` passed.
- Frontend build failed in the old `KnowledgeGraphPage.tsx` because React's `KeyboardEvent` type was used for native `window.addEventListener`; the React/Graph stage must fix it.
- Engine baseline: `283 passed, 14 failed`; failures include stale Agentic RAG/tool expectations, graph schema behavior, ingestion worker behavior, and Stage-A pipeline tests.
- Backend baseline had multiple existing failures plus a Windows pytest temporary-directory cleanup `PermissionError`; rerun under Python 3.11/container and record an exact baseline before broad full-suite claims.

Focused task tests and real-service gates remain mandatory even while these known baseline failures exist. By final cutover, the affected suites and full release gate must be green.

## Architectural Invariants

- Backend is the public control plane; Engine is the AI/RAG data plane.
- Browser traffic and Agent tools cannot bypass Backend authorization.
- `ActorContext` originates at the Backend boundary; model/tool inputs cannot override actor or tenant.
- Every query and projection is scoped by `tenant_id + kb_uid` and the correct active generation.
- MySQL is authoritative; Redis is delivery/cache only; Milvus, Elasticsearch, and Neo4j are rebuildable projections.
- Dense, BM25, and Graph are fused exactly once with Weighted RRF.
- Rerank receives loaded text, not IDs.
- `no_hits`, `degraded`, `unavailable`, and `invalid_request` remain distinct end to end.
- Knowledge files never appear as Agent sandbox paths, and internal storage paths never reach browser/model responses.
- New index/graph generations are built beside the active generation, validated, and atomically switched.
- MySQL graph facts and Outbox events commit atomically; projectors are idempotent.
- Every emitted `[Kx]` must resolve to current-run persisted Evidence.

## Final Acceptance

After all plans are complete:

```powershell
python -m pytest backend/tests engine/tests -q
node --test frontend/tests/*.test.mjs
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
pnpm.cmd --dir frontend test:e2e
python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
```

Then start applications using README Mode B:

```powershell
python -m engine.run
$env:SKIP_ENGINE='1'; python -m backend.run
pnpm.cmd --dir frontend dev -- --host 127.0.0.1 --port 5173
```

Browser acceptance must cover create/upload/index/query/citation/graph/delete/degraded/cross-KB isolation, deep-link restoration, Job SSE recovery, and rollback behavior before declaring completion.
