# CKP Topic Hub Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change CKP settlement from one-PKU canonical copies into local-first topic hubs that group related PKUs with `relation_type="about"`.

**Architecture:** Add a topic-candidate extraction layer after PKU extraction. Document and personal asset unit settlement will persist PKUs first, group the local PKU set into topic candidates, match those candidates against global topic CKPs, then attach member PKUs to CKPs with `about` links. Existing `same_as` data stays readable for backward compatibility.

**Tech Stack:** Python, FastAPI, SQLAlchemy ORM, pytest, OpenAI-compatible chat completions, existing Milvus CKP vector helper, React/Vite for graph display compatibility.

---

## File Structure

- Modify `backend/app/prompts/asset_parse.py`
  - Add topic-hub prompt constants and `build_ckp_topic_extraction_messages(...)`.
- Modify `backend/app/services/knowledge_governance.py`
  - Add topic dataclasses and parsing helpers.
  - Add local topic extraction and fallback.
  - Add topic-to-CKP matching and creation helpers.
  - Refactor `settle_personal_asset_unit_to_governance(...)`.
  - Refactor `settle_document_item_to_governance(...)`.
  - Mark document-created orphan CKPs as deprecated during `clear_document_item_governance(...)`.
- Modify `backend/tests/test_asset_unit_pku_extraction.py`
  - Add prompt builder coverage for topic extraction.
- Modify `backend/tests/test_document_chunk_pku_extraction.py`
  - Add document local topic aggregation coverage.
- Modify `backend/tests/test_knowledge_governance_models.py`
  - Update existing expectations where new settlement links use `about`.
- Modify `backend/tests/test_knowledge_graph_api.py`
  - Ensure graph/workbench accepts both old `same_as` and new `about`.
- Modify `frontend/src/pages/KnowledgeGraphWorkbench.tsx`
  - Keep showing the link label; optionally render `about` as topic membership text if there is already a label map.

No database migration is required for the first pass because `canonical_type` and `relation_type` are existing string fields and `extra_meta` already exists.

Commit steps are intentionally omitted because the current workspace instruction is no commits unless the user asks.

---

### Task 1: Add Topic-Hub Prompt Builder

**Files:**
- Modify: `backend/app/prompts/asset_parse.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write the failing prompt-builder test**

Add this test near the other prompt builder tests in `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_build_ckp_topic_extraction_messages_group_pkus_into_topics():
    from backend.app.prompts.asset_parse import build_ckp_topic_extraction_messages

    system_prompt, user_message = build_ckp_topic_extraction_messages(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM fine-tuning guide",
        summary="LoRA, SFT data, and evaluation practices.",
        category="AI",
        tags=["fine-tuning", "LoRA"],
        pkus=[
            {
                "ref": "pku_1",
                "statement": "LoRA reduces trainable parameters with low-rank matrices.",
                "unit_type": "method",
                "keywords": ["LoRA", "fine-tuning"],
                "concepts": ["parameter efficient tuning"],
                "entities": [],
                "domains": ["AI"],
                "evidence_span": "LoRA uses low-rank matrices.",
            },
            {
                "ref": "pku_2",
                "statement": "Fine-tuning evaluation should use a held-out validation set.",
                "unit_type": "rule",
                "keywords": ["evaluation", "fine-tuning"],
                "concepts": ["validation"],
                "entities": [],
                "domains": ["AI"],
                "evidence_span": "Use held-out validation data.",
            },
        ],
    )

    request = json.loads(user_message)

    assert "JSON" in system_prompt
    assert request["source"]["kind"] == "knowledge_item"
    assert request["source"]["id"] == "item-1"
    assert request["source"]["title"] == "LLM fine-tuning guide"
    assert request["pkus"][0]["ref"] == "pku_1"
    assert request["json_shape"]["topics"][0]["title"] == "Topic noun phrase"
    assert request["json_shape"]["topics"][0]["member_pku_refs"] == ["pku_1", "pku_2"]
    assert any("topic" in rule.lower() for rule in request["rules"])
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_build_ckp_topic_extraction_messages_group_pkus_into_topics -q
```

Expected: FAIL with an import error for `build_ckp_topic_extraction_messages`.

- [ ] **Step 3: Add the prompt builder**

Append this section after the document PKU extraction prompt section in `backend/app/prompts/asset_parse.py`:

```python
# ---------------------------------------------------------------------------
# CKP Topic Extraction (local PKU set -> topic hub candidates)
# ---------------------------------------------------------------------------

CKP_TOPIC_EXTRACTION_SYSTEM_PROMPT = (
    "You are Prism's CKP topic hub extractor. "
    "Return strict JSON only. Do not output Markdown."
)

CKP_TOPIC_EXTRACTION_TASK = (
    "Group a local set of PKUs into concise CKP topic hubs. "
    "A CKP is a reusable topic node, not a restatement of one PKU."
)

CKP_TOPIC_EXTRACTION_RULES = [
    "A topic title must be a concise noun phrase, not a full claim.",
    "Prefer fewer meaningful topic hubs over one topic per PKU.",
    "Each topic must reference at least one local PKU ref in member_pku_refs.",
    "Do not include member_pku_refs that are not present in the input pkus.",
    "Use the source title and metadata as context, but group by the PKU meanings.",
    "Return an empty topics array only when there are no usable PKUs.",
]

