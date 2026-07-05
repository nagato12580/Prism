# P4 图信号驱动的 CKP 状态治理 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Step B/P5 产出的图信号（社区 cohesion + god 节点）驱动 CKP 从 `draft` 晋升到 `stable`，信号与原因写进 `CKP.extra_meta`，只晋不降。

**Architecture:** 新增 `engine/app/graph/ckp_governance.py`：把每个 CKP 的 `concepts`/`entities`（JSON）映射到 `KnowledgeEntity` → 聚合 backing 实体的社区 cohesion（`graph_community` 表）与 is_god（Neo4j）→ 按阈值/god 规则把 draft→stable，写 extra_meta。在 `run_analysis` 末尾触发，失败隔离。

**Tech Stack:** Python 3.12 · SQLAlchemy（MySQL，测试 sqlite）· Neo4j（`GraphClient.are_gods`/`entity_community`）· pytest。

**Spec:** `docs/superpowers/specs/2026-07-05-p4-graph-driven-ckp-governance-design.md`

**Environment (执行机前置):**
- 仓库 `AIOne`，分支 `feature/entity-graph-projection`，`git pull`（tip 须含 **P5**——P4 读 P5 的 `graph_community` 表；P5 缺失时 cohesion 取 0、仅 god 生效，降级安全）。
- Python：项目解释器（本机 `/e/python/py312/python`）。
- pytest 必须带 `DATABASE_URL`：`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`。
- 提交信息末尾加 trailer：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

**关键既有接口（已确认）:**
```
CanonicalKnowledgePoint  # backend/app/models/knowledge_governance.py
  - id, user_id, status(draft/stable/disputed/deprecated), confidence
  - concepts: JSON list, entities: JSON list, extra_meta: JSON dict(name映射为metadata列)
KnowledgeEntity / EntityAlias  # normalized_key 匹配
GraphCommunity(user_id, community_id, label, cohesion)  # P5 新表
GraphClient.entity_community(entity_id) -> int|None      # Step B 读方法
GraphClient._execute_read(query, params) -> list[dict]    # 已有
entity_resolution.normalize_entity_key(text) -> str
run_analysis(db, graph, user_id, top_god, top_surprising)  # Step B；末尾会接 P5 持久化 + 本计划 govern
```

---

## 文件结构

- Create: `engine/app/graph/ckp_governance.py`（映射 + 信号聚合 + `govern_ckp_status_by_graph`）
- Create: `engine/tests/test_ckp_governance.py`
- Modify: `backend/app/services/graph_client.py`（加 `are_gods`）
- Modify: `engine/app/graph/analyzer.py`（run_analysis 末尾调 govern）
- Modify: `engine/app/config.py`（`GRAPH_GOV_*`）

---

## Task 1: 配置项

**Files:** Modify `engine/app/config.py`

- [ ] **Step 1: 在 `Settings` 类（`GRAPH_INSIGHTS_*` 附近）追加**

```python
    # ---- P4 graph-driven CKP governance ----
    GRAPH_GOV_ENABLED: bool = os.getenv("GRAPH_GOV_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_GOV_COHESION_THRESHOLD: float = float(os.getenv("GRAPH_GOV_COHESION_THRESHOLD", "0.3"))
```

- [ ] **Step 2: 验证**

Run: `cd AIOne && python -c "from engine.app.config import settings; print(settings.GRAPH_GOV_ENABLED, settings.GRAPH_GOV_COHESION_THRESHOLD)"`
Expected: `True 0.3`

- [ ] **Step 3: Commit**

```bash
cd AIOne
git add engine/app/config.py
git commit -m "feat(governance): add P4 graph-driven CKP governance config

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: GraphClient.are_gods（批量读 is_god）

**Files:** Modify `backend/app/services/graph_client.py`；Test: `engine/tests/test_ckp_governance.py`（新建，先放 graph_client 测试）

- [ ] **Step 1: 新建测试 `engine/tests/test_ckp_governance.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_ckp_gov_test.db"

from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self, rows): self.rows = rows; self.last = None
    def execute_read(self, fn): return fn(self)
    def run(self, query, **params):
        self.last = (query, params)
        return MagicMock(data=lambda: self.rows)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _client(rows):
    driver = MagicMock(); driver.session.return_value = _FakeSession(rows)
    return GraphClient(driver=driver, database="neo4j")


