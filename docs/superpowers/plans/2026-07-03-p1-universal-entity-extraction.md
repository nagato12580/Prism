# P1 全覆盖实体抽取（Stage A）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每一条入库的文档 chunk 都经过 LLM 式实体抽取（Stage A），把概念/术语/方法/人/机构/产品等实体写入 MySQL 并投影到 Neo4j，保证「万物进图、皆可遍历」——即使抽不出 PKU/CKP，内容也已挂在图上。

**Architecture:** Stage A 是一个独立的 LLM 抽取器，对每个 chunk 调一次 LLM（graphify 式抽取规范：三档置信度 EXTRACTED/INFERRED/AMBIGUOUS、JSON 输出），产出 `EntityCandidate`。多个 chunk 用 `ThreadPoolExecutor` 并行抽取（即「派子代理」；LangGraph 未安装，沿用 `runner.py` 的线程池模式，P2 可换 LangGraph）。候选写入复用现有 `entity_extraction.settle` 路径（MySQL `KnowledgeEntity/EntityMention/EntityRelation`），再由新增的 `project_item_entities` 增量投影到 Neo4j（`Source`↔`MENTIONED_IN`↔`Entity`）。graphify 引擎（cluster/god/diagnostics）留到 P2。

**Tech Stack:** Python 3.12 · SQLAlchemy（MySQL，测试用 sqlite）· OpenAI 兼容 LLM（DeepSeek/Qwen，`engine.app.llm.client.chat`）· Neo4j（`backend.app.services.graph_client.GraphClient`）· pytest。

**Spec:** `docs/superpowers/specs/2026-07-03-universal-graph-index-design.md`（本计划实现其中的 P1，对应 §4 抽取管线 Stage A + §3 节点/边全覆盖连接 + §8 代码改造点）。

---

## 文件结构

- Create: `engine/app/extraction/__init__.py`（空，包标记）
- Create: `engine/app/extraction/prompts.py`（Stage A 抽取 prompt + JSON 解析）
- Create: `engine/app/extraction/stage_a.py`（单 chunk 抽取 + 并行 fan-out）
- Create: `engine/tests/test_stage_a.py`（抽取与解析测试）
- Create: `engine/tests/test_pipeline_stage_a.py`（pipeline 集成测试）
- Create: `backend/tests/test_entity_settle.py`（settle 重构测试）
- Modify: `backend/app/services/entity_extraction.py`（抽出 `settle_entity_candidates` 共享写路径）
- Modify: `backend/app/services/graph_projection.py`（新增 `project_item_entities` 增量投影）
- Modify: `engine/app/ingestion/pipeline.py`（接入 Stage A）
- Modify: `engine/app/config.py`（新增 Stage A 配置）

---

## Task 1: 新增 Stage A 配置项

**Files:**
- Modify: `engine/app/config.py`

- [ ] **Step 1: 在 `engine/app/config.py` 的 `Settings` 类中追加配置（紧挨现有 `LLM_MODEL` 之后）**

```python
    ENTITY_EXTRACT_MODEL: str = os.getenv("ENTITY_EXTRACT_MODEL", "")
    ENTITY_EXTRACT_WORKERS: int = int(os.getenv("ENTITY_EXTRACT_WORKERS", "4"))
    ENTITY_EXTRACT_TIMEOUT_SECONDS: float = float(os.getenv("ENTITY_EXTRACT_TIMEOUT_SECONDS", "30"))
    ENTITY_EXTRACT_ENABLED: bool = os.getenv("ENTITY_EXTRACT_ENABLED", "1") not in ("0", "false", "False")
```

> `ENTITY_EXTRACT_MODEL` 默认空串表示复用 `LLM_MODEL`；可指向更便宜的模型（如 `qwen2.5:3b`）以控成本（spec §4 成本控制）。

- [ ] **Step 2: 验证可导入**

Run: `cd AIOne && python -c "from engine.app.config import settings; print(settings.ENTITY_EXTRACT_WORKERS, settings.ENTITY_EXTRACT_ENABLED)"`
Expected: `4 True`

- [ ] **Step 3: Commit**

```bash
git add engine/app/config.py
git commit -m "feat(extraction): add Stage A entity extraction config"
```

---

## Task 2: 重构出共享的 `settle_entity_candidates` 写路径

**Files:**
- Modify: `backend/app/services/entity_extraction.py:93-133`
- Test: `backend/tests/test_entity_settle.py`

