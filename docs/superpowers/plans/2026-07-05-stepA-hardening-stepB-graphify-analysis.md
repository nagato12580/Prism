# Step A 收尾加固 + Step B graphify 分析层 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P1（全覆盖实体抽取）之上，(Step A) 补齐重入库 Neo4j 清理 + 接回实体间关系 + 修 confidence 默认值；(Step B) 接入 graphify 分析层，每入库对全图跑社区发现/god/surprising 并稳定写回 Neo4j。

**Architecture:** Step A 让图谱在重入库时干净、并获得 Entity↔Entity `RELATED_TO` 连接组织。Step B 新增 `engine/app/graph/analyzer.py`：从 MySQL 导出 Entity-Entity 同质图（显式关系 + 共现边）→ graphify `build_from_json`/`cluster`/`surprising_connections` → 稳定重映射 community_id → 写回 Neo4j。god 节点因 graphify 会过滤 concept 节点，改用 NetworkX 度数直接计算。NetworkX 图临时即弃，不并存第二存储。所有新路径失败隔离，不阻断入库。

**Tech Stack:** Python 3.12 · SQLAlchemy（MySQL，测试 sqlite）· Neo4j（`GraphClient`）· graphify（`graphifyy`：build/cluster/score_all/surprising_connections/diagnostics）· NetworkX · pytest。

**Spec:** `docs/superpowers/specs/2026-07-05-stepA-hardening-stepB-graphify-analysis-design.md`

**Environment (执行机前置):**
- 仓库：`AIOne`，分支 `feature/entity-graph-projection`（先 `git pull` 到最新 `4440f5f`）。
- Python：项目所用解释器（本机为 `/e/python/py312/python`，已有 sqlalchemy/neo4j/langchain）。
- pytest 必须带 `DATABASE_URL`：`DATABASE_URL=sqlite:///./_t.db python -m pytest ...`（`backend/app/database.py` 在导入时建引擎，DATABASE_URL 空会报错）。backend 测试在 `backend/` 下跑（`testpaths=tests`），engine 测试在仓库根跑。
- Step B 需安装 graphify：`pip install graphifyy`（Task 6 会加进 requirements）。
- git 提交信息末尾加 trailer：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

**graphify API 速查（已实测签名）：**
```
build_from_json(extraction: dict, *, directed=False, root=None) -> nx.Graph
cluster(G, resolution=1.0) -> dict[int, list[node_id]]      # {community_id: [members]}
score_all(G, communities) -> dict[int, float]               # {community_id: cohesion}
surprising_connections(G, communities=None, top_n=5) -> list[dict]  # {source,target,note,confidence,relation}
god_nodes(G) -> 会过滤掉 concept 节点 → 本计划改用 nx.degree 自算
diagnose_extraction(extraction, *, directed=True, root=None, ...) -> dict   # 只记日志
```

---

## 文件结构

- Create: `engine/app/graph/__init__.py`（空包标记）
- Create: `engine/app/graph/analyzer.py`（graphify 复用：export / build / cluster / 稳定重映射 / 度数 god / surprising / diagnostics / 写回）
- Create: `engine/tests/test_graph_analyzer.py`
- Modify: `backend/app/services/graph_client.py`（A1 删 item Source；B3 读/写社区god）
- Modify: `backend/app/services/graph_projection.py`（A1 投影前清理；A2b 投影 EntityRelation）
- Modify: `backend/app/services/entity_extraction.py`（A2b 泛化 resolver；A3 confidence 默认 0.0）
- Modify: `engine/app/extraction/prompts.py`（A2a 加回 relations）
- Modify: `engine/app/extraction/stage_a.py`（A2a 解析 relations + 候选）
- Modify: `engine/app/ingestion/pipeline.py`（B5 接入 run_analysis）
- Modify: `engine/app/config.py`（B1 GRAPH_ANALYSIS_ENABLED）
- Modify: `requirements.txt`（B1 graphifyy）

---

# Step A — 收尾加固

## Task 1 (A3): confidence 默认值 0.5 → 0.0

**Files:**
- Modify: `backend/app/services/entity_extraction.py`（`EntityCandidate` dataclass）
- Test: `backend/tests/test_entity_settle.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_entity_settle.py` 末尾追加：

```python
from backend.app.services.entity_extraction import EntityCandidate


def test_entity_candidate_default_confidence_is_zero():
    c = EntityCandidate(kind="entity", entity_type="concept", surface_text="x", normalized_key="x")
    assert c.confidence == 0.0
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne/backend && DATABASE_URL=sqlite:///./_t.db python -m pytest tests/test_entity_settle.py::test_entity_candidate_default_confidence_is_zero -v`
Expected: FAIL（`assert 0.5 == 0.0`）

- [ ] **Step 3: 改默认值**

在 `backend/app/services/entity_extraction.py` 的 `EntityCandidate` 中：

```python
    confidence: float = 0.0
```

（原为 `0.5`。）

- [ ] **Step 4: 运行，确认通过 + 无回归**

Run: `cd AIOne/backend && DATABASE_URL=sqlite:///./_t.db python -m pytest tests/test_entity_settle.py -v`
Expected: PASS（含新增 + 既有 settle 测试）

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add backend/app/services/entity_extraction.py backend/tests/test_entity_settle.py
git commit -m "fix(entity): default EntityCandidate.confidence to 0.0 (0.5 is forbidden by Stage A discipline)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2 (A1): Neo4j 重入库清理（删 item 旧 Source）

**Files:**
- Modify: `backend/app/services/graph_client.py`（新增 `delete_item_sources`）
- Modify: `backend/app/services/graph_projection.py`（投影前清理）
- Test: `engine/tests/test_stage_a.py`（追加；用 FakeGraph）

- [ ] **Step 1: 追加失败测试**

在 `engine/tests/test_stage_a.py` 末尾追加（复用该文件已有的 `FakeGraph` 风格；这里新建一个带 delete 记录的 fake）：