def test_are_gods_returns_id_to_bool_map():
    rows = [{"id": "e1", "is_god": True}, {"id": "e2", "is_god": False}]
    c = _client(rows)
    out = c.are_gods(["e1", "e2", "e3"])   # e3 absent -> False
    assert out == {"e1": True, "e2": False, "e3": False}
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -v`
Expected: FAIL（`AttributeError: are_gods`）

- [ ] **Step 3: `graph_client.py` 加 `are_gods`**

在 `GraphClient` 中（`entity_community` 附近）加：

```python
    def are_gods(self, entity_ids: list[str]) -> dict[str, bool]:
        """Return {entity_id: bool} for the given ids; absent ids -> False."""
        if not entity_ids:
            return {}
        query = """
        MATCH (e:Entity) WHERE e.id IN $ids
        RETURN e.id AS id, coalesce(e.is_god, false) AS is_god
        """
        rows = self._execute_read(query, {"ids": entity_ids})
        found = {r["id"]: bool(r.get("is_god")) for r in rows if r.get("id")}
        return {eid: found.get(eid, False) for eid in entity_ids}
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add backend/app/services/graph_client.py engine/tests/test_ckp_governance.py
git commit -m "feat(graph): GraphClient.are_gods batch read is_god

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: CKP↔Entity 映射 + 信号聚合

**Files:** Create `engine/app/graph/ckp_governance.py`；Test: `engine/tests/test_ckp_governance.py`（追加）

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_ckp_governance.py` 末尾追加：

```python
from backend.app.database import Base, engine as _engine
from backend.app.models import (
    CanonicalKnowledgePoint, EntityAlias, GraphCommunity, KnowledgeEntity,
)
from sqlalchemy.orm import sessionmaker


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def _seed_entities_and_communities(db):
    db.add(KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="混合检索", status="active"))
    db.add(KnowledgeEntity(id="e2", user_id="default-user", entity_type="method",   canonical_name="RRF融合",   normalized_key="rrf融合",   status="active"))
    db.add(EntityAlias(id="a1", entity_id="e1", alias="混合检索", normalized_key="混合检索"))
    db.add(GraphCommunity(id="gc1", user_id="default-user", community_id=0, label="主题0", cohesion=0.45))
    db.commit()


class _FakeGraph:
    def __init__(self, communities, gods):
        self._communities = communities; self._gods = gods
    def entity_community(self, entity_id):
        return self._communities.get(entity_id)
    def are_gods(self, ids):
        return {i: self._gods.get(i, False) for i in ids}


def test_map_ckp_to_entities_matches_concepts_via_alias():
    db = _db(); _seed_entities_and_communities(db)
    try:
        from engine.app.graph.ckp_governance import map_ckp_to_entities
        ckp = CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                      canonical_statement="s", concepts=["混合检索"], entities=[])
        ids = map_ckp_to_entities(db, ckp)
        assert ids == ["e1"]
    finally:
        db.close()


def test_aggregate_signals_cohesion_max_and_god_backed():
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0, "e2": 0}, gods={"e2": True})
    try:
        from engine.app.graph.ckp_governance import aggregate_ckp_signals
        sig = aggregate_ckp_signals(db, g, ["e1", "e2"], user_id="default-user")
        assert sig["cohesion_score"] == 0.45   # max of community 0 cohesion
        assert sig["god_backed"] is True
    finally:
        db.close()


def test_aggregate_signals_empty_when_no_mapping():
    db = _db(); g = _FakeGraph(communities={}, gods={})
    try:
        from engine.app.graph.ckp_governance import aggregate_ckp_signals
        sig = aggregate_ckp_signals(db, g, [], user_id="default-user")
        assert sig == {"cohesion_score": 0.0, "god_backed": False}
    finally:
        db.close()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -k "map_ckp or aggregate_signals" -v`
Expected: FAIL（`ImportError: engine.app.graph.ckp_governance`）

- [ ] **Step 3: 创建 `engine/app/graph/ckp_governance.py`**

```python
"""P4 graph-driven CKP governance: map CKPs to entities, aggregate community
cohesion + god signals, and promote draft -> stable. Only promotes, never demotes.

Runs at the end of run_analysis (after Step B wrote community/god and P5 wrote
graph_community). Failure-isolated: never blocks analysis or ingestion.
"""
import logging
from datetime import datetime, timezone

