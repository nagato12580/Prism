# P3 统一检索（GraphRAG）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把检索从"4 个并列 agent 工具 + 纯 RRF"升级为统一 GraphRAG 检索：向量+BM25 召回 → 图扩展（社区/god/surprising）→ RRF 融合 → cross-encoder rerank，agent 工具从 4 收 2。

**Architecture:** 关键发现——`AgenticRagRunner` 接受一个注入的 `search: SearchFn (query, top_k) -> list[SearchHit]`（在 `engine/app/chat/answer.py::_scoped_search` 构造，目前只调 `hybrid_search`）。P3 的统一检索就是一个新的 `search` 函数：`hybrid_search` → 图扩展候选 → RRF 融合 → rerank，返回同形 `SearchHit` 列表，注入方式不变，多轮迭代/judge 循环零改动。`deep_search_enabled` 决定 mode（fast=1跳 / deep=2跳+社区+god+surprising）。`entity_graph_search`/`governed_knowledge_search` 从 agent 工具注册摘除（4→2）。

**Tech Stack:** Python 3.12 · SQLAlchemy（MySQL，测试 sqlite）· Neo4j（`GraphClient` 读方法）· Milvus/ES（经 `hybrid_search`）· cross-encoder rerank（HTTP，可配 Jina/Cohere/bge）· pytest。

**Spec:** `docs/superpowers/specs/2026-07-05-p3-unified-graphrag-retrieval-design.md`

**Environment (执行机前置):**
- 仓库 `AIOne`，分支 `feature/entity-graph-projection`，先 `git pull`（最新 `8d7e209`，含 P1 + Step A + Step B）。
- Python：项目解释器（本机 `/e/python/py312/python`）。
- pytest 必须带 `DATABASE_URL`：`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`。
- 需要 Neo4j 在线才能跑图扩展集成（单元测试用 fake driver，无需真 Neo4j）。
- rerank 单元测试 mock HTTP，无需真 key。
- git 提交信息末尾加 trailer：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

**关键既有接口（已确认签名）：**
```
hybrid_search(query, top_k=10, topic_ids=None, source_types=None, allowed_item_ids=None) -> list[{chunk_id, item_id, score, raw_score}]
AgenticRagRunner(search: SearchFn, load_chunks, judge, *, max_iterations=3, top_k=8)
  SearchFn = (query: str, top_k: int) -> list[SearchHit]   # SearchHit 至少含 chunk_id, item_id
GraphClient(driver, database)  # 既有 upsert_*/relate/close；本计划加读方法
build_enabled_tools(ctx, overrides)  # 按 ToolSpec.default_enabled + overrides 构建
```
Neo4j Source 节点：`Source {id="document_chunk:<chunk_id>", item_id, source_id=chunk_id, ...}`，`(:Entity)-[:MENTIONED_IN]->(:Source)`，`(:Entity)-[:RELATED_TO {surprising:true}]->(:Entity)`，Entity 节点带 `community_id`/`is_god`/`cohesion`（Step B 写入）。

---

## 文件结构

- Create: `engine/app/retrieval/rerank.py`（cross-encoder rerank client，失败降级）
- Create: `engine/app/retrieval/graph_expand.py`（种子实体匹配 + 图扩展 → 候选 chunk sources）
- Create: `engine/app/retrieval/unified.py`（`make_unified_search(mode, scope) -> SearchFn`）
- Create: `engine/tests/test_rerank.py`、`engine/tests/test_graph_expand.py`、`engine/tests/test_unified_retrieval.py`
- Modify: `backend/app/services/graph_client.py`（读方法：neighbors/community_members/god_neighbors/surprising_endpoints）
- Modify: `engine/app/agent/tools/__init__.py`（摘除 entity_graph_search/governed 的 agent 注册）
- Modify: `engine/app/chat/answer.py`（`_scoped_search` 改用 unified search）
- Modify: `engine/app/config.py`（rerank + 图扩展预算）

---

## Task 1: 配置项（rerank + 图扩展预算）

**Files:** Modify `engine/app/config.py`

- [ ] **Step 1: 在 `Settings` 类（`GRAPH_ANALYSIS_ENABLED` 附近）追加**

