# LLM Asset Unit PKU Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-PKU asset unit settlement with main-LLM multi-PKU extraction, summary fallback, and persisted PKU-to-PKU relations.

**Architecture:** Add a focused PKU extraction prompt/LLM helper, extend governance persistence to create many PKUs from one `PersonalAssetUnit`, and introduce a `pku_relation` table for direct PKU relations. Keep CKP creation and PKU-to-CKP links in the existing governance service.

**Tech Stack:** FastAPI, SQLAlchemy ORM, PyMySQL/MySQL, pytest, OpenAI-compatible SDK, existing Prism config and prompt modules.

---

## File Structure

- Modify `backend/app/models/knowledge_governance.py`: add `PKURelation` and relationships from `PersonalKnowledgeUnit`.
- Modify `backend/app/models/__init__.py`: export `PKURelation`.
- Modify `backend/app/utils/auto_migrate.py`: include `uq_pku_relation` in known unique constraints.
- Modify `backend/app/services/knowledge_governance.py`: add 12-type vocabulary, LLM extraction dataclasses/helpers, summary fallback, multi-PKU settlement, and PKU relation creation.
- Modify `backend/app/prompts/asset_parse.py`: add prompt builder for asset-unit PKU extraction, following the existing prompt-module pattern.
- Test `backend/tests/test_knowledge_governance_models.py`: model and unique constraint coverage for `PKURelation`.
- Test `backend/tests/test_assets_api.py` or new `backend/tests/test_asset_unit_pku_extraction.py`: settlement behavior, LLM success, LLM fallback, relation persistence, and no Ollama call.

---

### Task 1: Add PKU Relation Model

**Files:**
- Modify: `backend/app/models/knowledge_governance.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`
- Test: `backend/tests/test_knowledge_governance_models.py`

- [ ] **Step 1: Write the failing model test**

Add this test to `backend/tests/test_knowledge_governance_models.py`:

```python
def test_pku_relations_store_direct_pku_edges(db_session):
    from backend.app.models import PKURelation, PersonalKnowledgeUnit

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="rule",
        statement="确认后的资产单元必须沉淀为 PKU。",
        normalized_statement="确认后的资产单元必须沉淀为 PKU。",
        normalized_statement_hash="hash-a",
        status="active",
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="PKU 沉淀流程先抽取原子知识点再建立关系。",
        normalized_statement="PKU 沉淀流程先抽取原子知识点再建立关系。",
        normalized_statement_hash="hash-b",
        status="active",
    )
    db_session.add_all([first, second])
    db_session.flush()

    relation = PKURelation(
        user_id="default-user",
        source_pku_id=first.id,
        target_pku_id=second.id,
        relation_type="prerequisite_of",
        confidence=0.91,
        reason="规则是方法执行的前置约束。",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        llm_model="qwen-plus",
        extra_meta={"group": "PKU沉淀"},
    )
    db_session.add(relation)
    db_session.commit()

    loaded = db_session.query(PKURelation).one()
    assert loaded.source_pku.statement == "确认后的资产单元必须沉淀为 PKU。"
    assert loaded.target_pku.statement == "PKU 沉淀流程先抽取原子知识点再建立关系。"
    assert loaded.relation_type == "prerequisite_of"
    assert loaded.extra_meta == {"group": "PKU沉淀"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_knowledge_governance_models.py::test_pku_relations_store_direct_pku_edges -q
```

Expected: fail because `PKURelation` is not defined/exported.

- [ ] **Step 3: Implement the model**

In `backend/app/models/knowledge_governance.py`, update the `PersonalKnowledgeUnit` relationships:

```python
    outgoing_relations = relationship(
        "PKURelation",
        foreign_keys="PKURelation.source_pku_id",
        back_populates="source_pku",
        cascade="all, delete-orphan",
    )
    incoming_relations = relationship(
        "PKURelation",
        foreign_keys="PKURelation.target_pku_id",
        back_populates="target_pku",
        cascade="all, delete-orphan",
    )
```

Add this model after `PKUCanonicalLink`:

```python
class PKURelation(Base):
    __tablename__ = "pku_relation"
    __table_args__ = (
        UniqueConstraint(
            "source_pku_id",
            "target_pku_id",
            "relation_type",
            name="uq_pku_relation",
        ),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", index=True, nullable=False)

    source_pku_id = Column(
        CHAR(36),
        ForeignKey("personal_knowledge_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_pku_id = Column(
        CHAR(36),
        ForeignKey("personal_knowledge_unit.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    relation_type = Column(String(64), default="related_to", index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    source_kind = Column(String(64), default="", index=True)
    source_id = Column(CHAR(36), default="", index=True)
    llm_model = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    source_pku = relationship(
        "PersonalKnowledgeUnit",
        foreign_keys=[source_pku_id],
        back_populates="outgoing_relations",
    )
    target_pku = relationship(
        "PersonalKnowledgeUnit",
        foreign_keys=[target_pku_id],
        back_populates="incoming_relations",
    )
```