from backend.app.models import EntityAlias, KnowledgeEntity
from backend.app.services.entity_resolution import normalize_entity_key

logger = logging.getLogger("uvicorn.error")


def _ckp_surfaces(ckp) -> list[str]:
    names: list[str] = []
    for field in ("concepts", "entities", "aliases"):
        val = getattr(ckp, field, None) or []
        if isinstance(val, list):
            names.extend(str(x) for x in val if x)
    # de-dup preserving order
    seen = set(); out = []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out


def map_ckp_to_entities(db, ckp) -> list[str]:
    """Return backing KnowledgeEntity ids for a CKP via normalized_key + aliases."""
    keys = {normalize_entity_key(n) for n in _ckp_surfaces(ckp)}
    if not keys:
        return []
    user_id = getattr(ckp, "user_id", "default-user") or "default-user"
    # alias match first (covers surface variants)
    alias_rows = (
        db.query(EntityAlias.entity_id.label("eid"))
        .join(KnowledgeEntity, EntityAlias.entity_id == KnowledgeEntity.id)
        .filter(EntityAlias.normalized_key.in_(keys), KnowledgeEntity.user_id == user_id)
        .distinct()
        .all()
    )
    ids = [r.eid for r in alias_rows]
    if not ids:
        name_rows = (
            db.query(KnowledgeEntity.id)
            .filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.normalized_key.in_(keys))
            .all()
        )
        ids = [r.id for r in name_rows]
    # de-dup preserving order
    seen = set(); out = []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    return out


def aggregate_ckp_signals(db, graph, entity_ids: list[str], user_id: str = "default-user") -> dict:
    """Aggregate cohesion + god signals over backing entities.

    cohesion_score = max(graph_community.cohesion) over distinct backing communities.
    god_backed     = any backing entity is_god (Neo4j).
    """
    if not entity_ids:
        return {"cohesion_score": 0.0, "god_backed": False}

    # community per entity (Neo4j)
    cids: set[int] = set()
    for eid in entity_ids:
        try:
            cid = graph.entity_community(eid)
        except Exception as exc:
            logger.warning("[ckp_gov] entity_community_failed eid=%s err=%s", eid, exc)
            cid = None
        if cid is not None:
            cids.add(int(cid))

    # cohesion per community (graph_community table; P5)
    cohesion_score = 0.0
    if cids:
        try:
            from backend.app.models import GraphCommunity
            rows = db.query(GraphCommunity.cohesion).filter(
                GraphCommunity.user_id == user_id, GraphCommunity.community_id.in_(cids)
            ).all()
            scores = [float(r[0] or 0.0) for r in rows]
            cohesion_score = max(scores) if scores else 0.0
        except Exception as exc:
            logger.warning("[ckp_gov] cohesion_read_failed err=%s", exc)

    # god_backed (Neo4j batch)
    god_backed = False
    try:
        god_backed = any(graph.are_gods(entity_ids).values())
    except Exception as exc:
        logger.warning("[ckp_gov] are_gods_failed err=%s", exc)

    return {"cohesion_score": cohesion_score, "god_backed": god_backed}
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -v`
Expected: PASS（4 个）

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/ckp_governance.py engine/tests/test_ckp_governance.py
git commit -m "feat(governance): CKP->entity mapping + signal aggregation (cohesion/god)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 状态晋升 govern_ckp_status_by_graph（只晋不降）

**Files:** Modify `engine/app/graph/ckp_governance.py`；Test: `engine/tests/test_ckp_governance.py`（追加）

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_ckp_governance.py` 末尾追加：