```python
from backend.app.services.graph_projection import project_item_entities


class FakeGraphWithDelete:
    def __init__(self):
        self.upserted_sources = []
        self.upserted_entities = []
        self.relations = []
        self.deleted_item_ids = []

    def delete_item_sources(self, item_id):
        self.deleted_item_ids.append(item_id)

    def upsert_source(self, data):
        self.upserted_sources.append(data)

    def upsert_entity(self, data):
        self.upserted_entities.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append((start_label, start_id, rel_type, end_label, end_id))


def test_project_item_entities_deletes_old_sources_before_projecting():
    # build a sqlite session with one item/chunk/entity/mention (reuse the pattern
    # already present in this file's test_project_item_entities_* test for seeding)
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem, KnowledgeChunk, KnowledgeEntity, EntityMention
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc"))
        db.add(KnowledgeChunk(id="c1", item_id="i1", chunk_text="x", chunk_index=0, chunk_type="child"))
        ent = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="K", normalized_key="k", status="active")
        db.add(ent); db.flush()
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="K", normalized_key="k", confidence=0.85, extraction_method="llm_stage_a:INFERRED"))
        db.commit()

        fake = FakeGraphWithDelete()
        project_item_entities(db, fake, item_id="i1", user_id="default-user")

        # cleanup MUST run first, scoped to this item_id
        assert fake.deleted_item_ids == ["i1"]
        # and then re-projected
        assert any(e["id"] == "e1" for e in fake.upserted_entities)
    finally:
        db.close()
```

> 若 `KnowledgeItem`/`KnowledgeChunk` 有其它 NOT NULL 列，按 `backend/app/models/knowledge_item.py` 补齐（参考本文件已有的 `test_project_item_entities_*` 种子写法）。

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py::test_project_item_entities_deletes_old_sources_before_projecting -v`
Expected: FAIL（`FakeGraphWithDelete` 无 `delete_item_sources` 调用 / 或 AttributeError）

- [ ] **Step 3: `graph_client.py` 加 `delete_item_sources`**

在 `backend/app/services/graph_client.py` 的 `GraphClient` 类中（紧跟 `relate` 之后）加：

```python
    def delete_item_sources(self, item_id: str) -> None:
        """Delete all :Source nodes (and their edges) for one item. Idempotent."""
        query = """
        MATCH (s:Source {item_id: $item_id})
        DETACH DELETE s
        """
        self._execute_write(query, {"item_id": item_id})
```

- [ ] **Step 4: `graph_projection.py` 投影前清理**

在 `backend/app/services/graph_projection.py::project_item_entities` 函数体最前面（`mentions = ...` 查询之前）加：

```python
    # Clean this item's previous Source nodes/edges so re-ingest (fresh chunk
    # UUIDs) leaves no zombie Sources. Idempotent: delete then re-project.
    graph.delete_item_sources(item_id)
```

- [ ] **Step 5: 运行，确认通过 + 无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py -v`
Expected: PASS（全部 stage_a 测试，含新增）

- [ ] **Step 6: Commit**

```bash
cd AIOne
git add backend/app/services/graph_client.py backend/app/services/graph_projection.py engine/tests/test_stage_a.py
git commit -m "fix(graph): delete item's old Neo4j Sources before re-projecting (I2 no zombie edges)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3 (A2a): 接回实体间关系 —— 抽取侧（prompt + parser + 候选）

**Files:**
- Modify: `engine/app/extraction/prompts.py`
- Modify: `engine/app/extraction/stage_a.py`
- Test: `engine/tests/test_stage_a.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `engine/tests/test_stage_a.py` 末尾追加：

```python
from engine.app.extraction.prompts import parse_stage_a_relations


def test_parse_stage_a_relations_clean():
    raw = '{"entities":[],"relations":[{"subject":"混合检索","predicate":"uses","object":"RRF融合","tier":"INFERRED","score":0.85}]}'
    rels = parse_stage_a_relations(raw)
    assert len(rels) == 1
    assert rels[0]["subject"] == "混合检索"
    assert rels[0]["predicate"] == "uses"
    assert rels[0]["object"] == "RRF融合"
    assert rels[0]["score"] == 0.85


def test_parse_stage_a_relations_rejects_bad_score():
    raw = '{"entities":[],"relations":[{"subject":"a","predicate":"related_to","object":"b","tier":"EXTRACTED","score":0.5}]}'
    assert parse_stage_a_relations(raw) == []


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_returns_relation_candidates(mock_chat):
    mock_chat.return_value = (
        '{"entities":['
        '{"entity_type":"concept","surface":"混合检索","tier":"EXTRACTED","score":1.0,"evidence":""}'
        '],"relations":['
        '{"subject":"混合检索","predicate":"uses","object":"RRF融合","tier":"INFERRED","score":0.85}'
        ']}'
    )
    from engine.app.extraction.stage_a import extract_entities_for_chunk
    cands = extract_entities_for_chunk("text", chunk_id="c1")
    rels = [c for c in cands if c.kind == "relation"]
    assert len(rels) == 1
    r = rels[0]
    assert r.subject_surface == "混合检索"
    assert r.predicate == "uses"
    assert r.object_surface == "RRF融合"
    assert r.confidence == 0.85
    assert r.extraction_method.startswith("llm_stage_a:INFERRED")
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py -k "relations or returns_relation_candidates" -v`
Expected: FAIL（`ImportError: parse_stage_a_relations`）

- [ ] **Step 3: `prompts.py` —— 加回 relations 到 prompt + 新增 `parse_stage_a_relations`**

3a. 在 `STAGE_A_EXTRACTION_PROMPT` 中把被裁掉的 relations 段落加回（替换之前的 "P1 extracts entities only" 注释与开头）。新模板（注意 `{{ }}` 转义）：

```python
# Stage A extracts entities AND inter-entity relations. Relations give the graph
# the connective tissue that community detection (Step B) needs.
STAGE_A_EXTRACTION_PROMPT = """你是知识图谱实体抽取器。从下面的文本片段中抽取「实体」和「实体间关系」。

抽取范围（尽量全）：概念、术语、方法、产品、技术、人物、机构、地点、法规、数据集、工具等。
不要只抽人名/机构——这是通用知识库，概念和术语同样重要。

每个实体输出一个对象，字段：
- entity_type: 实体类型（concept/term/method/product/technology/person/organization/place/regulation/dataset/tool/other）
- surface: 实体在原文中的表面文本（原样，不要改写）
- tier: 置信档，三选一：EXTRACTED（原文直接出现）/ INFERRED（推断）/ AMBIGUOUS（不确定）
- score: 置信分数。EXTRACTED 必须 1.0；INFERRED 取 0.95/0.85/0.75/0.65/0.55 之一；AMBIGUOUS 取 0.1~0.3。禁止 0.5。
- evidence: 原文中支持该实体的短语（原文摘录，<=80字）

若两个实体有明显关系，输出 relations 数组，每个对象：
- subject / object：实体的 surface（必须与 entities 里的 surface 一致）
- predicate：related_to/uses/part_of/defines/supports/contradicts/alternative_to/depends_on 等
- tier / score：同上规则

只输出一个 JSON 对象，形如：
{{"entities": [{{"entity_type":"...","surface":"...","tier":"...","score":1.0,"evidence":"..."}}], "relations": [{{"subject":"...","predicate":"...","object":"...","tier":"...","score":0.85}}]}}
不要输出 JSON 以外的任何文字。

文本片段：
{chunk_text}
"""
```

