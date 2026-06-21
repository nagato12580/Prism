# Parent-Child CKP Topic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-level CKP hierarchy where existing local topic CKPs become child CKPs, new global parent CKPs group child CKPs, and graph/workbench APIs expose `parent CKP -> child CKP -> PKU -> source`.

**Architecture:** Reuse `CanonicalKnowledgePoint` for both parent and child CKPs. Reuse `CanonicalRelation` with `relation_type="subtopic_of"` for hierarchy, with `source_canonical_id = child` and `target_canonical_id = parent`. Keep PKU membership on child CKPs through existing `PKUCanonicalLink(relation_type="about", role="topic_member")`.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Pytest, TypeScript, React, Vite, Tailwind.

---

## File Map

- `backend/app/prompts/asset_parse.py`: add parent-topic assignment prompt builders.
- `backend/app/services/knowledge_governance.py`: parse parent-topic output, create/reuse parent CKPs, and link child CKPs to parent CKPs.
- `backend/app/api/knowledge_graph.py`: serialize CKP topic levels, parent-child edges, and hierarchical Workbench payload.
- `frontend/src/app/api.ts`: extend graph/workbench types for parent groups and CKP hierarchy edges.
- `frontend/src/pages/KnowledgeGraphWorkbench.tsx`: display parent CKP list, child CKP selector, and existing PKU evidence chain.
- `frontend/src/pages/KnowledgeGraphPage.tsx`: display parent/child CKP hierarchy in network graph.
- `backend/tests/test_asset_unit_pku_extraction.py`: prompt/parser tests.
- `backend/tests/test_knowledge_governance_models.py`: settlement tests.
- `backend/tests/test_knowledge_graph_api.py`: graph/workbench API tests.

## Task 1: Parent Topic Prompt And Parser

**Files:**
- Modify: `backend/app/prompts/asset_parse.py`
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Add failing prompt builder test**

Add to `backend/tests/test_asset_unit_pku_extraction.py` after the CKP topic extraction tests:

```python
def test_build_ckp_parent_topic_assignment_messages_groups_child_topics():
    from backend.app.prompts.asset_parse import build_ckp_parent_topic_assignment_messages

    system_prompt, user_message = build_ckp_parent_topic_assignment_messages(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM fine-tuning guide",
        summary="LoRA, data preparation, and evaluation practices.",
        category="AI",
        tags=["fine-tuning", "LoRA"],
        child_topics=[
            {
                "ref": "child_1",
                "title": "LoRA fine-tuning methods",
                "description": "Parameter-efficient methods for adapting LLMs.",
                "keywords": ["LoRA", "fine-tuning"],
                "concepts": ["parameter efficient tuning"],
                "domains": ["AI"],
                "entities": [],
                "member_pku_statements": ["LoRA reduces trainable parameters."],
            }
        ],
    )

    request = json.loads(user_message)
    assert "JSON" in system_prompt
    assert request["source"]["id"] == "item-1"
    assert request["child_topics"][0]["ref"] == "child_1"
    assert request["json_shape"]["parent_topics"][0]["title"] == "Broad topic noun phrase"
    assert request["json_shape"]["parent_topics"][0]["member_child_refs"] == ["child_1", "child_2"]
    assert any("parent" in rule.lower() for rule in request["rules"])
```

- [ ] **Step 2: Add failing parser test**

Add to `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_parse_ckp_parent_topic_assignment_keeps_valid_parent_topics():
    from backend.app.services import knowledge_governance as kg

    result = kg._parse_ckp_parent_topic_assignment(
        {
            "parent_topics": [
                {
                    "local_id": "parent_1",
                    "title": "LLM fine-tuning",
                    "description": "Methods, rules, and evaluation knowledge for adapting LLMs.",
                    "keywords": ["fine-tuning", "LoRA"],
                    "concepts": ["SFT"],
                    "domains": ["AI"],
                    "entities": [],
                    "member_child_refs": ["child_1", "child_2"],
                    "confidence": 0.9,
                    "reason": "Both child topics discuss fine-tuning.",
                },
                {"local_id": "bad", "title": "", "member_child_refs": ["child_3"]},
            ]
        },
        llm_model="qwen-plus",
    )

    assert len(result.parent_topics) == 1
    assert result.parent_topics[0].local_id == "parent_1"
    assert result.parent_topics[0].title == "LLM fine-tuning"
    assert result.parent_topics[0].member_child_refs == ["child_1", "child_2"]
    assert result.parent_topics[0].llm_model == "qwen-plus"
```