JSON_SHAPE_CKP_TOPIC_EXTRACTION: dict[str, Any] = {
    "topics": [
        {
            "local_id": "topic_1",
            "title": "Topic noun phrase",
            "description": "Short description of the topic hub",
            "keywords": ["keyword"],
            "concepts": ["concept"],
            "domains": ["domain"],
            "entities": ["entity"],
            "member_pku_refs": ["pku_1", "pku_2"],
            "confidence": 0.0,
            "reason": "Short grouping reason",
        }
    ]
}


def build_ckp_topic_extraction_request(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    pkus: list[dict[str, Any]],
    max_pkus: int = 80,
    max_statement_length: int = 700,
) -> str:
    """Build the user message JSON for local PKU topic grouping."""
    normalized_pkus = []
    for pku in pkus[:max_pkus]:
        normalized_pkus.append(
            {
                "ref": str(pku.get("ref") or ""),
                "statement": str(pku.get("statement") or "")[:max_statement_length],
                "unit_type": str(pku.get("unit_type") or ""),
                "keywords": pku.get("keywords") or [],
                "concepts": pku.get("concepts") or [],
                "entities": pku.get("entities") or [],
                "domains": pku.get("domains") or [],
                "evidence_span": str(pku.get("evidence_span") or "")[:max_statement_length],
            }
        )
    request = {
        "task": CKP_TOPIC_EXTRACTION_TASK,
        "source": {
            "kind": source_kind,
            "id": source_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
        },
        "pkus": normalized_pkus,
        "json_shape": JSON_SHAPE_CKP_TOPIC_EXTRACTION,
        "rules": CKP_TOPIC_EXTRACTION_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_ckp_topic_extraction_messages(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    pkus: list[dict[str, Any]],
) -> tuple[str, str]:
    """Build the system and user messages for local PKU topic grouping."""
    return (
        CKP_TOPIC_EXTRACTION_SYSTEM_PROMPT,
        build_ckp_topic_extraction_request(
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            pkus=pkus,
        ),
    )
```

- [ ] **Step 4: Run the test**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_build_ckp_topic_extraction_messages_group_pkus_into_topics -q
```

Expected: PASS.

---

### Task 2: Add Topic Candidate Dataclasses, Parser, and LLM Extraction

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write parser and extractor tests**

Add these tests to `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_parse_ckp_topic_extraction_keeps_valid_topics():
    from backend.app.services import knowledge_governance as kg

    result = kg._parse_ckp_topic_extraction(
        {
            "topics": [
                {
                    "local_id": "topic_1",
                    "title": "LLM fine-tuning",
                    "description": "Methods and rules for adapting large language models.",
                    "keywords": ["fine-tuning", "LoRA"],
                    "concepts": ["SFT"],
                    "domains": ["AI"],
                    "entities": [],
                    "member_pku_refs": ["pku_1", "pku_2"],
                    "confidence": 0.88,
                    "reason": "Both PKUs discuss fine-tuning.",
                },
                {
                    "local_id": "bad",
                    "title": "",
                    "member_pku_refs": ["pku_3"],
                },
            ]
        },
        llm_model="qwen-plus",
    )

    assert len(result.topics) == 1
    assert result.topics[0].local_id == "topic_1"
    assert result.topics[0].title == "LLM fine-tuning"
    assert result.topics[0].member_pku_refs == ["pku_1", "pku_2"]
    assert result.topics[0].llm_model == "qwen-plus"


def test_extract_ckp_topics_uses_main_llm(monkeypatch):
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = (
            '{"topics":[{"local_id":"topic_1","title":"LLM fine-tuning",'
            '"description":"Fine-tuning methods and rules.",'
            '"keywords":["fine-tuning"],"member_pku_refs":["pku_1"],'
            '"confidence":0.9,"reason":"shared topic"}]}'
        )

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

    result = kg._extract_ckp_topics_with_llm(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM guide",
        summary="Fine-tuning guide.",
        category="AI",
        tags=["fine-tuning"],
        pkus=[
            {
                "ref": "pku_1",
                "statement": "LoRA reduces trainable parameters.",
                "unit_type": "method",
                "keywords": ["LoRA"],
            }
        ],
    )

    assert captured["model"] == "qwen-plus"
    assert result.llm_model == "qwen-plus"
    assert result.topics[0].title == "LLM fine-tuning"
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_parse_ckp_topic_extraction_keeps_valid_topics backend/tests/test_asset_unit_pku_extraction.py::test_extract_ckp_topics_uses_main_llm -q
```

Expected: FAIL because topic dataclasses and helpers do not exist.

- [ ] **Step 3: Add imports and dataclasses**

In `backend/app/services/knowledge_governance.py`, add `build_ckp_topic_extraction_messages` to the existing prompt imports:

```python
from backend.app.prompts.asset_parse import (
    build_asset_unit_pku_extraction_messages,
    build_ckp_topic_extraction_messages,
    build_document_chunk_pku_extraction_messages,
)
```

Add these dataclasses after `AssetUnitPKUExtraction`:

```python
@dataclass(frozen=True)
class ExtractedCKPTopic:
    local_id: str
    title: str
    description: str
    keywords: list[str]
    concepts: list[str]
    entities: list[str]
    domains: list[str]
    member_pku_refs: list[str]
    confidence: float
    reason: str
    llm_model: str = ""


@dataclass(frozen=True)
class CKPTopicExtraction:
    topics: list[ExtractedCKPTopic]
    llm_model: str = ""
```

- [ ] **Step 4: Add parser and extractor helpers**

Add these helpers after `_parse_asset_unit_pku_extraction(...)`:

```python
def _parse_ckp_topic_extraction(data: dict[str, Any], *, llm_model: str = "") -> CKPTopicExtraction:
    topics: list[ExtractedCKPTopic] = []
    for item in _as_list(data.get("topics")):
        if not isinstance(item, dict):
            continue
        title = _normalize_space(str(item.get("title") or item.get("name") or ""))
        refs = [
            _normalize_space(str(ref))
            for ref in _as_list(item.get("member_pku_refs") or item.get("members") or item.get("pku_refs"))
            if _normalize_space(str(ref))
        ]
        if not title or not refs:
            continue
        topics.append(
            ExtractedCKPTopic(
                local_id=_normalize_space(str(item.get("local_id") or item.get("id") or title))[:120],
                title=title[:255],
                description=_normalize_space(str(item.get("description") or item.get("summary") or ""))[:1200],
                keywords=[str(value)[:120] for value in _as_list(item.get("keywords")) if str(value).strip()][:12],
                concepts=[str(value)[:120] for value in _as_list(item.get("concepts")) if str(value).strip()][:12],
                entities=[str(value)[:120] for value in _as_list(item.get("entities")) if str(value).strip()][:12],
                domains=[str(value)[:120] for value in _as_list(item.get("domains")) if str(value).strip()][:8],
                member_pku_refs=refs[:80],
                confidence=_clamp_confidence(item.get("confidence"), 0.75),
                reason=_normalize_space(str(item.get("reason") or ""))[:500],
                llm_model=llm_model,
            )
        )
    return CKPTopicExtraction(topics=topics, llm_model=llm_model)


def _extract_ckp_topics_with_llm(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    pkus: list[dict[str, Any]],
) -> CKPTopicExtraction:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY or not pkus:
        return CKPTopicExtraction([], llm_model="")
    try:
        system_prompt, user_message = build_ckp_topic_extraction_messages(
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags or [],
            pkus=pkus,
        )
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
        data = _parse_json_object(response.choices[0].message.content or "{}")
        return _parse_ckp_topic_extraction(data, llm_model=settings.LLM_MODEL)
    except Exception:
        return CKPTopicExtraction([], llm_model="")
```

- [ ] **Step 5: Run the tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_parse_ckp_topic_extraction_keeps_valid_topics backend/tests/test_asset_unit_pku_extraction.py::test_extract_ckp_topics_uses_main_llm -q
```

Expected: PASS.

---

### Task 3: Add Topic Matching, Creation, and Linking Helpers

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write tests for topic CKP creation and reuse**

Add these tests to `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_create_or_get_topic_ckp_creates_topic_hub_not_pku_copy(db_session, monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement_hash="topic-create-pku",
        keywords=["LoRA"],
        status="active",
    )
    db_session.add(pku)
    db_session.flush()
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    topic = kg.ExtractedCKPTopic(
        local_id="topic_1",
        title="LLM fine-tuning",
        description="Methods and rules for adapting large language models.",
        keywords=["fine-tuning", "LoRA"],
        concepts=["SFT"],
        entities=[],
        domains=["AI"],
        member_pku_refs=["pku_1"],
        confidence=0.89,
        reason="shared fine-tuning topic",
        llm_model="qwen-plus",
    )

    ckp = kg._create_or_get_topic_ckp(
        db_session,
        user_id="default-user",
        topic=topic,
        source_kind="personal_asset_unit",
        source_id="unit-1",
        source_title="Fine-tuning note",
    )

    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    assert ckp.canonical_statement == "Methods and rules for adapting large language models."
    assert ckp.canonical_statement != pku.normalized_statement
    assert ckp.extra_meta["created_from"] == "personal_asset_unit"
    assert ckp.extra_meta["topic_reason"] == "shared fine-tuning topic"


def test_find_existing_topic_ckp_reuses_high_vector_similarity(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    existing = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="LLM fine-tuning",
        canonical_statement="Fine-tuning methods for large language models.",
        keywords=["fine-tuning", "LoRA"],
        confidence=0.9,
        status="draft",
    )
    db_session.add(existing)
    db_session.commit()
    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": existing.id, "score": 0.84}],
    )

    topic = kg.ExtractedCKPTopic(
        local_id="topic_1",
        title="Large language model fine-tuning",
        description="LoRA and SFT practices.",
        keywords=["fine-tuning", "LoRA"],
        concepts=[],
        entities=[],
        domains=["AI"],
        member_pku_refs=["pku_1"],
        confidence=0.86,
        reason="same topic",
    )

    result = kg._find_existing_topic_ckp(db_session, user_id="default-user", topic=topic)

    assert result.id == existing.id