```python
def test_govern_promotes_draft_to_stable_on_cohesion(monkeypatch):
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0}, gods={"e1": False})
    db.add(CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                   canonical_statement="s", concepts=["混合检索"], status="draft"))
    db.commit()
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_ENABLED", True)
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_COHESION_THRESHOLD", 0.3)
    try:
        from engine.app.graph.ckp_governance import govern_ckp_status_by_graph
        res = govern_ckp_status_by_graph(db, g, user_id="default-user")
        ckp = db.query(CanonicalKnowledgePoint).filter_by(id="ckp1").one()
        assert ckp.status == "stable"
        assert ckp.extra_meta.get("graph_cohesion") == 0.45
        assert ckp.extra_meta.get("reason", "").startswith("graph:")
        assert res["promoted"] == 1
    finally:
        db.close()


def test_govern_promotes_draft_to_stable_on_god_even_without_cohesion(monkeypatch):
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 99}, gods={"e1": True})   # cid 99 has no graph_community -> cohesion 0
    db.add(CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                   canonical_statement="s", concepts=["混合检索"], status="draft"))
    db.commit()
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_ENABLED", True)
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_COHESION_THRESHOLD", 0.3)
    try:
        from engine.app.graph.ckp_governance import govern_ckp_status_by_graph
        govern_ckp_status_by_graph(db, g, user_id="default-user")
        ckp = db.query(CanonicalKnowledgePoint).filter_by(id="ckp1").one()
        assert ckp.status == "stable"
        assert ckp.extra_meta.get("reason") == "graph:god"
    finally:
        db.close()


def test_govern_keeps_draft_when_below_threshold_and_not_god(monkeypatch):
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0}, gods={"e1": False})
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_COHESION_THRESHOLD", 0.9)   # 0.45 < 0.9
    db.add(CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                   canonical_statement="s", concepts=["混合检索"], status="draft"))
    db.commit()
    try:
        from engine.app.graph.ckp_governance import govern_ckp_status_by_graph
        govern_ckp_status_by_graph(db, g, user_id="default-user")
        ckp = db.query(CanonicalKnowledgePoint).filter_by(id="ckp1").one()
        assert ckp.status == "draft"
    finally:
        db.close()


def test_govern_never_demotes_stable(monkeypatch):
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0}, gods={"e1": False})
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_COHESION_THRESHOLD", 0.9)  # would not promote
    db.add(CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                   canonical_statement="s", concepts=["混合检索"], status="stable"))
    db.commit()
    try:
        from engine.app.graph.ckp_governance import govern_ckp_status_by_graph
        govern_ckp_status_by_graph(db, g, user_id="default-user")
        ckp = db.query(CanonicalKnowledgePoint).filter_by(id="ckp1").one()
        assert ckp.status == "stable"   # unchanged, not demoted
    finally:
        db.close()


def test_govern_skips_deprecated(monkeypatch):
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0}, gods={"e1": True})
    monkeypatch.setattr("engine.app.config.settings.GRAPH_GOV_ENABLED", True)
    db.add(CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                   canonical_statement="s", concepts=["混合检索"], status="deprecated"))
    db.commit()
    try:
        from engine.app.graph.ckp_governance import govern_ckp_status_by_graph
        govern_ckp_status_by_graph(db, g, user_id="default-user")
        ckp = db.query(CanonicalKnowledgePoint).filter_by(id="ckp1").one()
        assert ckp.status == "deprecated"   # untouched
    finally:
        db.close()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -k govern -v`
Expected: FAIL（`ImportError: govern_ckp_status_by_graph`）

- [ ] **Step 3: 在 `engine/app/graph/ckp_governance.py` 追加**

```python
from ..config import settings


def govern_ckp_status_by_graph(db, graph, user_id: str = "default-user") -> dict:
    """Promote draft CKPs to stable based on graph signals (cohesion / god).

    Only promotes; never demotes. Skips deprecated. Writes signals + reason to
    CKP.extra_meta. Failure-isolated: returns a result dict, never raises.
    """
    promoted = 0
    signaled = 0
    if not settings.GRAPH_GOV_ENABLED:
        return {"promoted": 0, "signaled": 0, "skipped": True}
    try:
        from backend.app.models import CanonicalKnowledgePoint

        ckps = (
            db.query(CanonicalKnowledgePoint)
            .filter(
                CanonicalKnowledgePoint.user_id == user_id,
                CanonicalKnowledgePoint.status != "deprecated",
            )
            .all()
        )
        for ckp in ckps:
            entity_ids = map_ckp_to_entities(db, ckp)
            sig = aggregate_ckp_signals(db, graph, entity_ids, user_id=user_id)
            reason = ""
            if ckp.status == "draft":
                if sig["cohesion_score"] >= settings.GRAPH_GOV_COHESION_THRESHOLD:
                    ckp.status = "stable"; promoted += 1
                    reason = f"graph:cohesion({sig['cohesion_score']:.2f})"
                elif sig["god_backed"]:
                    ckp.status = "stable"; promoted += 1
                    reason = "graph:god"
            # write signals regardless (transparency), preserve existing meta keys
            meta = dict(ckp.extra_meta or {})
            meta.update({
                "graph_cohesion": sig["cohesion_score"],
                "god_backed": sig["god_backed"],
                "reason": reason,
                "graph_governed_at": datetime.now(timezone.utc).isoformat(),
            })
            ckp.extra_meta = meta
            if entity_ids:
                signaled += 1
        db.commit()
        return {"promoted": promoted, "signaled": signaled}
    except Exception as exc:
        logger.warning("[ckp_gov] govern_failed err=%s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return {"promoted": 0, "signaled": 0, "error": str(exc)}
```

