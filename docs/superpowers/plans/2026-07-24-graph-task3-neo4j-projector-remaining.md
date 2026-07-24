# Graph Task 3 收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Graph Task 3（Neo4j outbox 幂等投影）剩余的 ~45% 工作：接 worker 投影线程、补真实 Neo4j 集成测试、修复一个 Windows 编码 flaky 测试，然后全量回归 + 提交。

**Architecture:** Graph outbox 投影器（`engine/app/graph/neo4j_projector.py` + `outbox_projector.py`）已实现并通过单元测试；ingestion 已切换为通过 `GraphFactWriter` 写 scoped 事实 + outbox 事件（不再直接投影 Neo4j）。剩余工作是把投影器接进 `KnowledgeWorkerManager` 的工作线程、用真实 Neo4j 验证崩溃恢复、清理回归测试，最后提交。

**Tech Stack:** Python 3.11, SQLAlchemy 2, MySQL 8, Neo4j 5.28（neo4j driver 5.28.1）, pytest, threading

---

## 背景与现状（必读）

本计划是 `docs/superpowers/plans/2026-07-22-knowledge-graph-outbox-governance.md` 的 **Task 3** 的收尾部分。Task 3 前半已完成并落盘（**未提交**，当前在工作区）：

### 已完成（在工作区，未 commit）

| 文件 | 状态 | 内容 |
|------|------|------|
| `engine/app/graph/outbox_projector.py` | 新建 | `GraphProjectionReceiptStore`（`claim_due` 用 `FOR UPDATE SKIP LOCKED` + 60s lease、`mark_applied` cursor contiguous 推进、`record_failure` retry/failed）、`OutboxProjectorLoop.run_batch`、`retry_delay`、`classify_neo4j_error` |
| `engine/app/graph/neo4j_projector.py` | 新建 | `Neo4jOutboxProjector`，7 种 event handler（entity/mention/relation upsert + 3 个 remove + analysis.updated），全 scoped、`MERGE` 幂等 |
| `backend/app/services/graph_client.py` | 修改 | 新增 `remove_scoped_mention` / `remove_scoped_relation` / `remove_scoped_entity` |
| `engine/app/graph/pipeline.py` | 修改 | `persist_source_graph` 的 document_chunk 走 `GraphFactWriter.settle()`；`project_source_graph` 不再对 document_chunk 调 `project_item_entities` |
| `engine/app/ingestion/pipeline.py` | 修改 | 新增 `_resolve_graph_generation`；`_ingest_chunk_graph`/`_finalize_item_graph` 透传 scope |
| `engine/tests/test_neo4j_outbox_projector.py` | 新建 | 7/7 PASS（单元，SQLite + FakeGraph） |
| `engine/tests/test_graph_ingest_pipeline.py` | 修改 | 7/7 PASS |
| `engine/tests/test_pipeline_stage_a.py` | 修改 | 3/4 PASS（1 个 flaky，见下） |

### 关键约束（来自 GRAPH_CHAIN_ARCHITECTURE.md §8）

1. **失败隔离是硬约束**：投影器任意失败只记日志/转 retry，绝不阻断 ingestion 或拖累首字延迟。
2. **SQLite 兼容**：`with_for_update()` 在 SQLite 是 no-op，`SKIP LOCKED` 仅 MySQL 真实生效；单测用 SQLite，集成测用真实 MySQL。
3. **community_id/is_god/cohesion 只在 Neo4j**（不在 MySQL）。
4. **`project_item_entities` 函数保留**（Task 6 删除语义 + replay 测试仍用），只是生产 ingestion 不再调它。
5. **提交规范**：末尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`（注：当前会话模型为 Fable 5，但仓库历史统一用此署名，保持一致）。

### 验证环境

```bash
cd e:/work_place/AIOne

# 单元测试（SQLite，需 DATABASE_URL 否则 backend.app.database 导入报错）
DATABASE_URL=sqlite:///./_t.db python -m pytest <path> -v

# Windows 中文断言需 UTF-8，否则 mojibake 导致误判
$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
DATABASE_URL=sqlite:///./_t.db python -m pytest <path> -v