def test_create_or_get_topic_link_uses_about_relation(db_session):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters.",
        normalized_statement="LoRA reduces trainable parameters.",
        normalized_statement_hash="topic-about-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="LLM fine-tuning",
        canonical_statement="Fine-tuning topic hub.",
    )
    db_session.add_all([pku, ckp])
    db_session.flush()

    link = kg._create_or_get_generic_link(
        db_session,
        user_id="default-user",
        pku=pku,
        ckp=ckp,
        relation_type="about",
        role="topic_member",
        reason="PKU belongs to the topic.",
    )

    assert link.relation_type == "about"
    assert link.role == "topic_member"
    assert db_session.query(PKUCanonicalLink).count() == 1
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_create_or_get_topic_ckp_creates_topic_hub_not_pku_copy backend/tests/test_asset_unit_pku_extraction.py::test_find_existing_topic_ckp_reuses_high_vector_similarity backend/tests/test_asset_unit_pku_extraction.py::test_create_or_get_topic_link_uses_about_relation -q
```

Expected: FAIL because topic helper functions do not exist.

- [ ] **Step 3: Add topic matching helpers**

Add these helpers near `_find_existing_ckp(...)` in `backend/app/services/knowledge_governance.py`:

```python
def _topic_match_text(topic: ExtractedCKPTopic) -> str:
    return _normalize_space(
        " ".join(
            [
                topic.title,
                topic.description,
                " ".join(topic.keywords),
                " ".join(topic.concepts),
                " ".join(topic.domains),
            ]
        )
    )