- [ ] **Step 1: 写失败测试 `backend/tests/test_entity_settle.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_entity_settle_test.db"

from backend.app.database import Base, SessionLocal  # noqa: E402
from backend.app.models import EntityMention, KnowledgeEntity  # noqa: E402
from backend.app.services.entity_extraction import (  # noqa: E402
    EntityCandidate,
    settle_entity_candidates,
)
from backend.app.utils import auto_migrate  # noqa: E402


def _db():
    engine = SessionLocal.kw["bind"] if False else None  # placeholder removed below
    # use the shared engine
    from backend.app.database import engine as _engine
    Base.metadata.create_all(_engine)
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=_engine)
    return Session()


def test_settle_entity_candidates_writes_entity_and_mention():
    db = _db()
    try:
        candidates = [
            EntityCandidate(
                kind="entity",
                entity_type="concept",
                surface_text="混合检索",
                normalized_key="混合检索",
                aliases=["混合检索"],
                confidence=0.85,
                evidence_span="应结合 metadata filter",
                extraction_method="llm_stage_a:INFERRED",
            )
        ]
        settled = settle_entity_candidates(
            db,
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            chunk_id="chunk-1",
            candidates=candidates,
            user_id="default-user",
        )
        db.commit()
        assert len(settled) == 1
        ent = db.query(KnowledgeEntity).filter_by(entity_type="concept").one()
        assert ent.canonical_name == "混合检索"
        mention = db.query(EntityMention).filter_by(entity_id=ent.id, source_id="chunk-1").one()
        assert mention.extraction_method == "llm_stage_a:INFERRED"
    finally:
        db.close()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd AIOne/backend && python -m pytest tests/test_entity_settle.py -v`
Expected: FAIL（`ImportError: cannot import name 'settle_entity_candidates'`）

- [ ] **Step 3: 重构 `backend/app/services/entity_extraction.py`——把 settle 逻辑抽成独立函数**

把现有 `extract_and_settle_entities`（第 93–133 行）改为先抽候选、再委托给新的 `settle_entity_candidates`。替换整个 `extract_and_settle_entities` 函数，并在其上方新增 `settle_entity_candidates`：

```python
def settle_entity_candidates(
    db,
    candidates: list[EntityCandidate],
    source_kind: str,
    source_id: str,
    item_id: str = "",
    chunk_id: str = "",
    user_id: str = "default-user",
) -> list[KnowledgeEntity]:
    """Persist pre-extracted EntityCandidates (rule-based or LLM) to MySQL."""
    settled_by_surface: dict[tuple[str, str], KnowledgeEntity] = {}
    settled_entities: list[KnowledgeEntity] = []

    for candidate in candidates:
        if candidate.kind != "entity":
            continue
        entity = _upsert_entity(db, candidate, user_id)
        _upsert_aliases(db, entity, candidate)
        _upsert_mention(db, entity, candidate, source_kind, source_id, item_id, chunk_id)
        settled_by_surface[(candidate.entity_type, candidate.surface_text)] = entity
        settled_entities.append(entity)

    db.flush()

    for candidate in candidates:
        if candidate.kind != "relation":
            continue
        subject = _resolve_entity_for_relation(db, settled_by_surface, user_id, "person", candidate.subject_surface)
        object_entity = _resolve_entity_for_relation(
            db, settled_by_surface, user_id, candidate.object_entity_type, candidate.object_surface
        )
        if subject and object_entity:
            _upsert_relation(db, subject, object_entity, candidate, source_kind, source_id)

    db.flush()
    return settled_entities


def extract_and_settle_entities(
    db,
    source_kind: str,
    source_id: str,
    text: str,
    item_id: str = "",
    chunk_id: str = "",
    user_id: str = "default-user",
) -> list[KnowledgeEntity]:
    candidates = extract_entity_candidates_from_text(text, source_kind=source_kind)
    return settle_entity_candidates(
        db, candidates, source_kind=source_id and source_kind or source_kind,
        source_id=source_id, item_id=item_id, chunk_id=chunk_id, user_id=user_id,
    )
```

> 注意：保持 `extract_and_settle_entities` 对外签名不变（避免破坏现有调用方）。上面 `source_kind=...` 那行写成 `source_kind=source_kind` 即可，修正为：

```python
def extract_and_settle_entities(
    db,
    source_kind: str,
    source_id: str,
    text: str,
    item_id: str = "",
    chunk_id: str = "",
    user_id: str = "default-user",
) -> list[KnowledgeEntity]:
    candidates = extract_entity_candidates_from_text(text, source_kind=source_kind)
    return settle_entity_candidates(db, candidates, source_kind, source_id, item_id, chunk_id, user_id)
```

（以上修正版为准。）

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd AIOne/backend && python -m pytest tests/test_entity_settle.py -v`
Expected: PASS

- [ ] **Step 5: 跑现有 backend 测试，确认没破坏既有调用**

Run: `cd AIOne/backend && python -m pytest -k entity -v`
Expected: 现有 entity 相关测试仍 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/entity_extraction.py backend/tests/test_entity_settle.py
git commit -m "refactor(entity): extract settle_entity_candidates shared write path"
```

---

## Task 3: Stage A 抽取 prompt + 健壮 JSON 解析