> SQLAlchemy：直接对 `ckp.extra_meta`（JSON 列，模型属性名为 `extra_meta`，列名 `metadata`）整体赋值会触发更新；`ckp.status` 变更同样。`db.commit()` 持久化。

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_ckp_governance.py -v`
Expected: PASS（9 个）

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/ckp_governance.py engine/tests/test_ckp_governance.py
git commit -m "feat(governance): govern_ckp_status_by_graph (draft->stable by cohesion/god, no demote)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 接入 run_analysis（失败隔离）

**Files:** Modify `engine/app/graph/analyzer.py`；Test: `engine/tests/test_graph_analyzer.py`（追加）

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_analyzer.py` 末尾追加：

```python
def test_run_analysis_invokes_ckp_governance(monkeypatch):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityRelation
    from sqlalchemy.orm import sessionmaker
    from engine.app.graph import ckp_governance as ckg
    from engine.app.graph.analyzer import run_analysis

    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=1):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name, status="active"))
        db.flush()
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        monkeypatch.setattr(ckg, "generate_community_labels", lambda c, **kw: {cid: f"主题{cid}" for cid in c})
        monkeypatch.setattr(ckg, "compute_suggested_questions", lambda **kw: [])

        called = {"n": 0}
        def _fake_gov(db, graph, user_id, **kw):
            called["n"] += 1; return {"promoted": 0, "signaled": 0}
        monkeypatch.setattr("engine.app.graph.analyzer.govern_ckp_status_by_graph", _fake_gov)

        class _G:
            def read_entity_communities(self): return {}
            def set_entity_analysis(self, *a, **kw): pass
            def relate(self, *a, **kw): pass
        run_analysis(db, _G(), user_id="default-user")
        assert called["n"] == 1   # govern called once at end of run_analysis
    finally:
        db.close()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py::test_run_analysis_invokes_ckp_governance -v`
Expected: FAIL（govern 未被调用）

- [ ] **Step 3: 改 `engine/app/graph/analyzer.py`**

3a. 顶部 import 区（P5 的 insights import 附近）加：

```python
from .ckp_governance import govern_ckp_status_by_graph
```

3b. 在 run_analysis 的 **P5 持久化块之后、最终 `return {...}` 之前**插入：

```python
        # ---- P4: graph-driven CKP governance (promote draft -> stable) ----
        try:
            govern_ckp_status_by_graph(db, graph, user_id=user_id)
        except Exception as exc:
            logger.warning("[analyzer] ckp_governance_failed err=%s", exc)
```

> 插入点：紧跟 P5 那个 `try: ... from backend.app.models import GraphCommunity ...` 块之后，在 `return {"node_count": ..., "communities": ..., "god_nodes": ..., "surprising": ...}` 之前。govern 自身已失败隔离，这里再套一层 try/except 双保险。

- [ ] **Step 4: 运行，确认通过 + 既有 graph_analyzer 测试无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py engine/tests/test_ckp_governance.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/analyzer.py engine/tests/test_graph_analyzer.py
git commit -m "feat(governance): invoke CKP graph governance at end of run_analysis (failure-isolated)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 端到端验证（手动）

**Files:** 无代码改动。前置：P5 已实现且 `graph_community` 有数据。

- [ ] **Step 1: 起服务 + 入库触发（worker 建 CKP + run_analysis 跑 P5+P4）**

```bash
docker compose up -d
SKIP_ENGINE=1 python -m backend.run &
python -m engine.run &
# 上传文档 -> worker 抽 PKU/CKP -> 入库后 run_analysis -> P4 治理
RESP=$(curl -s -X POST http://localhost:5175/api/v1/upload/file -F "file=@/tmp/probe.md")
ITEM_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
sleep 60   # 等 worker + run_analysis
```