In `backend/app/models/__init__.py`, import and export `PKURelation`.

In `backend/app/utils/auto_migrate.py`, add `"uq_pku_relation"` to `KNOWN_UNIQUE_CONSTRAINTS`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_knowledge_governance_models.py::test_pku_relations_store_direct_pku_edges -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models/knowledge_governance.py backend/app/models/__init__.py backend/app/utils/auto_migrate.py backend/tests/test_knowledge_governance_models.py
git commit -m "feat: add pku relation model"
```

---

### Task 2: Add Asset Unit PKU Extraction Prompt Builder

**Files:**
- Modify: `backend/app/prompts/asset_parse.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write the failing prompt test**

Create `backend/tests/test_asset_unit_pku_extraction.py`:

```python
import json


def test_build_asset_unit_pku_extraction_messages_include_required_schema():
    from backend.app.prompts.asset_parse import build_asset_unit_pku_extraction_messages

    system, user = build_asset_unit_pku_extraction_messages(
        title="PKU 沉淀流程",
        summary="确认资产单元后抽取多条原子 PKU。",
        content="确认资产单元后，应使用主 LLM 抽取多条 PKU，并写入 PKU 关系。",
        category="知识治理",
        tags=["PKU", "资产单元"],
        source_asset_ids=["asset-1", "asset-2"],
    )

    payload = json.loads(user)
    assert "严格 JSON" in system
    assert payload["asset_unit"]["title"] == "PKU 沉淀流程"
    assert "concept" in payload["allowed_unit_types"]
    assert "constraint" in payload["allowed_unit_types"]
    assert payload["json_shape"]["pkus"][0]["unit_type"].startswith("concept|definition")
    assert "relations" in payload["json_shape"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_build_asset_unit_pku_extraction_messages_include_required_schema -q
```

Expected: fail because `build_asset_unit_pku_extraction_messages` does not exist.

- [ ] **Step 3: Implement prompt constants and builder**

Append to `backend/app/prompts/asset_parse.py`:

```python
ASSET_UNIT_PKU_EXTRACTION_SYSTEM_PROMPT = (
    "你是 Prism 的个人知识单元 PKU 抽取器。"
    "你必须只输出严格 JSON，不要输出思考过程、解释或 Markdown 代码块。"
)

PKU_UNIT_TYPES = [
    "concept",
    "definition",
    "claim",
    "method",
    "rule",
    "observation",
    "experiment_result",
    "decision",
    "problem",
    "question",
    "pattern",
    "constraint",
]

PKU_RELATION_TYPES = [
    "supports",
    "contradicts",
    "prerequisite_of",
    "derived_from",
    "refines",
    "causes",
    "enables",
    "constrains",
    "part_of",
    "same_topic",
]

JSON_SHAPE_ASSET_UNIT_PKU_EXTRACTION: dict[str, Any] = {
    "pkus": [
        {
            "statement": "一条原子化、可验证、可复用的中文知识单元陈述",
            "unit_type": "|".join(PKU_UNIT_TYPES),
            "evidence_span": "来自资产单元摘要或正文的直接证据片段",
            "keywords": ["关键词1", "关键词2"],
            "concepts": ["概念1", "概念2"],
            "entities": ["实体1", "实体2"],
            "domains": ["领域1"],
            "group": "可选分组名称",
            "confidence": 0.0,
            "reason": "简短说明为什么这样抽取和分类",
        }
    ],
    "relations": [
        {
            "from": "PKU A 的 statement",
            "to": "PKU B 的 statement",
            "type": "|".join(PKU_RELATION_TYPES),
            "confidence": 0.0,
            "reason": "简短说明关系依据",
        }
    ],
}

ASSET_UNIT_PKU_EXTRACTION_RULES = [
    "每个 PKU 必须是一个原子知识单元，只表达一个具体、可验证、可复用的知识判断。",
    "如果一个句子包含多个事实、步骤、条件或判断，必须拆成多条 PKU。",
    "statement 必须包含具体事实、条件、角色、动作、阈值、规则、方法步骤、观察结果或决策内容。",
    "不要把标题、章节名、列表标题、分类名本身作为独立 PKU。",
    "不要编造原文中没有的事实、数字、角色、关系或结论。",
    "evidence_span 必须来自资产单元摘要或正文的直接证据片段。",
    "所有自然语言文本内容用中文撰写，JSON 字段名保持英文。",
    "relation.from 和 relation.to 必须引用 pkus 中已有的 statement。",
]


def build_asset_unit_pku_extraction_request(
    *,
    title: str,
    summary: str,
    content: str,
    category: str = "",
    tags: list[str] | None = None,
    source_asset_ids: list[str] | None = None,
    max_content_length: int = 8000,
) -> str:
    request = {
        "task": "从个人资产单元中抽取多条细粒度、原子化 PKU，并尽可能抽取 PKU 之间的关系。",
        "asset_unit": {
            "title": title,
            "summary": summary,
            "content": content[:max_content_length],
            "category": category,
            "tags": tags or [],
            "source_asset_ids": source_asset_ids or [],
        },
        "allowed_unit_types": PKU_UNIT_TYPES,
        "allowed_relation_types": PKU_RELATION_TYPES,
        "rules": ASSET_UNIT_PKU_EXTRACTION_RULES,
        "json_shape": JSON_SHAPE_ASSET_UNIT_PKU_EXTRACTION,
    }
    return json.dumps(request, ensure_ascii=False)


def build_asset_unit_pku_extraction_messages(
    *,
    title: str,
    summary: str,
    content: str,
    category: str = "",
    tags: list[str] | None = None,
    source_asset_ids: list[str] | None = None,
    max_content_length: int = 8000,
) -> tuple[str, str]:
    return (
        ASSET_UNIT_PKU_EXTRACTION_SYSTEM_PROMPT,
        build_asset_unit_pku_extraction_request(
            title=title,
            summary=summary,
            content=content,
            category=category,
            tags=tags,
            source_asset_ids=source_asset_ids,
            max_content_length=max_content_length,
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_build_asset_unit_pku_extraction_messages_include_required_schema -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/prompts/asset_parse.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "feat: add asset unit pku extraction prompt"
```

---

### Task 3: Add LLM Extraction Parser and Validation

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing parser tests**

Append:

```python
def test_parse_asset_unit_pku_extraction_keeps_valid_pkus_and_relations():
    from backend.app.services.knowledge_governance import _parse_asset_unit_pku_extraction

    result = _parse_asset_unit_pku_extraction(
        {
            "pkus": [
                {
                    "statement": "PKU 抽取必须保留原文中的精确阈值。",
                    "unit_type": "rule",
                    "evidence_span": "保留技术术语的原文精确措辞，例如 ≥50人月。",
                    "keywords": ["PKU", "阈值"],
                    "concepts": ["PKU"],
                    "entities": [],
                    "domains": ["知识治理"],
                    "group": "抽取规则",
                    "confidence": 0.88,
                    "reason": "规则包含必须要求。",
                },
                {"statement": "非法类型会被丢弃。", "unit_type": "bad_type"},
            ],
            "relations": [
                {
                    "from": "PKU 抽取必须保留原文中的精确阈值。",
                    "to": "非法类型会被丢弃。",
                    "type": "supports",
                    "confidence": 0.7,
                    "reason": "测试关系。",
                }
            ],
        }
    )

    assert len(result.pkus) == 1
    assert result.pkus[0].unit_type == "rule"
    assert result.pkus[0].confidence == 0.88
    assert len(result.relations) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_parse_asset_unit_pku_extraction_keeps_valid_pkus_and_relations -q
```

Expected: fail because parser does not exist.

- [ ] **Step 3: Implement dataclasses and parser**

In `backend/app/services/knowledge_governance.py`, add imports:

```python
from openai import OpenAI
```

Extend constants:

```python
PKU_UNIT_TYPES = {
    "concept",
    "definition",
    "claim",
    "method",
    "rule",
    "observation",
    "experiment_result",
    "decision",
    "problem",
    "question",
    "pattern",
    "constraint",
}

PKU_RELATION_TYPES = {
    "supports",
    "contradicts",
    "prerequisite_of",
    "derived_from",
    "refines",
    "causes",
    "enables",
    "constrains",
    "part_of",
    "same_topic",
}
```

Add dataclasses:

```python
@dataclass(frozen=True)
class ExtractedPKU:
    statement: str
    unit_type: str
    evidence_span: str
    keywords: list[str]
    concepts: list[str]
    entities: list[str]
    domains: list[str]
    group: str
    confidence: float
    reason: str
    llm_model: str = ""


@dataclass(frozen=True)
class ExtractedPKURelation:
    from_statement: str
    to_statement: str
    relation_type: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class AssetUnitPKUExtraction:
    pkus: list[ExtractedPKU]
    relations: list[ExtractedPKURelation]
    llm_model: str = ""
```

Add helpers:

```python
def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(confidence, 1.0))


def _clean_string_list(value: Any, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _normalize_space(str(item or ""))
        if text and text not in cleaned:
            cleaned.append(text[:80])
        if len(cleaned) >= limit:
            break
    return cleaned


def _parse_asset_unit_pku_extraction(data: dict[str, Any], llm_model: str = "") -> AssetUnitPKUExtraction:
    parsed_pkus: list[ExtractedPKU] = []
    for item in _as_list(data.get("pkus")):
        if not isinstance(item, dict):
            continue
        statement = _normalize_space(str(item.get("statement") or ""))
        unit_type = str(item.get("unit_type") or "").strip().lower()
        evidence_span = _normalize_space(str(item.get("evidence_span") or ""))
        if not statement or unit_type not in PKU_UNIT_TYPES:
            continue
        parsed_pkus.append(
            ExtractedPKU(
                statement=statement[:1200],
                unit_type=unit_type,
                evidence_span=(evidence_span or statement)[:1200],
                keywords=_clean_string_list(item.get("keywords")),
                concepts=_clean_string_list(item.get("concepts")),
                entities=_clean_string_list(item.get("entities")),
                domains=_clean_string_list(item.get("domains")),
                group=_normalize_space(str(item.get("group") or ""))[:120],
                confidence=_clamp_confidence(item.get("confidence"), 0.72),
                reason=_normalize_space(str(item.get("reason") or ""))[:500],
                llm_model=llm_model,
            )
        )

    parsed_relations: list[ExtractedPKURelation] = []
    for item in _as_list(data.get("relations")):
        if not isinstance(item, dict):
            continue
        from_statement = _normalize_space(str(item.get("from") or ""))
        to_statement = _normalize_space(str(item.get("to") or ""))
        relation_type = str(item.get("type") or "").strip().lower()
        if not from_statement or not to_statement or relation_type not in PKU_RELATION_TYPES:
            continue
        parsed_relations.append(
            ExtractedPKURelation(
                from_statement=from_statement[:1200],
                to_statement=to_statement[:1200],
                relation_type=relation_type,
                confidence=_clamp_confidence(item.get("confidence"), 0.6),
                reason=_normalize_space(str(item.get("reason") or ""))[:500],
            )
        )

    return AssetUnitPKUExtraction(parsed_pkus, parsed_relations, llm_model=llm_model)
```

- [ ] **Step 4: Run parser test**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_parse_asset_unit_pku_extraction_keeps_valid_pkus_and_relations -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "feat: parse asset unit pku extraction"
```

---

### Task 4: Call Main LLM for Asset Unit PKU Extraction

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing LLM helper test**

Append:

```python
def test_extract_asset_unit_pkus_uses_main_llm(monkeypatch):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = '{"pkus":[{"statement":"资产单元确认后使用主 LLM 抽取 PKU。","unit_type":"method","evidence_span":"使用主 LLM 抽取多条 PKU。","confidence":0.9}],"relations":[]}'

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    unit = PersonalAssetUnit(
        id="unit-1",
        title="PKU 沉淀",
        summary="确认后使用主 LLM 抽取 PKU。",
        content="使用主 LLM 抽取多条 PKU。",
        category="知识治理",
        tags=["PKU"],
        source_asset_ids=["asset-1"],
    )

    result = kg._extract_asset_unit_pkus_with_llm(unit)

    assert captured["model"] == "qwen-plus"
    assert result.llm_model == "qwen-plus"
    assert result.pkus[0].unit_type == "method"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_extract_asset_unit_pkus_uses_main_llm -q
```

Expected: fail because `_extract_asset_unit_pkus_with_llm` does not exist.

- [ ] **Step 3: Implement LLM helper**

In `backend/app/services/knowledge_governance.py`, import:

```python
from backend.app.prompts.asset_parse import build_asset_unit_pku_extraction_messages
```

Add helper:

```python
def _extract_asset_unit_pkus_with_llm(unit: PersonalAssetUnit) -> AssetUnitPKUExtraction:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return AssetUnitPKUExtraction([], [], llm_model="")

    system_prompt, user_message = build_asset_unit_pku_extraction_messages(
        title=unit.title or "",
        summary=unit.summary or "",
        content=unit.content or "",
        category=unit.category or "",
        tags=unit.tags or [],
        source_asset_ids=unit.source_asset_ids or [],
    )
    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = _parse_json_object(content)
        return _parse_asset_unit_pku_extraction(data, llm_model=settings.LLM_MODEL)
    except Exception:
        return AssetUnitPKUExtraction([], [], llm_model="")