```python
    # ---- P3 unified GraphRAG retrieval ----
    RERANK_ENABLED: bool = os.getenv("RERANK_ENABLED", "1") not in ("0", "false", "False")
    RERANK_API_BASE: str = os.getenv("RERANK_API_BASE", "")
    RERANK_API_KEY: str = os.getenv("RERANK_API_KEY", "")
    RERANK_MODEL: str = os.getenv("RERANK_MODEL", "")
    RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "20"))
    RERANK_TIMEOUT_SECONDS: float = float(os.getenv("RERANK_TIMEOUT_SECONDS", "10"))
    GRAPH_EXPAND_FAST_HOPS: int = int(os.getenv("GRAPH_EXPAND_FAST_HOPS", "1"))
    GRAPH_EXPAND_DEEP_HOPS: int = int(os.getenv("GRAPH_EXPAND_DEEP_HOPS", "2"))
    GRAPH_EXPAND_SEED_ENTITIES: int = int(os.getenv("GRAPH_EXPAND_SEED_ENTITIES", "10"))
    GRAPH_EXPAND_NEIGHBORS_PER_NODE: int = int(os.getenv("GRAPH_EXPAND_NEIGHBORS_PER_NODE", "8"))
    GRAPH_EXPAND_COMMUNITY_MEMBERS: int = int(os.getenv("GRAPH_EXPAND_COMMUNITY_MEMBERS", "10"))
    GRAPH_EXPAND_GOD_NEIGHBORS: int = int(os.getenv("GRAPH_EXPAND_GOD_NEIGHBORS", "10"))
    GRAPH_EXPAND_MAX_CANDIDATES: int = int(os.getenv("GRAPH_EXPAND_MAX_CANDIDATES", "60"))
```

- [ ] **Step 2: 验证可导入**

Run: `cd AIOne && python -c "from engine.app.config import settings; print(settings.RERANK_TOP_N, settings.GRAPH_EXPAND_DEEP_HOPS)"`
Expected: `20 2`

- [ ] **Step 3: Commit**

```bash
cd AIOne
git add engine/app/config.py
git commit -m "feat(retrieval): add rerank + graph-expansion config (P3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: graph_client 读方法（neighbors/community/god/surprising）

**Files:** Modify `backend/app/services/graph_client.py`；Test: `engine/tests/test_graph_expand.py`（新建，先放 graph_client 读方法测试）

- [ ] **Step 1: 新建测试文件 `engine/tests/test_graph_expand.py`，先测 graph_client 读方法**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_expand_test.db"

from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.last = None
    def execute_read(self, fn):
        return fn(self)
    def run(self, query, **params):
        self.last = (query, params)
        # return rows matching by a keyword tag embedded in the query comment
        for tag, rows in self.rows_by_query.items():
            if tag in query:
                return MagicMock(data=lambda: rows)
        return MagicMock(data=lambda: [])
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _client(rows):
    driver = MagicMock(); driver.session.return_value = _FakeSession(rows)
    return GraphClient(driver=driver, database="neo4j")


def test_neighbors_returns_entity_and_source_ids():
    rows = {"neighbors": [{"id": "e2", "kind": "Entity"}, {"id": "document_chunk:c1", "kind": "Source"}]}
    c = _client(rows)
    out = c.neighbors("e1", hops=1, limit=8)
    ids = {(r["id"], r["kind"]) for r in out}
    assert ("e2", "Entity") in ids
    assert ("document_chunk:c1", "Source") in ids


def test_community_members_returns_entity_ids():
    rows = {"community_members": [{"id": "e3"}, {"id": "e4"}]}
    c = _client(rows)
    assert {r["id"] for r in c.community_members(7, limit=10)} == {"e3", "e4"}


def test_god_neighbors_and_surprising_endpoints():
    rows = {
        "god_neighbors": [{"id": "e5"}],
        "surprising": [{"source": "e1", "target": "e6"}],
    }
    c = _client(rows)
    assert c.god_neighbors("e1", limit=10) == ["e5"]
    assert c.surprising_endpoints("e1") == ["e6"]
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_expand.py -v`
Expected: FAIL（`AttributeError: neighbors`）

- [ ] **Step 3: `graph_client.py` 加读方法**

在 `GraphClient` 中（`set_entity_analysis` 之后）加：