**Files:**
- Create: `engine/app/extraction/__init__.py`
- Create: `engine/app/extraction/prompts.py`
- Test: `engine/tests/test_stage_a.py`（解析部分）

- [ ] **Step 1: 建空包标记**

创建 `engine/app/extraction/__init__.py`，内容为空。

- [ ] **Step 2: 写失败测试 `engine/tests/test_stage_a.py`（先只测解析）**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_stage_a_test.db"

from engine.app.extraction.prompts import parse_stage_a_json, STAGE_A_EXTRACTION_PROMPT


def test_parse_stage_a_json_clean_array():
    raw = '[{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"..."}]'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["entity_type"] == "concept"
    assert result[0]["surface"] == "混合检索"
    assert result[0]["score"] == 0.85


def test_parse_stage_a_json_strips_fences_and_prose():
    raw = '好的，结果如下：\n```json\n[{"entity_type":"person","surface":"张三","tier":"EXTRACTED","score":1.0,"evidence":""}]\n```\n以上。'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["surface"] == "张三"


def test_parse_stage_a_json_empty_returns_empty():
    assert parse_stage_a_json("") == []
    assert parse_stage_a_json("no json here") == []


def test_parse_stage_a_json_rejects_score_out_of_range():
    raw = '[{"entity_type":"concept","surface":"x","tier":"EXTRACTED","score":0.5,"evidence":""}]'
    result = parse_stage_a_json(raw)
    # EXTRACTED must be 1.0; invalid tier/score combos are dropped
    assert result == []


def test_prompt_contains_required_fields():
    for token in ["entity_type", "surface", "tier", "score", "evidence", "EXTRACTED", "INFERRED", "AMBIGUOUS"]:
        assert token in STAGE_A_EXTRACTION_PROMPT
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -v -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: engine.app.extraction.prompts`）

- [ ] **Step 4: 实现 `engine/app/extraction/prompts.py`**

```python
"""Stage A entity extraction prompt and JSON parsing.

graphify-style discipline: three confidence tiers (EXTRACTED/INFERRED/AMBIGUOUS),
discrete score set (EXTRACTED=1.0; INFERRED in {0.95,0.85,0.75,0.65,0.55}; AMBIGUOUS in [0.1,0.3]).
Score 0.5 is forbidden.
"""
import json
import re

STAGE_A_EXTRACTION_PROMPT = """你是知识图谱实体抽取器。从下面的文本片段中抽取「实体」和「实体间关系」。

抽取范围（尽量全）：概念、术语、方法、产品、技术、人物、机构、地点、法规、数据集、工具等。
不要只抽人名/机构——这是通用知识库，概念和术语同样重要。

每个实体输出一个对象，字段：
- entity_type: 实体类型（concept/term/method/product/technology/person/organization/place/regulation/dataset/tool/other）
- surface: 实体在原文中的表面文本（原样，不要改写）
- tier: 置信档，三选一：EXTRACTED（原文直接出现）/ INFERRED（推断）/ AMBIGUOUS（不确定）
- score: 置信分数。EXTRACTED 必须 1.0；INFERRED 取 0.95/0.85/0.75/0.65/0.55 之一；AMBIGUOUS 取 0.1~0.3。禁止 0.5。
- evidence: 原文中支持该实体的短语（原文摘录，<=80字）

可选：若两个实体有明显关系，输出 relations 数组：{subject, predicate, object, tier, score}，predicate 用 related_to/uses/part_of/defines/supports/contradicts/alternative_to 等。

只输出一个 JSON 对象，形如：
{"entities": [{"entity_type":"...","surface":"...","tier":"...","score":1.0,"evidence":"..."}], "relations": []}
不要输出 JSON 以外的任何文字。

文本片段：
{chunk_text}
"""

_VALID_SCORES_INFERRED = {0.95, 0.85, 0.75, 0.65, 0.55}


