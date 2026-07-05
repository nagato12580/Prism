# P5 图洞察接入对话 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Step B 已算好的图谱洞察(社区标签 / god 枢纽 / surprising 隐藏联系 / suggest_questions)以**被动注入**方式交给 agent——仿 `active_recall`,让回答能主动提示"这张图还藏着 X 联系 / 你还可以追问 Y"。

**Architecture:** 仿 `engine/app/agent/active_recall.py::recall_memory_context`:新增 `engine/app/graph/insights.py::graph_insights_context(query, user_id) -> str`,在 `runner._build_messages` 里紧跟 `recall_memory_context` 之后注入一段 SystemMessage。内部自建 db session + GraphClient(不污染 runner 签名),信号门控 + try/except + 超时,无命中返回 `""`。洞察来源:run_analysis 末尾补算社区标签(便宜 LLM)+ suggest_questions(结构化,过滤桥接问题),写两张新表 `graph_community` / `graph_insight_summary`。

**Tech Stack:** Python 3.12 · SQLAlchemy(MySQL,测试 sqlite)· Neo4j(`GraphClient`)· graphify(`suggest_questions`,结构化无 LLM)· OpenAI 兼容 LLM(社区标签)· pytest。

**Spec:** `docs/superpowers/specs/2026-07-05-p5-graph-insights-injection-design.md`

**Environment (执行机前置):**
- 仓库 `AIOne`,分支 `feature/entity-graph-projection`,`git pull`(tip `2c37e69`,含 P1+StepA+StepB+P3)。
- Python:项目解释器(本机 `/e/python/py312/python`)。
- pytest 必须带 `DATABASE_URL`:`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`。
- 提交信息末尾加 trailer:`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

**关键既有接口(已确认):**
```
recall_memory_context(query, ...) -> str   # 仿照对象;内部自建 _Session,返回 "" 或背景块
AgenticRagRunner / runner._build_messages  # 已注入 recall_memory_context 作 SystemMessage (runner.py:478)
match_seed_entities(db, query, limit) -> list[str]   # P3 graph_expand.py,复用
GraphClient.entity_community(entity_id) -> int|None  # Step B 补的读方法
GraphClient.surprising_endpoints(entity_id) -> list[str]
run_analysis(db, graph, user_id, top_god, top_surprising) -> dict   # Step B;已算 communities/final/cohesion_by_cid/god_ids/surprising/exported
engine.app.llm.client.chat(messages, *, model=None) -> str
graphify.analyze.suggest_questions(G, communities, community_labels, top_n) -> list[{type,question,why}]  # 结构化,无 LLM;桥接问题会被 concept 过滤
```

---

## 文件结构

- Create: `backend/app/models/graph_community.py`(`GraphCommunity`)
- Create: `backend/app/models/graph_insight_summary.py`(`GraphInsightSummary`)
- Create: `engine/app/graph/insights.py`(`has_insight_signal` / `generate_community_labels` / `compute_suggested_questions` / `graph_insights_context`)
- Create: `engine/tests/test_graph_insights.py`
- Modify: `backend/app/models/__init__.py`(导出两个新模型 → auto_migrate 建表)
- Modify: `engine/app/graph/analyzer.py`(run_analysis 末尾补算标签+问题,写两张表)
- Modify: `engine/app/agent/runner.py`(`_build_messages` 注入 graph_insights_context)
- Modify: `engine/app/config.py`(P5 配置)

---

## Task 1: 配置项

**Files:** Modify `engine/app/config.py`

- [ ] **Step 1: 在 `Settings` 类(`GRAPH_ANALYSIS_ENABLED` 附近)追加**

```python
    # ---- P5 graph insights injection ----
    GRAPH_INSIGHTS_ENABLED: bool = os.getenv("GRAPH_INSIGHTS_ENABLED", "1") not in ("0", "false", "False")
    GRAPH_INSIGHTS_TIMEOUT_SECONDS: float = float(os.getenv("GRAPH_INSIGHTS_TIMEOUT_SECONDS", "3.0"))
    GRAPH_INSIGHTS_SEED_ENTITIES: int = int(os.getenv("GRAPH_INSIGHTS_SEED_ENTITIES", "6"))
    GRAPH_INSIGHTS_MAX_SURPRISING: int = int(os.getenv("GRAPH_INSIGHTS_MAX_SURPRISING", "2"))
    GRAPH_INSIGHTS_MAX_GOD: int = int(os.getenv("GRAPH_INSIGHTS_MAX_GOD", "2"))
    GRAPH_INSIGHTS_MAX_QUESTIONS: int = int(os.getenv("GRAPH_INSIGHTS_MAX_QUESTIONS", "2"))
    COMMUNITY_LABEL_MODEL: str = os.getenv("COMMUNITY_LABEL_MODEL", "")