```

- [ ] **Step 4: Run LLM helper test**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_extract_asset_unit_pkus_uses_main_llm -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "feat: extract asset unit pkus with main llm"
```

---

### Task 5: Persist Multiple PKUs and Summary Fallback

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing multi-PKU settlement test**

Append:

```python
def test_asset_unit_settlement_persists_multiple_llm_pkus(db_session, monkeypatch):
    from backend.app.models import PersonalAssetUnit, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg
    from backend.app.services.knowledge_governance import AssetUnitPKUExtraction, ExtractedPKU

    unit = PersonalAssetUnit(
        user_id="default-user",
        title="PKU 沉淀流程",
        summary="确认资产单元后抽取 PKU。",
        content="确认资产单元后使用主 LLM 抽取多条 PKU，并建立 PKU 关系。",
        category="知识治理",
        tags=["PKU"],
        source_asset_ids=["asset-1"],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: AssetUnitPKUExtraction(
            pkus=[
                ExtractedPKU(
                    statement="确认资产单元后使用主 LLM 抽取多条 PKU。",
                    unit_type="method",
                    evidence_span="使用主 LLM 抽取多条 PKU。",
                    keywords=["PKU"],
                    concepts=["资产单元"],
                    entities=[],
                    domains=["知识治理"],
                    group="PKU沉淀流程",
                    confidence=0.91,
                    reason="描述了方法流程。",
                    llm_model="qwen-plus",
                ),
                ExtractedPKU(
                    statement="PKU 关系需要写入 PKU 关系表。",
                    unit_type="rule",
                    evidence_span="建立 PKU 关系。",
                    keywords=["PKU关系"],
                    concepts=["关系表"],
                    entities=[],
                    domains=["知识治理"],
                    group="PKU沉淀流程",
                    confidence=0.87,
                    reason="表达了写入规则。",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)

    assert result.pku_count == 2
    pkus = db_session.query(PersonalKnowledgeUnit).order_by(PersonalKnowledgeUnit.statement.asc()).all()
    assert {pku.unit_type for pku in pkus} == {"method", "rule"}
    assert {pku.llm_model for pku in pkus} == {"qwen-plus"}
```

- [ ] **Step 2: Write failing fallback test**

Append:

```python
def test_asset_unit_settlement_falls_back_to_summary_when_llm_empty(db_session, monkeypatch):
    from backend.app.models import PersonalAssetUnit, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg
    from backend.app.services.knowledge_governance import AssetUnitPKUExtraction

    unit = PersonalAssetUnit(
        user_id="default-user",
        title="兜底策略",
        summary="LLM 抽取失败时，资产单元使用 summary 生成单条 PKU。",
        content="这段正文很长，但不能直接截断当作 PKU statement。",
        category="知识治理",
        tags=["PKU"],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: AssetUnitPKUExtraction([], [], llm_model=""),
    )

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).one()
    assert pku.statement == "LLM 抽取失败时，资产单元使用 summary 生成单条 PKU。"
    assert pku.evidence_span == "这段正文很长，但不能直接截断当作 PKU statement。"
    assert pku.llm_model == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_persists_multiple_llm_pkus backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_falls_back_to_summary_when_llm_empty -q
```

Expected: fail because settlement still creates one PKU from content and calls Ollama classifier.

- [ ] **Step 4: Implement PKU creation from extracted PKUs**

Change `_create_or_get_asset_unit_pku` signature:

```python
def _create_or_get_asset_unit_pku(
    db: Session,
    *,
    unit: PersonalAssetUnit,
    extracted: ExtractedPKU,
) -> PersonalKnowledgeUnit:
    normalized = _normalize_space(extracted.statement)
    statement_hash = _text_hash(normalized)
    existing = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == unit.user_id,
            PersonalKnowledgeUnit.source_kind == "personal_asset_unit",
            PersonalKnowledgeUnit.source_id == unit.id,
            PersonalKnowledgeUnit.unit_type == extracted.unit_type,
            PersonalKnowledgeUnit.normalized_statement_hash == statement_hash,
        )
        .first()
    )
    if existing:
        return existing

    keywords = extracted.keywords or _extract_keywords(
        extracted.statement,
        unit.title,
        unit.summary,
        unit.category,
        unit.tags or [],
    )
    pku = PersonalKnowledgeUnit(
        user_id=unit.user_id,
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type=extracted.unit_type,
        statement=extracted.statement,
        normalized_statement=normalized,
        normalized_statement_hash=statement_hash,
        modality="fact",
        domains=extracted.domains or ([unit.category] if unit.category else []),
        entities=extracted.entities,
        concepts=extracted.concepts or (unit.tags or []),
        keywords=keywords,
        evidence_span=extracted.evidence_span[:1200],
        confidence=_clamp_confidence(extracted.confidence, 0.72),
        llm_model=extracted.llm_model,
        status="active",
    )
    db.add(pku)
    db.flush()
    return pku
```

Add fallback helper:

```python
def _fallback_asset_unit_summary_pku(unit: PersonalAssetUnit) -> ExtractedPKU | None:
    summary = _normalize_space(unit.summary or "")
    if not summary:
        return None
    evidence = _normalize_space(unit.content or unit.summary or "")
    return ExtractedPKU(
        statement=summary[:1200],
        unit_type=_unit_type_from_unit_text(summary),
        evidence_span=(evidence or summary)[:1200],
        keywords=_extract_keywords(summary, unit.title, unit.category, unit.tags or []),
        concepts=unit.tags or [],
        entities=[],
        domains=[unit.category] if unit.category else [],
        group="",
        confidence=float((unit.confidence or {}).get("overall", 0.55) or 0.55),
        reason="Summary fallback because LLM PKU extraction returned no valid PKUs.",
        llm_model="",
    )
```

Rewrite `settle_personal_asset_unit_to_governance`:

```python
def settle_personal_asset_unit_to_governance(db: Session, unit: PersonalAssetUnit) -> GovernanceResult:
    if unit.status != "confirmed":
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    extraction = _extract_asset_unit_pkus_with_llm(unit)
    extracted_pkus = list(extraction.pkus)
    if not extracted_pkus:
        fallback = _fallback_asset_unit_summary_pku(unit)
        extracted_pkus = [fallback] if fallback else []
    if not extracted_pkus:
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    pku_ids: set[str] = set()
    ckp_ids: set[str] = set()
    link_ids: set[str] = set()

    for extracted in extracted_pkus:
        pku = _create_or_get_asset_unit_pku(db, unit=unit, extracted=extracted)
        ckp = _create_or_get_ckp_from_pku(
            db,
            user_id=unit.user_id or DEFAULT_USER_ID,
            pku=pku,
            title=unit.title or pku.statement,
            summary=unit.summary or "",
            aliases=[unit.title] if unit.title else [],
            extra_meta={
                "created_from": "personal_asset_unit",
                "source_unit_id": unit.id,
                "source_asset_ids": unit.source_asset_ids or [],
                "extraction_group": extracted.group,
                "extraction_reason": extracted.reason,
            },
        )
        link = _create_or_get_generic_link(
            db,
            user_id=unit.user_id or DEFAULT_USER_ID,
            pku=pku,
            ckp=ckp,
            relation_type="same_as",
            role="synthesized_personal_knowledge",
            reason="Settlement from confirmed PersonalAssetUnit PKU extraction.",
        )
        pku_ids.add(pku.id)
        ckp_ids.add(ckp.id)
        link_ids.add(link.id)

    return GovernanceResult(pku_count=len(pku_ids), canonical_count=len(ckp_ids), link_count=len(link_ids))
```

