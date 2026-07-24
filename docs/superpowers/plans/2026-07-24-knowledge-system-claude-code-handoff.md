# Prism Knowledge System — Claude Code Continuation Handoff

**Date:** 2026-07-24
**Objective:** Continue from the current worktree and finish the complete six-stage native Prism knowledge-system adaptation. Do not reduce the goal to the already-passing subset.

## 1. Mandatory Workspace

Use only:

```text
H:\Agent\Project\Prism\prism\.worktrees\knowledge-system-full
```

Required branch:

```text
codex/knowledge-system-full
```

Do not edit or copy implementation files into the parent checkout:

```text
H:\Agent\Project\Prism\prism
```

Published handoff checkpoint:

```text
base implementation: 90dcd0b feat(agent): 统一知识工具返回契约
handoff commit: includes this document and the Agent Task 3 RED test
expected checkout: clean
```

The tracked RED test file is intentional TDD work for Agent Task 3. Preserve it and implement against it.

Start with:

```powershell
cd H:\Agent\Project\Prism\prism\.worktrees\knowledge-system-full
git status --short
git branch --show-current
git log -5 --oneline
```

## 2. Read Before Editing

Read completely, in this order:

1. `CLAUDE.md`
2. `docs/GRAPH_CHAIN_ARCHITECTURE.md`
3. `docs/superpowers/specs/2026-07-22-yuxi-knowledge-system-adaptation-design.md`
4. `docs/superpowers/plans/2026-07-22-knowledge-system-kilo-handoff.md`
5. `docs/superpowers/plans/2026-07-22-knowledge-system-roadmap.md`
6. All six stage plans referenced by the roadmap:
   - `2026-07-22-knowledge-foundation.md`
   - `2026-07-22-knowledge-ingestion-generation.md`
   - `2026-07-22-knowledge-retrieval-evaluation.md`
   - `2026-07-22-knowledge-agent-tools-citations.md`
   - `2026-07-22-knowledge-graph-outbox-governance.md`
   - `2026-07-22-knowledge-react-product-cutover.md`
7. This handoff.

The roadmap's Plan 4–6 completion table contains older Kilo claims such as “existing” or broad smoke-test results. Those claims do **not** prove the detailed 2026-07-22 plans are complete. Treat the six detailed plans and current code/tests as authoritative. Replace stale roadmap entries with actual commits and gates as work completes.

## 3. Execution Rules

- Follow the detailed stage plans in order. Current position is **Agent Task 3**.
- Every Task uses TDD: add a failing behavior test, observe the expected RED, implement the minimum complete behavior, then rerun focused and regression tests.
- Make one implementation commit per Task. Documentation-only stage records may use a separate commit.
- For every Task, perform specification review first, then code-quality/security review.
- Do not proceed while any Critical or Important finding remains.
- Use real MySQL, Redis, Milvus, Elasticsearch, and Neo4j for the gates that cover migrations, concurrency, durable jobs, projection, indexing, retrieval, or cutover. SQLite/mock-only evidence is insufficient for those paths.
- Do not implement Dify, Notion, or LightRAG.
- Do not expose `.env`, credentials, API keys, service tokens, provider payloads, absolute storage paths, `storage_uri`, or internal file paths.
- Preserve the existing Prism GraphRAG main chain. Add scoped adapters and cutover paths exactly as designed; do not replace the main chain casually.
- Do not stop between Tasks to ask whether to continue. Continue through Agent, Graph, Product/Cutover, final verification, and three-service startup.

## 4. Completed and Verified Work

### Foundation

Foundation Tasks 1–6 are complete. Important commits/gates are recorded in the roadmap. Key evidence includes fresh/legacy MySQL Alembic gates, real MySQL Job concurrency, removal of the implicit default user, ActorContext/access policy, safe FileStorage, and authorized v1 CRUD.

### Ingestion

Ingestion Tasks 1–6 are complete, including parser registry, chunk presets, upload Saga, durable parse/chunk workers, atomic Milvus/ES generation publication, and recoverable cross-store cleanup.

Recent completion commits include:

```text
59a532e fix(knowledge): 补齐分块租户作用域
abffe10 feat(knowledge): 恢复持久任务摄取边界
1ecf104 feat(knowledge): 增加原子索引 generation 发布
5d8ea6c feat(knowledge): 增加可恢复的跨存储清理
```

Use `git log --oneline --reverse b66f913^..HEAD` for the exact authoritative history.

### Retrieval / Evaluation / Enrichment

Retrieval Tasks 1–8 are complete:

```text
3550ab1 feat(retrieval): 定义检索通道健康契约
884d905 fix(retrieval): 强制三路知识库作用域
421af4e refactor(retrieval): 统一单次三路 RRF 融合
330ecb0 fix(retrieval): 使用正文执行重排
7c49206 fix(retrieval): 让深度检索参数与改写真正生效
1071f95 feat(retrieval): 增加证据契约与检索 API
13bc964 feat(knowledge): 增加可复现的 RAG 评估
18b834f feat(knowledge): 增加导图示例问题与安全导出
dab14d3 docs(knowledge): 记录检索阶段验收结果
```

Verified evidence:

- 190 focused retrieval/evaluation/enrichment tests passed.
- Real MySQL enrichment cancel/worker lock interleavings: 2 passed.
- Real Milvus 2.4 + Elasticsearch + Neo4j cross-KB/file/source-type isolation: passed.
- Retrieval Task 8 specification and final quality reviews: APPROVED.
- `compileall` and `git diff --check`: clean at stage completion.

Concurrency invariants already fixed and must remain:

- Enrichment API, worker, and reaper use `topic FOR UPDATE -> scoped job FOR UPDATE`.
- Job reads after waiting use `populate_existing()`/current reads.
- Terminal cancel is idempotent.
- If cancel commits after the worker's pre-LLM/pre-terminal read, cancel wins; stale output is not written back as ready.

### Agent Task 1 — Complete

Commit:

```text
8bc2439 feat(agent): 增加签名知识库运行范围
```

Implemented canonical JSON + HMAC-SHA256 Backend signing and Engine verification, strict URL-safe Base64 decoding, constant-time signature comparison, frozen/forbid-extra schemas, shared `KNOWLEDGE_SCOPE_SECRET`, malformed/tamper tests, and expiry-at-deadline behavior.

Evidence: 9 focused tests passed; specification and quality reviews APPROVED.

### Agent Task 2 — Complete

Commit:

```text
90dcd0b feat(agent): 统一知识工具返回契约
```

Implemented frozen generic `ToolEnvelope[T]`, `ToolWarning`, and `ToolProblem` with strict status-shape invariants and constructors for ok/no-hits/degraded/error.

Important reviewed API detail:

- The error constructor is named `ToolEnvelope.from_error(...)`.
- The instance/JSON field remains `error`.
- Do not change the constructor back to `ToolEnvelope.error(...)`: Pydantic generic specialization treats a same-name classmethod as the field default and breaks `ToolEnvelope[Payload]` plus JSON schema generation.

Evidence: 5 focused tests passed; generic schema and mutation regressions passed; specification and quality reviews APPROVED.

## 5. Exact Current Task: Agent Task 3

Plan source:

```text
docs/superpowers/plans/2026-07-22-knowledge-agent-tools-citations.md
```

Current tracked RED test:

```text
engine/tests/test_knowledge_base_tools.py
```

Run:

```powershell
python -m pytest engine/tests/test_knowledge_base_tools.py -q
```

Current expected result:

```text
6 failed
ModuleNotFoundError: No module named 'engine.app.agent.tools.knowledge_base'
```

The RED tests currently require:

- exactly six tool builders: `list_kbs`, `query_kb`, `search_file`, `find_kb_document`, `open_kb_document`, `get_mindmap`;
- `query_kb` rejects a KB outside `allowed_kb_uids` before retrieval;
- list output contains only `kb_uid`, `name`, `description`, `status`;
- retrieval receives the verified tenant/run scope and tool output strips `tenant_id`;
- file search is tenant/KB scoped, safe-field-only, and cursor paginated;
- find/open are bounded and never expose `storage_uri`, `file_path`, or other internal paths;
- mindmap access is scoped;
- no tool input schema contains `actor_id` or `tenant_id`.

Next implementation files from the plan:

- create `engine/app/agent/tools/knowledge_base.py`;
- modify `engine/app/agent/tools/base.py` to carry `db`, `trace_id`, `run_id`, verified `knowledge_scope`, and `retrieval_service` while preserving old tests/callers until Task 4/6 wiring is complete;
- modify `engine/app/agent/tools/__init__.py` to register only the stable knowledge-tool set and remove overlapping model-visible knowledge/deep/page-index registrations;
- keep old implementations only as internal adapters where needed.

Implementation cautions discovered during inspection:

- Existing `ToolContext` currently contains only `rag_runner`, citations/stats/clarify holders. Many legacy tests instantiate it with those fields, so add new context dependencies in a compatibility-safe way now, then make production construction authoritative in Tasks 4/6.
- `KnowledgeFile` contains sensitive `storage_uri`, `file_path`, `relative_path`, and legacy aliases. Tool DTOs must whitelist public fields rather than dumping ORM objects.
- `query_kb` should return canonical Evidence data but remove tenant/internal/provider/storage fields from model-visible output.
- File cursor pagination must use a stable bounded cursor, not offset-only pagination.
- Regex find must be bounded (pattern count/length, document/window count) and invalid regex must return a typed domain error.
- `OpenDocumentInput` should reject ambiguous simultaneous `line` and `offset` values.
- All domain failures use `ToolEnvelope.from_error(...)`; unexpected exceptions remain traced execution errors as required by the plan.