```

- [ ] **Step 2: 验证**

Run: `cd AIOne && python -c "from engine.app.config import settings; print(settings.GRAPH_INSIGHTS_ENABLED, settings.GRAPH_INSIGHTS_TIMEOUT_SECONDS)"`
Expected: `True 3.0`

- [ ] **Step 3: Commit**

```bash
cd AIOne
git add engine/app/config.py
git commit -m "feat(insights): add P5 graph-insights injection config

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 两张新表(GraphCommunity + GraphInsightSummary)

**Files:** Create `backend/app/models/graph_community.py`、`backend/app/models/graph_insight_summary.py`;Modify `backend/app/models/__init__.py`;Test: `engine/tests/test_graph_insights.py`(建表测试)

- [ ] **Step 1: 写失败测试 `engine/tests/test_graph_insights.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_insights_test.db"

from backend.app.database import Base, engine as _engine
from sqlalchemy.orm import sessionmaker


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_graph_community_and_summary_tables_exist_and_writable():
    from backend.app.models import GraphCommunity, GraphInsightSummary
    db = _db()
    try:
        db.add(GraphCommunity(id="gc1", user_id="default-user", community_id=0, label="混合检索优化", cohesion=0.42))
        db.add(GraphInsightSummary(id="gs1", user_id="default-user",
                                   suggested_questions=[{"type": "god", "question": "Q?", "why": "w"}]))
        db.commit()
        assert db.query(GraphCommunity).filter_by(user_id="default-user", community_id=0).one().label == "混合检索优化"
        assert db.query(GraphInsightSummary).filter_by(user_id="default-user").one().suggested_questions[0]["question"] == "Q?"
    finally:
        db.close()
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -v`
Expected: FAIL(`ImportError: cannot import name 'GraphCommunity'`)

- [ ] **Step 3: 创建 `backend/app/models/graph_community.py`**

```python
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def _uuid() -> str:
    return str(uuid.uuid4())


class GraphCommunity(Base):
    __tablename__ = "graph_community"
    __table_args__ = (UniqueConstraint("user_id", "community_id", name="uq_graph_community_user_cid"),)

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    community_id = Column(Integer, nullable=False)
    label = Column(String(64), default="")
    cohesion = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
```

- [ ] **Step 4: 创建 `backend/app/models/graph_insight_summary.py`**

```python
import uuid

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.mysql import CHAR, JSON

from ..database import Base
from ..utils.time import local_now


def _uuid() -> str:
    return str(uuid.uuid4())


class GraphInsightSummary(Base):
    __tablename__ = "graph_insight_summary"
    __table_args__ = (UniqueConstraint("user_id", name="uq_graph_insight_summary_user"),)

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    suggested_questions = Column(JSON, default=list)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)
```

- [ ] **Step 5: 注册到 `backend/app/models/__init__.py`**

在 `from .entity import ...` 之后加:

```python
from .graph_community import GraphCommunity
from .graph_insight_summary import GraphInsightSummary
```

并在 `__all__` 列表里追加 `"GraphCommunity"`, `"GraphInsightSummary"`。

- [ ] **Step 6: 运行,确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py::test_graph_community_and_summary_tables_exist_and_writable -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd AIOne
git add backend/app/models/graph_community.py backend/app/models/graph_insight_summary.py backend/app/models/__init__.py engine/tests/test_graph_insights.py
git commit -m "feat(insights): GraphCommunity + GraphInsightSummary models

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 信号门控 + 社区标签生成(LLM)

**Files:** Create `engine/app/graph/insights.py`;Test: `engine/tests/test_graph_insights.py`(追加)

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_insights.py` 末尾追加:

```python
from unittest.mock import patch
from engine.app.graph.insights import has_insight_signal, generate_community_labels