3b. 在 `prompts.py` 末尾新增（复用已有的 `_extract_json_object`、`_valid_entity` 做置信校验）：

```python
def parse_stage_a_relations(raw: str) -> list[dict]:
    """Parse the relations array from model output. Validates tier/score like entities.

    Returns list of dicts: {subject, predicate, object, tier, score}.
    """
    if not raw or not raw.strip():
        return []
    blob = _extract_json_object(raw)
    if not blob:
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    relations = data.get("relations", [])
    if not isinstance(relations, list):
        return []
    result = []
    for item in relations:
        if not isinstance(item, dict) or not _valid_entity(item):
            continue
        subject = (item.get("subject") or "").strip()
        obj = (item.get("object") or "").strip()
        predicate = (item.get("predicate") or "related_to").strip() or "related_to"
        if not subject or not obj:
            continue
        result.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "tier": item["tier"],
                "score": float(item["score"]),
            }
        )
    return result
```

> `_valid_entity` 校验的是 tier/score 组合，relation 复用同一规则（合法）。

- [ ] **Step 4: `stage_a.py` —— 解析 relations 并转候选**

4a. 修改 import：

```python
from .prompts import STAGE_A_EXTRACTION_PROMPT, parse_stage_a_json, parse_stage_a_relations
```

4b. 修改 `extract_entities_for_chunk`，把 relations 也转成候选并合并返回：

```python
def extract_entities_for_chunk(chunk_text: str, chunk_id: str = "") -> list[EntityCandidate]:
    """Extract entity + relation candidates for one chunk via LLM. Never raises."""
    text = (chunk_text or "").strip()[:_MAX_CHUNK_CHARS]
    if not text:
        return []
    prompt = STAGE_A_EXTRACTION_PROMPT.format(chunk_text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], model=_stage_a_model())
    except Exception as exc:
        logger.warning("[stage_a] llm_failed chunk_id=%s error=%s", chunk_id, exc)
        return []
    entities = parse_stage_a_json(raw)
    relations = parse_stage_a_relations(raw)
    candidates = [_to_candidate(p, chunk_id) for p in entities]
    candidates.extend(_to_relation_candidate(r, chunk_id) for r in relations)
    return candidates
```

4c. 在 `_to_candidate` 之后新增 `_to_relation_candidate`：

```python
def _to_relation_candidate(item: dict, chunk_id: str) -> EntityCandidate:
    subject = item["subject"]
    obj = item["object"]
    tier = item["tier"]
    score = item["score"]
    return EntityCandidate(
        kind="relation",
        confidence=score,
        evidence_span=f"{subject} {item['predicate']} {obj}",
        extraction_method=f"llm_stage_a:{tier}",
        subject_surface=subject,
        predicate=item["predicate"],
        object_surface=obj,
        object_entity_type="",
    )
```

> `object_entity_type=""` 表示未知类型，交给泛化后的 resolver 跨类型解析（Task 4）。

- [ ] **Step 5: 运行，确认通过 + 既有 stage_a 测试无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py -v`
Expected: PASS（注意 `test_prompt_contains_required_fields` 仍过——prompt 仍含 entity_type/surface/tier/score/evidence 等token）

- [ ] **Step 6: Commit**

```bash
cd AIOne
git add engine/app/extraction/prompts.py engine/app/extraction/stage_a.py engine/tests/test_stage_a.py
git commit -m "feat(extraction): re-add inter-entity relations to Stage A (prompt + parser + candidates)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4 (A2b): 关系落库 —— 泛化 resolver + 投影 RELATED_TO

**Files:**
- Modify: `backend/app/services/entity_extraction.py`（泛化 `_resolve_entity_for_relation` + 调用处）
- Modify: `backend/app/services/graph_projection.py`（`project_item_entities` 投影 EntityRelation）
- Test: `backend/tests/test_entity_settle.py`（追加）、`engine/tests/test_stage_a.py`（追加）

- [ ] **Step 1: 追加失败测试（关系落库）**

在 `backend/tests/test_entity_settle.py` 末尾追加：

```python
def test_settle_entity_candidates_persists_concept_relation():
    from backend.app.database import Base, engine as _engine
    from backend.app.models import EntityRelation, KnowledgeEntity
    from backend.app.services.entity_extraction import EntityCandidate, settle_entity_candidates
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        candidates = [
            EntityCandidate(kind="entity", entity_type="concept", surface_text="混合检索",
                            normalized_key="混合检索", aliases=["混合检索"], confidence=1.0,
                            extraction_method="llm_stage_a:EXTRACTED"),
            EntityCandidate(kind="entity", entity_type="method", surface_text="RRF融合",
                            normalized_key="rrf融合", aliases=["rrf融合"], confidence=1.0,
                            extraction_method="llm_stage_a:EXTRACTED"),
            EntityCandidate(kind="relation", confidence=0.85,
                            evidence_span="混合检索 uses RRF融合",
                            extraction_method="llm_stage_a:INFERRED",
                            subject_surface="混合检索", predicate="uses",
                            object_surface="RRF融合", object_entity_type=""),
        ]
        settle_entity_candidates(db, candidates, source_kind="document_chunk", source_id="c1",
                                 item_id="i1", chunk_id="c1", user_id="default-user")
        db.commit()
        rels = db.query(EntityRelation).all()
        assert len(rels) == 1
        subj = db.query(KnowledgeEntity).filter_by(canonical_name="混合检索").one()
        obj = db.query(KnowledgeEntity).filter_by(canonical_name="RRF融合").one()
        assert rels[0].subject_entity_id == subj.id
        assert rels[0].object_entity_id == obj.id
        assert rels[0].predicate == "uses"
    finally:
        db.close()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne/backend && DATABASE_URL=sqlite:///./_t.db python -m pytest tests/test_entity_settle.py::test_settle_entity_candidates_persists_concept_relation -v`
Expected: FAIL（resolver 用硬编码 "person" 找不到 concept subject → 不建关系）

- [ ] **Step 3: 泛化 `_resolve_entity_for_relation`**