def _extract_json_object(raw: str) -> str | None:
    """Find the first {...} or [...] JSON block, tolerating ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.S)
    if fenced:
        return fenced.group(1)
    match = re.search(r"\{.*\}|\[.*\]", raw, re.S)
    return match.group(0) if match else None


def _valid_entity(item: dict) -> bool:
    tier = item.get("tier")
    score = item.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return False
    if tier == "EXTRACTED":
        return abs(score - 1.0) < 1e-6
    if tier == "INFERRED":
        return any(abs(score - s) < 1e-6 for s in _VALID_SCORES_INFERRED)
    if tier == "AMBIGUOUS":
        return 0.1 <= score <= 0.3
    return False


def parse_stage_a_json(raw: str) -> list[dict]:
    """Parse model output into a validated list of entity dicts.

    Accepts either {"entities":[...]} or a bare [...]. Drops invalid tier/score.
    Returns normalized dicts with keys: entity_type, surface, tier, score, evidence.
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
    entities = data["entities"] if isinstance(data, dict) else data
    if not isinstance(entities, list):
        return []
    result = []
    for item in entities:
        if not isinstance(item, dict) or not _valid_entity(item):
            continue
        surface = (item.get("surface") or item.get("surface_text") or "").strip()
        if not surface:
            continue
        result.append(
            {
                "entity_type": (item.get("entity_type") or "other").strip() or "other",
                "surface": surface,
                "tier": item["tier"],
                "score": float(item["score"]),
                "evidence": (item.get("evidence") or "").strip(),
            }
        )
    return result
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -v`
Expected: PASS（5 个测试）

- [ ] **Step 6: Commit**

```bash
git add engine/app/extraction/__init__.py engine/app/extraction/prompts.py engine/tests/test_stage_a.py
git commit -m "feat(extraction): Stage A prompt and robust JSON parser with tier discipline"
```

---

## Task 4: 单 chunk 抽取 —— LLM 调用 + 转 EntityCandidate

**Files:**
- Create: `engine/app/extraction/stage_a.py`
- Test: `engine/tests/test_stage_a.py`（追加）

- [ ] **Step 1: 追加失败测试到 `engine/tests/test_stage_a.py`**

```python
from unittest.mock import patch

from backend.app.services.entity_extraction import EntityCandidate
from engine.app.extraction.stage_a import extract_entities_for_chunk


_FAKE_LLM_OUTPUT = (
    '{"entities": ['
    '{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"结合向量与关键词"},'
    '{"entity_type":"method","surface":"RRF融合","tier":"EXTRACTED","score":1.0,"evidence":"RRF"}'
    ']}'
)


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_returns_candidates(mock_chat):
    mock_chat.return_value = _FAKE_LLM_OUTPUT
    candidates = extract_entities_for_chunk("some chunk text", chunk_id="c1")
    assert len(candidates) == 2
    assert all(c.kind == "entity" for c in candidates)
    types = {c.entity_type for c in candidates}
    assert types == {"concept", "method"}
    concept = next(c for c in candidates if c.entity_type == "concept")
    assert concept.surface_text == "混合检索"
    assert concept.confidence == 0.85
    assert concept.extraction_method.startswith("llm_stage_a:INFERRED")


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_llm_failure_returns_empty(mock_chat):
    mock_chat.side_effect = RuntimeError("llm down")
    assert extract_entities_for_chunk("text", chunk_id="c1") == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -k extract_entities_for_chunk -v`
Expected: FAIL（`ImportError: engine.app.extraction.stage_a`）

- [ ] **Step 3: 实现 `engine/app/extraction/stage_a.py`（先只写单 chunk 函数）**

```python
"""Stage A LLM entity extraction. One subagent = one chunk = one LLM call."""
import logging

from backend.app.services.entity_extraction import EntityCandidate
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key

from ..config import settings
from ..llm.client import chat
from .prompts import STAGE_A_EXTRACTION_PROMPT, parse_stage_a_json

logger = logging.getLogger("uvicorn.error")

_MAX_CHUNK_CHARS = 4000  # truncate very long chunks before sending to LLM


def extract_entities_for_chunk(chunk_text: str, chunk_id: str = "") -> list[EntityCandidate]:
    """Extract entity candidates for one chunk via LLM. Never raises."""
    text = (chunk_text or "").strip()[:_MAX_CHUNK_CHARS]
    if not text:
        return []
    prompt = STAGE_A_EXTRACTION_PROMPT.format(chunk_text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], model=_stage_a_model())
    except Exception as exc:
        logger.warning("[stage_a] llm_failed chunk_id=%s error=%s", chunk_id, exc)
        return []
    parsed = parse_stage_a_json(raw)
    return [_to_candidate(p, chunk_id) for p in parsed]


def _stage_a_model() -> str | None:
    return settings.ENTITY_EXTRACT_MODEL or None


def _to_candidate(item: dict, chunk_id: str) -> EntityCandidate:
    surface = item["surface"]
    entity_type = item["entity_type"]
    tier = item["tier"]
    score = item["score"]
    return EntityCandidate(
        kind="entity",
        entity_type=entity_type,
        surface_text=surface,
        normalized_key=normalize_entity_key(surface),
        aliases=alias_keys_for_surface(surface, entity_type=entity_type),
        confidence=score,
        evidence_span=item.get("evidence", "")[:500],
        extraction_method=f"llm_stage_a:{tier}",
    )
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -k extract_entities_for_chunk -v`
Expected: PASS（2 个测试）

- [ ] **Step 5: Commit**

```bash
git add engine/app/extraction/stage_a.py engine/tests/test_stage_a.py
git commit -m "feat(extraction): single-chunk Stage A LLM entity extractor"
```

---

## Task 5: 并行 fan-out（ThreadPoolExecutor「子代理」）

**Files:**
- Modify: `engine/app/extraction/stage_a.py`
- Test: `engine/tests/test_stage_a.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
from engine.app.extraction.stage_a import extract_stage_a_parallel