def test_has_insight_signal_positive_and_negative():
    assert has_insight_signal("混合检索和重排有什么关系") is True     # "关系" 触发
    assert has_insight_signal("还有别的相关内容吗") is True          # "还有/相关" 触发
    assert has_insight_signal("你好") is False


@patch("engine.app.graph.insights.chat")
def test_generate_community_labels_uses_llm_and_returns_mapping(mock_chat):
    mock_chat.return_value = "混合检索优化"
    communities_by_cid = {0: ["混合检索", "RRF融合", "重排"]}
    labels = generate_community_labels(communities_by_cid, user_id="default-user")
    assert labels == {0: "混合检索优化"}
    assert mock_chat.call_count == 1


@patch("engine.app.graph.insights.chat")
def test_generate_community_labels_llm_failure_returns_empty(mock_chat):
    mock_chat.side_effect = RuntimeError("llm down")
    assert generate_community_labels({0: ["a", "b"]}) == {}
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -k "insight_signal or community_labels" -v`
Expected: FAIL(`ImportError: engine.app.graph.insights`)

- [ ] **Step 3: 创建 `engine/app/graph/insights.py`**

```python
"""P5 graph insights: signal gating + community labeling + question mining +
per-query insight block injection (mirrors active_recall).

Insights are precomputed in run_analysis (community labels via cheap LLM,
suggested_questions structurally) and stored in graph_community /
graph_insight_summary. graph_insights_context() reads them per-query and
returns a short background block (or "" ) injected into the system prompt.
"""
import logging

from ..config import settings
from ..llm.client import chat

logger = logging.getLogger("uvicorn.error")

_INSIGHT_SIGNALS = ("关系", "联系", "区别", "还有", "相关", "关联", "为什么", "怎么办", "怎么", "哪些", "之间", "属于")


def has_insight_signal(query: str) -> bool:
    text = (query or "").strip()
    if not text or len(text) < 2:
        return False
    return any(sig in text for sig in _INSIGHT_SIGNALS)


def generate_community_labels(communities_by_cid: dict[int, list[str]], user_id: str = "default-user") -> dict[int, str]:
    """One cheap LLM call per community -> <=6 char Chinese label.

    communities_by_cid: {cid: [entity surface names]}.
    Returns {cid: label}. Empty on any failure (non-fatal).
    """
    if not communities_by_cid:
        return {}
    model = settings.COMMUNITY_LABEL_MODEL or None
    labels: dict[int, str] = {}
    for cid, names in communities_by_cid.items():
        names = [n for n in names if n][:12]
        if not names:
            continue
        prompt = (
            "用一个不超过6个汉字的中文短语概括下面这组知识点的共同主题，只输出短语本身：\n"
            + "、".join(names)
        )
        try:
            raw = chat([{"role": "user", "content": prompt}], model=model)
            label = (raw or "").strip().strip("\"'""").replace("\n", "")[:6]
            if label:
                labels[cid] = label
        except Exception as exc:
            logger.warning("[insights] community_label_failed cid=%s err=%s", cid, exc)
    return labels
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -v`
Expected: PASS(4 个)

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/insights.py engine/tests/test_graph_insights.py
git commit -m "feat(insights): signal gating + community label generation (cheap LLM)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: suggest_questions 挖掘(结构化,过滤桥接)

**Files:** Modify `engine/app/graph/insights.py`;Test: `engine/tests/test_graph_insights.py`(追加)

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_insights.py` 末尾追加:

```python
from engine.app.graph.insights import compute_suggested_questions


def test_compute_suggested_questions_drops_bridge_and_keeps_god_ambiguous():
    # graphify returns questions with type tags; we drop bridge_node (concept-filtered)
    fake_questions = [
        {"type": "bridge_node", "question": "Why does A connect C0 to C1?", "why": "betweenness"},
        {"type": "god", "question": "Is X really central?", "why": "high inferred degree"},
        {"type": "ambiguous_edge", "question": "Rel between P and Q?", "why": "ambiguous"},
    ]
    out = compute_suggested_questions(_graph=lambda: None, _questions_override=fake_questions, top_n=5)
    types = {q["type"] for q in out}
    assert "bridge_node" not in types
    assert {"god", "ambiguous_edge"} <= types


def test_compute_suggested_questions_returns_empty_on_failure():
    def _boom(**kw):
        raise RuntimeError("graphify")
    out = compute_suggested_questions(_questions_fn=_boom, top_n=5)
    assert out == []
```