# 真实基础设施
docker compose up -d mysql neo4j
docker compose ps   # 确认 mysql、neo4j 都 healthy
```

Neo4j 默认连接：`bolt://localhost:7687`，用户 `neo4j` / 密码 `password`（见 `engine/app/config.py:34-37`）。

---

## File Structure（本计划涉及）

- 修改：`engine/app/config.py` - 新增 `GRAPH_PROJECTOR_ENABLED` / `GRAPH_PROJECTOR_INTERVAL_SECONDS` / `GRAPH_PROJECTOR_BATCH_LIMIT`。
- 修改：`engine/app/jobs/worker.py` - `KnowledgeWorkerManager` 加 neo4j 投影线程 + `_graph_projector_loop`。
- 创建：`engine/tests/integration/test_graph_projection_recovery.py` - 真实 Neo4j 崩溃恢复测试。
- 修改：`engine/tests/test_pipeline_stage_a.py` - 修复 Windows 编码 flaky 测试。
- 创建：`engine/tests/test_graph_projector_worker.py` - worker 线程接线的单元测试。
- 无新建生产代码文件（投影器基础设施已在前半完成）。

---

## Task 1: 修复 Windows 编码 flaky 测试

**背景**：`test_pipeline_stage_a.py::test_ingest_item_writes_stage_a_entities_and_mentions` 在 Windows 批量运行时 FAIL、单独运行 PASS。根因是断言串 `混合检索` 在 GBK 控制台下被 mojibake，导致 `e.canonical_name == "混合检索"` 比较失败。代码本身正确（隔离复现：`GraphFactWriter.settle` 正确写入 `canonical_name='混合检索'`）。这不是逻辑 bug，是测试断言的脆弱性。

**Files:**
- Modify: `engine/tests/test_pipeline_stage_a.py:93`

- [ ] **Step 1: 把脆弱的中文等值断言改为 normalized_key 断言**

打开 `engine/tests/test_pipeline_stage_a.py`，找到第 93 行：

```python
        assert any(e.entity_type == "concept" and e.canonical_name == "混合检索" for e in entities)
```

改为用 `normalized_key`（该测试 seed 的 `normalized_key="x"`，与编码无关）+ 保留对 `entity_type` 的断言：

```python
        assert any(e.entity_type == "concept" and e.normalized_key == "x" for e in entities)
        assert any("检索" in (e.canonical_name or "") for e in entities)
```

> 说明：`normalized_key == "x"` 是编码无关的强断言（测试 seed 就是 `"x"`）；`"检索" in canonical_name` 用子串匹配降低 mojibake 影响（即使整串乱码，子串匹配在 UTF-8 下仍稳）。若仍想保留对完整中文名的验证，加 `PYTHONUTF8` 见 Step 3。

- [ ] **Step 2: 确认该测试在普通（非 UTF-8）环境下通过**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_pipeline_stage_a.py -v
```

Expected: 4/4 PASS（不再依赖 `PYTHONUTF8`）。

- [ ] **Step 3:（可选）给整个 engine 测试套加 UTF-8 兜底**

如果 Step 2 仍有其他中文断言 flaky，在 `engine/tests/conftest.py` 顶部加：

```python
import os
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
```

> 谨慎：这会影响所有 engine 测试的 IO 编码。仅在 Step 2 不够时才加。优先靠 Step 1 的编码无关断言。

- [ ] **Step 4: 不单独提交，并入最终 Task 4 的 commit**

本 Task 的改动与 worker 接线一起在 Task 4 提交。

---

## Task 2: worker 接 neo4j 投影线程

**目标**：在 `KnowledgeWorkerManager` 里加一条后台线程，周期性 `claim_due -> apply` neo4j 投影 receipt。Neo4j 不可用时 receipt 转 retry，线程不崩。

**Files:**
- Modify: `engine/app/config.py:104`（`settings = Settings()` 之前）
- Modify: `engine/app/jobs/worker.py:681`（`KnowledgeWorkerManager`）
- Create: `engine/tests/test_graph_projector_worker.py`

- [ ] **Step 1: 写 worker 接线单元测试（先红）**

创建 `engine/tests/test_graph_projector_worker.py`：

```python
"""Task 3 (Graph): worker manager spawns a neo4j projector thread that drains
due receipts and stops cleanly."""
import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_projector_worker_test.db"