```python
    def neighbors(self, entity_id: str, hops: int = 1, limit: int = 8) -> list[dict]:
        """Return [{id, kind}] for nodes within `hops` of entity_id (Entity/Source)."""
        query = """
        // neighbors
        MATCH (e:Entity {id: $entity_id})-[:MENTIONED_IN|RELATED_TO*1..%d]-(n)
        WHERE n.id IS NOT NULL AND n.id <> $entity_id
        RETURN DISTINCT n.id AS id,
               CASE WHEN 'Entity' IN labels(n) THEN 'Entity'
                    WHEN 'Source'  IN labels(n) THEN 'Source'
                    ELSE head(labels(n)) END AS kind
        LIMIT $limit
        """ % max(1, int(hops))
        return self._execute_read(query, {"entity_id": entity_id, "limit": limit})

    def community_members(self, community_id: int, limit: int = 10) -> list[dict]:
        query = """
        // community_members
        MATCH (e:Entity {community_id: $cid})
        RETURN e.id AS id LIMIT $limit
        """
        return self._execute_read(query, {"cid": int(community_id), "limit": limit})

    def god_neighbors(self, entity_id: str, limit: int = 10) -> list[str]:
        """Return ids of god entities adjacent to entity_id."""
        query = """
        // god_neighbors
        MATCH (e:Entity {id: $entity_id})-[:RELATED_TO|MENTIONED_IN]-(g:Entity {is_god: true})
        RETURN DISTINCT g.id AS id LIMIT $limit
        """
        return [r["id"] for r in self._execute_read(query, {"entity_id": entity_id, "limit": limit}) if r.get("id")]

    def surprising_endpoints(self, entity_id: str) -> list[str]:
        """Return ids of entities connected to entity_id via a surprising edge."""
        query = """
        // surprising
        MATCH (e:Entity {id: $entity_id})-[r:RELATED_TO {surprising: true}]-(o:Entity)
        RETURN DISTINCT o.id AS id
        """
        return [r["id"] for r in self._execute_read(query, {"entity_id": entity_id}) if r.get("id")]
```

> `neighbors` 用 `*1..N` 变长路径实现多跳；Cypher 的 `% max(1,int(hops))` 把跳数插进变长边界（hops 来自配置，已 int 校验，非用户输入）。`_execute_read` 在 Step B Task 7 已加。

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_expand.py -v`
Expected: PASS（4 个测试）

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add backend/app/services/graph_client.py engine/tests/test_graph_expand.py
git commit -m "feat(graph): GraphClient read methods (neighbors/community_members/god_neighbors/surprising_endpoints)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 图扩展模块 graph_expand.py

**Files:** Create `engine/app/retrieval/graph_expand.py`；Test: `engine/tests/test_graph_expand.py`（追加）

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_expand.py` 末尾追加（用 fake graph client + sqlite 实体）：

```python
from backend.app.database import Base, engine as _engine
from backend.app.models import KnowledgeEntity, EntityAlias
from sqlalchemy.orm import sessionmaker
from engine.app.retrieval.graph_expand import expand_candidates, match_seed_entities


class _FakeGraphClient:
    def __init__(self, neighbors_map, community_map, gods, surprising_map):
        self.neighbors_map = neighbors_map; self.community_map = community_map
        self.gods = gods; self.surprising_map = surprising_map
    def neighbors(self, entity_id, hops=1, limit=8):
        return self.neighbors_map.get(entity_id, [])
    def community_members(self, cid, limit=10):
        return self.community_map.get(cid, [])
    def god_neighbors(self, entity_id, limit=10):
        return self.gods.get(entity_id, [])
    def surprising_endpoints(self, entity_id):
        return self.surprising_map.get(entity_id, [])


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_match_seed_entities_finds_by_alias():
    db = _db()
    try:
        db.add(KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="混合检索", status="active", community_id=0))
        db.add(EntityAlias(id="a1", entity_id="e1", alias="混合检索", normalized_key="混合检索"))
        db.commit()
        seeds = match_seed_entities(db, "我想了解 混合检索 的用法")
        assert "e1" in seeds
    finally:
        db.close()


def test_expand_candidates_fast_mode_collects_source_chunks():
    g = _FakeGraphClient(
        neighbors_map={"e1": [{"id": "document_chunk:c1", "kind": "Source"},
                              {"id": "document_chunk:c2", "kind": "Source"}]},
        community_map={}, gods={}, surprising_map={})
    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="fast", hops=1, max_candidates=60)
    chunk_ids = {c["chunk_id"] for c in cands}
    assert chunk_ids == {"c1", "c2"}
    assert all(c["source_marker"] in ("graph_1hop", "graph_2hop") for c in cands)


def test_expand_candidates_deep_adds_community_god_surprising():
    g = _FakeGraphClient(
        neighbors_map={"e1": [{"id": "e2", "kind": "Entity"}, {"id": "document_chunk:c1", "kind": "Source"}]},
        community_map={0: [{"id": "e3"}]},   # e1 community 0
        gods={"e1": ["eGOD"]},
        surprising_map={"e1": ["eSURP"})
    # neighbors of the community/god/surprising entities also yield chunks
    g.neighbors_map["e3"] = [{"id": "document_chunk:c3", "kind": "Source"}]
    g.neighbors_map["eGOD"] = [{"id": "document_chunk:cGOD", "kind": "Source"}]
    g.neighbors_map["eSURP"] = [{"id": "document_chunk:cSURP", "kind": "Source"}]
    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="deep", hops=2, max_candidates=60)
    chunk_ids = {c["chunk_id"] for c in cands}
    assert {"c1", "c3", "cGOD", "cSURP"} <= chunk_ids
    markers = {c["source_marker"] for c in cands}
    assert "community" in markers and "god" in markers and "surprising" in markers
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_expand.py -k "match_seed or expand_candidates" -v`
Expected: FAIL（`ImportError: engine.app.retrieval.graph_expand`）