After GREEN, run at least:

```powershell
python -m pytest engine/tests/test_knowledge_base_tools.py engine/tests/test_agent_tools.py engine/tests/test_deep_knowledge_search_tool.py -q
python -m compileall -q engine/app/agent
git diff --check
```

Then do spec review, quality/security review, fix all Critical/Important findings, and commit only Task 3.

Suggested commit:

```text
feat(agent): 增加六个授权知识工具
```

## 6. Remaining Ordered Work

### Agent Plan

1. **Task 3** — six scoped read-only knowledge tools (currently RED).
2. **Task 4** — bind Knowledge Skill, prompt, registry, and actual tool visibility consistently.
3. **Task 5** — run-local CitationRegistry, stable K1… IDs, validation, and persisted Evidence snapshots.
4. **Task 6** — NDJSON v2 events and Backend-authorized streaming proxy; browser must not directly own private Engine authorization.
5. Run the Agent plan verification and record real commits/gates in the roadmap, replacing stale Kilo entries.

### Graph Plan

Execute all Tasks 1–8 in `2026-07-22-knowledge-graph-outbox-governance.md` in order:

- scoped graph facts/generations/outbox schema;
- atomic MySQL facts + Outbox commit;
- idempotent Neo4j projector;
- idempotent Milvus graph-vector projector;
- atomic graph-generation activation;
- file mention deletion preserving shared entities;
- scoped GraphRAG/governance without replacing the existing main chain;
- separate build/replay/re-extraction commands.

Required real gates include MySQL transaction/concurrency, Redis durable delivery/replay, Neo4j outage/recovery, Milvus outage/recovery, generation activation, shared-entity deletion isolation, and old GraphRAG regression coverage.

### React / Product / Cutover Plan

Execute all Tasks 1–10 in `2026-07-22-knowledge-react-product-cutover.md` in order. The existing frontend smoke page and old “41/41” verifier do not prove these detailed Tasks complete.

Required outcomes include:

- typed frontend API boundaries;
- deep-link routes and Zustand workspace state;
- file workbench and safe read-only document drawer;
- resumable Job SSE;
- retrieval laboratory;
- graph/governance/mindmap/evaluation/settings product surfaces;
- chat citation-to-document loop;
- legacy backfill and side generations;
- shadow verification, atomic cutover, rollback;
- full browser E2E and removal of legacy knowledge paths.

## 7. Infrastructure Notes

Previously confirmed service ports:

```text
MySQL         127.0.0.1:13306
Redis         127.0.0.1:16379
Elasticsearch 127.0.0.1:9200
Neo4j         127.0.0.1:7474 / 7687
Milvus        127.0.0.1:19530
```

The long-running `prism-milvus-1` instance developed stale etcd/proxy registration and alternated between flush timeout and `node not match` errors. Restarting Milvus/etcd did not make that instance a trustworthy gate.

The Retrieval real-service gate passed using a temporary **no-volume** Milvus 2.4 + isolated etcd + isolated MinIO stack on a separate host port, while using the real existing Elasticsearch and Neo4j. Reuse this clean temporary pattern when the persistent instance is unhealthy; clean up the temporary containers/network afterward. Do not delete or reset the user's persistent data volumes.

For MySQL integration, derive the root password from the running container environment without printing it, URL-encode it, target only the dedicated `prism_test` database, and clear environment variables after the test. Never echo the database URL or password.

## 8. Final Completion Gate

Do not claim the system is complete until every detailed Task in all six plans is implemented, reviewed, independently committed, and verified.

Final commands from the roadmap must be run against the final current state:

```powershell
python -m pytest backend/tests engine/tests -q
node --test frontend/tests/*.test.mjs
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend test:e2e
python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
```

Also verify with real services:

- create/upload/parse/index/query/citation/graph/delete;
- no-hits vs degraded vs unavailable;
- cross-tenant/cross-KB/file/source isolation;
- duplicate delivery/idempotency;
- projector outage/replay/recovery;
- backfill/shadow/cutover/rollback;
- browser deep links, Job reconnection, retrieval lab, graph/evaluation, and citation drawer;
- no secret/internal storage path reaches browser, model, logs, ZIP, or public API.

Finally start and keep running for user acceptance:

```text
Backend
Engine
Frontend
```

Report the exact URLs, final commit range, test counts, real-service evidence, known non-blocking warnings, and any intentionally retained compatibility adapters.