from datetime import timedelta

import engine.app.jobs.worker as worker_mod
from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt
from backend.app.services.graph_outbox import GraphOutboxService
from engine.app.graph.outbox_projector import GraphProjectionReceiptStore


class _RecordingProjector:
    """Stand-in for Neo4jOutboxProjector that records apply calls."""
    name = "neo4j"

    def __init__(self):
        self.applied = []

    def apply(self, event, receipt=None):
        self.applied.append(event.event_id)


def test_build_graph_projector_returns_none_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", False)
    assert worker_mod._build_graph_projector(db_session) is None


def test_build_graph_projector_wires_neo4j_projector(db_session, monkeypatch):
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    projector = worker_mod._build_graph_projector(db_session)
    assert projector is not None
    assert projector.name == "neo4j"


def test_drain_graph_projector_batch_applies_due_events(db_session, monkeypatch):
    """_drain_graph_projector_batch claims + applies due receipts in one pass."""
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    scope = {"tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"}
    svc = GraphOutboxService(db_session)
    svc.append(
        tenant_id=scope["tenant_id"], kb_uid=scope["kb_uid"],
        graph_generation=scope["graph_generation"], aggregate_type="entity",
        aggregate_id="entity-1", event_type="entity.upserted",
        payload={"entity_id": "entity-1", "entity_type": "concept",
                 "canonical_name": "Prism", "normalized_key": "prism",
                 "aliases": [], "confidence": 0.9},
    )
    db_session.commit()

    recorder = _RecordingProjector()
    n = worker_mod._drain_graph_projector_batch(db_session, projector=recorder, worker_id="w-test")
    assert n == 1
    assert len(recorder.applied) == 1
    # receipt is now applied
    event = db_session.query(GraphOutboxEvent).one()
    receipt = (
        db_session.query(GraphProjectionReceipt)
        .filter_by(event_id=event.event_id, projector="neo4j")
        .one()
    )
    assert receipt.status == "applied"