在 `backend/app/services/entity_extraction.py` 中，把 `_resolve_entity_for_relation` 替换为（支持空/未知 entity_type 时跨类型解析）：

```python
def _resolve_entity_for_relation(
    db,
    settled_by_surface: dict[tuple[str, str], KnowledgeEntity],
    user_id: str,
    entity_type: str,
    surface_text: str,
) -> KnowledgeEntity | None:
    # 1) prefer an exact (type, surface) hit among just-settled entities
    if entity_type:
        hit = settled_by_surface.get((entity_type, surface_text))
        if hit:
            return hit
    else:
        # unknown type: match any settled entity sharing this surface
        for (etype, surf), ent in settled_by_surface.items():
            if surf == surface_text:
                return ent
    # 2) fall back to the DB, keyed by normalized surface; scoped to user.
    key = normalize_entity_key(surface_text)
    if entity_type:
        return (
            db.query(KnowledgeEntity)
            .filter_by(user_id=user_id, entity_type=entity_type, normalized_key=key)
            .one_or_none()
        )
    # unknown type: any entity with this normalized key
    matches = (
        db.query(KnowledgeEntity)
        .filter_by(user_id=user_id, normalized_key=key)
        .all()
    )
    return matches[0] if matches else None
```

3b. `settle_entity_candidates` 中关系分支的调用要传候选自带的 `object_entity_type`（可能为 ""）。找到 `settle_entity_candidates` 里处理 `kind == "relation"` 的循环，确认它对 subject 也用泛化解析。当前代码 subject 写死 `"person"`，改为按候选解析。把那段循环改为：

```python
    for candidate in candidates:
        if candidate.kind != "relation":
            continue
        subject = _resolve_entity_for_relation(
            db, settled_by_surface, user_id, "", candidate.subject_surface
        )
        object_entity = _resolve_entity_for_relation(
            db, settled_by_surface, user_id, candidate.object_entity_type, candidate.object_surface
        )
        if subject and object_entity:
            _upsert_relation(db, subject, object_entity, candidate, source_kind, source_id)
```

（subject 类型未知 → 传 ""，由泛化 resolver 跨类型匹配。）

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne/backend && DATABASE_URL=sqlite:///./_t.db python -m pytest tests/test_entity_settle.py -v`
Expected: PASS

- [ ] **Step 5: 追加投影测试（EntityRelation → RELATED_TO）**

在 `engine/tests/test_stage_a.py` 末尾追加（用 `FakeGraphWithDelete`）：

```python
def test_project_item_entities_projects_relation_as_related_to():
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem, KnowledgeChunk, KnowledgeEntity, EntityMention, EntityRelation
    from sqlalchemy.orm import sessionmaker
    from backend.app.services.graph_projection import project_item_entities
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc"))
        db.add(KnowledgeChunk(id="c1", item_id="i1", chunk_text="x", chunk_index=0, chunk_type="child"))
        e1 = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="a", status="active")
        e2 = KnowledgeEntity(id="e2", user_id="default-user", entity_type="method", canonical_name="RRF融合", normalized_key="b", status="active")
        db.add_all([e1, e2]); db.flush()
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="混合检索", normalized_key="a", confidence=1.0, extraction_method="llm_stage_a:EXTRACTED"))
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="rk1", source_kind="document_chunk", source_id="c1", confidence=0.85, extraction_method="llm_stage_a:INFERRED"))
        db.commit()
        fake = FakeGraphWithDelete()
        project_item_entities(db, fake, item_id="i1", user_id="default-user")
        assert ("Entity", "e1", "RELATED_TO", "Entity", "e2") in fake.relations
    finally:
        db.close()
```

- [ ] **Step 6: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py::test_project_item_entities_projects_relation_as_related_to -v`
Expected: FAIL（project_item_entities 还没投影 relations）

- [ ] **Step 7: `graph_projection.py::project_item_entities` 投影 relations**

在 `project_item_entities` 返回前（mentions 循环之后、`return edges` 之前）追加：

```python
    # Project this item's inter-entity relations as RELATED_TO edges.
    item_relations = (
        db.query(EntityRelation)
        .filter(EntityRelation.source_kind == "document_chunk", EntityRelation.source_id.in_(source_cache_ids()))
        .all()
    ) if False else []  # placeholder removed below
```

（上面占位行删除，正式代码：）在 mentions 循环里收集本 item 涉及的 chunk id，循环后查询关系并投影。具体：在 `source_cache: set[str] = set()` 旁边再加 `chunk_ids: set[str] = set()`，在每个 mention 处理时 `chunk_ids.add(mention.source_id)`。然后在 `return edges` 之前加：

```python
    if chunk_ids:
        relations = (
            db.query(EntityRelation)
            .filter(EntityRelation.source_kind == "document_chunk", EntityRelation.source_id.in_(chunk_ids))
            .all()
        )
        for relation in relations:
            if not relation.object_entity_id:
                continue
            graph.relate(
                "Entity",
                relation.subject_entity_id,
                "RELATED_TO",
                "Entity",
                relation.object_entity_id,
                _relation_props(relation, ["predicate", "confidence", "evidence_span", "extraction_method"]),
            )
            edges += 1
```

并在每个 mention 处理末尾加 `chunk_ids.add(mention.source_id)`（与 `source_cache.add(...)` 并列）。

> `EntityRelation` 已在文件顶部 import（`graph_projection.py` 现有 import 列表里有 `EntityRelation`）。

- [ ] **Step 8: 运行，确认通过 + 全量 stage_a 无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd AIOne
git add backend/app/services/entity_extraction.py backend/app/services/graph_projection.py backend/tests/test_entity_settle.py engine/tests/test_stage_a.py
git commit -m "feat(graph): generalize relation resolver + project inter-entity RELATED_TO (I1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Step B — graphify 分析层

## Task 5 (B1): 依赖 + 配置

**Files:**
- Modify: `requirements.txt`
- Modify: `engine/app/config.py`

- [ ] **Step 1: 加依赖**

在 `requirements.txt` 末尾加：

```text
graphifyy>=0.3.10
```

执行机运行：`pip install graphifyy`（或 `pip install -r requirements.txt`）。

- [ ] **Step 2: 加配置**

在 `engine/app/config.py` 的 `Settings` 类（`ENTITY_EXTRACT_ENABLED` 附近）加：

```python
    GRAPH_ANALYSIS_ENABLED: bool = os.getenv("GRAPH_ANALYSIS_ENABLED", "1") not in ("0", "false", "False")