def _find_existing_topic_ckp(
    db: Session,
    *,
    user_id: str,
    topic: ExtractedCKPTopic,
) -> CanonicalKnowledgePoint | None:
    title = _normalize_space(topic.title)
    if not title:
        return None
    query = db.query(CanonicalKnowledgePoint).filter(
        CanonicalKnowledgePoint.user_id == user_id,
        CanonicalKnowledgePoint.status != "deprecated",
        CanonicalKnowledgePoint.canonical_type == "topic",
    )
    exact = query.filter(CanonicalKnowledgePoint.title == title).first()
    if exact:
        return exact

    words = [word for word in topic.keywords[:6] if len(word) >= 2]
    candidates = query.filter(CanonicalKnowledgePoint.title.like(f"%{title[:32]}%")).limit(10).all()
    if not candidates and words:
        candidates = query.filter(
            or_(*(CanonicalKnowledgePoint.keywords.like(f"%{word}%") for word in words))
        ).limit(10).all()
    topic_words = set(topic.keywords + topic.concepts + topic.domains)
    best: CanonicalKnowledgePoint | None = None
    best_score = 0
    for candidate in candidates:
        candidate_words = set(_as_list(candidate.keywords) + _as_list(candidate.concepts) + _as_list(candidate.domains))
        title_match = 3 if _normalize_space(candidate.title).lower() == title.lower() else 0
        score = len(topic_words & candidate_words) + title_match
        if score > best_score:
            best = candidate
            best_score = score
    if best and best_score >= 2:
        return best

    try:
        vector_hits = search_ckp_vectors(text=_topic_match_text(topic), user_id=user_id, canonical_type="topic", top_k=8)
    except Exception:
        vector_hits = []
    for hit in vector_hits:
        ckp_id = str(hit.get("ckp_id") or "")
        score = float(hit.get("score") or 0.0)
        if not ckp_id:
            continue
        candidate = (
            db.query(CanonicalKnowledgePoint)
            .filter(
                CanonicalKnowledgePoint.id == ckp_id,
                CanonicalKnowledgePoint.user_id == user_id,
                CanonicalKnowledgePoint.status != "deprecated",
                CanonicalKnowledgePoint.canonical_type == "topic",
            )
            .first()
        )
        if candidate and score >= 0.82:
            return candidate
    return None
```

- [ ] **Step 4: Add topic CKP creation helper**

Add this helper after `_create_or_get_ckp_from_pku(...)`:

```python
def _create_or_get_topic_ckp(
    db: Session,
    *,
    user_id: str,
    topic: ExtractedCKPTopic,
    source_kind: str,
    source_id: str,
    source_title: str = "",
) -> CanonicalKnowledgePoint:
    existing = _find_existing_topic_ckp(db, user_id=user_id, topic=topic)
    if existing:
        return existing

    statement = topic.description or f"Topic hub for {topic.title}."
    ckp = CanonicalKnowledgePoint(
        user_id=user_id,
        canonical_type="topic",
        title=_short_title(topic.title, "Untitled topic"),
        canonical_statement=statement,
        summary=topic.description,
        aliases=[source_title] if source_title and source_title != topic.title else [],
        domains=topic.domains,
        entities=topic.entities,
        concepts=topic.concepts,
        keywords=topic.keywords,
        scope={},
        conditions={},
        status="draft",
        confidence=topic.confidence,
        extra_meta={
            "created_from": source_kind,
            "source_id": source_id,
            "source_title": source_title,
            "topic_local_id": topic.local_id,
            "topic_reason": topic.reason,
            "topic_llm_model": topic.llm_model,
        },
    )
    db.add(ckp)
    db.flush()
    _refresh_ckp_vector(ckp)
    return ckp
```

- [ ] **Step 5: Run the tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_create_or_get_topic_ckp_creates_topic_hub_not_pku_copy backend/tests/test_asset_unit_pku_extraction.py::test_find_existing_topic_ckp_reuses_high_vector_similarity backend/tests/test_asset_unit_pku_extraction.py::test_create_or_get_topic_link_uses_about_relation -q
```

Expected: PASS.

---

### Task 4: Add Local Topic Settlement Helper

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write helper tests**