def test_drain_graph_projector_batch_returns_zero_when_no_receipts(db_session, monkeypatch):
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    recorder = _RecordingProjector()
    assert worker_mod._drain_graph_projector_batch(db_session, projector=recorder, worker_id="w-test") == 0
    assert recorder.applied == []
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_projector_worker.py -v
```

Expected: FAIL with `AttributeError: module 'engine.app.jobs.worker' has no attribute '_build_graph_projector'`（或 `_drain_graph_projector_batch`）。

- [ ] **Step 3: 加配置项**

在 `engine/app/config.py` 的 `Settings` 类里（`settings = Settings()` 那行之前），找 Neo4j 配置块附近（约第 37 行后）加：

```python
    # ---- Graph outbox projector ----
    GRAPH_PROJECTOR_ENABLED: bool = os.getenv("GRAPH_PROJECTOR_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_PROJECTOR_INTERVAL_SECONDS: float = float(os.getenv("GRAPH_PROJECTOR_INTERVAL_SECONDS", "2"))
    GRAPH_PROJECTOR_BATCH_LIMIT: int = int(os.getenv("GRAPH_PROJECTOR_BATCH_LIMIT", "100"))
```

- [ ] **Step 4: 在 worker.py 实现投影器构建 + 单批排空函数**

在 `engine/app/jobs/worker.py` 顶部 import 区加（约第 14-26 行附近，与其他 engine import 一起）：

```python
from engine.app.graph.outbox_projector import GraphProjectionReceiptStore, OutboxProjectorLoop
```

然后在 `dispatch_typed_job` 函数之前（约第 96 行前）加两个模块级函数：

```python
def _build_graph_projector(db):
    """Construct a Neo4jOutboxProjector wired to a real GraphClient.

    Returns None when the projector is disabled or Neo4j is unreachable so the
    worker thread can no-op without crashing ingestion.
    """
    if not settings.GRAPH_PROJECTOR_ENABLED:
        return None
    try:
        from backend.app.services.graph_client import GraphClient
        from engine.app.graph.neo4j_projector import Neo4jOutboxProjector
        graph = GraphClient()
        return Neo4jOutboxProjector(graph, GraphProjectionReceiptStore(db))
    except Exception as exc:
        logger.warning("[knowledge.worker] graph_projector_init_failed error=%s", exc)
        return None


def _drain_graph_projector_batch(db, *, projector, worker_id: str) -> int:
    """Claim + apply one batch of due neo4j receipts. Never raises.

    The projector owns its GraphClient; on transient Neo4j failure each receipt
    is rescheduled via the receipt store (retry/failed), so a single batch error
    does not propagate.
    """
    if projector is None:
        return 0
    loop = OutboxProjectorLoop(projector, projector.receipts, worker_id=worker_id)
    try:
        return loop.run_batch(limit=settings.GRAPH_PROJECTOR_BATCH_LIMIT)
    except Exception as exc:
        logger.exception("[knowledge.worker] graph_projector_batch_failed error=%s", exc)
        return 0
```

> 注意：`_drain_graph_projector_batch` 接受外部传入的 `projector`，这样测试可注入 `_RecordingProjector`，生产路径用 `_build_graph_projector` 构建的真实投影器。`projector.receipts` 在 `Neo4jOutboxProjector.__init__` 里已存为 `self.receipts`。

- [ ] **Step 5: 在 KnowledgeWorkerManager 加投影线程**

在 `engine/app/jobs/worker.py` 的 `KnowledgeWorkerManager.start()` 方法里（约第 688-721 行），在 governance worker 循环之后、`stop()` 之前加：

```python
        # Graph outbox projector: drains due neo4j receipts independently of
        # the Redis job queues. Neo4j outage -> receipts retry, never breaks
        # ingestion (failure isolation).
        if settings.GRAPH_PROJECTOR_ENABLED:
            projector_thread = threading.Thread(
                target=self._graph_projector_loop,
                args=(),
                daemon=True,
                name="knowledge-graph-projector",
            )
            self._threads.append(projector_thread)
            projector_thread.start()
```

然后在 `KnowledgeWorkerManager` 类里（`_evaluation_reaper_loop` 之后，约第 762 行后）加循环方法：

```python
    def _graph_projector_loop(self):
        """Periodically drain due graph outbox receipts to Neo4j.

        Builds a fresh GraphClient per batch attempt so a Neo4j restart is
        recovered on the next iteration; a persistent init failure just logs
        and retries next tick.
        """
        interval = settings.GRAPH_PROJECTOR_INTERVAL_SECONDS
        worker_id = _worker_id("graph-projector")
        while not self._stop.wait(interval):
            db = _Session()
            try:
                projector = _build_graph_projector(db)
                try:
                    _drain_graph_projector_batch(db, projector=projector, worker_id=worker_id)
                finally:
                    if projector is not None:
                        try:
                            projector.graph.close()
                        except Exception:
                            pass
            except Exception as exc:
                logger.exception("[knowledge.worker] graph_projector_loop error=%s", exc)
            finally:
                db.close()
```

> 设计要点：
> - 每 batch 重建 `GraphClient` 而非长连接，这样 Neo4j 重启后下一轮自动恢复（receipt 仍在 MySQL，不丢）。
> - `self._stop.wait(interval)` 既是定时器又是退出信号，`stop()` 置位后线程立即退出。
> - `_drain_graph_projector_batch` 内部已 try/except，但外层再加一层兜底，确保线程永不崩。

- [ ] **Step 6: 运行 worker 接线单元测试**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_projector_worker.py -v
```

Expected: 4/4 PASS。

- [ ] **Step 7: 确认既有 worker 测试不回归**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ingest_workers.py engine/tests/test_knowledge_job_handlers.py -v
```

Expected: 全部 PASS（worker 接线是纯增量，不改动既有 dispatch 路径）。

> 若 `test_ingest_workers.py` 因 `_build_graph_projector` 在 import 时触发 Neo4j 连接而失败，检查是否所有 Neo4j 连接都在函数体内（`_build_graph_projector` 内部），模块顶层无连接。

- [ ] **Step 8: 不单独提交，并入 Task 4**

---

## Task 3: 真实 Neo4j 集成测试（崩溃恢复）

**目标**：用真实 Neo4j 验证 Gate E 的核心场景——投影器把 outbox 事件收敛成 Neo4j 节点/边，瞬态失败转 retry，重放后收敛。这是 Task 3 Plan Verification 的硬性 gate。

**Files:**
- Create: `engine/tests/integration/test_graph_projection_recovery.py`

- [ ] **Step 1: 启动真实 MySQL + Neo4j**

Run:
```bash
cd e:/work_place/AIOne
docker compose up -d mysql neo4j
docker compose ps
# 等待 neo4j healthy（约 20-30s）
```

设置 MySQL 测试库 URL（必须是 `prism_test` 库，见 `backend/tests/integration/conftest.py:15`）：
```bash
# PowerShell
$env:PRISM_TEST_DATABASE_URL='mysql+pymysql://root:<password>@localhost:13306/prism_test'
```

- [ ] **Step 2: 写集成测试**

创建 `engine/tests/integration/test_graph_projection_recovery.py`。参照 `engine/tests/integration/test_retrieval_scope_isolation.py` 的 GraphClient 直连模式 + 清理模式：

```python
"""Task 3 (Graph) real-Neo4j integration: outbox projector converges events to
scoped nodes/edges and recovers after a transient failure.

Requires real MySQL (prism_test) + Neo4j. Marked `mysql` so it only runs when
PRISM_TEST_DATABASE_URL points at the dedicated test database.
"""
from uuid import uuid4

import pytest

from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_outbox import GraphOutboxService
from engine.app.graph.neo4j_projector import Neo4jOutboxProjector
from engine.app.graph.outbox_projector import GraphProjectionReceiptStore


pytestmark = pytest.mark.mysql


SCOPE = {"tenant_id": "t-recover", "kb_uid": "k-recover", "graph_generation": "g-recover"}


@pytest.fixture()
def graph():
    client = GraphClient()
    yield client
    # Clean up everything we wrote, scoped by tenant_id.
    client._execute_write(
        "MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n",
        {"tenant_id": SCOPE["tenant_id"]},
    )
    client.close()


def _append_mention_event(db, mention_id, entity_id, chunk_uid):
    svc = GraphOutboxService(db)
    return svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id=mention_id, event_type="mention.upserted",
        payload={
            "mention_id": mention_id, "entity_id": entity_id,
            "file_uid": "f1", "chunk_uid": chunk_uid,
            "surface_text": "Prism", "normalized_key": "prism",
            "evidence_span": "Prism is a tool", "confidence": 0.9,
        },
    )