@patch("engine.app.extraction.stage_a.extract_entities_for_chunk")
def test_extract_stage_a_parallel_collects_all_chunks(mock_extract):
    mock_extract.side_effect = lambda text, chunk_id: [EntityCandidate(kind="entity", entity_type="concept", surface_text=chunk_id, confidence=1.0)]
    chunks = [(f"chunk-{i}", f"text {i}") for i in range(5)]
    result = extract_stage_a_parallel(chunks, max_workers=3)
    assert set(result.keys()) == {f"chunk-{i}" for i in range(5)}
    assert mock_extract.call_count == 5


@patch("engine.app.extraction.stage_a.extract_entities_for_chunk")
def test_extract_stage_a_parallel_isolates_chunk_failure(mock_extract):
    def fake(text, chunk_id):
        if chunk_id == "bad":
            raise RuntimeError("boom")
        return [EntityCandidate(kind="entity", entity_type="concept", surface_text=chunk_id, confidence=1.0)]
    mock_extract.side_effect = fake
    result = extract_stage_a_parallel([("bad", "x"), ("good", "y")], max_workers=2)
    assert result["good"] and result["good"][0].surface_text == "good"
    assert result.get("bad", []) == []  # failed chunk does not crash the batch
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -k parallel -v`
Expected: FAIL（`ImportError: cannot import name 'extract_stage_a_parallel'`）

- [ ] **Step 3: 在 `engine/app/extraction/stage_a.py` 追加 fan-out 函数**

在文件顶部 import 区追加：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

在文件末尾追加：

```python
def extract_stage_a_parallel(
    chunks: list[tuple[str, str]],
    max_workers: int | None = None,
) -> dict[str, list[EntityCandidate]]:
    """Fan out Stage A extraction across chunks in parallel.

    chunks: list of (chunk_id, chunk_text). Each chunk is one 'subagent' (one LLM call).
    Returns {chunk_id: [EntityCandidate, ...]}. A failed chunk yields an empty list
    and never aborts the batch.
    """
    workers = max_workers or settings.ENTITY_EXTRACT_WORKERS
    results: dict[str, list[EntityCandidate]] = {}
    if not chunks:
        return results
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks)), thread_name_prefix="stage-a") as pool:
        future_to_chunk = {pool.submit(extract_entities_for_chunk, text, cid): cid for cid, text in chunks}
        for future in as_completed(future_to_chunk):
            cid = future_to_chunk[future]
            try:
                results[cid] = future.result()
            except Exception as exc:
                logger.warning("[stage_a] chunk_failed chunk_id=%s error=%s", cid, exc)
                results[cid] = []
    return results
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -v`
Expected: PASS（全部 stage_a 测试）

- [ ] **Step 5: Commit**

```bash
git add engine/app/extraction/stage_a.py engine/tests/test_stage_a.py
git commit -m "feat(extraction): parallel Stage A fan-out via ThreadPoolExecutor"
```

---

## Task 6: 增量投影 helper —— `project_item_entities`（MySQL → Neo4j）

**Files:**
- Modify: `backend/app/services/graph_projection.py`
- Test: `engine/tests/test_stage_a.py`（追加，用 fake graph；放 engine 因依赖图较小）

> 说明：投影 helper 放在 `graph_projection.py` 与现有 `project_entity_graph` 同模块；测试用 fake `GraphClient`。

- [ ] **Step 1: 追加失败测试 `engine/tests/test_stage_a.py`**

```python
from backend.app.services.graph_projection import project_item_entities


class FakeGraph:
    def __init__(self):
        self.upserted_sources = []
        self.upserted_entities = []
        self.relations = []  # list of (start_label, start_id, rel, end_label, end_id)

    def upsert_source(self, data):
        self.upserted_sources.append(data)

    def upsert_entity(self, data):
        self.upserted_entities.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append((start_label, start_id, rel_type, end_label, end_id))


def test_project_item_entities_upserts_source_entity_and_mentioned_in():
    # build a sqlite db with one item, one chunk, one entity + mention on that chunk
    from backend.app.database import Base, engine as _engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.models import KnowledgeItem, KnowledgeChunk, KnowledgeEntity, EntityMention
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc", content="x"))
        db.add(KnowledgeChunk(id="c1", item_id="i1", chunk_text="x", chunk_index=0, chunk_type="child"))
        ent = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="x", status="active")
        db.add(ent)
        db.flush()
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="混合检索", normalized_key="x", confidence=0.85, extraction_method="llm_stage_a:INFERRED"))
        db.commit()

        fake = FakeGraph()
        project_item_entities(db, fake, item_id="i1", user_id="default-user")

        assert any(s["item_id"] == "i1" for s in fake.upserted_sources)
        assert any(e["id"] == "e1" for e in fake.upserted_entities)
        assert ("Entity", "e1", "MENTIONED_IN", "Source", "document_chunk:c1") in fake.relations
    finally:
        db.close()