```

- [ ] **Step 3: 验证 graphify 可导入 + 配置可读**

Run: `cd AIOne && python -c "import graphify; from engine.app.config import settings; print('graphify+config OK', settings.GRAPH_ANALYSIS_ENABLED)"`
Expected: `graphify+config OK True`

- [ ] **Step 4: Commit**

```bash
cd AIOne
git add requirements.txt engine/app/config.py
git commit -m "feat(graph): add graphifyy dependency + GRAPH_ANALYSIS_ENABLED flag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6 (B2): 导出 Entity-Entity 图给 graphify

**Files:**
- Create: `engine/app/graph/__init__.py`（空）
- Create: `engine/app/graph/analyzer.py`（先只写 export）
- Test: `engine/tests/test_graph_analyzer.py`

- [ ] **Step 1: 建空包**

创建 `engine/app/graph/__init__.py`，内容为空。

- [ ] **Step 2: 写失败测试 `engine/tests/test_graph_analyzer.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_analyzer_test.db"

from backend.app.database import Base, engine as _engine
from backend.app.models import KnowledgeEntity, EntityMention, EntityRelation
from sqlalchemy.orm import sessionmaker

from engine.app.graph.analyzer import export_graph_for_graphify


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_export_builds_nodes_and_cooccurrence_and_relation_edges():
    db = _db()
    try:
        e1 = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="a", status="active")
        e2 = KnowledgeEntity(id="e2", user_id="default-user", entity_type="method", canonical_name="RRF融合", normalized_key="b", status="active")
        e3 = KnowledgeEntity(id="e3", user_id="default-user", entity_type="concept", canonical_name="重排", normalized_key="c", status="active")
        db.add_all([e1, e2, e3]); db.flush()
        # e1,e2 both mentioned by chunk c1 -> co-occurrence edge e1-e2
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="混合检索", normalized_key="a", confidence=1.0))
        db.add(EntityMention(id="m2", entity_id="e2", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="RRF融合", normalized_key="b", confidence=1.0))
        # explicit relation e2-e3
        db.add(EntityRelation(id="r1", subject_entity_id="e2", predicate="uses", object_entity_id="e3", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        exported = export_graph_for_graphify(db, user_id="default-user")
        ids = {n["id"] for n in exported["nodes"]}
        assert ids == {"e1", "e2", "e3"}
        # co-occurrence edge e1-e2 + relation edge e2-e3 = at least 2 edges
        pairs = {(e["source"], e["target"]) for e in exported["edges"]}
        assert (("e1", "e2") in pairs or ("e2", "e1") in pairs)
        assert (("e2", "e3") in pairs or ("e3", "e2") in pairs)
    finally:
        db.close()
```

- [ ] **Step 3: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: FAIL（`ImportError: engine.app.graph.analyzer`）

- [ ] **Step 4: 实现 `engine/app/graph/analyzer.py`（先 export）**

```python
"""graphify analysis layer: export the Entity graph, run community/god/surprising,
write community_id / is_god / cohesion / surprising edges back to Neo4j.

The Neo4j/MySQL graph store is the single source of truth; the NetworkX graph
built here is temporary (built from MySQL, discarded after analysis).
"""
import logging
from collections import defaultdict
from itertools import combinations

from backend.app.models import EntityMention, EntityRelation, KnowledgeEntity

logger = logging.getLogger("uvicorn.error")


def export_graph_for_graphify(db, user_id: str = "default-user") -> dict:
    """Export entities + entity-entity edges as a graphify {nodes, edges} dict.

    Edges come from two sources:
      1. explicit EntityRelation rows (predicate -> relation)
      2. co-occurrence: two entities mentioned by the same Source (chunk) -> edge
    Co-occurrence projects the Source-Entity bipartite graph onto an
    Entity-Entity homogeneous graph, which is what community detection needs.
    """
    entities = (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.status != "deprecated")
        .all()
    )
    nodes = [
        {
            "id": e.id,
            "label": e.canonical_name or e.id,
            "file_type": "concept",
            "source_file": f"entity:{e.id}",
            "source_location": None,
        }
        for e in entities
    ]
    active_ids = {e.id for e in entities}

    edges = []
    seen = set()

    def _add_edge(src, tgt, relation, confidence, score):
        if src not in active_ids or tgt not in active_ids or src == tgt:
            return
        key = (src, tgt) if src < tgt else (tgt, src)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {
                "source": src,
                "target": tgt,
                "relation": relation,
                "confidence": confidence,
                "confidence_score": score,
                "source_file": f"entity:{src}",
                "source_location": None,
                "weight": 1.0,
            }
        )

    # 1) explicit relations
    for rel in db.query(EntityRelation).filter(EntityRelation.source_kind == "document_chunk").all():
        if rel.object_entity_id:
            _add_edge(rel.subject_entity_id, rel.object_entity_id, rel.predicate or "related_to", "INFERRED", float(rel.confidence or 0.75))

    # 2) co-occurrence: entities sharing a chunk source
    by_source = defaultdict(set)
    for m in db.query(EntityMention).filter(EntityMention.source_kind == "document_chunk").all():
        if m.entity_id in active_ids:
            by_source[m.source_id].add(m.entity_id)
    for members in by_source.values():
        members = list(members)
        if len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            _add_edge(a, b, "co_occurs_with", "INFERRED", 0.75)

    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 5: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd AIOne
git add engine/app/graph/__init__.py engine/app/graph/analyzer.py engine/tests/test_graph_analyzer.py
git commit -m "feat(graph): export Entity-Entity graph (relations + co-occurrence) for graphify

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7 (B3): graph_client 读旧社区 + 写分析结果

**Files:**
- Modify: `backend/app/services/graph_client.py`
- Test: `engine/tests/test_graph_analyzer.py`（追加，fake driver）

- [ ] **Step 1: 追加失败测试**

在 `engine/tests/test_graph_analyzer.py` 末尾追加（用一个 fake driver 测读写方法，不连真 Neo4j）：

```python
from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self):
        self.entities = {}   # id -> props
        self.written = []
    def execute_read(self, fn):
        return fn(self)
    def execute_write(self, fn):
        return fn(self)
    def run(self, query, **params):
        self.written.append((query, params))
        if query.strip().startswith("MATCH (e:Entity) WHERE e.community_id"):
            return MagicMock(data=lambda: [{"id": i, "cid": p["community_id"]} for i, p in self.entities.items() if p.get("community_id") is not None])
        return MagicMock()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_graph_client_read_write_analysis():
    sess = _FakeSession()
    driver = MagicMock(); driver.session.return_value = sess
    client = GraphClient(driver=driver, database="neo4j")

    # seed one entity with an old community
    sess.entities["e1"] = {"community_id": 7}
    old = client.read_entity_communities()
    assert old == {"e1": 7}

    client.set_entity_analysis("e2", community_id=7, is_god=True, cohesion=0.42)
    # a write happened
    assert any("SET" in q for q, _ in sess.written)
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py::test_graph_client_read_write_analysis -v`
Expected: FAIL（`read_entity_communities`/`set_entity_analysis` 不存在）

- [ ] **Step 3: `graph_client.py` 加两个方法 + `_execute_read`**

在 `GraphClient` 中加：

```python
    def _execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        with self.driver.session(database=self.database) as session:
            return session.execute_read(lambda tx: tx.run(query, **(params or {})).data())

    def read_entity_communities(self) -> dict[str, int]:
        """Return {entity_id: community_id} for entities that already have one."""
        rows = self._execute_read(
            "MATCH (e:Entity) WHERE e.community_id IS NOT NULL "
            "RETURN e.id AS id, e.community_id AS cid"
        )
        return {r["id"]: r["cid"] for r in rows if r.get("id") is not None}

    def set_entity_analysis(self, entity_id: str, community_id: int, is_god: bool, cohesion: float) -> None:
        query = """
        MATCH (e:Entity {id: $entity_id})
        SET e.community_id = $community_id,
            e.is_god = $is_god,
            e.cohesion = $cohesion
        """
        self._execute_write(
            query,
            {
                "entity_id": entity_id,
                "community_id": community_id,
                "is_god": is_god,
                "cohesion": cohesion,
            },
        )
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add backend/app/services/graph_client.py engine/tests/test_graph_analyzer.py
git commit -m "feat(graph): GraphClient read old communities + write analysis (community_id/is_god/cohesion)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8 (B4): analyzer.run_analysis（cluster + 稳定重映射 + god + surprising + 写回）