- [ ] **Step 3: Verify failure**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_build_ckp_parent_topic_assignment_messages_groups_child_topics backend/tests/test_asset_unit_pku_extraction.py::test_parse_ckp_parent_topic_assignment_keeps_valid_parent_topics -q
```

Expected: fails because prompt builder and parser do not exist.

- [ ] **Step 4: Implement prompt builder**

In `backend/app/prompts/asset_parse.py`, add parent assignment constants and builders after the current CKP topic extraction builders:

```python
CKP_PARENT_TOPIC_ASSIGNMENT_SYSTEM_PROMPT = (
    "You are Prism's CKP parent topic builder. "
    "Return strict JSON only. Do not output Markdown."
)

CKP_PARENT_TOPIC_ASSIGNMENT_TASK = (
    "Group child CKP topic clusters into broader parent CKP topics. "
    "A parent CKP is a global theme that can contain multiple child CKPs."
)

CKP_PARENT_TOPIC_ASSIGNMENT_RULES = [
    "Use a broad but concrete noun phrase title for each parent topic.",
    "Prefer parent topics that can hold multiple child topics across documents and asset units.",
    "Do not use generic categories such as AI, Notes, Research, or Knowledge as parent titles unless the child topics are truly that broad.",
    "Each parent topic must reference at least one child topic ref.",
    "Do not reference unknown child topic refs.",
    "Return empty parent_topics only when there are no usable child topics.",
]

JSON_SHAPE_CKP_PARENT_TOPIC_ASSIGNMENT: dict[str, Any] = {
    "parent_topics": [
        {
            "local_id": "parent_1",
            "title": "Broad topic noun phrase",
            "description": "Short parent topic description",
            "keywords": ["keyword"],
            "concepts": ["concept"],
            "domains": ["domain"],
            "entities": ["entity"],
            "member_child_refs": ["child_1", "child_2"],
            "confidence": 0.0,
            "reason": "Short parent grouping reason",
        }
    ],
}


def _parent_child_topic_payload(topic: dict[str, Any], max_text_length: int) -> dict[str, Any]:
    return {
        "ref": str(topic.get("ref") or ""),
        "title": str(topic.get("title") or "")[:max_text_length],
        "description": str(topic.get("description") or "")[:max_text_length],
        "keywords": topic.get("keywords") or [],
        "concepts": topic.get("concepts") or [],
        "entities": topic.get("entities") or [],
        "domains": topic.get("domains") or [],
        "member_pku_statements": [
            str(statement or "")[:max_text_length]
            for statement in (topic.get("member_pku_statements") or [])[:8]
        ],
    }