```

> 注：`KnowledgeItem` 必填字段以实际模型为准。若测试因 NOT NULL 报错，按 `backend/app/models/knowledge_item.py` 补字段（运行报错会列出缺失列）。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -k project_item_entities -v`
Expected: FAIL（`ImportError: cannot import name 'project_item_entities'`）

- [ ] **Step 3: 在 `backend/app/services/graph_projection.py` 末尾追加**

```python
def project_item_entities(db, graph, item_id: str, user_id: str = "default-user") -> int:
    """Incrementally project one item's entities + mentions to Neo4j.

    Upserts the Source node per chunk, the Entity nodes, and MENTIONED_IN edges.
    Returns the number of edges projected. Scoped to one item (no full reproject).
    """
    edges = 0
    mentions = (
        db.query(EntityMention)
        .join(KnowledgeEntity, EntityMention.entity_id == KnowledgeEntity.id)
        .filter(EntityMention.item_id == item_id, KnowledgeEntity.status != "deprecated")
        .all()
    )
    if not mentions:
        return 0

    entity_cache: dict[str, KnowledgeEntity] = {}
    source_cache: set[str] = set()
    for mention in mentions:
        entity = entity_cache.get(mention.entity_id)
        if entity is None:
            entity = db.query(KnowledgeEntity).filter_by(id=mention.entity_id).one_or_none()
            if entity is None:
                continue
            entity_cache[mention.entity_id] = entity
            graph.upsert_entity(
                {
                    "id": entity.id,
                    "user_id": entity.user_id,
                    "entity_type": entity.entity_type,
                    "canonical_name": entity.canonical_name,
                    "normalized_key": entity.normalized_key,
                    "status": entity.status,
                    "confidence": entity.confidence,
                }
            )

        source_node = _source_node_for_mention(db, mention, user_id)
        if source_node["id"] not in source_cache:
            graph.upsert_source(source_node)
            source_cache.add(source_node["id"])
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                ["confidence", "evidence_span", "extraction_method", "source_kind", "source_id"],
            ),
        )
        edges += 1
    return edges
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd AIOne && python -m pytest engine/tests/test_stage_a.py -k project_item_entities -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/graph_projection.py engine/tests/test_stage_a.py
git commit -m "feat(graph): project_item_entities incremental MySQL->Neo4j projection"
```

---

## Task 7: 把 Stage A 接入 ingestion pipeline

**Files:**
- Modify: `engine/app/ingestion/pipeline.py`（在 `ingest_item` 内，store_mysql_chunks 之后、done 之前）

- [ ] **Step 1: 写失败测试 `engine/tests/test_pipeline_stage_a.py`**

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_pipeline_stage_a_test.db"

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import KnowledgeEntity, KnowledgeMention if False else None  # placeholder, see below
```

> 占位行删掉，正式测试如下（覆盖写）：

```python
import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_pipeline_stage_a_test.db"

from unittest.mock import patch

from backend.app.database import Base, engine as _engine
from backend.app.models import EntityMention, KnowledgeChunk, KnowledgeEntity, KnowledgeItem
from backend.app.services.entity_extraction import EntityCandidate
from sqlalchemy.orm import sessionmaker

from engine.app.ingestion import pipeline as pl


def _seed_item(item_id="i1", content="混合检索结合向量与关键词，并使用 RRF 融合。"):
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    db.query(KnowledgeItem).delete()
    db.query(KnowledgeChunk).delete()
    db.add(KnowledgeItem(id=item_id, user_id="default-user", title="doc", content=content))
    db.commit()
    db.close()
    return item_id


@patch("engine.app.ingestion.pipeline._project_item_entities_to_graph")
@patch("engine.app.ingestion.pipeline.project_item_entities")
@patch("engine.app.ingestion.pipeline.extract_stage_a_parallel")
@patch("engine.app.ingestion.pipeline.embed_texts")
@patch("engine.app.ingestion.pipeline.insert_vectors_batch")
@patch("engine.app.ingestion.pipeline.delete_vectors_by_ids")
@patch("engine.app.ingestion.pipeline.get_es")
def test_pipeline_runs_stage_a_and_settles_to_mysql(
    _es, _delvec, _insvec, _embed, mock_parallel, _proj1, _proj2, monkeypatch,
):
    _embed.return_value = [[0.1] * 8]
    _es_return = type("R", (), {"delete_by_query": lambda *a, **k: None})()
    # ES helpers.bulk path: short-circuit by making chunks empty? Instead disable ES via empty parents not possible.
    monkeypatch.setattr(pl, "_bulk_index_chunks_es", lambda **kw: 0)
    monkeypatch.setattr(pl, "_delete_es_chunks_by_item", lambda item_id: None)
    mock_parallel.return_value = {
        "c-child-0": [
            EntityCandidate(kind="entity", entity_type="concept", surface_text="混合检索",
                            normalized_key="x", aliases=["x"], confidence=0.85,
                            extraction_method="llm_stage_a:INFERRED")
        ]
    }

    item_id = _seed_item()
    pl.ingest_item(item_id)

    db = sessionmaker(bind=_engine)()
    try:
        ents = db.query(KnowledgeEntity).all()
        mentions = db.query(EntityMention).filter_by(item_id=item_id).all()
        assert len(ents) >= 1
        assert any(e.entity_type == "concept" for e in ents)
        assert len(mentions) >= 1
    finally:
        db.close()