Add this test to `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_settle_local_pku_topics_links_members_to_fewer_topic_ckps(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters.",
        normalized_statement="LoRA reduces trainable parameters.",
        normalized_statement_hash="local-topic-pku-1",
        keywords=["LoRA", "fine-tuning"],
        concepts=["LoRA"],
        domains=["AI"],
        status="active",
        confidence=0.91,
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="rule",
        statement="Fine-tuning evaluation should use validation data.",
        normalized_statement="Fine-tuning evaluation should use validation data.",
        normalized_statement_hash="local-topic-pku-2",
        keywords=["evaluation", "fine-tuning"],
        concepts=["validation"],
        domains=["AI"],
        status="active",
        confidence=0.87,
    )
    db_session.add_all([first, second])
    db_session.flush()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_1", "pku_2"],
                    confidence=0.9,
                    reason="same local source topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg._settle_local_pku_topics(
        db_session,
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        source_title="Fine-tuning note",
        source_summary="LoRA and evaluation.",
        source_category="AI",
        source_tags=["fine-tuning"],
        pku_refs=[
            ("pku_1", first),
            ("pku_2", second),
        ],
        role="topic_member",
        reason="Local topic settlement.",
    )

    assert result == (1, 2)
    ckp = db_session.query(CanonicalKnowledgePoint).one()
    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    links = db_session.query(PKUCanonicalLink).order_by(PKUCanonicalLink.pku_id.asc()).all()
    assert len(links) == 2
    assert {link.relation_type for link in links} == {"about"}
    assert {link.canonical_id for link in links} == {ckp.id}
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_settle_local_pku_topics_links_members_to_fewer_topic_ckps -q
```

Expected: FAIL because `_settle_local_pku_topics` does not exist.

- [ ] **Step 3: Add PKU payload and fallback helpers**

Add these helpers near the topic extraction helpers:

```python
def _pku_topic_payload(ref: str, pku: PersonalKnowledgeUnit) -> dict[str, Any]:
    return {
        "ref": ref,
        "statement": pku.normalized_statement or pku.statement,
        "unit_type": pku.unit_type,
        "keywords": pku.keywords or [],
        "concepts": pku.concepts or [],
        "entities": pku.entities or [],
        "domains": pku.domains or [],
        "evidence_span": pku.evidence_span or "",
    }


def _fallback_local_topic(
    *,
    source_title: str,
    source_summary: str,
    source_category: str,
    source_tags: list[str],
    pku_refs: list[tuple[str, PersonalKnowledgeUnit]],
) -> ExtractedCKPTopic | None:
    if not pku_refs:
        return None
    keywords: list[str] = []
    concepts: list[str] = []
    domains: list[str] = [source_category] if source_category else []
    for _, pku in pku_refs:
        keywords.extend(str(value) for value in _as_list(pku.keywords))
        concepts.extend(str(value) for value in _as_list(pku.concepts))
        domains.extend(str(value) for value in _as_list(pku.domains))
    title = _short_title(source_title or " ".join(keywords[:3]) or pku_refs[0][1].normalized_statement, "Untitled topic")
    return ExtractedCKPTopic(
        local_id="fallback_topic",
        title=title,
        description=_normalize_space(source_summary or f"Topic hub for {title}."),
        keywords=list(dict.fromkeys([*source_tags, *keywords]))[:12],
        concepts=list(dict.fromkeys(concepts))[:12],
        entities=[],
        domains=list(dict.fromkeys(domains))[:8],
        member_pku_refs=[ref for ref, _ in pku_refs],
        confidence=0.72,
        reason="Fallback topic because topic extraction returned no valid topics.",
        llm_model="",
    )
```

- [ ] **Step 4: Add local topic settlement helper**

Add this helper after `_create_or_get_generic_link(...)`:

```python
def _settle_local_pku_topics(
    db: Session,
    *,
    user_id: str,
    source_kind: str,
    source_id: str,
    source_title: str,
    source_summary: str = "",
    source_category: str = "",
    source_tags: list[str] | None = None,
    pku_refs: list[tuple[str, PersonalKnowledgeUnit]],
    role: str,
    reason: str,
) -> tuple[int, int]:
    if not pku_refs:
        return (0, 0)
    ref_to_pku = {ref: pku for ref, pku in pku_refs}
    extraction = _extract_ckp_topics_with_llm(
        source_kind=source_kind,
        source_id=source_id,
        title=source_title,
        summary=source_summary,
        category=source_category,
        tags=source_tags or [],
        pkus=[_pku_topic_payload(ref, pku) for ref, pku in pku_refs],
    )
    topics = list(extraction.topics)
    if not topics:
        fallback = _fallback_local_topic(
            source_title=source_title,
            source_summary=source_summary,
            source_category=source_category,
            source_tags=source_tags or [],
            pku_refs=pku_refs,
        )
        topics = [fallback] if fallback else []

    ckp_ids: set[str] = set()
    link_ids: set[str] = set()
    linked_pku_ids: set[str] = set()
    for topic in topics:
        member_refs = [ref for ref in topic.member_pku_refs if ref in ref_to_pku]
        if not member_refs:
            continue
        ckp = _create_or_get_topic_ckp(
            db,
            user_id=user_id,
            topic=topic,
            source_kind=source_kind,
            source_id=source_id,
            source_title=source_title,
        )
        ckp_ids.add(ckp.id)
        for ref in member_refs:
            pku = ref_to_pku[ref]
            link = _create_or_get_generic_link(
                db,
                user_id=user_id,
                pku=pku,
                ckp=ckp,
                relation_type="about",
                role=role,
                reason=reason,
            )
            link_ids.add(link.id)
            linked_pku_ids.add(pku.id)

    unlinked = [(ref, pku) for ref, pku in pku_refs if pku.id not in linked_pku_ids]
    if unlinked and topics:
        ckp = _create_or_get_topic_ckp(
            db,
            user_id=user_id,
            topic=topics[0],
            source_kind=source_kind,
            source_id=source_id,
            source_title=source_title,
        )
        ckp_ids.add(ckp.id)
        for _, pku in unlinked:
            link = _create_or_get_generic_link(
                db,
                user_id=user_id,
                pku=pku,
                ckp=ckp,
                relation_type="about",
                role=role,
                reason=f"{reason} Added to fallback topic because no extracted topic referenced this PKU.",
            )
            link_ids.add(link.id)
    return (len(ckp_ids), len(link_ids))
```