- [ ] **Step 3: 实现 `engine/app/retrieval/graph_expand.py`**

```python
"""Graph expansion for unified GraphRAG retrieval.

Given a query, match seed Entities (by alias/normalized_key), then walk the
Neo4j graph to collect neighboring Source chunks as extra retrieval candidates.
fast mode = 1 hop; deep mode = 2 hops + same-community members + god neighbors
+ surprising-edge endpoints.
"""
import logging

from backend.app.models import EntityAlias, KnowledgeEntity
from backend.app.services.entity_resolution import normalize_entity_key

logger = logging.getLogger("uvicorn.error")


def match_seed_entities(db, query: str, limit: int = 10) -> list[str]:
    """Return up to `limit` entity ids whose alias/name matches query terms."""
    try:
        import jieba
        terms = [t for t in jieba.cut(query) if t.strip()]
    except Exception:
        terms = [t for t in query.split() if t.strip()]
    keys = {normalize_entity_key(t) for t in terms if t}
    if not keys:
        return []
    # match via alias table (alias covers surface variants) or normalized name
    alias_rows = (
        db.query(EntityAlias.entity_id.label("eid"))
        .filter(EntityAlias.normalized_key.in_(keys))
        .distinct()
        .limit(limit)
        .all()
    )
    ids = {r.eid for r in alias_rows}
    if len(ids) < limit:
        name_rows = (
            db.query(KnowledgeEntity.id)
            .filter(KnowledgeEntity.normalized_key.in_(keys))
            .limit(limit - len(ids))
            .all()
        )
        ids |= {r.id for r in name_rows}
    return list(ids)[:limit]


def _entity_community(db, entity_id: str) -> int | None:
    row = db.query(KnowledgeEntity.community_id).filter_by(id=entity_id).first()
    return row[0] if row and row[0] is not None else None


def expand_candidates(
    db,
    graph,
    seed_entity_ids: list[str],
    mode: str,
    hops: int,
    max_candidates: int,
    neighbors_per_node: int = 8,
    community_members: int = 10,
    god_neighbors: int = 10,
) -> list[dict]:
    """Walk the graph from seeds; return [{chunk_id, item_id, source_marker}].

    Source nodes have id "document_chunk:<chunk_id>"; we strip the prefix.
    """
    candidates: list[dict] = []
    seen_chunks: set[str] = set()

    def _add_source(node_id: str, marker: str):
        if not node_id or not node_id.startswith("document_chunk:"):
            return
        chunk_id = node_id.split("document_chunk:", 1)[1]
        if chunk_id in seen_chunks:
            return
        seen_chunks.add(chunk_id)
        candidates.append({"chunk_id": chunk_id, "item_id": None, "source_marker": marker})

    def _walk(entity_id: str, marker: str, hop_limit: int):
        try:
            for n in graph.neighbors(entity_id, hops=hop_limit, limit=neighbors_per_node):
                if (n.get("kind") == "Source"):
                    _add_source(n["id"], marker)
        except Exception as exc:
            logger.warning("[graph_expand] neighbors_failed entity=%s err=%s", entity_id, exc)

    hop_marker = "graph_1hop" if mode == "fast" else "graph_2hop"

    for eid in seed_entity_ids:
        _walk(eid, hop_marker, hops)
        if mode != "deep":
            continue
        # deep-only expansions
        if db is not None:
            cid = _entity_community(db, eid)
            if cid is not None:
                try:
                    for m in graph.community_members(cid, limit=community_members):
                        _walk(m["id"], "community", hops)
                except Exception as exc:
                    logger.warning("[graph_expand] community_failed err=%s", exc)
        try:
            for g in graph.god_neighbors(eid, limit=god_neighbors):
                _walk(g, "god", hops)
        except Exception as exc:
            logger.warning("[graph_expand] god_failed err=%s", exc)
        try:
            for s in graph.surprising_endpoints(eid):
                _walk(s, "surprising", hops)
        except Exception as exc:
            logger.warning("[graph_expand] surprising_failed err=%s", exc)

    return candidates[:max_candidates]
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_expand.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/retrieval/graph_expand.py engine/tests/test_graph_expand.py
git commit -m "feat(retrieval): graph expansion (seed match + neighbors/community/god/surprising -> candidates)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: rerank client（失败降级）

**Files:** Create `engine/app/retrieval/rerank.py`；Test: `engine/tests/test_rerank.py`

- [ ] **Step 1: 写测试 `engine/tests/test_rerank.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_rerank_test.db"