```

> 说明：pipeline 依赖 ES/Milvus，测试里用 monkeypatch 把它们桩掉，聚焦验证 Stage A→MySQL 这条链路。若 fixture 细节与真实签名有出入，按报错微调（报错信息会明确指出）。

- [ ] **Step 2: 运行测试，确认失败**

Run: `cd AIOne && python -m pytest engine/tests/test_pipeline_stage_a.py -v`
Expected: FAIL（pipeline 未调用 Stage A，mentions 为空 / 导入错误）

- [ ] **Step 3: 修改 `engine/app/ingestion/pipeline.py`**

在 import 区追加：

```python
from ..extraction.stage_a import extract_stage_a_parallel
from backend.app.services.entity_extraction import settle_entity_candidates
from backend.app.services.graph_projection import project_item_entities
from backend.app.services.graph_client import GraphClient
```

新增一个把 Stage A 接到 MySQL + Neo4j 的内部函数（放在 `ingest_item` 之前）：

```python
def _run_stage_a_for_item(db, item_id: str, user_id: str) -> None:
    """Stage A: LLM-extract entities for every child chunk, settle to MySQL, project to Neo4j.

    Failures are logged and swallowed so graph/extraction issues never break ingestion.
    """
    if not settings.ENTITY_EXTRACT_ENABLED:
        return
    try:
        from backend.app.models.knowledge_item import KnowledgeChunk

        chunks = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "child")
            .all()
        )
        if not chunks:
            return
        chunk_inputs = [(c.id, c.chunk_text or "") for c in chunks]
        _log_stage(item_id, "stage_a_extract", chunks=len(chunk_inputs))
        per_chunk = extract_stage_a_parallel(chunk_inputs)

        for chunk in chunks:
            candidates = per_chunk.get(chunk.id, [])
            if not candidates:
                continue
            settle_entity_candidates(
                db,
                candidates,
                source_kind="document_chunk",
                source_id=chunk.id,
                item_id=item_id,
                chunk_id=chunk.id,
                user_id=user_id,
            )
        db.commit()
        _log_stage(item_id, "stage_a_settled")

        _project_item_entities_to_graph(db, item_id, user_id)
    except Exception as exc:
        logger.warning("[ingest.pipeline] stage_a_failed item_id=%s error=%s", item_id, exc)


def _project_item_entities_to_graph(db, item_id: str, user_id: str) -> None:
    try:
        client = GraphClient()
        try:
            project_item_entities(db, client, item_id=item_id, user_id=user_id)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("[ingest.pipeline] graph_projection_failed item_id=%s error=%s", item_id, exc)
```

在 `ingest_item` 内，找到 `db.commit()` 之后、`_log_stage(item_id, "done"...)` 之前（即 ES 索引完成、最后一次 commit 之后），插入调用。具体：把

```python
        _log_stage(item_id, "commit")
        db.commit()
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _log_stage(item_id, "done", children=len(child_texts), elapsed_ms=elapsed_ms)
        return len(child_texts)
```

改为：

```python
        _log_stage(item_id, "commit")
        db.commit()

        user_id = (item.user_id if hasattr(item, "user_id") else None) or "default-user"
        _run_stage_a_for_item(db, item_id, user_id)

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _log_stage(item_id, "done", children=len(child_texts), elapsed_ms=elapsed_ms)
        return len(child_texts)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `cd AIOne && python -m pytest engine/tests/test_pipeline_stage_a.py -v`
Expected: PASS

- [ ] **Step 5: 跑全部 engine + backend 测试，确认无回归**

Run: `cd AIOne && python -m pytest engine backend -q`
Expected: 现有测试仍通过（若有依赖外部 Milvus/ES/Neo4j 的集成测试失败，属环境问题，记录但非本计划引入）

- [ ] **Step 6: Commit**

```bash
git add engine/app/ingestion/pipeline.py engine/tests/test_pipeline_stage_a.py
git commit -m "feat(ingest): wire Stage A entity extraction into pipeline with graph projection"
```