> 注:测试用依赖注入(`_questions_override` / `_questions_fn`)避开真图;实现里支持这些可选参数,默认调 graphify。

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -k "suggested_questions" -v`
Expected: FAIL(`ImportError: compute_suggested_questions`)

- [ ] **Step 3: 在 `engine/app/graph/insights.py` 追加**

```python
# graphify's bridge-node questions are filtered out for concept nodes (same as
# god_nodes); keep god / ambiguous_edge / surprising-derived questions only.
_KEEP_QUESTION_TYPES = {"god", "ambiguous_edge", "verification", "isolated"}


def compute_suggested_questions(
    G=None,
    communities: dict | None = None,
    community_labels: dict | None = None,
    top_n: int = 7,
    _questions_override: list[dict] | None = None,
    _questions_fn=None,
) -> list[dict]:
    """Structural question mining via graphify.suggest_questions (no LLM).

    Drops bridge_node (concept-filtered) and other unhelpful types.
    Returns [{type, question, why}]. Empty on any failure (non-fatal).
    """
    try:
        if _questions_override is not None:
            raw = _questions_override
        else:
            from graphify.analyze import suggest_questions
            fn = _questions_fn or suggest_questions
            raw = fn(G, communities or {}, community_labels or {}, top_n=top_n)
    except Exception as exc:
        logger.warning("[insights] suggest_questions_failed err=%s", exc)
        return []
    kept = [q for q in raw if isinstance(q, dict) and q.get("type") in _KEEP_QUESTION_TYPES]
    return kept[:top_n]
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -v`
Expected: PASS(6 个)

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/insights.py engine/tests/test_graph_insights.py
git commit -m "feat(insights): structural suggest_questions mining (drop bridge_node)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: run_analysis 末尾补算 + 持久化标签与问题

**Files:** Modify `engine/app/graph/analyzer.py`;Test: `engine/tests/test_graph_analyzer.py`(追加)

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_analyzer.py` 末尾追加(验证 run_analysis 写了 graph_community + graph_insight_summary):

```python
def test_run_analysis_persists_community_labels_and_questions(monkeypatch):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityRelation, GraphCommunity, GraphInsightSummary
    from sqlalchemy.orm import sessionmaker
    from engine.app.graph.analyzer import run_analysis
    from engine.app.graph import insights as ins

    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=1):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name, status="active"))
        db.flush()
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.add(EntityRelation(id="r2", subject_entity_id="e1", predicate="uses", object_entity_id="e3", relation_key="k2", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        # stub the LLM label call + graph (read/write analysis) so run_analysis stays deterministic
        monkeypatch.setattr(ins, "generate_community_labels", lambda c, **kw: {cid: f"主题{cid}" for cid in c})
        monkeypatch.setattr(ins, "compute_suggested_questions", lambda **kw: [{"type": "god", "question": "Q?", "why": "w"}])

        class _G:
            def read_entity_communities(self): return {}
            def set_entity_analysis(self, *a, **kw): pass
            def relate(self, *a, **kw): pass
        run_analysis(db, _G(), user_id="default-user")

        gcs = db.query(GraphCommunity).filter_by(user_id="default-user").all()
        assert len(gcs) >= 1 and all(gc.label.startswith("主题") for gc in gcs)
        summ = db.query(GraphInsightSummary).filter_by(user_id="default-user").one()
        assert summ.suggested_questions[0]["question"] == "Q?"
    finally:
        db.close()
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py::test_run_analysis_persists_community_labels_and_questions -v`
Expected: FAIL(run_analysis 还没写 graph_community / graph_insight_summary)

- [ ] **Step 3: 改 `engine/app/graph/analyzer.py`**

3a. 顶部 import 区加:

```python
from .insights import compute_suggested_questions, generate_community_labels
```

3b. 在 run_analysis 的 `return {"node_count": ..., "communities": ..., "god_nodes": ..., "surprising": ...}` **之前**插入持久化逻辑(此时 `communities`/`final`/`cohesion_by_cid`/`exported`/`god_ids` 都在作用域内):