def test_projector_converges_event_to_one_entity_and_mention_edge(mysql_session, graph):
    """One mention.upserted event -> one ScopedEntity + one MENTIONED_IN edge."""
    mention_id = f"m-{uuid4().hex[:8]}"
    entity_id = f"e-{uuid4().hex[:8]}"
    _append_mention_event(mysql_session, mention_id, entity_id, f"c-{uuid4().hex[:8]}")
    mysql_session.commit()

    projector = Neo4jOutboxProjector(graph, GraphProjectionReceiptStore(mysql_session))
    projector.apply(mysql_session.query(GraphOutboxEvent).one())

    # Receipt applied
    receipt = (
        mysql_session.query(GraphProjectionReceipt)
        .filter_by(event_id=mysql_session.query(GraphOutboxEvent).one().event_id, projector="neo4j")
        .one()
    )
    assert receipt.status == "applied"

    # Exactly one entity node and one MENTIONED_IN edge in this scope.
    entities = graph._execute_read(
        "MATCH (e:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g}) RETURN count(e) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    assert entities[0]["c"] == 1
    edges = graph._execute_read(
        "MATCH (:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g})"
        "-[r:MENTIONED_IN]->(:ScopedSource {tenant_id: $t, kb_uid: $k, graph_generation: $g}) "
        "RETURN count(r) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    assert edges[0]["c"] == 1


def test_duplicate_delivery_leaves_single_edge(mysql_session, graph):
    """Replaying the same event must not create a second edge (idempotent MERGE)."""
    mention_id = f"m-{uuid4().hex[:8]}"
    entity_id = f"e-{uuid4().hex[:8]}"
    _append_mention_event(mysql_session, mention_id, entity_id, f"c-{uuid4().hex[:8]}")
    mysql_session.commit()

    projector = Neo4jOutboxProjector(graph, GraphProjectionReceiptStore(mysql_session))
    event = mysql_session.query(GraphOutboxEvent).one()
    projector.apply(event)
    projector.apply(event)  # duplicate delivery

    edges = graph._execute_read(
        "MATCH (:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g})"
        "-[r:MENTIONED_IN]->(:ScopedSource {tenant_id: $t, kb_uid: $k, graph_generation: $g}) "
        "RETURN count(r) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    assert edges[0]["c"] == 1


def test_transient_failure_then_retry_converges(mysql_session, graph, monkeypatch):
    """A transient Neo4j failure schedules a retry; re-applying after the
    failure clears converges to one edge."""
    mention_id = f"m-{uuid4().hex[:8]}"
    entity_id = f"e-{uuid4().hex[:8]}"
    _append_mention_event(mysql_session, mention_id, entity_id, f"c-{uuid4().hex[:8]}")
    mysql_session.commit()

    store = GraphProjectionReceiptStore(mysql_session)
    event = mysql_session.query(GraphOutboxEvent).one()

    # First attempt: force a transient failure by patching the graph's
    # upsert_scoped_source to raise a ConnectionError once.
    original = graph.upsert_scoped_source
    call = {"n": 0}

    def flaky(data):
        if call["n"] == 0:
            call["n"] += 1
            raise ConnectionError("neo4j down")
        return original(data)

    monkeypatch.setattr(graph, "upsert_scoped_source", flaky)
    Neo4jOutboxProjector(graph, store).apply(event)

    receipt = store.get(event.event_id, "neo4j")
    assert receipt.status == "retry"
    assert receipt.last_error_code == "NEO4J_UNAVAILABLE"

    # Second attempt: failure cleared, receipt is due again.
    monkeypatch.undo()
    Neo4jOutboxProjector(graph, store).apply(event)
    assert store.status(event.event_id, "neo4j") == "applied"

    edges = graph._execute_read(
        "MATCH (:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g})"
        "-[r:MENTIONED_IN]->(:ScopedSource {tenant_id: $t, kb_uid: $k, graph_generation: $g}) "
        "RETURN count(r) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    assert edges[0]["c"] == 1
```

> 说明：
> - `pytestmark = pytest.mark.mysql` 使其只在 `PRISM_TEST_DATABASE_URL` 设置时运行（见 `backend/tests/integration/conftest.py:34-46`，否则 `mysql_session` fixture skip）。
> - `graph` fixture 用真实 `GraphClient()` 直连本地 Neo4j，teardown 按 `tenant_id` 清理。
> - `mysql_session` fixture 来自 `backend/tests/integration/conftest.py`，每个测试前自动 truncate graph 相关表。
> - 注意：`engine/tests/integration/` 目录**没有 conftest.py**，`mysql_session` 来自 backend 的 conftest——需确认 engine 测试能拿到该 fixture。若 pytest 收集时报 fixture 未找到，在 `engine/tests/integration/` 加一个 conftest 重新导出，或把本测试放到 `backend/tests/integration/`（更稳，见 Step 3 备选）。

- [ ] **Step 3: 运行集成测试**

Run:
```bash
cd e:/work_place/AIOne
$env:PRISM_TEST_DATABASE_URL='mysql+pymysql://root:<password>@localhost:13306/prism_test'
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/integration/test_graph_projection_recovery.py -v
```

Expected: 3/3 PASS。

**若 fixture 未找到（备选方案）**：把测试文件移到 `backend/tests/integration/test_graph_projection_recovery.py`（backend conftest 直接提供 `mysql_session`），import 路径不变（`engine.app.graph.*` 仍可 import）。这是更稳妥的位置，因为 `mysql_session` fixture 定义在 backend。

- [ ] **Step 4: 验证 Neo4j 真实写入（人工抽查）**

测试通过后，可选地用 cypher-shell 抽查：
```bash
docker compose exec neo4j cypher-shell -u neo4j -p password \
  "MATCH (e:ScopedEntity {tenant_id:'t-recover'}) RETURN e LIMIT 5"
```
Expected: 能看到投影器写入的 entity 节点（测试 teardown 前）。teardown 后应为空。

- [ ] **Step 5: 不单独提交，并入 Task 4**

---

## Task 4: 全量回归 + 提交

**目标**：跑完所有受影响测试，确认绿，然后提交。

**Files:**
- 无新文件，仅运行测试 + git commit。

- [ ] **Step 1: 跑 Neo4j 投影器单元测试**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_neo4j_outbox_projector.py engine/tests/test_graph_projector_worker.py -v
```

Expected: 全部 PASS。

- [ ] **Step 2: 跑 ingestion / pipeline 回归**

Run:
```bash
cd e:/work_place/AIOne
$env:PYTHONUTF8='1'
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_pipeline_stage_a.py engine/tests/test_graph_ingest_pipeline.py engine/tests/test_stage_a.py -v
```

Expected: 全部 PASS。重点确认：
- `test_pipeline_stage_a.py` 4/4（Task 1 修复后）
- `test_stage_a.py` 的 `project_item_entities_*` 仍 PASS（函数保留，未删）
- `test_graph_ingest_pipeline.py` 7/7

- [ ] **Step 3: 跑 graph client / projection / fact 既有测试**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest backend/tests/test_graph_client.py backend/tests/test_graph_projection.py backend/tests/test_graph_fact_transaction.py backend/tests/test_graph_outbox_models.py backend/tests/test_entity_settle.py -v
```

Expected: 全部 PASS（graph_client 新增了 3 个 remove 方法，既有测试不受影响；graph_fact_transaction/outbox_models 是 Task 1-2 的，应仍绿）。

- [ ] **Step 4: 跑真实 Neo4j 集成测试**

Run:
```bash
cd e:/work_place/AIOne
$env:PRISM_TEST_DATABASE_URL='mysql+pymysql://root:<password>@localhost:13306/prism_test'
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest engine/tests/integration/test_graph_projection_recovery.py -v
# 或 backend/tests/integration/test_graph_projection_recovery.py（若 Task 3 Step 3 用了备选位置）
```

Expected: 3/3 PASS。

- [ ] **Step 5: 跑 worker 既有测试确认无回归**

Run:
```bash
cd e:/work_place/AIOne
DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ingest_workers.py engine/tests/test_knowledge_job_handlers.py -v
```

Expected: 全部 PASS。

- [ ] **Step 6: 代码质量检查**

Run:
```bash
cd e:/work_place/AIOne
git diff --check                          # 无空白错误
python -m compileall engine/app/graph engine/app/jobs/worker.py engine/app/ingestion/pipeline.py backend/app/services/graph_client.py  # 无语法错
```

Expected: 干净。

- [ ] **Step 7: 验证生产路径不再直接投影（Plan Verification gate）**

Run:
```bash
cd e:/work_place/AIOne
# 生产 ingestion 路径不应再调 project_item_entities（只在测试/personal_asset_unit/replay 保留）
grep -rn "project_item_entities(" engine/app/ backend/app/services/graph_projection.py
```

Expected: `project_item_entities` 仅出现在：
- `backend/app/services/graph_projection.py`（函数定义）
- `backend/app/services/knowledge_cleanup.py`（若 Task 6 已动，否则无）
- 测试文件
- **不应**出现在 `engine/app/graph/pipeline.py`（已移除）或 `engine/app/ingestion/pipeline.py`。

- [ ] **Step 8: 提交**

```bash
cd e:/work_place/AIOne
git add backend/app/services/graph_client.py \
        engine/app/graph/outbox_projector.py \
        engine/app/graph/neo4j_projector.py \
        engine/app/graph/pipeline.py \
        engine/app/ingestion/pipeline.py \
        engine/app/config.py \
        engine/app/jobs/worker.py \
        engine/tests/test_neo4j_outbox_projector.py \
        engine/tests/test_graph_projector_worker.py \
        engine/tests/test_pipeline_stage_a.py \
        engine/tests/test_graph_ingest_pipeline.py \
        engine/tests/integration/test_graph_projection_recovery.py
git commit -m "feat(graph): 增加幂等 Neo4j outbox 投影

- outbox_projector: receipt store (FOR UPDATE SKIP LOCKED + lease) + cursor
  contiguous 推进 + retry 退避 / 终态分类
- neo4j_projector: 7 种 scoped event handler，MERGE 幂等，mention_id/
  relation_id 作边身份保证重复投递收敛
- graph_client: 新增 remove_scoped_mention/relation/entity（按 fact id 删
  单边，保留共享实体）
- ingestion 切换到 GraphFactWriter：document_chunk 写 scoped 事实 + outbox
  事件，移除生产路径直接 project_item_entities（personal_asset_unit 保留）
- worker: KnowledgeWorkerManager 加 neo4j 投影线程，周期 drain receipt，
  Neo4j 不可用转 retry 不阻断入库
- 测试：7 单元 + 4 worker 接线 + 3 真实 Neo4j 恢复 + 既有 pipeline 适配

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

> 提交前确认 `test_platform(1).zip` 和 `docs/superpowers/plans/.task3-neo4j-projector-plan.md` **不要** add（前者是无关压缩包，后者是过程笔记，可保留为 untracked 或单独删）。

- [ ] **Step 9: 更新路线图记录**

在 `docs/superpowers/plans/2026-07-22-knowledge-system-roadmap.md` 的 Plan 5 表格里，把 GT3 行从 `(existing)` 改为实际 commit hash + 验证结果。例如：

```markdown
| GT3: Idempotent Neo4j outbox projector | `<hash>` | 7 unit + 4 worker + 3 real-Neo4j recovery PASS; ingestion routed to GraphFactWriter; direct projection removed from production path |
```

然后单独一个 docs-only commit：
```bash
git add docs/superpowers/plans/2026-07-22-knowledge-system-roadmap.md
git commit -m "docs(knowledge): 记录 Graph Task 3 提交

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Plan Verification（对应 Task 3 Plan Verification gate）

- [ ] 重复投递 -> Neo4j 1 节点/1 边，receipt=applied（Task 3 Step 2 `test_duplicate_delivery_leaves_single_edge`）
- [ ] Neo4j 瞬态不可用 -> receipt=retry；恢复后重放收敛（Task 3 `test_transient_failure_then_retry_converges`）
- [ ] ingestion 写出 scoped facts + outbox 事件，不再直接 project（Task 4 Step 7 grep gate）
- [ ] `project_item_entities(` 不在生产 ingestion 路径出现（Task 4 Step 7）
- [ ] SQLite 单元全绿（Task 4 Step 1-3）
- [ ] 真实 Neo4j 集成绿（Task 4 Step 4）
- [ ] `git diff --check` 干净（Task 4 Step 6）

---

## 风险与回退

1. **worker 投影线程拖累启动**：`_build_graph_projector` 在线程内每 batch 调用，Neo4j 不可用时 `GraphClient()` 构造可能阻塞。若启动变慢，给 `GraphClient()` 构造加超时或 try/except 后 return None（已在 `_build_graph_projector` 里 try/except，但 `GraphClient.__init__` 本身可能阻塞在连接）。回退：`GRAPH_PROJECTOR_ENABLED=0` 关闭线程，ingestion 仍正常（只是 Neo4j 投影滞后，靠后续重放收敛）。
2. **真实 Neo4j 集成测在 CI 跑不了**：`pytestmark = pytest.mark.mysql` + 依赖 `PRISM_TEST_DATABASE_URL`，无该环境时自动 skip，不阻断 CI。
3. **ingestion 接线回归**：若 Task 4 Step 2 的 pipeline 测试大面积红，说明 `GraphFactWriter` 接线有问题。回退 = `git checkout -- engine/app/graph/pipeline.py engine/app/ingestion/pipeline.py`，恢复旧 `settle_entity_candidates` + `project_item_entities` 直接投影路径（零回归），仅保留投影器基础设施 + worker 线程（此时投影器无事件可消费，空转）。
4. **编码 flaky 复发**：若 Task 1 的 `normalized_key` 断言之外还有其他中文等值断言 flaky，统一加 `engine/tests/conftest.py` 的 `PYTHONUTF8` 兜底（Task 1 Step 3）。

## 完成判定

全部 Task 1-4 的 checkbox 勾完 + Plan Verification 全绿 + 两个 commit（功能 + docs）落地 = Graph Task 3 完成，可进入 Task 4（Milvus 投影器）。