---

## Task 8: 端到端验证（真实 LLM + Neo4j，手动）

**Files:** 无代码改动，仅验证

- [ ] **Step 1: 确认环境变量**

`.env` 里至少有：`DATABASE_URL`、`LLM_API_BASE`/`LLM_API_KEY`/`LLM_MODEL`、`NEO4J_URI`/`NEO4J_USERNAME`/`NEO4J_PASSWORD`、`EMBEDDING_*`。可选 `ENTITY_EXTRACT_MODEL` 指向便宜模型。

- [ ] **Step 2: 启动依赖 + 服务**

```bash
cd AIOne
docker-compose up -d            # MySQL/Milvus/Neo4j/ES/Redis
SKIP_ENGINE=1 python -m backend.run &   # 或按你常规方式起
python -m engine.run &
```

- [ ] **Step 3: 上传一份之前「抽不出实体」的碎片型文档**（例如一段只有概念、无人名机构的技术笔记），通过 `/api/v1/ingest` 入库。

- [ ] **Step 4: 在 Neo4j 里验证全覆盖**

运行 Cypher：

```cypher
MATCH (s:Source)-[r:MENTIONED_IN]-(e:Entity)
WHERE s.item_id = $item_id
RETURN s.title, type(r), e.canonical_name, e.entity_type LIMIT 25
```

Expected: 能看到该文档的 Source 节点挂到多个 Entity（concept/method/term…），证明「之前不进图的内容现在进图了」。

- [ ] **Step 5: 验证幂等**——对同一文档再入库一次，确认没有重复 mention（`uq_entity_mention_source_surface` 约束生效）、没有报错。

- [ ] **Step 6: 若全部通过，标记 P1 完成**

```bash
git log --oneline -8   # 确认 7 个提交都在
```

在 spec 的 P1 行标注完成日期。

---

## Self-Review（计划完成后自查）

**1. Spec 覆盖：**
- spec §3 全覆盖连接（MENTIONS_ENTITY/MENTIONED_IN 强制）→ Task 6 投影 + Task 7 每个 chunk 都过 Stage A。✓
- spec §4 两段式抽取 Stage A 强制 + 三档置信度 + node/边幂等 → Task 3（tier discipline）、Task 2/7（settle 幂等走唯一约束）。✓
- spec §4 增量边 diff → Task 2/6 复用唯一约束做幂等去重；旧边清理在 pipeline 的 `clear_document_item_governance`+chunk 删除阶段处理（Stage A 的 mention 因 chunk_id 变更随 chunk 删除级联）。注：完整的「旧 Entity 边 diff」细化为 P2 随 graphify 诊断门一起做（spec §5/P2）。
- spec §4 成本控制（便宜模型 + 并行 + 缓存）→ Task 1 `ENTITY_EXTRACT_MODEL`、Task 5 并行。缓存随 graphify 复用在 P2。✓
- spec §7 代理拓扑：图谱维护代理由 pipeline 内 Stage A fan-out 承担（本期为 pipeline 内联；独立「图谱维护代理」LangGraph 化属 P2+，因 langgraph 未安装）。✓（计划已注明）

**2. 占位符扫描：** Task 7 Step 1 的 `_project_item_entities_to_graph` 已在 Step 3 定义；`KnowledgeMention if False else None` 占位行已明确「删掉，用正式测试」。无其他 TODO/TBD。✓

**3. 类型一致性：** `EntityCandidate` 字段（kind/entity_type/surface_text/normalized_key/aliases/confidence/evidence_span/extraction_method）在 Task 2/4/5/7 使用一致；`settle_entity_candidates(db, candidates, source_kind, source_id, item_id, chunk_id, user_id)` 签名在 Task 2 定义、Task 7 调用一致；`extract_stage_a_parallel(chunks, max_workers)` 在 Task 5 定义、Task 7 调用一致；`project_item_entities(db, graph, item_id, user_id)` 在 Task 6 定义、Task 7 调用一致。✓

---

## 风险提示

- **ES/Milvus 桩化**：Task 7 测试需把 ES/Milvus 桩掉；若真实签名与桩不一致，按报错调整（报错明确）。
- **KnowledgeItem 必填字段**：Task 6 测试构造 `KnowledgeItem(id, user_id, title, content)`，若模型还有其它 NOT NULL 列（如 `media_type`），按 `backend/app/models/knowledge_item.py` 补齐。
- **Neo4j 不可用**：`_project_item_entities_to_graph` 已 try/except，Neo4j 宕机只告警、不阻断入库（spec 原则：图失败不影响主流程）。
- **LLM 成本**：高频增量下每 chunk 一次 LLM 调用；务必把 `ENTITY_EXTRACT_MODEL` 指向便宜模型，并控制 `ENTITY_EXTRACT_WORKERS`。