```python
        # ---- P5: persist community labels + suggested questions ----
        try:
            from collections import defaultdict
            from backend.app.models import GraphCommunity, GraphInsightSummary

            label_by_id = {n["id"]: n.get("label", n["id"]) for n in exported["nodes"]}
            members_by_cid: dict[int, list[str]] = defaultdict(list)
            for node_id, cid in final.items():
                members_by_cid[int(cid)].append(label_by_id.get(node_id, node_id))

            labels = generate_community_labels(dict(members_by_cid), user_id=user_id)

            # upsert per-community label + cohesion
            existing = {gc.community_id: gc for gc in db.query(GraphCommunity).filter_by(user_id=user_id).all()}
            for cid, members in members_by_cid.items():
                gc = existing.get(cid)
                if gc is None:
                    gc = GraphCommunity(user_id=user_id, community_id=cid)
                    db.add(gc)
                gc.label = labels.get(cid, "")
                gc.cohesion = float(cohesion_by_cid.get(_new_cid_for_node(communities, members[0]) if members else -1, 0.0))
            db.flush()

            questions = compute_suggested_questions(
                G=G, communities=communities,
                community_labels={cid: labels.get(cid, "") for cid in members_by_cid},
                top_n=7,
            )
            summ = db.query(GraphInsightSummary).filter_by(user_id=user_id).one_or_none()
            if summ is None:
                summ = GraphInsightSummary(user_id=user_id)
                db.add(summ)
            summ.suggested_questions = questions
            db.commit()
        except Exception as exc:
            logger.warning("[analyzer] insights_persist_failed err=%s", exc)
            try:
                db.rollback()
            except Exception:
                pass
```

> `run_analysis` 已有 `db` 与 `user_id` 形参(Step B),无需改签名。`final`/`communities`/`cohesion_by_cid`/`exported` 均已在作用域。这段失败只记日志 + rollback,不影响前面已写的 community_id/god/surprising。

- [ ] **Step 4: 运行,确认通过 + 既有 graph_analyzer 测试无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/analyzer.py engine/tests/test_graph_analyzer.py
git commit -m "feat(insights): persist community labels + suggested_questions in run_analysis

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 注入逻辑 graph_insights_context

**Files:** Modify `engine/app/graph/insights.py`;Test: `engine/tests/test_graph_insights.py`(追加)

- [ ] **Step 1: 追加测试**

在 `engine/tests/test_graph_insights.py` 末尾追加:

```python
from engine.app.graph.insights import graph_insights_context


class _FakeGraph:
    def __init__(self, communities, surprising, gods_in_comm):
        self._communities = communities; self._surprising = surprising; self._gods_in_comm = gods_in_comm
    def entity_community(self, entity_id):
        return self._communities.get(entity_id)
    def surprising_endpoints(self, entity_id):
        return self._surprising.get(entity_id, [])
    def god_neighbors(self, entity_id, limit=10):
        return []  # not used here


def _db_with(entities, community_rows, summary_questions):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityAlias, GraphCommunity, GraphInsightSummary
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    for eid, name in entities:
        db.add(KnowledgeEntity(id=eid, user_id="default-user", entity_type="concept", canonical_name=name, normalized_key=name, status="active"))
        db.add(EntityAlias(id="al_"+eid, entity_id=eid, alias=name, normalized_key=name))
    for cid, label in community_rows:
        db.add(GraphCommunity(id=f"gc{cid}", user_id="default-user", community_id=cid, label=label, cohesion=0.4))
    db.add(GraphInsightSummary(id="gs1", user_id="default-user", suggested_questions=summary_questions))
    db.commit()
    return db


def test_graph_insights_context_composes_block_when_seeds_hit():
    db = _db_with([("e1", "混合检索")], [(0, "混合检索优化")],
                  [{"type": "god", "question": "X 真的中心吗?", "why": "w"}])
    g = _FakeGraph(communities={"e1": 0}, surprising={"e1": ["e2"]}, gods_in_comm={0: ["eGOD"]})
    # add e2 name + a god entity to db so rendering has names
    db.add_all([__import__("backend.app.models", fromlist=["KnowledgeEntity"]).KnowledgeEntity(id="e2", user_id="default-user", entity_type="concept", canonical_name="RRF融合", normalized_key="rrf", status="active"),
                __import__("backend.app.models", fromlist=["KnowledgeEntity"]).KnowledgeEntity(id="eGOD", user_id="default-user", entity_type="concept", canonical_name="枢纽概念", normalized_key="hub", status="active", )])
    db.commit()
    try:
        block = graph_insights_context("混合检索和别的有什么关系", user_id="default-user", db=db, graph_client=g)
        assert "隐藏联系" in block or "surprising" in block or "RRF融合" in block
        assert "混合检索优化" in block            # community label rendered
        assert "可追问" in block or "追问" in block  # question rendered
    finally:
        db.close()


def test_graph_insights_context_empty_when_no_signal():
    assert graph_insights_context("你好", user_id="default-user", db=None, graph_client=None) == ""


def test_graph_insights_context_empty_when_seeds_miss():
    db = _db_with([("e1", "混合检索")], [(0, "主题0")], [])
    g = _FakeGraph(communities={"e1": 0}, surprising={}, gods_in_comm={})
    try:
        # query talks about something unrelated -> no seed -> ""
        assert graph_insights_context("xyzabc 不存在的概念", user_id="default-user", db=db, graph_client=g) == ""
    finally:
        db.close()


def test_graph_insights_context_disabled_returns_empty():
    db = _db_with([("e1", "混合检索")], [(0, "主题0")], [])
    g = _FakeGraph(communities={"e1": 0}, surprising={"e1": ["e2"]}, gods_in_comm={})
    try:
        assert graph_insights_context("混合检索的关系", user_id="default-user", db=db, graph_client=g, enabled=False) == ""
    finally:
        db.close()
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -k "graph_insights_context" -v`
Expected: FAIL(`ImportError: graph_insights_context`)