**Files:**
- Modify: `engine/app/graph/analyzer.py`
- Test: `engine/tests/test_graph_analyzer.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `engine/tests/test_graph_analyzer.py` 末尾追加：

```python
from engine.app.graph.analyzer import run_analysis, _remap_communities


def test_remap_keeps_stable_ids_for_unchanged_community():
    # old: {e1,e2,e3}->cid 5
    old = {"e1": 5, "e2": 5, "e3": 5}
    new = {0: ["e1", "e2", "e3", "e4"]}   # same community, one new node
    final = _remap_communities(new, old)
    assert final["e1"] == 5 and final["e2"] == 5 and final["e3"] == 5   # stable
    assert final["e4"] == 5                                               # joined same community


def test_remap_assigns_new_id_to_brand_new_community():
    old = {"e1": 5}
    new = {0: ["e1"], 1: ["e2", "e3"]}   # e2,e3 brand new, no overlap with old
    final = _remap_communities(new, old)
    assert final["e1"] == 5
    assert final["e2"] == final["e3"]                                    # same new community
    assert final["e2"] != 5                                              # a new id


class _AnalysisFakeGraph:
    """Records analysis writes; supports the methods run_analysis calls."""
    def __init__(self): self.old = {}; self.set_calls = []; self.relations = []
    def read_entity_communities(self): return dict(self.old)
    def set_entity_analysis(self, eid, community_id, is_god, cohesion):
        self.set_calls.append((eid, community_id, is_god, cohesion))
    def relate(self, sl, si, rt, el, ei, props=None):
        if sl == "Entity" and el == "Entity":
            self.relations.append((si, ei, props))