> 若该 item 没有 CKP 产出（worker 未跑或 PKU 抽取为空），P4 无对象——先确认 worker 正常（见排查）。

- [ ] **Step 2: 验证 CKP 状态晋升 + 信号留痕**

```bash
docker compose exec -T mysql mysql -uroot -p"<DB_PASSWORD>" "<DB_NAME>" -e \
  "SELECT status, COUNT(*) AS n FROM canonical_knowledge_point WHERE user_id='default-user' GROUP BY status;
   SELECT id, status, JSON_EXTRACT(metadata, '$.graph_cohesion') AS coh,
          JSON_EXTRACT(metadata, '$.god_backed') AS god,
          JSON_EXTRACT(metadata, '$.reason') AS reason
   FROM canonical_knowledge_point WHERE user_id='default-user' LIMIT 20;"
```
期望：出现 `status=stable` 的 CKP（之前全是 draft）；其 metadata 含 `graph_cohesion`/`god_backed`/`reason`。

- [ ] **Step 3: 验证降级**

`.env` 设 `GRAPH_GOV_ENABLED=0`，重新入库一份文档，查 CKP → 全部 draft（不被图信号晋升）。

- [ ] **Step 4: 全部通过 → P4 验收完成**

```bash
git log --oneline -6   # 确认 5 个提交都在
```

---

## Self-Review（计划完成后自查）

**1. Spec 覆盖：**
- 映射（concepts/entities JSON → KnowledgeEntity）→ Task 3 `map_ckp_to_entities`。✓
- 信号聚合（cohesion from graph_community、god from Neo4j）→ Task 3 `aggregate_ckp_signals` + Task 2 `are_gods`。✓
- 晋升规则（cohesion≥THR 或 god_backed → stable；只晋不降；skip deprecated）→ Task 4。✓
- 透明性（extra_meta: graph_cohesion/god_backed/reason/graph_governed_at）→ Task 4。✓
- 触发点（run_analysis 末尾，失败隔离）→ Task 5。✓
- 配置（GRAPH_GOV_ENABLED/THR）→ Task 1。✓
- 测试 + e2e → 各 Task TDD + Task 6。✓

**2. 占位符扫描：** Task 6 Step 2 的 `<DB_PASSWORD>`/`<DB_NAME>` 用 .env 实际值替换（runbook 体系已说明）。无 TBD/TODO。

**3. 类型一致性：**
- `map_ckp_to_entities(db, ckp) -> list[str]`：Task 3 定义，Task 4 调用一致。
- `aggregate_ckp_signals(db, graph, entity_ids, user_id) -> {cohesion_score, god_backed}`：Task 3 定义，Task 4 调用一致。
- `govern_ckp_status_by_graph(db, graph, user_id) -> {promoted, signaled, ...}`：Task 4 定义，Task 5 调用一致。
- `GraphClient.are_gods(ids) -> dict[str,bool]`：Task 2 定义，Task 3 调用一致。
- 复用 `GraphClient.entity_community`（Step B）、`GraphCommunity`（P5）、`normalize_entity_key`（既有）签名一致。✓
- `CKP.extra_meta`（模型属性名 extra_meta，列名 metadata）：Task 4 用属性名赋值，与 P1/既有用法一致。✓

**4. 执行机注意：**
- **P4 依赖 P5**：`graph_community` 表由 P5 创建并填充。须先完成 P5 再跑 P4（或 P4 在 graph_community 缺表/无数据时 cohesion=0，仅 god 生效——`aggregate_ckp_signals` 的 try/except 已降级）。
- Task 5 插入点须在 P5 持久化之后（P5 写 graph_community，P4 读它）。
- Task 4 的 extra_meta 整体赋值会触发 SQLAlchemy JSON 列变更检测；若某些版本不感知整体替换，可改用 `flag_modified`——执行时若发现 status 变了但 metadata 没存，加 `from sqlalchemy.orm.attributes import flag_modified; flag_modified(ckp, "extra_meta")`（属实现细节，报错再补）。
- CKP 产出依赖 worker（`settle_document_item_to_governance`）正常；e2e 若无 CKP，先查 worker 日志。