- [ ] **Step 3: 在 `engine/app/graph/insights.py` 追加**

```python
def graph_insights_context(
    query: str,
    user_id: str = "default-user",
    *,
    db=None,
    graph_client=None,
    enabled: bool | None = None,
) -> str:
    """Return a short graph-insight background block for the query, or "".

    Mirrors active_recall: signal-gated, never raises, never delays first token.
    Caller may pass db/graph_client for testing; production path builds them.
    """
    if enabled is None:
        enabled = settings.GRAPH_INSIGHTS_ENABLED
    if not enabled or not has_insight_signal(query):
        return ""

    own_db = db is None
    own_graph = graph_client is None
    if own_db:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        db = sessionmaker(bind=create_engine(settings.DATABASE_URL, pool_pre_ping=True))()
    if own_graph:
        try:
            from backend.app.services.graph_client import GraphClient
            graph_client = GraphClient()
        except Exception as exc:
            logger.warning("[insights] graph_client_unavailable err=%s", exc)
            graph_client = None

    try:
        from backend.app.models import GraphCommunity, GraphInsightSummary, KnowledgeEntity
        from engine.app.retrieval.graph_expand import match_seed_entities

        seeds = match_seed_entities(db, query, limit=settings.GRAPH_INSIGHTS_SEED_ENTITIES)
        if not seeds or graph_client is None:
            return ""

        # communities touched by seeds
        cids: set[int] = set()
        for sid in seeds:
            cid = graph_client.entity_community(sid)
            if cid is not None:
                cids.add(int(cid))
        if not cids:
            return ""

        gc_rows = db.query(GraphCommunity).filter(GraphCommunity.community_id.in_(cids)).all()
        label_by_cid = {gc.community_id: gc.label for gc in gc_rows}

        # surprising endpoints of seeds -> other entities (render names)
        surprising_pairs: list[tuple[str, str]] = []
        for sid in seeds:
            for other in graph_client.surprising_endpoints(sid):
                surprising_pairs.append((sid, other))
        surprising_pairs = surprising_pairs[: settings.GRAPH_INSIGHTS_MAX_SURPRISING]

        # god entities in touched communities (read via Neo4j neighbors of seeds)
        god_ids: list[str] = []
        for sid in seeds:
            god_ids.extend(graph_client.god_neighbors(sid, limit=settings.GRAPH_INSIGHTS_MAX_GOD))
        god_ids = list(dict.fromkeys(god_ids))[: settings.GRAPH_INSIGHTS_MAX_GOD]

        # global suggested questions (top-N)
        summ = db.query(GraphInsightSummary).filter_by(user_id=user_id).one_or_none()
        questions = (summ.suggested_questions if summ else [])[: settings.GRAPH_INSIGHTS_MAX_QUESTIONS]

        # resolve names
        name_ids = set(seeds) | {o for _, o in surprising_pairs} | set(god_ids)
        name_map = {e.id: e.canonical_name for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.id.in_(name_ids)).all()}

        lines = ["【图谱洞察】"]
        for a, b in surprising_pairs:
            lines.append(f"- 隐藏联系：{name_map.get(a,a)} 与 {name_map.get(b,b)} 存在跨主题关联")
        if god_ids:
            lines.append("- 枢纽节点：" + "、".join(name_map.get(g, g) for g in god_ids))
        if cids and any(label_by_cid.get(c) for c in cids):
            lines.append("- 当前主题：" + "、".join(label_by_cid[c] for c in cids if label_by_cid.get(c)))
        if questions:
            lines.append("- 可追问：" + "；".join(q.get("question", "") for q in questions))
        if len(lines) == 1:
            return ""
        lines.append("回答时可参考这些联系，并在合适时主动提示用户。")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[insights] graph_insights_context_failed err=%s", exc)
        return ""
    finally:
        if own_db:
            try: db.close()
            except Exception: pass
        if own_graph and graph_client is not None:
            try: graph_client.close()
            except Exception: pass
```