- [ ] **Step 5: Run multi-PKU and fallback tests**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_persists_multiple_llm_pkus backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_falls_back_to_summary_when_llm_empty -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "feat: settle asset units into multiple pkus"
```

---

### Task 6: Persist LLM PKU Relations

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing relation settlement test**

Append:

```python
def test_asset_unit_settlement_persists_llm_pku_relations(db_session, monkeypatch):
    from backend.app.models import PKURelation, PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg
    from backend.app.services.knowledge_governance import (
        AssetUnitPKUExtraction,
        ExtractedPKU,
        ExtractedPKURelation,
    )

    unit = PersonalAssetUnit(
        user_id="default-user",
        title="PKU 关系",
        summary="PKU 关系需要落表。",
        content="先抽取 PKU，再写入 PKU 之间的 prerequisite_of 关系。",
        category="知识治理",
        tags=["PKU关系"],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.flush()

    first = "资产单元确认后先抽取原子 PKU。"
    second = "抽取出的 PKU 关系需要写入 pku_relation 表。"
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: AssetUnitPKUExtraction(
            pkus=[
                ExtractedPKU(first, "method", first, [], [], [], [], "", 0.9, "", "qwen-plus"),
                ExtractedPKU(second, "rule", second, [], [], [], [], "", 0.9, "", "qwen-plus"),
            ],
            relations=[
                ExtractedPKURelation(
                    from_statement=first,
                    to_statement=second,
                    relation_type="prerequisite_of",
                    confidence=0.93,
                    reason="先抽取再入库。",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, unit)

    relation = db_session.query(PKURelation).one()
    assert relation.relation_type == "prerequisite_of"
    assert relation.source_kind == "personal_asset_unit"
    assert relation.source_id == unit.id
    assert relation.llm_model == "qwen-plus"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_persists_llm_pku_relations -q
```

Expected: fail because relations are not persisted.

- [ ] **Step 3: Implement relation persistence**

In `backend/app/services/knowledge_governance.py`, import `PKURelation`.

Add helper:

```python
def _create_or_get_pku_relation(
    db: Session,
    *,
    user_id: str,
    source_pku: PersonalKnowledgeUnit,
    target_pku: PersonalKnowledgeUnit,
    relation: ExtractedPKURelation,
    source_kind: str,
    source_id: str,
    llm_model: str,
) -> PKURelation:
    existing = (
        db.query(PKURelation)
        .filter(
            PKURelation.source_pku_id == source_pku.id,
            PKURelation.target_pku_id == target_pku.id,
            PKURelation.relation_type == relation.relation_type,
        )
        .first()
    )
    if existing:
        return existing
    row = PKURelation(
        user_id=user_id,
        source_pku_id=source_pku.id,
        target_pku_id=target_pku.id,
        relation_type=relation.relation_type,
        confidence=relation.confidence,
        reason=relation.reason,
        source_kind=source_kind,
        source_id=source_id,
        llm_model=llm_model,
        extra_meta={},
    )
    db.add(row)
    db.flush()
    return row
```

Update `settle_personal_asset_unit_to_governance` to build a statement map:

```python
    pku_by_statement: dict[str, PersonalKnowledgeUnit] = {}
```

Inside the PKU loop after creating `pku`:

```python
        pku_by_statement[_normalize_space(extracted.statement)] = pku
```

After the PKU loop:

```python
    relation_ids: set[str] = set()
    if extracted_pkus == list(extraction.pkus):
        for relation in extraction.relations:
            source_pku = pku_by_statement.get(_normalize_space(relation.from_statement))
            target_pku = pku_by_statement.get(_normalize_space(relation.to_statement))
            if not source_pku or not target_pku or source_pku.id == target_pku.id:
                continue
            row = _create_or_get_pku_relation(
                db,
                user_id=unit.user_id or DEFAULT_USER_ID,
                source_pku=source_pku,
                target_pku=target_pku,
                relation=relation,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                llm_model=extraction.llm_model,
            )
            relation_ids.add(row.id)
```

Extend `GovernanceResult` if relation counts must be returned by API:

```python
@dataclass(frozen=True)
class GovernanceResult:
    pku_count: int
    canonical_count: int
    link_count: int
    pku_relation_count: int = 0
```

Return:

```python
    return GovernanceResult(
        pku_count=len(pku_ids),
        canonical_count=len(ckp_ids),
        link_count=len(link_ids),
        pku_relation_count=len(relation_ids),
    )
```

- [ ] **Step 4: Run relation test**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_persists_llm_pku_relations -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "feat: persist pku relations from asset units"
```

---

### Task 7: Protect Against Ollama Use for Asset Units

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write failing no-Ollama regression test**

Append:

```python
def test_asset_unit_settlement_does_not_call_ollama_type_classifier(db_session, monkeypatch):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg
    from backend.app.services.knowledge_governance import AssetUnitPKUExtraction

    unit = PersonalAssetUnit(
        user_id="default-user",
        title="不使用 Ollama",
        summary="资产单元使用 summary 兜底生成 PKU。",
        content="不再使用 Ollama 小模型为资产单元打 unit_type。",
        status="confirmed",
    )
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(kg, "_extract_asset_unit_pkus_with_llm", lambda unit: AssetUnitPKUExtraction([], []))

    def fail_ollama(**kwargs):
        raise AssertionError("asset unit settlement must not call Ollama type classifier")

    monkeypatch.setattr(kg, "_ollama_pku_type_decision", fail_ollama)

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)

    assert result.pku_count == 1
```

- [ ] **Step 2: Run test**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py::test_asset_unit_settlement_does_not_call_ollama_type_classifier -q
```

Expected: pass after Task 5. If it fails, remove any remaining `_ollama_pku_type_decision` call from asset-unit settlement.

- [ ] **Step 3: Commit if code changed**

```powershell
git add backend/app/services/knowledge_governance.py backend/tests/test_asset_unit_pku_extraction.py
git commit -m "test: ensure asset unit settlement skips ollama classifier"
```

---

### Task 8: Verify API Confirm Response and Existing Tests

**Files:**
- Modify if needed: `backend/app/schemas/asset.py`
- Modify if needed: `backend/app/api/assets.py`
- Test: `backend/tests/test_assets_api.py`

- [ ] **Step 1: Decide whether API must expose PKU relation count**

If `PersonalAssetUnitConfirmResponse` should expose direct PKU relation count, add this field in `backend/app/schemas/asset.py`:

```python
pku_relation_count: int = 0
```

Then in `backend/app/api/assets.py`, return:

```python
pku_relation_count=governance.pku_relation_count,
```

If the UI does not need this count yet, skip the schema/API change and keep relation count internal.

- [ ] **Step 2: Update existing confirm tests**

In `backend/tests/test_assets_api.py`, update tests that expect `pku_count == 1` for asset unit confirmation. For LLM-backed unit tests, monkeypatch `_extract_asset_unit_pkus_with_llm` to return deterministic extraction. For fallback tests, assert the summary fallback behavior.

Use this monkeypatch shape:

```python
from backend.app.services.knowledge_governance import AssetUnitPKUExtraction, ExtractedPKU

monkeypatch.setattr(
    "backend.app.services.knowledge_governance._extract_asset_unit_pkus_with_llm",
    lambda unit: AssetUnitPKUExtraction(
        pkus=[
            ExtractedPKU(
                statement="资产单元确认后生成一条测试 PKU。",
                unit_type="claim",
                evidence_span="资产单元确认后生成一条测试 PKU。",
                keywords=[],
                concepts=[],
                entities=[],
                domains=[],
                group="",
                confidence=0.8,
                reason="test",
                llm_model="test-model",
            )
        ],
        relations=[],
        llm_model="test-model",
    ),
)
```

- [ ] **Step 3: Run focused backend tests**

Run:

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_assets_api.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```powershell
git add backend/app/schemas/asset.py backend/app/api/assets.py backend/tests/test_assets_api.py
git commit -m "test: update asset unit confirm governance counts"
```

---

### Task 9: Full Verification

**Files:**
- No code files unless fixing failures.

- [ ] **Step 1: Run governance-related tests**

```powershell
python -m pytest backend\tests\test_asset_unit_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_knowledge_graph_api.py backend\tests\test_assets_api.py backend\tests\test_personal_asset_items_api.py -q
```

Expected: all pass.

- [ ] **Step 2: Run backend test suite if time allows**

```powershell
python -m pytest backend\tests -q
```

Expected: all pass.

- [ ] **Step 3: Inspect migration behavior manually**

Start backend once against the development database and watch for:

```text
[auto_migrate] Create table: pku_relation
```

or no output if the table already exists.

- [ ] **Step 4: Manual API smoke test**

Confirm a `personal_asset_unit` through the UI or API. Then inspect DB:

```sql
SELECT source_kind, source_id, unit_type, statement, llm_model
FROM personal_knowledge_unit
WHERE source_kind = 'personal_asset_unit'
ORDER BY created_at DESC
LIMIT 10;

SELECT relation_type, confidence, source_kind, source_id, llm_model
FROM pku_relation
ORDER BY created_at DESC
LIMIT 10;
```

Expected: one confirmed asset unit can create multiple PKUs and relation rows when the LLM returns relations.

- [ ] **Step 5: Final commit**

```powershell
git status --short
git commit -m "feat: extract multiple pkus from asset units"
```

Only commit files changed by this plan.

---

## Self-Review

- Spec coverage: covers main LLM extraction, 12 PKU types, no Ollama for asset units, summary fallback, PKU relation table, and verification.
- Placeholder scan: no TBD/TODO placeholders remain in the implementation steps.
- Type consistency: plan consistently uses `ExtractedPKU`, `ExtractedPKURelation`, `AssetUnitPKUExtraction`, `PKURelation`, and `pku_relation_count`.