- [ ] **Step 5: Run the helper test**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_settle_local_pku_topics_links_members_to_fewer_topic_ckps -q
```

Expected: PASS.

---

### Task 5: Refactor Personal Asset Unit Settlement to Topic Hubs

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: Write settlement behavior test**

Add this test to `backend/tests/test_asset_unit_pku_extraction.py`:

```python
def test_asset_unit_settlement_groups_pkus_under_topic_ckp_with_about_links(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit(
        title="LLM fine-tuning note",
        summary="LoRA and evaluation practices.",
        category="AI",
        tags=["fine-tuning"],
    )
    db_session.add(unit)
    db_session.flush()
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="LoRA reduces trainable parameters.",
                    unit_type="method",
                    evidence_span="LoRA reduces trainable parameters.",
                    keywords=["LoRA", "fine-tuning"],
                    concepts=["LoRA"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.91,
                    reason="method",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="Fine-tuning evaluation should use validation data.",
                    unit_type="rule",
                    evidence_span="Evaluation should use validation data.",
                    keywords=["evaluation", "fine-tuning"],
                    concepts=["validation"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.87,
                    reason="rule",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_1", "pku_2"],
                    confidence=0.9,
                    reason="same local topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 2
    assert result.canonical_count == 1
    assert result.link_count == 2
    ckp = db_session.query(CanonicalKnowledgePoint).one()
    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    assert ckp.canonical_statement != "LoRA reduces trainable parameters."
    assert {link.relation_type for link in db_session.query(PKUCanonicalLink).all()} == {"about"}
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py::test_asset_unit_settlement_groups_pkus_under_topic_ckp_with_about_links -q
```

Expected: FAIL because current settlement creates per-PKU CKPs and `same_as` links.

- [ ] **Step 3: Replace CKP creation inside asset unit settlement**

In `settle_personal_asset_unit_to_governance(...)`, keep PKU persistence and relation creation, but remove this block from the PKU loop:

```python
ckp = _create_or_get_ckp_from_pku(...)
link = _create_or_get_generic_link(... relation_type="same_as" ...)
ckp_ids.add(ckp.id)
link_ids.add(link.id)
```

Inside the loop, only persist PKUs and fill refs:

```python
for extracted in extracted_pkus:
    pku = _create_or_get_asset_unit_pku(db, unit=unit, extracted=extracted)
    pku_ids.add(pku.id)
    if extracted.local_id:
        pku_by_ref[_normalize_space(extracted.local_id)] = pku
    pku_by_ref[_normalize_space(extracted.statement)] = pku
```

After the PKU loop and before relation creation, add:

```python
topic_ckp_count, topic_link_count = _settle_local_pku_topics(
    db,
    user_id=unit.user_id or DEFAULT_USER_ID,
    source_kind="personal_asset_unit",
    source_id=unit.id,
    source_title=unit.title or "",
    source_summary=unit.summary or "",
    source_category=unit.category or "",
    source_tags=unit.tags or [],
    pku_refs=[
        (extracted.local_id or _normalize_space(extracted.statement), pku_by_ref[_normalize_space(extracted.local_id or extracted.statement)])
        for extracted in extracted_pkus
        if _normalize_space(extracted.local_id or extracted.statement) in pku_by_ref
    ],
    role="topic_member",
    reason="Settlement from confirmed PersonalAssetUnit topic grouping.",
)
```

Then change the returned result to use those counts:

```python
return GovernanceResult(
    pku_count=len(pku_ids),
    canonical_count=topic_ckp_count,
    link_count=topic_link_count,
    pku_relation_count=len(relation_ids),
)
```

- [ ] **Step 4: Run asset unit tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py -q
```

Expected: Some older tests that assert `same_as` or one CKP per PKU may fail. Update only those expectations to the new topic-hub semantics:

```python
assert {link.relation_type for link in links} == {"about"}
```

For tests that specifically exercise old `_find_existing_ckp(...)`, keep them unchanged because the old helper remains for backward compatibility.

- [ ] **Step 5: Re-run asset unit tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py -q
```

Expected: PASS.

---

### Task 6: Refactor Document Settlement to Cluster Across the Current Document

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write document-level aggregation test**

Add this test to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_document_settlement_groups_all_chunk_pkus_under_document_topic_ckp(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(
        title="LLM fine-tuning guide",
        summary="LoRA and evaluation practices.",
        category="AI",
        tags=["fine-tuning"],
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    first_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="LoRA reduces trainable parameters.",
        chunk_type="parent",
        chunk_index=0,
    )
    second_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Fine-tuning evaluation should use validation data.",
        chunk_type="parent",
        chunk_index=1,
    )
    db_session.add_all([first_chunk, second_chunk])
    db_session.flush()

    def fake_extract(item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None):
        if anchor_chunk.id == first_chunk.id:
            return kg.AssetUnitPKUExtraction(
                pkus=[
                    kg.ExtractedPKU(
                        local_id="pku_lora",
                        statement="LoRA reduces trainable parameters.",
                        unit_type="method",
                        evidence_span="LoRA reduces trainable parameters.",
                        keywords=["LoRA", "fine-tuning"],
                        concepts=["LoRA"],
                        entities=[],
                        domains=["AI"],
                        group="fine-tuning",
                        confidence=0.91,
                        reason="method",
                        llm_model="qwen-plus",
                    )
                ],
                relations=[],
                llm_model="qwen-plus",
            )
        return kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_eval",
                    statement="Fine-tuning evaluation should use validation data.",
                    unit_type="rule",
                    evidence_span="Evaluation should use validation data.",
                    keywords=["evaluation", "fine-tuning"],
                    concepts=["validation"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.88,
                    reason="rule",
                    llm_model="qwen-plus",
                )
            ],
            relations=[],
            llm_model="qwen-plus",
        )

    monkeypatch.setattr(kg, "_extract_document_chunk_pkus_with_llm", fake_extract)
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_lora", "pku_eval"],
                    confidence=0.9,
                    reason="document-level topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 2
    assert result.canonical_count == 1
    assert result.link_count == 2
    ckp = db_session.query(CanonicalKnowledgePoint).one()
    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    assert {link.relation_type for link in db_session.query(PKUCanonicalLink).all()} == {"about"}
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest backend/tests/test_document_chunk_pku_extraction.py::test_document_settlement_groups_all_chunk_pkus_under_document_topic_ckp -q
```

Expected: FAIL because current settlement creates CKPs per PKU inside each chunk loop.

- [ ] **Step 3: Refactor document settlement to collect PKUs across chunks**

In `settle_document_item_to_governance(...)`, add before the chunk loop:

```python
local_pku_refs: list[tuple[str, PersonalKnowledgeUnit]] = []
```

Inside the extracted PKU loop, remove per-PKU `_create_or_get_ckp_from_pku(...)` and `same_as` link creation. Replace that portion with:

```python
ref = _normalize_space(extracted.local_id or extracted.statement)
pku_ids.add(pku.id)
if ref:
    local_pku_refs.append((ref, pku))
if extracted.local_id:
    pku_by_ref[_normalize_space(extracted.local_id)] = pku
pku_by_ref[_normalize_space(extracted.statement)] = pku
```

After the chunk loop has finished, before returning `GovernanceResult`, add:

```python
topic_ckp_count, topic_link_count = _settle_local_pku_topics(
    db,
    user_id=item.user_id or DEFAULT_USER_ID,
    source_kind="document_chunk",
    source_id=item.id,
    source_title=item.title or "",
    source_summary=item.summary or "",
    source_category=item.category or "",
    source_tags=item.tags or [],
    pku_refs=local_pku_refs,
    role="topic_member",
    reason="Settlement from document-level topic grouping.",
)
```

Change the returned result:

```python
return GovernanceResult(
    pku_count=len(pku_ids),
    canonical_count=topic_ckp_count,
    link_count=topic_link_count,
    pku_relation_count=len(relation_ids),
)
```

- [ ] **Step 4: Run document tests**

Run:

```powershell
pytest backend/tests/test_document_chunk_pku_extraction.py -q
```

Expected: Some old CKP count/link relation assertions may fail. Update them so new document settlement expects topic CKPs and `about` links.

- [ ] **Step 5: Re-run document tests**

Run:

```powershell
pytest backend/tests/test_document_chunk_pku_extraction.py -q
```

Expected: PASS.

---

### Task 7: Deprecate Document-Created Orphan CKPs on Re-Ingest Cleanup

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write cleanup test**

Add this test to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_clear_document_item_governance_deprecates_document_orphan_topic_ckps(db_session):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Fine-tuning guide", user_id="default-user")
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="LoRA reduces parameters.", chunk_type="parent")
    db_session.add(chunk)
    db_session.flush()
    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="LoRA reduces parameters.",
        normalized_statement="LoRA reduces parameters.",
        normalized_statement_hash="cleanup-topic-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="LLM fine-tuning",
        canonical_statement="Fine-tuning topic hub.",
        status="draft",
        extra_meta={"created_from": "document_chunk", "source_id": item.id},
    )
    db_session.add_all([pku, ckp])
    db_session.flush()
    db_session.add(
        PKUCanonicalLink(
            user_id="default-user",
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
        )
    )
    db_session.commit()

    deleted = kg.clear_document_item_governance(db_session, item.id)
    db_session.commit()

    assert deleted == 1
    db_session.refresh(ckp)
    assert ckp.status == "deprecated"
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest backend/tests/test_document_chunk_pku_extraction.py::test_clear_document_item_governance_deprecates_document_orphan_topic_ckps -q
```

Expected: FAIL because current cleanup deletes PKUs only.

- [ ] **Step 3: Update cleanup**

Modify `clear_document_item_governance(...)`:

```python
def clear_document_item_governance(db: Session, item_id: str) -> int:
    chunk_ids = [
        row.id
        for row in db.query(KnowledgeChunk.id)
        .filter(KnowledgeChunk.item_id == item_id)
        .all()
    ]
    if not chunk_ids:
        return 0

    pkus = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id.in_(chunk_ids),
        )
        .all()
    )
    affected_ckp_ids = {
        link.canonical_id
        for pku in pkus
        for link in pku.canonical_links
    }
    count = len(pkus)
    for pku in pkus:
        db.delete(pku)
    db.flush()

    if affected_ckp_ids:
        ckps = (
            db.query(CanonicalKnowledgePoint)
            .filter(
                CanonicalKnowledgePoint.id.in_(affected_ckp_ids),
                CanonicalKnowledgePoint.status != "deprecated",
            )
            .all()
        )
        for ckp in ckps:
            meta = ckp.extra_meta or {}
            created_from_document = (
                meta.get("created_from") == "document_chunk"
                and meta.get("source_id") == item_id
            )
            active_links = [
                link
                for link in ckp.pku_links
                if link.pku and link.pku.status == "active"
            ]
            if created_from_document and not active_links:
                ckp.status = "deprecated"
    db.flush()
    return count