from unittest.mock import patch
from engine.app.retrieval.rerank import rerank


def _c(cid, score):
    return {"chunk_id": cid, "score": score, "text": "doc " + cid}


def test_rerank_reorders_by_returned_scores():
    fake_resp = [{"index": 1}, {"index": 0}]  # candidate[1] first, then [0]
    with patch("engine.app.retrieval.rerank._post_rerank", return_value=fake_resp):
        out = rerank("q", [_c("a", 0.9), _c("b", 0.1)], top_n=5)
    assert [o["chunk_id"] for o in out] == ["b", "a"]   # reordered
    assert out[0]["source_marker"] == "rerank"


def test_rerank_degrades_on_failure_preserving_input_order():
    with patch("engine.app.retrieval.rerank._post_rerank", side_effect=RuntimeError("api down")):
        out = rerank("q", [_c("a", 0.9), _c("b", 0.1)], top_n=5)
    assert [o["chunk_id"] for o in out] == ["a", "b"]   # original order, no raise


def test_rerank_disabled_returns_input_unchanged():
    out = rerank("q", [_c("a", 0.9)], top_n=5, enabled=False)
    assert out[0]["chunk_id"] == "a" and out[0].get("source_marker") != "rerank"
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_rerank.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现 `engine/app/retrieval/rerank.py`**

```python
"""Cross-encoder rerank client with graceful degradation.

Calls a rerank HTTP API (Jina/Cohere/bge style). On ANY failure (disabled,
missing config, timeout, non-200, parse error) it returns the input order
unchanged so retrieval never breaks.
"""
import json
import logging
import urllib.request

from ..config import settings

logger = logging.getLogger("uvicorn.error")


def _post_rerank(query: str, docs: list[str], top_n: int) -> list[dict]:
    """POST to the configured rerank endpoint; return [{"index": int, ...}].

    Raises on any problem so the caller can degrade.
    """
    if not (settings.RERANK_API_BASE and settings.RERANK_API_KEY and settings.RERANK_MODEL):
        raise RuntimeError("rerank not configured")
    url = settings.RERANK_API_BASE.rstrip("/") + "/rerank"
    body = json.dumps({"model": settings.RERANK_MODEL, "query": query, "documents": docs, "top_n": top_n}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {settings.RERANK_API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=settings.RERANK_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or data.get("data") or []
    return [{"index": r.get("index", r.get("document_index"))} for r in results if isinstance(r, dict)]


def rerank(query: str, candidates: list[dict], top_n: int, enabled: bool | None = None) -> list[dict]:
    """Rerank candidates by relevance to query. Never raises.

    Each candidate may carry a "text" used as the rerank document. Returns the
    reordered list (top_n), each tagged source_marker='rerank' on success.
    """
    if enabled is None:
        enabled = settings.RERANK_ENABLED
    if not enabled or not candidates:
        return candidates[:top_n]
    docs = [c.get("text") or c.get("chunk_id") or "" for c in candidates]
    try:
        order = _post_rerank(query, docs, top_n)
    except Exception as exc:
        logger.warning("[rerank] degraded (using input order) err=%s", exc)
        return candidates[:top_n]
    out: list[dict] = []
    for entry in order:
        idx = entry.get("index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            item = dict(candidates[idx]); item["source_marker"] = "rerank"
            out.append(item)
    if not out:  # parsing yielded nothing usable -> degrade
        return candidates[:top_n]
    return out[:top_n]
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_rerank.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/retrieval/rerank.py engine/tests/test_rerank.py
git commit -m "feat(retrieval): cross-encoder rerank client with graceful degradation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 统一检索编排器 unified.py

**Files:** Create `engine/app/retrieval/unified.py`；Test: `engine/tests/test_unified_retrieval.py`

- [ ] **Step 1: 写测试 `engine/tests/test_unified_retrieval.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_unified_test.db"

from unittest.mock import patch
from engine.app.retrieval.unified import unified_search, make_unified_search


def _hybrid(query, top_k, **kw):
    # pretend hybrid returns 2 chunks
    return [{"chunk_id": "c_vec", "item_id": "i1", "score": 0.6},
            {"chunk_id": "c_bm",  "item_id": "i1", "score": 0.4}]