def build_ckp_parent_topic_assignment_request(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    child_topics: list[dict[str, Any]],
    max_child_topics: int = 80,
    max_text_length: int = 700,
) -> str:
    request = {
        "task": CKP_PARENT_TOPIC_ASSIGNMENT_TASK,
        "source": {
            "kind": source_kind,
            "id": source_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
        },
        "child_topics": [
            _parent_child_topic_payload(topic, max_text_length)
            for topic in child_topics[:max_child_topics]
        ],
        "json_shape": JSON_SHAPE_CKP_PARENT_TOPIC_ASSIGNMENT,
        "rules": CKP_PARENT_TOPIC_ASSIGNMENT_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_ckp_parent_topic_assignment_messages(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    child_topics: list[dict[str, Any]],
    max_child_topics: int = 80,
    max_text_length: int = 700,
) -> tuple[str, str]:
    return (
        CKP_PARENT_TOPIC_ASSIGNMENT_SYSTEM_PROMPT,
        build_ckp_parent_topic_assignment_request(
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            child_topics=child_topics,
            max_child_topics=max_child_topics,
            max_text_length=max_text_length,
        ),
    )
```

- [ ] **Step 5: Implement parser dataclasses and parser**

In `backend/app/services/knowledge_governance.py`, import `build_ckp_parent_topic_assignment_messages`.

Add after `CKPTopicExtraction`:

```python
@dataclass(frozen=True)
class ExtractedCKPParentTopic:
    local_id: str
    title: str
    description: str
    keywords: list[str]
    concepts: list[str]
    entities: list[str]
    domains: list[str]
    member_child_refs: list[str]
    confidence: float
    reason: str
    llm_model: str = ""


@dataclass(frozen=True)
class CKPParentTopicAssignment:
    parent_topics: list[ExtractedCKPParentTopic]
    llm_model: str = ""
```

Add after `_parse_ckp_topic_extraction`:

```python
def _parse_ckp_parent_topic_assignment(data: dict[str, Any], *, llm_model: str = "") -> CKPParentTopicAssignment:
    parent_topics: list[ExtractedCKPParentTopic] = []
    for item in data.get("parent_topics") or []:
        if not isinstance(item, dict):
            continue
        title = _normalize_space(str(item.get("title") or ""))
        if not title:
            continue
        refs = [_normalize_space(str(ref or "")) for ref in (item.get("member_child_refs") or [])]
        refs = [ref for ref in refs if ref]
        if not refs:
            continue
        parent_topics.append(
            ExtractedCKPParentTopic(
                local_id=_normalize_space(str(item.get("local_id") or title)),
                title=title,
                description=_normalize_space(str(item.get("description") or "")),
                keywords=_clean_string_list(item.get("keywords")),
                concepts=_clean_string_list(item.get("concepts")),
                entities=_clean_string_list(item.get("entities")),
                domains=_clean_string_list(item.get("domains")),
                member_child_refs=refs,
                confidence=_clamp_confidence(item.get("confidence"), 0.65),
                reason=_normalize_space(str(item.get("reason") or "")),
                llm_model=llm_model,
            )
        )
    return CKPParentTopicAssignment(parent_topics=parent_topics, llm_model=llm_model)
```

- [ ] **Step 6: Verify prompt/parser tests pass**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_build_ckp_parent_topic_assignment_messages_groups_child_topics backend/tests/test_asset_unit_pku_extraction.py::test_parse_ckp_parent_topic_assignment_keeps_valid_parent_topics -q
```

Expected: pass.

## Task 2: Parent CKP Creation And Child Linking

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_knowledge_governance_models.py`

- [ ] **Step 1: Add failing settlement test**

Add to `backend/tests/test_knowledge_governance_models.py` after the document/asset shared CKP test:

```python
def test_asset_unit_settlement_links_child_ckp_to_parent_ckp(db_session, monkeypatch):
    from backend.app.models import CanonicalRelation
    from backend.app.services import knowledge_governance as kg

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            [
                kg.ExtractedPKU(
                    statement="LoRA reduces trainable parameters with low-rank matrices.",
                    unit_type="method",
                    evidence_span="LoRA uses low-rank matrices.",
                    keywords=["LoRA", "fine-tuning"],
                    concepts=["parameter efficient tuning"],
                    entities=[],
                    domains=["AI"],
                    group="LoRA fine-tuning methods",
                    confidence=0.9,
                    reason="explicit",
                    local_id="pku_1",
                )
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            [
                kg.ExtractedCKPTopic(
                    local_id="child_1",
                    title="LoRA fine-tuning methods",
                    description="Parameter-efficient methods for adapting LLMs.",
                    keywords=["LoRA", "fine-tuning"],
                    concepts=["parameter efficient tuning"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_1"],
                    confidence=0.9,
                    reason="shared local topic",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            [
                kg.ExtractedCKPParentTopic(
                    local_id="parent_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["SFT"],
                    entities=[],
                    domains=["AI"],
                    member_child_refs=["child_1"],
                    confidence=0.88,
                    reason="broader topic",
                )
            ]
        ),
    )

    unit = PersonalAssetUnit(
        title="LoRA practice",
        content="LoRA reduces trainable parameters with low-rank matrices.",
        summary="LoRA practice notes.",
        category="AI",
        tags=["LoRA", "fine-tuning"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(unit)
    db_session.flush()

    result = settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    ckps = db_session.query(CanonicalKnowledgePoint).all()
    assert {ckp.title for ckp in ckps} == {"LoRA fine-tuning methods", "LLM fine-tuning"}
    parent = next(ckp for ckp in ckps if ckp.title == "LLM fine-tuning")
    child = next(ckp for ckp in ckps if ckp.title == "LoRA fine-tuning methods")
    assert parent.extra_meta["topic_level"] == "parent"
    assert child.extra_meta["topic_level"] == "child"

    relation = db_session.query(CanonicalRelation).one()
    assert relation.source_canonical_id == child.id
    assert relation.target_canonical_id == parent.id
    assert relation.relation_type == "subtopic_of"
    assert result.canonical_count == 2
```

- [ ] **Step 2: Verify failure**

Run:

```powershell
pytest backend/tests/test_knowledge_governance_models.py::test_asset_unit_settlement_links_child_ckp_to_parent_ckp -q
```

Expected: fails because parent assignment and `CanonicalRelation` creation are missing.

- [ ] **Step 3: Import model and implement LLM parent extraction**

In `backend/app/services/knowledge_governance.py`, import `CanonicalRelation`.

Add after `_extract_ckp_topics_with_llm`:

```python
def _extract_ckp_parent_topics_with_llm(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    summary: str,
    category: str,
    tags: list[str],
    child_topics: list[dict[str, Any]],
) -> CKPParentTopicAssignment:
    if not child_topics or not settings.LLM_API_KEY:
        return CKPParentTopicAssignment(parent_topics=[])
    system_prompt, user_message = build_ckp_parent_topic_assignment_messages(
        source_kind=source_kind,
        source_id=source_id,
        title=title,
        summary=summary,
        category=category,
        tags=tags,
        child_topics=child_topics,
    )
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {}
    return _parse_ckp_parent_topic_assignment(data, llm_model=settings.LLM_MODEL)
```

- [ ] **Step 4: Add hierarchy helpers**

Add before `_settle_local_pku_topics`:

```python
def _topic_level(ckp: CanonicalKnowledgePoint) -> str:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    level = str(meta.get("topic_level") or "").strip().lower()
    return level or "child"


def _parent_topic_payload(ref: str, topic: ExtractedCKPTopic, member_pkus: list[PersonalKnowledgeUnit]) -> dict[str, Any]:
    return {
        "ref": ref,
        "title": topic.title,
        "description": topic.description,
        "keywords": topic.keywords,
        "concepts": topic.concepts,
        "entities": topic.entities,
        "domains": topic.domains,
        "member_pku_statements": [pku.statement for pku in member_pkus[:8]],
    }


def _fallback_parent_topic(
    *,
    child_topic: ExtractedCKPTopic,
    source_title: str,
    source_category: str,
) -> ExtractedCKPParentTopic:
    title = _normalize_space(source_category) or _normalize_space(source_title) or child_topic.title
    if title.lower() in {"ai", "notes", "research", "knowledge"}:
        title = child_topic.title
    return ExtractedCKPParentTopic(
        local_id=f"parent:{child_topic.local_id}",
        title=title,
        description=child_topic.description or f"Topic group for {title}.",
        keywords=child_topic.keywords,
        concepts=child_topic.concepts,
        entities=child_topic.entities,
        domains=child_topic.domains,
        member_child_refs=[child_topic.local_id],
        confidence=max(0.55, child_topic.confidence - 0.1),
        reason="Fallback parent topic from source metadata and child topic.",
        llm_model="",
    )


def _create_or_get_parent_topic_ckp(
    db: Session,
    *,
    user_id: str,
    parent_topic: ExtractedCKPParentTopic,
    source_kind: str,
    source_id: str,
    source_title: str,
) -> CanonicalKnowledgePoint:
    existing = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.user_id == user_id,
            CanonicalKnowledgePoint.status != "deprecated",
            CanonicalKnowledgePoint.canonical_type == "topic",
            CanonicalKnowledgePoint.title == parent_topic.title,
        )
        .all()
    )
    for candidate in existing:
        if _topic_level(candidate) == "parent":
            return candidate
    ckp = CanonicalKnowledgePoint(
        user_id=user_id,
        canonical_type="topic",
        title=_short_title(parent_topic.title, "Untitled parent topic"),
        canonical_statement=parent_topic.description or f"Topic hub for {parent_topic.title}.",
        summary=parent_topic.description,
        aliases=[source_title] if source_title and source_title != parent_topic.title else [],
        domains=parent_topic.domains,
        entities=parent_topic.entities,
        concepts=parent_topic.concepts,
        keywords=parent_topic.keywords,
        scope={},
        conditions={},
        status="draft",
        confidence=parent_topic.confidence,
        extra_meta={
            "topic_level": "parent",
            "created_from": "global_topic_rollup",
            "source_kind": source_kind,
            "source_id": source_id,
            "source_title": source_title,
            "parent_topic_local_id": parent_topic.local_id,
            "parent_topic_reason": parent_topic.reason,
            "parent_topic_llm_model": parent_topic.llm_model,
        },
    )
    db.add(ckp)
    db.flush()
    _refresh_ckp_vector(ckp)
    return ckp


def _create_or_get_ckp_hierarchy_relation(
    db: Session,
    *,
    user_id: str,
    child: CanonicalKnowledgePoint,
    parent: CanonicalKnowledgePoint,
    confidence: float,
    reason: str,
) -> CanonicalRelation | None:
    if child.id == parent.id:
        return None
    existing = (
        db.query(CanonicalRelation)
        .filter(
            CanonicalRelation.source_canonical_id == child.id,
            CanonicalRelation.target_canonical_id == parent.id,
            CanonicalRelation.relation_type == "subtopic_of",
        )
        .first()
    )
    if existing:
        return existing
    relation = CanonicalRelation(
        user_id=user_id,
        source_canonical_id=child.id,
        target_canonical_id=parent.id,
        relation_type="subtopic_of",
        confidence=confidence,
        reason=reason,
        extra_meta={},
    )
    db.add(relation)
    db.flush()
    return relation
```

- [ ] **Step 5: Mark local CKPs as child**

In `_create_or_get_topic_ckp`, add `topic_level` to new CKP metadata:

```python
        extra_meta={
            "topic_level": "child",
            "created_from": source_kind,
            "source_id": source_id,
            "source_title": source_title,
            "topic_local_id": topic.local_id,
            "topic_reason": topic.reason,
            "topic_llm_model": topic.llm_model,
        },
```

If an existing CKP is reused and has no `topic_level`, update `existing.extra_meta` to include `"topic_level": "child"` before returning.

- [ ] **Step 6: Extend `_settle_local_pku_topics`**

Inside `_settle_local_pku_topics`, record each local topic CKP:

```python
    child_topic_refs: dict[str, tuple[ExtractedCKPTopic, CanonicalKnowledgePoint, list[PersonalKnowledgeUnit]]] = {}
    parent_relation_ids: set[str] = set()
```

After each child CKP is created:

```python
        child_topic_refs[topic.local_id] = (topic, ckp, [ref_to_pku[ref] for ref in member_refs])
```

Before returning, assign parent topics:

```python
    if child_topic_refs:
        parent_assignment = _extract_ckp_parent_topics_with_llm(
            source_kind=source_kind,
            source_id=source_id,
            title=source_title,
            summary=source_summary,
            category=source_category,
            tags=source_tags or [],
            child_topics=[
                _parent_topic_payload(ref, topic, member_pkus)
                for ref, (topic, _ckp, member_pkus) in child_topic_refs.items()
            ],
        )
        parent_topics = list(parent_assignment.parent_topics)
        if not parent_topics:
            parent_topics = [
                _fallback_parent_topic(
                    child_topic=topic,
                    source_title=source_title,
                    source_category=source_category,
                )
                for topic, _ckp, _member_pkus in child_topic_refs.values()
            ]
        linked_child_ids: set[str] = set()
        for parent_topic in parent_topics:
            member_child_refs = [ref for ref in parent_topic.member_child_refs if ref in child_topic_refs]
            if not member_child_refs:
                continue
            parent_ckp = _create_or_get_parent_topic_ckp(
                db,
                user_id=user_id,
                parent_topic=parent_topic,
                source_kind=source_kind,
                source_id=source_id,
                source_title=source_title,
            )
            ckp_ids.add(parent_ckp.id)
            for child_ref in member_child_refs:
                _topic, child_ckp, _member_pkus = child_topic_refs[child_ref]
                relation = _create_or_get_ckp_hierarchy_relation(
                    db,
                    user_id=user_id,
                    child=child_ckp,
                    parent=parent_ckp,
                    confidence=parent_topic.confidence,
                    reason=parent_topic.reason or "Parent CKP assignment from local topic grouping.",
                )
                if relation:
                    parent_relation_ids.add(relation.id)
                    linked_child_ids.add(child_ckp.id)
        for _child_ref, (topic, child_ckp, _member_pkus) in child_topic_refs.items():
            if child_ckp.id in linked_child_ids:
                continue
            fallback_parent = _fallback_parent_topic(
                child_topic=topic,
                source_title=source_title,
                source_category=source_category,
            )
            parent_ckp = _create_or_get_parent_topic_ckp(
                db,
                user_id=user_id,
                parent_topic=fallback_parent,
                source_kind=source_kind,
                source_id=source_id,
                source_title=source_title,
            )
            ckp_ids.add(parent_ckp.id)
            relation = _create_or_get_ckp_hierarchy_relation(
                db,
                user_id=user_id,
                child=child_ckp,
                parent=parent_ckp,
                confidence=fallback_parent.confidence,
                reason=fallback_parent.reason,
            )
            if relation:
                parent_relation_ids.add(relation.id)
```

Return:

```python
    return (len(ckp_ids), len(link_ids) + len(parent_relation_ids))
```

- [ ] **Step 7: Verify governance tests**

Run:

```powershell
pytest backend/tests/test_knowledge_governance_models.py::test_asset_unit_settlement_links_child_ckp_to_parent_ckp backend/tests/test_knowledge_governance_models.py::test_document_and_asset_unit_pkus_can_share_ckp_with_distinct_roles -q
```

Expected: pass. If the older shared CKP test assumes exactly one CKP, update it to assert one shared child CKP plus one parent CKP.

## Task 3: Graph API Hierarchy Payload

**Files:**
- Modify: `backend/app/api/knowledge_graph.py`
- Test: `backend/tests/test_knowledge_graph_api.py`

- [ ] **Step 1: Add failing Workbench hierarchy API test**

Add to `backend/tests/test_knowledge_graph_api.py`:

```python
def test_knowledge_graph_workbench_groups_child_ckps_under_parent(client, db_session):
    from backend.app.models import CanonicalKnowledgePoint, CanonicalRelation, PKUCanonicalLink

    parent = CanonicalKnowledgePoint(
        title="LLM fine-tuning",
        canonical_statement="Methods and rules for adapting large language models.",
        canonical_type="topic",
        status="draft",
        confidence=0.9,
        extra_meta={"topic_level": "parent"},
    )
    child = CanonicalKnowledgePoint(
        title="LoRA fine-tuning methods",
        canonical_statement="Parameter-efficient methods for adapting LLMs.",
        canonical_type="topic",
        status="draft",
        confidence=0.88,
        extra_meta={"topic_level": "child"},
    )
    unit = PersonalAssetUnit(id="unit-1", title="LoRA note", content="LoRA reduces trainable parameters.")
    pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id="unit-1",
        statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement_hash="hierarchy-pku",
        unit_type="method",
        modality="fact",
        status="active",
        confidence=0.9,
        keywords=["LoRA"],
    )
    db_session.add_all([parent, child, unit, pku])
    db_session.flush()
    db_session.add_all(
        [
            CanonicalRelation(
                source_canonical_id=child.id,
                target_canonical_id=parent.id,
                relation_type="subtopic_of",
                confidence=0.87,
                reason="child belongs to parent",
            ),
            PKUCanonicalLink(
                pku_id=pku.id,
                canonical_id=child.id,
                relation_type="about",
                role="topic_member",
                confidence=0.9,
                reason="member",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph/workbench")
    assert response.status_code == 200
    payload = response.json()

    assert payload["parents"][0]["label"] == "LLM fine-tuning"
    parent_group = payload["parent_groups"][payload["parents"][0]["id"]]
    assert parent_group["children"][0]["ckp"]["label"] == "LoRA fine-tuning methods"
    assert parent_group["children"][0]["pkus"][0]["pku"]["label"] == "LoRA reduces trainable parameters with low-rank matrices."
    assert parent_group["children"][0]["parent_link"]["type"] == "canonical_relation"
    assert parent_group["children"][0]["parent_link"]["label"] == "subtopic_of"
```

- [ ] **Step 2: Add failing network hierarchy API test**

Add:

```python
def test_knowledge_graph_returns_parent_child_ckp_edges(client, db_session):
    from backend.app.models import CanonicalKnowledgePoint, CanonicalRelation

    parent = CanonicalKnowledgePoint(
        title="LLM fine-tuning",
        canonical_statement="Methods and rules for adapting large language models.",
        canonical_type="topic",
        status="draft",
        confidence=0.9,
        extra_meta={"topic_level": "parent"},
    )
    child = CanonicalKnowledgePoint(
        title="LoRA fine-tuning methods",
        canonical_statement="Parameter-efficient methods for adapting LLMs.",
        canonical_type="topic",
        status="draft",
        confidence=0.88,
        extra_meta={"topic_level": "child"},
    )
    db_session.add_all([parent, child])
    db_session.flush()
    db_session.add(
        CanonicalRelation(
            source_canonical_id=child.id,
            target_canonical_id=parent.id,
            relation_type="subtopic_of",
            confidence=0.87,
            reason="child belongs to parent",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph?q=fine-tuning")
    assert response.status_code == 200
    payload = response.json()

    node_by_label = {node["label"]: node for node in payload["nodes"]}
    assert node_by_label["LLM fine-tuning"]["topic_level"] == "parent"
    assert node_by_label["LoRA fine-tuning methods"]["topic_level"] == "child"
    hierarchy_edges = [edge for edge in payload["edges"] if edge["type"] == "canonical_relation"]
    assert hierarchy_edges[0]["source"] == node_by_label["LLM fine-tuning"]["id"]
    assert hierarchy_edges[0]["target"] == node_by_label["LoRA fine-tuning methods"]["id"]
    assert hierarchy_edges[0]["label"] == "subtopic_of"
```

- [ ] **Step 3: Verify failure**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_workbench_groups_child_ckps_under_parent backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_returns_parent_child_ckp_edges -q
```

Expected: fails because hierarchy payload is not implemented.

- [ ] **Step 4: Serialize topic levels and canonical hierarchy edges**

In `backend/app/api/knowledge_graph.py`, import `CanonicalRelation`.

Add:

```python
def _ckp_topic_level(canonical: CanonicalKnowledgePoint) -> str:
    meta = canonical.extra_meta if isinstance(canonical.extra_meta, dict) else {}
    level = str(meta.get("topic_level") or "").strip().lower()
    return level if level in {"parent", "child"} else "child"
```

Add `topic_level=_ckp_topic_level(canonical)` to `_serialize_canonical`.

Add:

```python
def _canonical_relation_edge(relation: CanonicalRelation, *, parent_to_child: bool = True) -> dict[str, Any]:
    source = f"ckp:{relation.target_canonical_id}" if parent_to_child else f"ckp:{relation.source_canonical_id}"
    target = f"ckp:{relation.source_canonical_id}" if parent_to_child else f"ckp:{relation.target_canonical_id}"
    return _edge(
        f"edge:canonical_relation:{relation.id}",
        source,
        target,
        "canonical_relation",
        relation.relation_type,
        confidence=relation.confidence,
        reason=relation.reason,
    )
```

- [ ] **Step 5: Extend Workbench response**

Keep existing `ckps`, `groups`, and `stats`. Add transition fields:

```python
"parents": parents,
"parent_groups": parent_groups,
```

Implementation shape:

1. Query all `CanonicalRelation(relation_type="subtopic_of")`.
2. Build `child_to_relation` by `source_canonical_id`.
3. Load parent CKPs by `target_canonical_id`.
4. For each current child `ckp` group, place it under its parent if one exists.
5. If no parent exists, use that CKP as a compatibility parent with a single child and `parent_link=None`.
6. Compute each parent group's `child_count`, `pku_count`, and `source_count`.

Use this payload shape:

```python
parent_groups[parent_node_id] = {
    "parent": parent_node,
    "children": [
        {
            **groups[child_node_id],
            "parent_link": _canonical_relation_edge(relation, parent_to_child=True),
        }
    ],
    "stats": {"child_count": 1, "pku_count": 1, "source_count": 1},
}
```

- [ ] **Step 6: Extend network graph response**

In `get_knowledge_graph`, query relevant `subtopic_of` relations where either source or target is in `canonical_ids`. Add missing parent/child CKP nodes, then add `canonical_relation` edges from parent to child using `_canonical_relation_edge(..., parent_to_child=True)`.

- [ ] **Step 7: Verify API tests**

Run:

```powershell
pytest backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_workbench_groups_child_ckps_under_parent backend/tests/test_knowledge_graph_api.py::test_knowledge_graph_returns_parent_child_ckp_edges -q
```

Expected: pass.

## Task 4: Frontend Types And Workbench UI

**Files:**
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/pages/KnowledgeGraphWorkbench.tsx`

- [ ] **Step 1: Update API types**

In `frontend/src/app/api.ts`, change:

```ts
export type KnowledgeGraphEdgeType = 'canonical_pku' | 'pku_source' | 'pku_relation' | 'canonical_relation'
```

Add to `KnowledgeGraphNode`:

```ts
  topic_level?: 'parent' | 'child' | string
  child_count?: number
  pku_count?: number
  source_count?: number
```

Add:

```ts
export interface KnowledgeGraphWorkbenchChildGroup extends KnowledgeGraphWorkbenchGroup {
  parent_link?: KnowledgeGraphEdge | null
}

export interface KnowledgeGraphWorkbenchParentGroup {
  parent: KnowledgeGraphNode & {
    child_count?: number
    pku_count?: number
    source_count?: number
  }
  children: KnowledgeGraphWorkbenchChildGroup[]
  stats: {
    child_count: number
    pku_count: number
    source_count: number
  }
}
```

Extend `KnowledgeGraphWorkbenchPayload`:

```ts
  parents?: Array<
    KnowledgeGraphNode & {
      child_count?: number
      pku_count?: number
      source_count?: number
    }
  >
  parent_groups?: Record<string, KnowledgeGraphWorkbenchParentGroup>
```

- [ ] **Step 2: Add parent selection state**

In `KnowledgeGraphWorkbench.tsx`, import `KnowledgeGraphWorkbenchParentGroup`.

Add:

```ts
  const [selectedParentId, setSelectedParentId] = useState<string | null>(null)
  const selectedParentGroup = selectedParentId && payload?.parent_groups ? payload.parent_groups[selectedParentId] : null
```

In `loadWorkbench`, after data is loaded:

```ts
      const parents = data.parents?.length ? data.parents : data.ckps
      const nextParentId = parents.some((parent) => parent.id === selectedParentId)
        ? selectedParentId
        : parents[0]?.id ?? null
      const nextParentGroup = nextParentId && data.parent_groups ? data.parent_groups[nextParentId] : null
      const nextChildId = nextParentGroup?.children.some((child) => child.ckp.id === selectedCkpId)
        ? selectedCkpId
        : nextParentGroup?.children[0]?.ckp.id ?? data.ckps[0]?.id ?? null
      setSelectedParentId(nextParentId)
      setSelectedCkpId(nextChildId)
      setSelection(nextChildId ? { kind: 'ckp', node: data.groups[nextChildId].ckp } : null)
```

- [ ] **Step 3: Change left list to parent CKPs**

Use:

```tsx
const parentList = payload?.parents?.length ? payload.parents : payload?.ckps ?? []
```

Map `parentList` instead of `payload.ckps`. On click:

```tsx
setSelectedParentId(parent.id)
const parentGroup = payload?.parent_groups?.[parent.id]
const firstChild = parentGroup?.children[0]
setSelectedCkpId(firstChild?.ckp.id ?? parent.id)
setSelection({ kind: 'ckp', node: firstChild?.ckp ?? parent })
```

Show `parent.child_count ?? 1` as child CKP count and keep `pku_count/source_count`.

- [ ] **Step 4: Add child CKP selector in middle column**

Before the current CKP header section, render:

```tsx
{selectedParentGroup ? (
  <section className="mb-4 rounded-lg border border-[var(--prism-line)] bg-white p-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold uppercase text-slate-500">Child CKP</span>
      {selectedParentGroup.children.map((child) => (
        <button
          key={child.ckp.id}
          type="button"
          onClick={() => {
            setSelectedCkpId(child.ckp.id)
            setSelection({ kind: 'ckp', node: child.ckp })
          }}
          className={cn(
            'rounded-md border px-2.5 py-1.5 text-xs font-medium transition',
            selectedCkpId === child.ckp.id
              ? 'border-blue-300 bg-blue-50 text-blue-700'
              : 'border-[var(--prism-line)] bg-white text-slate-600 hover:bg-slate-50',
          )}
        >
          {child.ckp.label}
        </button>
      ))}
    </div>
  </section>
) : null}
```

- [ ] **Step 5: Build frontend**

Run from `frontend`:

```powershell
npm.cmd run build
```

Expected: pass. Existing Vite chunk warning is acceptable.

## Task 5: Network Graph Parent/Child Display

**Files:**
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`

- [ ] **Step 1: Style canonical hierarchy edges**

In `edgeStyle`, add:

```ts
  if (edge.type === 'canonical_relation') {
    return {
      stroke: active ? '#155eef' : '#93c5fd',
      strokeWidth: active ? 2.6 : 1.8,
      strokeDasharray: undefined,
    }
  }
```

- [ ] **Step 2: Place parent CKPs before child CKPs**

In `createInitialPositions`, split canonical nodes:

```ts
const parentCanonicals = nodes.filter((node) => node.type === 'canonical' && node.topic_level === 'parent')
const childCanonicals = nodes.filter((node) => node.type === 'canonical' && node.topic_level !== 'parent')
```

Use x positions roughly:

```ts
parent canonical: 120
child canonical: 300
pku: 520
asset: 760
personal_asset_unit: 930
document_chunk: 1020
```

Keep backend node type as `canonical`; only frontend positioning changes.

- [ ] **Step 3: Label parent CKPs distinctly**

When rendering canonical nodes, display `父 CKP` or `Parent CKP` for `topic_level === 'parent'`, and keep existing CKP label for child CKPs.

- [ ] **Step 4: Build frontend**

Run from `frontend`:

```powershell
npm.cmd run build
```

Expected: pass.

## Task 6: Full Verification

**Files:**
- No code changes unless verification reveals defects.

- [ ] **Step 1: Run backend targeted tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py backend/tests/test_knowledge_governance_models.py backend/tests/test_knowledge_graph_api.py -q
```

Expected: pass.

- [ ] **Step 2: Run frontend build**

Run from `frontend`:

```powershell
npm.cmd run build
```

Expected: pass. Existing chunk-size warning is acceptable.

- [ ] **Step 3: Inspect diff**

Run:

```powershell
git diff --stat
git diff -- backend/app/services/knowledge_governance.py backend/app/api/knowledge_graph.py frontend/src/pages/KnowledgeGraphWorkbench.tsx
```

Expected: changes are limited to parent-child CKP hierarchy, API payload, and Workbench/network display. Do not revert unrelated existing changes.