- [ ] **Step 4: 运行,确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -v`
Expected: PASS(全部 insights 测试)

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/insights.py engine/tests/test_graph_insights.py
git commit -m "feat(insights): graph_insights_context per-query insight block injection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: runner 注入 graph_insights_context

**Files:** Modify `engine/app/agent/runner.py`;Test: `engine/tests/test_agent_runner.py`(追加一个轻量注入断言)或 `test_graph_insights.py`

- [ ] **Step 1: 追加测试(验证 _build_messages 注入,降级安全)**

在 `engine/tests/test_graph_insights.py` 末尾追加:

```python
def test_build_messages_injects_graph_insights(monkeypatch):
    import engine.app.graph.insights as ins
    monkeypatch.setattr(ins, "graph_insights_context", lambda q, **kw: "【图谱洞察】stub")
    # also neutralize memory recall to isolate
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    from engine.app.agent.runner import LangChainAgentRunner
    from langchain_core.messages import SystemMessage
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    msgs = runner._build_messages("混合检索的关系", history=[])
    sys_texts = [m.content for m in msgs if isinstance(m, SystemMessage)]
    assert any("图谱洞察" in t for t in sys_texts)


def test_build_messages_without_insights_when_disabled(monkeypatch):
    monkeypatch.setattr("engine.app.graph.insights.graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    from engine.app.agent.runner import LangChainAgentRunner
    from langchain_core.messages import SystemMessage
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    msgs = runner._build_messages("你好", history=[])
    sys_texts = [m.content for m in msgs if isinstance(m, SystemMessage)]
    assert all("图谱洞察" not in t for t in sys_texts)
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py -k "build_messages" -v`
Expected: FAIL(runner 还没注入)

- [ ] **Step 3: 改 `engine/app/agent/runner.py`**

3a. 顶部 import 区(紧跟 `from .active_recall import recall_memory_context` 之后)加:

```python
from ..graph.insights import graph_insights_context
```

3b. 在 `_build_messages` 里,紧跟 `recall_memory_context` 注入那段之后(即现有 `except Exception as exc:` 收尾 active_recall 之后)追加:

```python
        try:
            insights_block = graph_insights_context(query)
            if insights_block:
                messages.append(SystemMessage(content=insights_block))
                logger.info("[agent] graph_insights injected chars=%s", len(insights_block))
        except Exception as exc:
            logger.warning("[agent] graph_insights failed (ignored): %s", quoted(str(exc), limit=200))
```

> 紧贴 active_recall 的 try/except 之后即可;query/`messages` 变量均在作用域。

- [ ] **Step 4: 运行,确认通过 + runner 既有测试无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_insights.py engine/tests/test_agent_runner.py -v`
Expected: PASS(test_agent_runner.py 若有依赖真实模型的用例报错属环境问题,非本任务引入)

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/agent/runner.py engine/tests/test_graph_insights.py
git commit -m "feat(agent): inject graph_insights_context into system prompt (mirrors active_recall)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: 端到端验证(手动)

**Files:** 无代码改动。参考 `docs/superpowers/plans/2026-07-05-p3-stepb-e2e-verification-runbook.md` 的服务启动方式。

- [ ] **Step 1: 起服务 + 重新入库触发 run_analysis 补算**

```bash
docker compose up -d
SKIP_ENGINE=1 python -m backend.run &
python -m engine.run &
# 上传一份文档,等 run_analysis 跑完(会写 graph_community + graph_insight_summary)
RESP=$(curl -s -X POST http://localhost:5175/api/v1/upload/file -F "file=@/tmp/probe.md")
ITEM_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
sleep 45
```

- [ ] **Step 2: 验证标签/问题已写表**

```bash
docker compose exec -T mysql mysql -uroot -p"<DB_PASSWORD>" "<DB_NAME>" -e \
  "SELECT community_id, label, cohesion FROM graph_community WHERE user_id='default-user' LIMIT 20;
   SELECT JSON_LENGTH(suggested_questions) AS q_n FROM graph_insight_summary WHERE user_id='default-user';"
```
期望:每个社区有 ≤6 字 label;summary 有 ≥1 个问题。

- [ ] **Step 3: 验证注入(探索性问题)**

```bash
curl -s -N -X POST http://localhost:5180/api/v1/chat/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"混合检索和重排之间有什么关系?还有别的相关联系吗","history":[]}' | head -c 3000
```
查 engine 日志:`docker compose logs engine 2>/dev/null | grep "graph_insights injected"` → 出现 `chars=N` 即注入成功。

- [ ] **Step 4: 验证降级**

`.env` 设 `GRAPH_INSIGHTS_ENABLED=0`,重启 engine,再问同样问题 → 日志无 `graph_insights injected`,对话正常。

- [ ] **Step 5: 全部通过 → P5 验收完成**

```bash
git log --oneline -9   # 确认 7 个提交都在
```

---

## Self-Review(计划完成后自查)

**1. Spec 覆盖:**
- 注入机制(仿 active_recall)→ Task 6 `graph_insights_context` + Task 7 runner 接线。✓
- run_analysis 补算社区标签 + suggest_questions → Task 5。✓
- graph_community / graph_insight_summary 两张表 → Task 2。✓
- suggest_questions 过滤 bridge_node → Task 4。✓
- 信号门控 + try/except + 超时 + 降级 → Task 3(has_insight_signal)+ Task 6(`""` 路径)+ Task 1(`GRAPH_INSIGHTS_ENABLED`)+ Task 7(try/except)。✓
- 测试 + e2e → 各 Task TDD + Task 8。✓
- 配置 → Task 1。✓

**2. 占位符扫描:** Task 8 Step 2 的 `<DB_PASSWORD>`/`<DB_NAME>` 用 .env 实际值替换(已在 runbook 体系里说明),非代码占位。无 TBD/TODO。Task 6 测试里用 `__import__` 内联构造 KnowledgeEntity 是为减少 import 行,功能等价,可读但偏巧;若执行者嫌乱可改成顶部 import(不影响正确性)。

**3. 类型一致性:**
- `generate_community_labels(communities_by_cid: dict[int,list[str]], user_id) -> dict[int,str]`:Task 3 定义,Task 5 调用一致。
- `compute_suggested_questions(G, communities, community_labels, top_n, ...) -> list[dict]`:Task 4 定义,Task 5 调用一致。
- `graph_insights_context(query, user_id, *, db, graph_client, enabled) -> str`:Task 6 定义,Task 7 调用一致。
- `GraphCommunity(user_id, community_id, label, cohesion)` / `GraphInsightSummary(user_id, suggested_questions)`:Task 2 定义,Task 5/6 读写一致。
- 复用 `match_seed_entities(db, query, limit)`(P3)、`GraphClient.entity_community/surprising_endpoints/god_neighbors`(Step B+P3)签名一致。✓

**4. 执行机注意:**
- Task 2 建表依赖 auto_migrate 在 backend 启动时跑(`Base.metadata.tables`),注册到 `__init__.py` 即可被扫描。
- Task 5 的 `run_analysis` 必须在 Step B 已合入的代码上(已确认 tip 含 Step B)。
- graphify `suggest_questions` 桥接分支过滤 concept 节点 → Task 4 显式丢弃 `bridge_node`。
- 社区标签 LLM 用 `COMMUNITY_LABEL_MODEL`(默认空=复用 `LLM_MODEL`);失败不阻断(Task 3 已测)。