def test_run_analysis_writes_community_and_does_not_crash_on_small_graph():
    db = _db()
    try:
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=1):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name, status="active"))
        db.flush()
        # a couple relations to give the graph structure
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.add(EntityRelation(id="r2", subject_entity_id="e1", predicate="uses", object_entity_id="e3", relation_key="k2", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()
        fake = _AnalysisFakeGraph()
        result = run_analysis(db, fake, user_id="default-user")
        # every entity got a community_id written
        written_ids = {c[0] for c in fake.set_calls}
        assert written_ids == {f"e{i}" for i in range(1, 6)}
        assert result["node_count"] == 5
    finally:
        db.close()
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: FAIL（`run_analysis`/`_remap_communities` 未定义）

- [ ] **Step 3: 在 `analyzer.py` 追加实现**

```python
def _remap_communities(new_comms: dict[int, list[str]], old: dict[str, int]) -> dict[str, int]:
    """Map new community ids back to stable old ids by max Jaccard overlap.

    new_comms: {new_cid: [node_ids]} from graphify.cluster
    old: {node_id: old_cid} read from Neo4j before recompute
    Returns {node_id: final_cid} where final_cid reuses old ids when possible.
    """
    old_by_cid: dict[int, set[str]] = defaultdict(set)
    for node_id, cid in old.items():
        old_by_cid[cid].add(node_id)

    used_old: set[int] = set()
    new_to_final: dict[int, int] = {}
    next_id = (max(old_by_cid.keys()) + 1) if old_by_cid else 0

    for new_cid, members in new_comms.items():
        member_set = set(members)
        best_old, best_score = None, 0.0
        for old_cid, old_set in old_by_cid.items():
            if old_cid in used_old or not old_set:
                continue
            union = member_set | old_set
            score = len(member_set & old_set) / len(union) if union else 0.0
            if score > best_score:
                best_score, best_old = score, old_cid
        if best_old is not None and best_score > 0:
            new_to_final[new_cid] = best_old
            used_old.add(best_old)
        else:
            new_to_final[new_cid] = next_id
            next_id += 1

    return {node_id: new_to_final[cid] for cid, members in new_comms.items() for node_id in members}


def run_analysis(db, graph, user_id: str = "default-user", top_god: int = 20, top_surprising: int = 20) -> dict:
    """Run graphify analysis over the full entity graph and write results to Neo4j.

    Never raises (caller wraps in try/except, but we guard anyway).
    """
    try:
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import surprising_connections
        from graphify.diagnostics import diagnose_extraction
    except Exception as exc:
        logger.warning("[analyzer] graphify_import_failed error=%s", exc)
        return {"node_count": 0, "skipped": True}

    exported = export_graph_for_graphify(db, user_id=user_id)
    node_count = len(exported["nodes"])
    if node_count == 0:
        return {"node_count": 0, "skipped": True}

    try:
        G = build_from_json(exported, directed=False)
        communities = cluster(G)                       # {cid: [members]}
        cohesion_by_cid = score_all(G, communities)    # {cid: float}
        old = graph.read_entity_communities() if hasattr(graph, "read_entity_communities") else {}
        final = _remap_communities(communities, old)   # {node_id: final_cid}

        # god nodes = top by degree (graphify.god_nodes filters out concept nodes,
        # so compute hubs directly)
        ranked = sorted(G.degree, key=lambda x: x[1], reverse=True)
        god_ids = {nid for nid, _ in ranked[:top_god]}

        # surprising connections
        surprising = []
        try:
            surprising = surprising_connections(G, communities, top_n=top_surprising)
        except Exception as exc:
            logger.warning("[analyzer] surprising_failed error=%s", exc)

        # write back per node
        for node_id, cid in final.items():
            graph.set_entity_analysis(
                node_id,
                community_id=int(cid),
                is_god=node_id in god_ids,
                cohesion=float(cohesion_by_cid.get(_new_cid_for_node(communities, node_id), 0.0)),
            )

        # write surprising edges
        for s in surprising:
            try:
                graph.relate(
                    "Entity", s.get("source"), "RELATED_TO", "Entity", s.get("target"),
                    {"surprising": True, "note": s.get("note", "")},
                )
            except Exception as exc:
                logger.warning("[analyzer] surprising_edge_write_failed %s", exc)

        # diagnostics: log only, never block
        try:
            diag = diagnose_extraction(exported, directed=False)
            dangling = diag.get("dangling_endpoint_edges", 0)
            if dangling:
                logger.warning("[analyzer] diagnostics dangling_endpoint_edges=%s", dangling)
        except Exception:
            pass

        return {"node_count": node_count, "communities": len(communities),
                "god_nodes": len(god_ids), "surprising": len(surprising)}
    except Exception as exc:
        logger.warning("[analyzer] run_analysis_failed error=%s", exc)
        return {"node_count": node_count, "skipped": True, "error": str(exc)}


def _new_cid_for_node(communities: dict[int, list[str]], node_id: str) -> int:
    for cid, members in communities.items():
        if node_id in members:
            return cid
    return -1
```

- [ ] **Step 4: 运行，确认通过**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_graph_analyzer.py -v`
Expected: PASS（含稳定重映射 + run_analysis 写回）

- [ ] **Step 5: Commit**

```bash
cd AIOne
git add engine/app/graph/analyzer.py engine/tests/test_graph_analyzer.py
git commit -m "feat(graph): run_analysis (cluster + stable remap + degree-god + surprising + diagnostics)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9 (B5): 接入 pipeline（失败隔离）

**Files:**
- Modify: `engine/app/ingestion/pipeline.py`
- Modify: `engine/tests/test_pipeline_stage_a.py`（追加）

- [ ] **Step 1: 追加失败测试**

在 `engine/tests/test_pipeline_stage_a.py` 末尾追加（在已有的 ingest 测试基础上，断言 run_analysis 被调用、且其异常不阻断入库）：

```python
def test_pipeline_invokes_graph_analysis_after_stage_a(monkeypatch):
    import engine.app.ingestion.pipeline as pl
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem
    from sqlalchemy.orm import sessionmaker
    from backend.app.services.entity_extraction import EntityCandidate
    Base.metadata.create_all(_engine)

    # stub external services (same pattern as the existing test in this file)
    monkeypatch.setattr(pl, "embed_texts", lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr(pl, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pl, "delete_vectors_by_ids", lambda ids: None)
    monkeypatch.setattr(pl, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pl, "_bulk_index_chunks_es", lambda **kw: 0)
    monkeypatch.setattr(pl, "extract_stage_a_parallel",
                        lambda chunks, **kw: {cid: [EntityCandidate(kind="entity", entity_type="concept", surface_text="x", normalized_key="x", confidence=1.0)] for cid, _ in chunks})
    monkeypatch.setattr(pl, "project_item_entities", lambda *a, **kw: 0)

    calls = {"n": 0}
    def _fake_run_analysis(db, graph, user_id, **kw):
        calls["n"] += 1
        return {"node_count": 0}
    monkeypatch.setattr(pl, "run_analysis", _fake_run_analysis)

    db = sessionmaker(bind=_engine)()
    db.query(KnowledgeItem).delete()
    db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc", content="一段足够长的概念性文本内容用于产生至少一个子分块 " * 4))
    db.commit(); db.close()

    pl.ingest_item("i1")
    assert calls["n"] == 1   # run_analysis was called once after Stage A


def test_pipeline_graph_analysis_failure_does_not_break_ingestion(monkeypatch):
    import engine.app.ingestion.pipeline as pl
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem, EntityMention
    from sqlalchemy.orm import sessionmaker
    from backend.app.services.entity_extraction import EntityCandidate
    Base.metadata.create_all(_engine)

    monkeypatch.setattr(pl, "embed_texts", lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr(pl, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pl, "delete_vectors_by_ids", lambda ids: None)
    monkeypatch.setattr(pl, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pl, "_bulk_index_chunks_es", lambda **kw: 0)
    monkeypatch.setattr(pl, "extract_stage_a_parallel",
                        lambda chunks, **kw: {cid: [EntityCandidate(kind="entity", entity_type="concept", surface_text="x", normalized_key="x", confidence=1.0)] for cid, _ in chunks})
    monkeypatch.setattr(pl, "project_item_entities", lambda *a, **kw: 0)
    def _boom(*a, **kw):
        raise RuntimeError("graphify boom")
    monkeypatch.setattr(pl, "run_analysis", _boom)

    db = sessionmaker(bind=_engine)()
    db.query(KnowledgeItem).delete()
    db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc", content="一段足够长的概念性文本内容用于产生至少一个子分块 " * 4))
    db.commit(); db.close()

    count = pl.ingest_item("i1")   # must NOT raise
    assert count >= 1
```

> 上述测试假设 `ingest_item` 内通过 `pl.run_analysis(...)` 调用（即 run_analysis 在 pipeline 模块命名空间被导入）。Step 3 会把它 import 进来。

- [ ] **Step 2: 运行，确认失败**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_pipeline_stage_a.py -k "graph_analysis" -v`
Expected: FAIL（`pl.run_analysis` 不存在 / 未被调用）

- [ ] **Step 3: 修改 `pipeline.py`**

3a. 顶部 import 区加：

```python
from ..graph.analyzer import run_analysis
```

3b. 在 `_project_item_entities_to_graph` 之后新增一个组合函数（保证投影+分析都在失败隔离内）：

```python
def _project_and_analyze(db, item_id: str, user_id: str) -> None:
    """Project this item's entities to Neo4j, then run full-graph graphify analysis.

    Both steps are best-effort: failures are logged and never break ingestion.
    """
    _project_item_entities_to_graph(db, item_id, user_id)
    if not settings.GRAPH_ANALYSIS_ENABLED:
        return
    try:
        client = GraphClient()
        try:
            run_analysis(db, client, user_id=user_id)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("[ingest.pipeline] graph_analysis_failed item_id=%s error=%s", item_id, exc)
```

3c. 在 `_run_stage_a_for_item` 中，把原来调用 `_project_item_entities_to_graph(db, item_id, user_id)` 的那一行，改为调用 `_project_and_analyze(db, item_id, user_id)`。

- [ ] **Step 4: 运行，确认通过 + pipeline 套件无回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_pipeline_stage_a.py -v`
Expected: PASS（含两个新测试 + 既有）

- [ ] **Step 5: 全量新测试回归**

Run: `cd AIOne && DATABASE_URL=sqlite:///./_t.db python -m pytest engine/tests/test_stage_a.py engine/tests/test_pipeline_stage_a.py engine/tests/test_graph_analyzer.py backend/tests/test_entity_settle.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
cd AIOne
git add engine/app/ingestion/pipeline.py engine/tests/test_pipeline_stage_a.py
git commit -m "feat(ingest): run graphify analysis after Stage A projection (failure-isolated)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10 (B6): 端到端验证（手动，真实服务）

**Files:** 无代码改动。参考 `docs/superpowers/plans/2026-07-03-p1-task8-verification-runbook.md` 的服务启动方式。

- [ ] **Step 1: 装依赖 + 起服务**

```bash
cd AIOne
pip install graphifyy
docker compose up -d
SKIP_ENGINE=1 python -m backend.run &
python -m engine.run &
```

- [ ] **Step 2: 上传一份概念密集文档**

```bash
RESP=$(curl -s -X POST http://localhost:5175/api/v1/upload/file -F "file=@/tmp/stage_a_probe.md")
ITEM_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
sleep 30   # 等 Stage A + 全图分析
```

- [ ] **Step 3: 验证 Step A（实体间 RELATED_TO 边）**

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity)
   WHERE r.extraction_method IS NOT NULL OR r.predicate IS NOT NULL
   RETURN a.canonical_name, type(r), b.canonical_name LIMIT 25;"
```
Expected: 出现 concept↔method 等 `RELATED_TO` 边（A2 成功）。

- [ ] **Step 4: 验证 Step B（社区 / god / cohesion）**

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity)
   RETURN e.community_id AS cid, e.is_god AS god, e.cohesion AS coh, count(*) AS n
   ORDER BY cid;"
```
Expected: 实体按 `community_id` 分组；部分 `is_god=true`；`cohesion` 有值。

- [ ] **Step 5: 验证稳定性（再入库 community_id 不漂）**

```bash
curl -s -X POST http://localhost:5180/api/v1/ingest -H 'Content-Type: application/json' -d "{\"item_id\": \"$ITEM_ID\"}"
sleep 30
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity) WHERE e.community_id IS NOT NULL
   RETURN e.canonical_name, e.community_id ORDER BY e.canonical_name LIMIT 20;"
```
Expected: 同名实体的 `community_id` 与首次基本一致（稳定重映射生效）。

- [ ] **Step 6: 验证 surprising 边**

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) WHERE r.surprising=true
   RETURN a.canonical_name, b.canonical_name, r.note LIMIT 10;"
```
Expected: 若有跨社区桥接，出现 `surprising=true` 边（图很小时可能为空，正常）。

- [ ] **Step 7: 全部通过 → Step A + B 验收完成**

```bash
git log --oneline -12   # 确认 9 个提交都在
```

---

## Self-Review（计划完成后自查）

**1. Spec 覆盖：**
- A1（Neo4j 重入库清理）→ Task 2。✓
- A2（接回 relations：prompt/parser/候选 → 泛化 resolver → 投影 RELATED_TO）→ Task 3 + Task 4。✓
- A3（confidence 默认 0.0）→ Task 1。✓
- B1（依赖 + 配置）→ Task 5。✓
- B2（export 含共现边）→ Task 6。✓
- B3（graph_client 读旧社区 + 写分析）→ Task 7。✓
- B4（run_analysis：build/cluster/稳定重映射/度数god/surprising/diagnostics/写回）→ Task 8。✓
- B5（接入 pipeline + 失败隔离）→ Task 9。✓
- B6（手动 e2e）→ Task 10。✓
- 失败隔离 / `GRAPH_ANALYSIS_ENABLED` / 不并存第二存储 / 稳定 community_id：均在 Task 8/9 覆盖。✓

**2. 占位符扫描：** Task 4 Step 7 有一处"占位行删除"提示，已紧跟给出正式代码（`chunk_ids` 收集 + relations 投影）。无其它 TBD/TODO。

**3. 类型一致性：**
- `export_graph_for_graphify(db, user_id) -> dict{nodes,edges}`：Task 6 定义，Task 8 调用一致。
- `run_analysis(db, graph, user_id, top_god=20, top_surprising=20) -> dict`：Task 8 定义，Task 9 调用一致。
- `_remap_communities(new_comms, old) -> {node_id: cid}`：Task 8 定义并在内部使用，签名一致。
- `GraphClient.read_entity_communities() -> {id: cid}`、`set_entity_analysis(eid, community_id, is_god, cohesion)`、`delete_item_sources(item_id)`：Task 2/7 定义，Task 8/9 调用一致。
- `parse_stage_a_relations(raw) -> list[dict]`、`_to_relation_candidate`：Task 3 定义，签名一致。
- graphify 实测签名（cluster→{cid:[members]}、score_all→{cid:float}、surprising→[{source,target,...}]）与 Task 8 用法一致；god_nodes 因过滤 concept 改用 nx.degree。✓

**4. 已知执行机注意：**
- 必须 `pip install graphifyy`（Task 5）。
- pytest 必须带 `DATABASE_URL`。
- Task 4/6/8 的种子需按真实模型 NOT NULL 列补齐（报错会列出）。
- graphify 在小图上 cluster 可能只产 1 个社区、surprising 可能为空——测试已用足够节点/边构造。