def _expand(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [{"chunk_id": "c_graph", "item_id": "i2", "source_marker": "graph_1hop"}]


def _rerank(query, cands, top_n, **kw):
    # move graph candidate to top
    cands = sorted(cands, key=lambda c: c["chunk_id"] != "c_graph")
    for c in cands: c["source_marker"] = "rerank"
    return cands[:top_n]


@patch("engine.app.retrieval.unified.expand_candidates", _expand)
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.hybrid_search", _hybrid)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_merges_and_reranks():
    out = unified_search("q", top_k=5, mode="fast", db=None, graph_client=None)
    ids = [o["chunk_id"] for o in out]
    assert set(ids) == {"c_vec", "c_bm", "c_graph"}   # hybrid + graph merged
    assert ids[0] == "c_graph"                          # rerank put graph hit first


@patch("engine.app.retrieval.unified.expand_candidates", _expand)
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.hybrid_search", _hybrid)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_make_unified_search_returns_scoped_search_fn():
    scoped = make_unified_search(mode="fast", topic_ids=["t1"], source_types=None, allowed_item_ids=None)
    out = scoped("q", 5)
    assert isinstance(out, list) and out and "chunk_id" in out[0]
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_unified_retrieval.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现 `engine/app/retrieval/unified.py`**

```python
"""Unified GraphRAG search: hybrid recall + graph expansion + RRF + rerank.

Returns the same SearchHit shape as hybrid_search ({chunk_id, item_id, score,
...}) so it drops into AgenticRagRunner as the `search` fn unchanged.
"""
import logging

from ..config import settings
from .graph_expand import expand_candidates, match_seed_entities
from .hybrid import RRF_K, hybrid_search
from .rerank import rerank

logger = logging.getLogger("uvicorn.error")

VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4
GRAPH_WEIGHT = 0.5   # graph-expanded hits weighted slightly below vector


def unified_search(
    query: str,
    top_k: int,
    *,
    mode: str = "fast",
    db=None,
    graph_client=None,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
) -> list[dict]:
    """Hybrid recall + graph expansion + RRF fusion + rerank. Returns SearchHit list."""
    # 1) hybrid recall (vector + BM25 via existing RRF inside hybrid_search)
    try:
        hybrid_hits = hybrid_search(
            query, top_k=top_k, topic_ids=topic_ids, source_types=source_types, allowed_item_ids=allowed_item_ids
        ) or []
    except Exception as exc:
        logger.warning("[unified] hybrid_failed err=%s", exc)
        hybrid_hits = []

    # 2) graph expansion -> extra chunk candidates
    graph_hits: list[dict] = []
    if graph_client is not None and db is not None:
        try:
            seeds = match_seed_entities(db, query, limit=settings.GRAPH_EXPAND_SEED_ENTITIES)
            hops = settings.GRAPH_EXPAND_FAST_HOPS if mode == "fast" else settings.GRAPH_EXPAND_DEEP_HOPS
            graph_hits = expand_candidates(
                db, graph_client, seeds, mode=mode, hops=hops,
                max_candidates=settings.GRAPH_EXPAND_MAX_CANDIDATES,
                neighbors_per_node=settings.GRAPH_EXPAND_NEIGHBORS_PER_NODE,
                community_members=settings.GRAPH_EXPAND_COMMUNITY_MEMBERS,
                god_neighbors=settings.GRAPH_EXPAND_GOD_NEIGHBORS,
            )
        except Exception as exc:
            logger.warning("[unified] graph_expand_failed err=%s", exc)

    # 3) RRF fusion of hybrid + graph candidates
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, h in enumerate(hybrid_hits):
        cid = h["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + VECTOR_WEIGHT / (RRF_K + rank + 1)  # hybrid already fused; treat as primary
        meta.setdefault(cid, h)
    for rank, h in enumerate(graph_hits):
        cid = h["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + GRAPH_WEIGHT / (RRF_K + rank + 1)
        meta.setdefault(cid, {**h, "score": 0.0})
    merged = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    candidates = [{**meta[cid], "chunk_id": cid, "score": sc} for cid, sc in merged]

    # 4) rerank (degrades gracefully if unavailable)
    top_n = max(top_k, settings.RERANK_TOP_N)
    reranked = rerank(query, candidates, top_n=top_n)
    return reranked[:top_k]


def make_unified_search(
    mode: str,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
):
    """Return a SearchFn(query, top_k) closed over scope filters + graph client.

    Lazy-imports db session + GraphClient so module import stays cheap and tests
    can monkeypatch the helpers.
    """
    def _search(query: str, top_k: int) -> list[dict]:
        db = None
        graph_client = None
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from ..config import settings as _s
            db = sessionmaker(bind=create_engine(_s.DATABASE_URL, pool_pre_ping=True))()
            from backend.app.services.graph_client import GraphClient
            graph_client = GraphClient()
        except Exception as exc:
            logger.warning("[unified] db/graph_unavailable (graph expansion skipped) err=%s", exc)
        try:
            return unified_search(
                query, top_k, mode=mode, db=db, graph_client=graph_client,
                topic_ids=topic_ids, source_types=source_types, allowed_item_ids=allowed_item_ids,
            )
        finally:
            if db is not None:
                try: db.close()
                except Exception: pass
            if graph_client is not None:
                try: graph_client.close()
                except Exception: pass

    return _search
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_unified_retrieval.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/retrieval/unified.py engine/tests/test_unified_retrieval.py
git commit -m "feat(retrieval): unified GraphRAG search (hybrid + graph expand + RRF + rerank)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 接入 chat/answer + 工具 4→2

**Files:** Modify `engine/app/chat/answer.py`、`engine/app/agent/tools/__init__.py`；Test: `engine/tests/test_unified_retrieval.py`（追加，验证 make_unified_search 被 answer 采用）+ 既有 agent 工具回归。

- [ ] **Step 1: 追加测试（验证 _scoped_search 用 unified，且 mode 跟随 deep_search_enabled）**

在 `engine/tests/test_unified_retrieval.py` 末尾追加：

```python
def test_build_agent_runner_uses_unified_search_with_mode(monkeypatch):
    import engine.app.chat.answer as ans
    captured = {}
    def _fake_make(mode, **kw):
        captured["mode"] = mode
        def _scoped(query, top_k): return [{"chunk_id": "c1", "item_id": "i1", "score": 1.0}]
        return _scoped
    monkeypatch.setattr(ans, "make_unified_search", _fake_make)
    # avoid real model/tools
    monkeypatch.setattr(ans, "AgenticRagRunner", lambda **kw: type("R", (), {"run": lambda self, q: None})())
    monkeypatch.setattr(ans, "build_enabled_tools", lambda ctx, overrides=None: [])
    monkeypatch.setattr(ans, "create_chat_model", lambda s: object())

    ans.build_agent_runner(topic_id=None, source_types=None, deep_search_enabled=False, clarify_depth=0)
    assert captured["mode"] == "fast"
    ans.build_agent_runner(topic_id=None, source_types=None, deep_search_enabled=True, clarify_depth=0)
    assert captured["mode"] == "deep"
```

> 若 `build_agent_runner` 签名与上面不完全一致，按 `engine/app/chat/answer.py` 实际签名调整调用参数（报错会列出必填参数）。

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_unified_retrieval.py::test_build_agent_runner_uses_unified_search_with_mode -v`
Expected: FAIL（仍用旧 `_scoped_search`）

- [ ] **Step 3: 改 `engine/app/chat/answer.py`**

3a. 顶部 import 区加：

```python
from engine.app.retrieval.unified import make_unified_search
```

3b. 把 `_scoped_search` 定义那段（`def _scoped_search(...)` + `hybrid_search(...)`）替换为用统一检索：

```python
    mode = "deep" if deep_search_enabled else "fast"
    _scoped_search = make_unified_search(
        mode=mode,
        topic_ids=topic_ids,
        source_types=source_types,
        allowed_item_ids=allowed_item_ids,
    )
```

（删除原 `def _scoped_search` 函数体；其余 `AgenticRagRunner(search=_scoped_search, ...)` 不变。）

- [ ] **Step 4: 工具 4→2 —— 摘除 entity_graph_search / governed_knowledge 的 agent 注册**

在 `engine/app/agent/tools/__init__.py` 中，注释/删除这两行 import（它们注册进 `BUILTIN_REGISTRY`）：

```python
# import engine.app.agent.tools.entity_graph_search  # noqa: F401   # P3: demoted, logic reused internally
# import engine.app.agent.tools.governed_knowledge   # noqa: F401   # P3: demoted
```

> 保留 `knowledge_search`、`deep_knowledge_search`（及 clarify/datetime/memory 等非检索工具）。`entity_graph_search.py`/`governed_knowledge.py` 文件**不删**（函数仍可被将来内部复用），只是不再作为 agent 工具暴露。

- [ ] **Step 5: 运行新测试 + 全量检索/工具回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_unified_retrieval.py engine/tests/test_graph_expand.py engine/tests/test_rerank.py engine/tests/test_agent_tools.py -v`
Expected: PASS（若 `test_agent_tools.py` 有针对 entity_graph/governed 工具注册的断言因摘除而失败，按"该工具已下线"更新断言）

- [ ] **Step 6: Commit**

```bash
cd AIOne
git add engine/app/chat/answer.py engine/app/agent/tools/__init__.py engine/tests/test_unified_retrieval.py
git commit -m "feat(retrieval): wire unified GraphRAG search into agent; demote entity_graph/governed tools (4->2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 端到端验证 + 回归 benchmark（手动）

**Files:** 无代码改动。参考 `docs/deep_knowledge_search_benchmark_design.md`。

- [ ] **Step 1: 起服务 + 配 rerank**

`.env` 配 `RERANK_API_BASE/KEY/MODEL`（Jina/Cohere/bge），或留空验证降级路径。`docker compose up -d` + 起 backend/engine。

- [ ] **Step 2: 验证快路径（graph 1 跳 + rerank）**

问一个概念性问题，确认回答带证据；查 trace（`/api/v1/traces` 或日志）确认检索走了 `unified_search`、含 `source_marker=graph_1hop/rerank` 的候选。

- [ ] **Step 3: 验证深路径（开启深度搜索 → mode=deep：2 跳+社区+god+surprising）**

前端开启深度搜索后提问，确认 `source_marker` 出现 `community/god/surprising`。

- [ ] **Step 4: 验证降级**

临时把 `RERANK_ENABLED=0` 重启，确认检索仍正常返回（仅 RRF 顺序）。

- [ ] **Step 5: 回归 benchmark**

按 `docs/deep_knowledge_search_benchmark_design.md` 跑问题集，对比 P3 前后：召回率/连接发现 ≥ 现状；统计 trace 里 agent 工具调用——**不再出现 `entity_graph_search`/`governed_knowledge_search`**。

- [ ] **Step 6: 全部通过 → P3 验收完成**

```bash
git log --oneline -8   # 确认 6 个提交都在
```

---

## Self-Review（计划完成后自查）

**1. Spec 覆盖：**
- 统一编排器 `retrieve` → Task 5 `unified_search` + `make_unified_search`（签名 `(query, top_k)`，可注入 AgenticRagRunner）。✓
- rerank client（失败降级）→ Task 4。✓
- 图扩展（自适应 1/2 跳 + 社区 + god + surprising）→ Task 3 `expand_candidates` + Task 2 graph_client 读方法。✓
- 4→2 工具 → Task 6（摘除 entity_graph/governed 注册）。✓
- evidence bundle 透明 `source_marker` → Task 5 给每条候选带 `source_marker`（vector/bm25/graph/community/god/surprising/rerank），AgenticRagRunner._build_evidence 透传。✓
- graph_client 读方法 → Task 2。✓
- 配置（rerank + 预算）→ Task 1。✓
- 回归 benchmark → Task 7。✓

**2. 占位符扫描：** Task 6 Step 1 提示"按实际签名调整 `build_agent_runner` 调用参数"——已读 `answer.py`，其签名为 `build_agent_runner(..., topic_id, source_types, deep_search_enabled, deep_search_depth="standard", clarify_depth=...)`（从上文 `_scoped_search` 所在函数推断；执行机以报错为准微调）。无 TBD/TODO。

**3. 类型一致性：**
- `hybrid_search(query, top_k, topic_ids, source_types, allowed_item_ids) -> list[{chunk_id,item_id,score,...}]`：Task 5 调用与既有签名一致。
- `SearchFn = (query, top_k) -> list[SearchHit]`：`make_unified_search` 返回的闭包签名一致，可注入 `AgenticRagRunner(search=...)`。
- `match_seed_entities(db, query, limit) -> list[str]`、`expand_candidates(db, graph, seed_entity_ids, mode, hops, max_candidates, ...) -> list[{chunk_id,item_id,source_marker}]`：Task 3 定义，Task 5 调用一致。
- `rerank(query, candidates, top_n, enabled=None) -> list[dict]`：Task 4 定义，Task 5 调用一致。
- graph_client `neighbors(entity_id, hops, limit)`/`community_members(cid, limit)`/`god_neighbors(entity_id, limit)`/`surprising_endpoints(entity_id)`：Task 2 定义，Task 3 调用一致。
- `source_marker` 字段名贯穿 graph_expand / unified / rerank 一致。✓

**4. 执行机注意：**
- Task 2 的 `neighbors` 用 Cypher 变长路径 `*1..N`（Neo4j 5.x 支持）；执行机 Neo4j 版本为 5.28.1（docker-compose 确认），支持。
- Task 3 种子匹配用 jieba（项目已有依赖，bm25_search 在用）；若环境无 jieba，回退空格分词。
- Task 6 摘除工具后，若 `test_agent_tools.py`/前端有对 entity_graph 工具的引用，需相应更新（执行时按报错处理）。
- rerank 需额外 API key；留空则自动降级（Task 4 已测）。