```

- [ ] **Step 4: Run the cleanup test**

Run:

```powershell
pytest backend/tests/test_document_chunk_pku_extraction.py::test_clear_document_item_governance_deprecates_document_orphan_topic_ckps -q
```

Expected: PASS.

---

### Task 8: Update Governance and Graph Compatibility Tests

**Files:**
- Modify: `backend/tests/test_knowledge_governance_models.py`
- Modify: `backend/tests/test_knowledge_graph_api.py`
- Modify: `frontend/src/pages/KnowledgeGraphWorkbench.tsx` if needed

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
pytest backend/tests/test_knowledge_governance_models.py backend/tests/test_knowledge_graph_api.py -q
```

Expected: Some tests may fail because they expect `same_as` for newly settled links or `canonical_type` copied from PKU type.

- [ ] **Step 2: Update new-settlement expectations only**

For tests that create links manually with `same_as`, keep them. They verify backward compatibility.

For tests that call settlement functions and then assert link types, update:

```python
assert {link.relation_type for link in links} == {"about"}
```

For tests that assert CKP type from settlement, update:

```python
assert {ckp.canonical_type for ckp in ckps} == {"topic"}
```

For tests that assert one CKP per PKU, update to assert fewer topic hubs when mocked topic extraction groups multiple PKUs:

```python
assert db_session.query(CanonicalKnowledgePoint).count() == 1
assert db_session.query(PKUCanonicalLink).count() == 2
```

- [ ] **Step 3: Ensure graph workbench still shows link labels**

Inspect `frontend/src/pages/KnowledgeGraphWorkbench.tsx`. If it already renders `entry.link.label`, no functional change is required. If a label map exists, add:

```tsx
const LINK_LABELS: Record<string, string> = {
  about: 'about',
  same_as: 'same_as',
}
```

and render:

```tsx
{LINK_LABELS[entry.link.label] ?? entry.link.label}
```

- [ ] **Step 4: Re-run focused tests**

Run:

```powershell
pytest backend/tests/test_knowledge_governance_models.py backend/tests/test_knowledge_graph_api.py -q
```

Expected: PASS.

---

### Task 9: Full Verification

**Files:**
- No planned edits.

- [ ] **Step 1: Run backend governance tests**

Run:

```powershell
pytest backend/tests/test_asset_unit_pku_extraction.py backend/tests/test_document_chunk_pku_extraction.py backend/tests/test_knowledge_governance_models.py backend/tests/test_knowledge_graph_api.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend tests likely affected by governance**

Run:

```powershell
pytest backend/tests/test_personal_asset_items_api.py backend/tests/test_ckp_vectors.py -q
```

Expected: PASS. If `test_ckp_vectors.py` assumes canonical type values, update only expectations that are now topic-specific for newly created CKPs.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: Build exits 0. Existing Vite chunk-size warnings are acceptable.

- [ ] **Step 4: Manual sanity check with local app if servers are running**

Open the graph page and verify:

- new CKPs read as topic nodes;
- multiple PKUs appear under one CKP when topic extraction groups them;
- links show `about`;
- old `same_as` links still render.

If no dev servers are running, skip this manual step and report that only automated verification was run.

---

## Self-Review

Spec coverage:

- CKP as topic hub: Tasks 3, 5, 6.
- PKU as atomic evidence unit: existing extraction retained in Tasks 5 and 6.
- `about` relation: Tasks 3, 5, 6, 8.
- Local-first aggregation: Tasks 4, 5, 6.
- Global reuse: Task 3.
- Manual merge workbench deferred with metadata preserved: Task 3 stores `topic_reason`, `topic_llm_model`, `source_*`.
- Existing data compatibility: Task 8.
- Re-ingest orphan handling: Task 7.

Placeholder scan:

- No `TBD` or `TODO` placeholders.
- Manual merge workbench is explicitly out of first-pass scope per spec.

Type consistency:

- Topic dataclasses use `ExtractedCKPTopic` and `CKPTopicExtraction`.
- Prompt builder is `build_ckp_topic_extraction_messages`.
- Settlement helper returns `(canonical_count, link_count)`.
- New links use existing `PKUCanonicalLink.relation_type` with value `about`.
