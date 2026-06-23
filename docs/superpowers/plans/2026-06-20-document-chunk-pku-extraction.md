# Document Chunk PKU Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade document chunk governance so parent chunks use the main LLM to extract multiple PKUs and PKU relations, anchored to the current parent chunk with neighboring parent chunks as context.

**Architecture:** Add a document-specific PKU extraction prompt and LLM helper, then refactor document settlement to reuse the existing asset-unit PKU parser, CKP canonicalization, PKU link creation, and PKU relation persistence. Keep evidence and persistence anchored to the current parent chunk while passing previous/next parent chunks only as context.

**Tech Stack:** FastAPI backend, SQLAlchemy ORM, pytest, OpenAI-compatible SDK, existing Prism prompt and governance modules.

---

## File Structure

- Modify `backend/app/prompts/asset_parse.py`: add document chunk PKU extraction constants and builders, reusing the asset-unit PKU vocabularies.
- Modify `backend/app/services/knowledge_governance.py`: add document LLM extraction helper, document fallback helper, extracted-PKU persistence helper, anchor context windows, and relation persistence for document chunks.
- Create `backend/tests/test_document_chunk_pku_extraction.py`: prompt, LLM helper, settlement, relation, context, and fallback tests.
- Modify `backend/tests/test_knowledge_governance_models.py`: replace the document Ollama behavior test with a no-Ollama fallback regression and keep CKP sharing coverage.
- Modify `engine/tests/test_ingestion_governance.py`: monkeypatch document extraction so ingest governance remains deterministic under the new LLM-first path.

---

### Task 1: Add Document Chunk PKU Prompt Builder

**Files:**
- Modify: `backend/app/prompts/asset_parse.py`
- Create/Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write the failing prompt test**

Create `backend/tests/test_document_chunk_pku_extraction.py` with:

```python
import json

from backend.app.prompts.asset_parse import (
    ASSET_UNIT_PKU_RELATION_TYPES,
    ASSET_UNIT_PKU_UNIT_TYPES,
    build_document_chunk_pku_extraction_messages,
)


def test_build_document_chunk_pku_extraction_messages_include_anchor_context_schema():
    system_prompt, user_message = build_document_chunk_pku_extraction_messages(
        item_id="item-1",
        title="Hybrid retrieval guide",
        summary="Metadata filters and vector recall work together.",
        category="RAG",
        tags=["metadata", "retrieval"],
        source_type="manual",
        anchor_chunk={
            "id": "chunk-2",
            "text": "Metadata filters restrict retrieval results by source or project.",
            "index": 1,
        },
        previous_chunk={
            "id": "chunk-1",
            "text": "Hybrid retrieval combines keyword and vector recall.",
            "index": 0,
        },
        next_chunk={
            "id": "chunk-3",
            "text": "The filtered candidates are reranked before answering.",
            "index": 2,
        },
    )

    request = json.loads(user_message)

    assert "JSON" in system_prompt
    assert request["source_item"]["id"] == "item-1"
    assert request["source_item"]["title"] == "Hybrid retrieval guide"
    assert request["anchor_chunk"]["id"] == "chunk-2"
    assert request["anchor_chunk"]["text"] == "Metadata filters restrict retrieval results by source or project."
    assert request["context_chunks"]["previous"]["id"] == "chunk-1"
    assert request["context_chunks"]["next"]["id"] == "chunk-3"
    assert request["allowed_unit_types"] == ASSET_UNIT_PKU_UNIT_TYPES
    assert request["allowed_relation_types"] == ASSET_UNIT_PKU_RELATION_TYPES
    assert request["json_shape"]["pkus"][0]["local_id"] == "pku_1"
    assert request["json_shape"]["relations"][0]["source_local_id"] == "pku_1"
    assert any("anchor" in rule.lower() for rule in request["rules"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_build_document_chunk_pku_extraction_messages_include_anchor_context_schema -q
```

Expected: fail with `ImportError` because `build_document_chunk_pku_extraction_messages` does not exist.

- [ ] **Step 3: Add prompt constants and builder**

Append this section to `backend/app/prompts/asset_parse.py` after the asset unit PKU extraction section:

```python
# ---------------------------------------------------------------------------
# Document Chunk PKU Extraction (anchor parent chunk -> atomic PKUs)
# ---------------------------------------------------------------------------

DOCUMENT_CHUNK_PKU_EXTRACTION_SYSTEM_PROMPT = (
    "You are Prism's document knowledge unit (PKU) extractor. "
    "Return strict JSON only. Do not output Markdown."
)

DOCUMENT_CHUNK_PKU_EXTRACTION_TASK = (
    "Extract reusable atomic PKUs from the anchor document chunk. "
    "Use neighboring chunks only as context for resolving terms and references."
)

DOCUMENT_CHUNK_PKU_EXTRACTION_RULES = [
    "Every PKU must be atomic, reusable, semantically complete, and supported by the anchor chunk.",
    "Use previous and next chunks only as context; do not create a PKU whose evidence exists only in a context chunk.",
    "The evidence field must quote or closely match text from the anchor chunk.",
    "Do not extract headings, vague summaries, or unsupported conclusions as PKUs.",
    "unit_type must use one value from allowed_unit_types.",
    "relation_type must use one value from allowed_relation_types.",
    "relations may only reference local_id values from this response.",
    "Return an empty pkus array when the anchor chunk contains no reusable knowledge.",
]

JSON_SHAPE_DOCUMENT_CHUNK_PKU_EXTRACTION: dict[str, Any] = {
    "pkus": [
        {
            "local_id": "pku_1",
            "statement": "Atomic knowledge statement supported by the anchor chunk",
            "normalized_statement": "Optional normalized statement",
            "unit_type": ASSET_UNIT_PKU_UNIT_TYPES,
            "keywords": ["keyword"],
            "domains": ["domain"],
            "entities": ["entity"],
            "concepts": ["concept"],
            "confidence": 0.0,
            "evidence": "Evidence span from the anchor chunk",
            "reason": "Short extraction reason",
        }
    ],
    "relations": [
        {
            "source_local_id": "pku_1",
            "target_local_id": "pku_2",
            "relation_type": ASSET_UNIT_PKU_RELATION_TYPES,
            "reason": "Short relation reason",
            "confidence": 0.0,
        }
    ],
}


def _chunk_payload(chunk: dict[str, Any] | None, max_text_length: int) -> dict[str, Any] | None:
    if not chunk:
        return None
    return {
        "id": str(chunk.get("id") or ""),
        "index": chunk.get("index"),
        "text": str(chunk.get("text") or "")[:max_text_length],
    }


def build_document_chunk_pku_extraction_request(
    *,
    item_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    anchor_chunk: dict[str, Any],
    previous_chunk: dict[str, Any] | None = None,
    next_chunk: dict[str, Any] | None = None,
    max_anchor_length: int = 6000,
    max_context_length: int = 2500,
) -> str:
    request = {
        "task": DOCUMENT_CHUNK_PKU_EXTRACTION_TASK,
        "source_item": {
            "id": item_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
            "source_type": source_type,
        },
        "anchor_chunk": _chunk_payload(anchor_chunk, max_anchor_length),
        "context_chunks": {
            "previous": _chunk_payload(previous_chunk, max_context_length),
            "next": _chunk_payload(next_chunk, max_context_length),
        },
        "allowed_unit_types": ASSET_UNIT_PKU_UNIT_TYPES,
        "allowed_relation_types": ASSET_UNIT_PKU_RELATION_TYPES,
        "json_shape": JSON_SHAPE_DOCUMENT_CHUNK_PKU_EXTRACTION,
        "rules": DOCUMENT_CHUNK_PKU_EXTRACTION_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_document_chunk_pku_extraction_messages(
    *,
    item_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    anchor_chunk: dict[str, Any],
    previous_chunk: dict[str, Any] | None = None,
    next_chunk: dict[str, Any] | None = None,
    max_anchor_length: int = 6000,
    max_context_length: int = 2500,
) -> tuple[str, str]:
    return (
        DOCUMENT_CHUNK_PKU_EXTRACTION_SYSTEM_PROMPT,
        build_document_chunk_pku_extraction_request(
            item_id=item_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            source_type=source_type,
            anchor_chunk=anchor_chunk,
            previous_chunk=previous_chunk,
            next_chunk=next_chunk,
            max_anchor_length=max_anchor_length,
            max_context_length=max_context_length,
        ),
    )
```

- [ ] **Step 4: Run the prompt test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_build_document_chunk_pku_extraction_messages_include_anchor_context_schema -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend\app\prompts\asset_parse.py backend\tests\test_document_chunk_pku_extraction.py
git commit -m "feat: add document chunk pku extraction prompt"
```

---

### Task 2: Add Document Chunk LLM Extraction Helper

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write the failing LLM helper test**

Append to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_extract_document_chunk_pkus_uses_main_llm_and_anchor_context(monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = (
            '{"pkus":[{"local_id":"pku_1",'
            '"statement":"Metadata filters restrict retrieval by source.",'
            '"unit_type":"method",'
            '"evidence_span":"Metadata filters restrict retrieval by source.",'
            '"keywords":["metadata","retrieval"],'
            '"confidence":0.9}],'
            '"relations":[]}'
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

    item = KnowledgeItem(
        id="item-1",
        title="Hybrid retrieval",
        summary="Metadata filters help retrieval.",
        category="RAG",
        tags=["metadata"],
        source_type="manual",
        user_id="default-user",
    )
    previous = KnowledgeChunk(id="chunk-1", item_id="item-1", chunk_text="Hybrid retrieval combines signals.", chunk_type="parent")
    anchor = KnowledgeChunk(id="chunk-2", item_id="item-1", chunk_text="Metadata filters restrict retrieval by source.", chunk_type="parent")
    next_chunk = KnowledgeChunk(id="chunk-3", item_id="item-1", chunk_text="Reranking happens after filtering.", chunk_type="parent")

    result = kg._extract_document_chunk_pkus_with_llm(item, anchor, previous, next_chunk, anchor_index=1)

    request = json.loads(captured["messages"][1]["content"])
    assert captured["model"] == "qwen-plus"
    assert request["anchor_chunk"]["id"] == "chunk-2"
    assert request["context_chunks"]["previous"]["id"] == "chunk-1"
    assert request["context_chunks"]["next"]["id"] == "chunk-3"
    assert result.llm_model == "qwen-plus"
    assert result.pkus[0].statement == "Metadata filters restrict retrieval by source."
    assert result.pkus[0].unit_type == "method"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_extract_document_chunk_pkus_uses_main_llm_and_anchor_context -q
```

Expected: fail with `AttributeError` because `_extract_document_chunk_pkus_with_llm` does not exist.

- [ ] **Step 3: Import the document prompt builder**

In `backend/app/services/knowledge_governance.py`, change:

```python
from backend.app.prompts.asset_parse import build_asset_unit_pku_extraction_messages
```

to:

```python
from backend.app.prompts.asset_parse import (
    build_asset_unit_pku_extraction_messages,
    build_document_chunk_pku_extraction_messages,
)
```

- [ ] **Step 4: Add a chunk payload helper and LLM helper**

Add this after `_extract_asset_unit_pkus_with_llm`:

```python
def _document_chunk_prompt_payload(chunk: KnowledgeChunk | None, index: int | None = None) -> dict[str, Any] | None:
    if not chunk:
        return None
    return {
        "id": chunk.id,
        "index": index,
        "text": chunk.chunk_text or "",
    }


def _extract_document_chunk_pkus_with_llm(
    item: KnowledgeItem,
    anchor_chunk: KnowledgeChunk,
    previous_chunk: KnowledgeChunk | None = None,
    next_chunk: KnowledgeChunk | None = None,
    *,
    anchor_index: int | None = None,
) -> AssetUnitPKUExtraction:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return AssetUnitPKUExtraction([], [], llm_model="")

    system_prompt, user_message = build_document_chunk_pku_extraction_messages(
        item_id=item.id,
        title=item.title or "",
        summary=item.summary or "",
        category=item.category or "",
        tags=item.tags or [],
        source_type=item.source_type or "",
        anchor_chunk=_document_chunk_prompt_payload(anchor_chunk, anchor_index) or {"id": anchor_chunk.id, "text": ""},
        previous_chunk=_document_chunk_prompt_payload(previous_chunk, None),
        next_chunk=_document_chunk_prompt_payload(next_chunk, None),
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

- [ ] **Step 5: Run the LLM helper test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_extract_document_chunk_pkus_uses_main_llm_and_anchor_context -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py
git commit -m "feat: extract document chunk pkus with main llm"
```

---

### Task 3: Persist Multiple Document PKUs From One Anchor Chunk

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write the failing multi-PKU settlement test**

Append to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_document_chunk_settlement_persists_multiple_llm_pkus_from_anchor(db_session, monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(
        title="Metadata retrieval",
        content="",
        summary="Metadata filters narrow retrieval.",
        category="RAG",
        tags=["metadata", "retrieval"],
        source_type="manual",
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    anchor = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filters restrict retrieval by source. Filtered candidates are reranked before answering.",
        chunk_type="parent",
    )
    db_session.add(anchor)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="Metadata filters restrict retrieval by source.",
                    unit_type="method",
                    evidence_span="Metadata filters restrict retrieval by source.",
                    keywords=["metadata", "retrieval"],
                    concepts=["metadata filter"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.91,
                    reason="anchor evidence",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="Filtered retrieval candidates are reranked before answering.",
                    unit_type="method",
                    evidence_span="Filtered candidates are reranked before answering.",
                    keywords=["rerank"],
                    concepts=["reranking"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.87,
                    reason="anchor evidence",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 2
    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").all()
    assert len(pkus) == 2
    assert {pku.source_id for pku in pkus} == {anchor.id}
    assert {pku.llm_model for pku in pkus} == {"qwen-plus"}
    assert {pku.unit_type for pku in pkus} == {"method"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_settlement_persists_multiple_llm_pkus_from_anchor -q
```

Expected: fail because current settlement creates one coarse PKU and does not call `_extract_document_chunk_pkus_with_llm`.

- [ ] **Step 3: Add extracted document PKU persistence helper**

Replace `_create_or_get_document_pku` with:

```python
def _create_or_get_document_pku_from_extracted(
    db: Session,
    *,
    item: KnowledgeItem,
    chunk: KnowledgeChunk,
    extracted: ExtractedPKU,
) -> PersonalKnowledgeUnit:
    normalized = _normalize_space(extracted.statement)
    statement_hash = _text_hash(normalized)
    user_id = item.user_id or DEFAULT_USER_ID
    existing = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == user_id,
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id == chunk.id,
            PersonalKnowledgeUnit.unit_type == extracted.unit_type,
            PersonalKnowledgeUnit.normalized_statement_hash == statement_hash,
        )
        .first()
    )
    if existing:
        return existing

    keywords = extracted.keywords or _extract_keywords(
        extracted.statement,
        item.title,
        item.summary,
        item.category,
        item.tags or [],
    )
    pku = PersonalKnowledgeUnit(
        user_id=user_id,
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type=extracted.unit_type,
        statement=extracted.statement,
        normalized_statement=normalized,
        normalized_statement_hash=statement_hash,
        modality="fact",
        domains=extracted.domains or ([item.category] if item.category else []),
        entities=extracted.entities,
        concepts=extracted.concepts or (item.tags or []),
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

- [ ] **Step 4: Add fallback helper**

Add this after `_create_or_get_document_pku_from_extracted`:

```python
def _fallback_document_chunk_pku(item: KnowledgeItem, chunk: KnowledgeChunk) -> ExtractedPKU | None:
    statement = _normalize_space(chunk.chunk_text or "")
    if not statement:
        return None
    statement = statement[:1200]
    return ExtractedPKU(
        statement=statement,
        unit_type=_unit_type_from_document_text(statement),
        evidence_span=statement,
        keywords=_extract_keywords(statement, item.title, item.summary, item.category, item.tags or []),
        concepts=item.tags or [],
        entities=[],
        domains=[item.category] if item.category else [],
        group="",
        confidence=0.72,
        reason="Document chunk fallback because LLM PKU extraction returned no valid PKUs.",
        llm_model="",
    )
```

- [ ] **Step 5: Rewrite document settlement to use LLM extraction**

Replace the body of `settle_document_item_to_governance` after the chunk lookup with:

```python
    pku_ids: set[str] = set()
    ckp_ids: set[str] = set()
    link_ids: set[str] = set()

    for index, chunk in enumerate(chunks):
        previous_chunk = chunks[index - 1] if index > 0 else None
        next_chunk = chunks[index + 1] if index + 1 < len(chunks) else None
        extraction = _extract_document_chunk_pkus_with_llm(
            item,
            chunk,
            previous_chunk,
            next_chunk,
            anchor_index=index,
        )
        extracted_pkus = list(extraction.pkus)
        if not extracted_pkus:
            fallback = _fallback_document_chunk_pku(item, chunk)
            extracted_pkus = [fallback] if fallback else []
        if not extracted_pkus:
            continue

        for extracted in extracted_pkus:
            pku = _create_or_get_document_pku_from_extracted(
                db,
                item=item,
                chunk=chunk,
                extracted=extracted,
            )
            ckp = _create_or_get_ckp_from_pku(
                db,
                user_id=item.user_id or DEFAULT_USER_ID,
                pku=pku,
                title=item.title or pku.statement,
                summary=item.summary or "",
                aliases=[item.title] if item.title else [],
                extra_meta={
                    "created_from": "document_chunk",
                    "source_item_id": item.id,
                    "source_chunk_id": chunk.id,
                    "anchor_chunk_index": index,
                    "extraction_group": extracted.group,
                    "extraction_reason": extracted.reason,
                },
            )
            link = _create_or_get_generic_link(
                db,
                user_id=item.user_id or DEFAULT_USER_ID,
                pku=pku,
                ckp=ckp,
                relation_type="same_as",
                role="external_reference",
                reason="Settlement from document chunk PKU extraction.",
            )
            pku_ids.add(pku.id)
            ckp_ids.add(ckp.id)
            link_ids.add(link.id)

    return GovernanceResult(pku_count=len(pku_ids), canonical_count=len(ckp_ids), link_count=len(link_ids))
```

- [ ] **Step 6: Run the multi-PKU test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_settlement_persists_multiple_llm_pkus_from_anchor -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py
git commit -m "feat: settle document chunks into llm pkus"
```

---

### Task 4: Persist Document PKU Relations

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write the failing relation test**

Append to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_document_chunk_settlement_persists_llm_pku_relations(db_session, monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem, PKURelation
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="PKU workflow", category="Governance", tags=["pku"], user_id="default-user")
    db_session.add(item)
    db_session.flush()
    anchor = KnowledgeChunk(
        item_id=item.id,
        chunk_text="First extract atomic PKUs. Then link prerequisite relations between the extracted PKUs.",
        chunk_type="parent",
    )
    db_session.add(anchor)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="Document settlement first extracts atomic PKUs.",
                    unit_type="method",
                    evidence_span="First extract atomic PKUs.",
                    keywords=["pku"],
                    concepts=["PKU extraction"],
                    entities=[],
                    domains=["Governance"],
                    group="workflow",
                    confidence=0.9,
                    reason="anchor evidence",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="Document settlement links prerequisite relations between extracted PKUs.",
                    unit_type="method",
                    evidence_span="Then link prerequisite relations between the extracted PKUs.",
                    keywords=["relation"],
                    concepts=["PKU relation"],
                    entities=[],
                    domains=["Governance"],
                    group="workflow",
                    confidence=0.88,
                    reason="anchor evidence",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[
                kg.ExtractedPKURelation(
                    from_ref="pku_1",
                    to_ref="pku_2",
                    relation_type="prerequisite_of",
                    confidence=0.86,
                    reason="Extraction comes before relation linking.",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_relation_count == 1
    relation = db_session.query(PKURelation).one()
    assert relation.source_kind == "document_chunk"
    assert relation.source_id == anchor.id
    assert relation.relation_type == "prerequisite_of"
    assert relation.llm_model == "qwen-plus"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_settlement_persists_llm_pku_relations -q
```

Expected: fail because document settlement does not persist relations or return `pku_relation_count`.

- [ ] **Step 3: Update settlement to store relations per anchor**

In `settle_document_item_to_governance`, add:

```python
    relation_ids: set[str] = set()
```

After `link_ids.add(link.id)`, add local reference mapping. The loop should have a `pku_by_ref` dict per anchor:

```python
        pku_by_ref: dict[str, PersonalKnowledgeUnit] = {}
```

Inside the PKU loop after `link_ids.add(link.id)`, add:

```python
            if extracted.local_id:
                pku_by_ref[_normalize_space(extracted.local_id)] = pku
            pku_by_ref[_normalize_space(extracted.statement)] = pku
```

After the PKU loop for that anchor, add:

```python
        if extraction.pkus:
            for relation in extraction.relations:
                source_pku = pku_by_ref.get(_normalize_space(relation.from_ref))
                target_pku = pku_by_ref.get(_normalize_space(relation.to_ref))
                if not source_pku or not target_pku or source_pku.id == target_pku.id:
                    continue
                row = _create_or_get_pku_relation(
                    db,
                    user_id=item.user_id or DEFAULT_USER_ID,
                    source_pku=source_pku,
                    target_pku=target_pku,
                    relation=relation,
                    source_kind="document_chunk",
                    source_id=chunk.id,
                    llm_model=extraction.llm_model,
                )
                relation_ids.add(row.id)
```

Change the return statement to:

```python
    return GovernanceResult(
        pku_count=len(pku_ids),
        canonical_count=len(ckp_ids),
        link_count=len(link_ids),
        pku_relation_count=len(relation_ids),
    )
```

- [ ] **Step 4: Run the relation test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_settlement_persists_llm_pku_relations -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py
git commit -m "feat: persist document pku relations"
```

---

### Task 5: Verify Neighbor Context Windows During Settlement

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`

- [ ] **Step 1: Write the failing context-window test**

Append to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_document_settlement_passes_previous_and_next_parent_chunks(db_session, monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Chunk context", category="RAG", tags=[], user_id="default-user")
    db_session.add(item)
    db_session.flush()
    first = KnowledgeChunk(item_id=item.id, chunk_text="Previous parent context.", chunk_type="parent")
    second = KnowledgeChunk(item_id=item.id, chunk_text="Anchor parent content.", chunk_type="parent")
    third = KnowledgeChunk(item_id=item.id, chunk_text="Next parent context.", chunk_type="parent")
    db_session.add_all([first, second, third])
    db_session.flush()

    calls = []

    def fake_extract(item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None):
        calls.append(
            {
                "anchor": anchor_chunk.id,
                "previous": previous_chunk.id if previous_chunk else None,
                "next": next_chunk.id if next_chunk else None,
                "index": anchor_index,
            }
        )
        return kg.AssetUnitPKUExtraction(pkus=[], relations=[], llm_model="")

    monkeypatch.setattr(kg, "_extract_document_chunk_pkus_with_llm", fake_extract)

    kg.settle_document_item_to_governance(db_session, item.id)

    assert calls == [
        {"anchor": first.id, "previous": None, "next": second.id, "index": 0},
        {"anchor": second.id, "previous": first.id, "next": third.id, "index": 1},
        {"anchor": third.id, "previous": second.id, "next": None, "index": 2},
    ]
```

- [ ] **Step 2: Run the test to verify it fails or passes for the right reason**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_settlement_passes_previous_and_next_parent_chunks -q
```

Expected before Task 3 implementation: fail because settlement does not call the helper. Expected after Task 3 implementation: pass. If it fails because ordering is nondeterministic, update `settle_document_item_to_governance` ordering to use `created_at.asc(), id.asc()` exactly as the current implementation does.

- [ ] **Step 3: Run the test to verify it passes**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_settlement_passes_previous_and_next_parent_chunks -q
```

Expected: pass.

- [ ] **Step 4: Commit if code changed**

```powershell
git add backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py
git commit -m "test: cover document chunk anchor context windows"
```

---

### Task 6: Replace Document Ollama Behavior With Deterministic Fallback

**Files:**
- Modify: `backend/tests/test_knowledge_governance_models.py`
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_document_chunk_pku_extraction.py`, `backend/tests/test_knowledge_governance_models.py`

- [ ] **Step 1: Write the no-Ollama fallback test**

Append to `backend/tests/test_document_chunk_pku_extraction.py`:

```python
def test_document_chunk_fallback_does_not_call_ollama_type_classifier(db_session, monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(
        title="Fallback document",
        category="RAG",
        tags=["metadata"],
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter is defined as a constraint on retrieval candidates.",
        chunk_type="parent",
    )
    db_session.add(chunk)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction([], []),
    )
    monkeypatch.setattr(
        kg,
        "_ollama_pku_type_decision",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Document fallback must not call Ollama")),
    )

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").one()
    assert pku.statement == "Metadata filter is defined as a constraint on retrieval candidates."
    assert pku.unit_type == "definition"
    assert pku.llm_model == ""
```

- [ ] **Step 2: Run the fallback test to verify it passes after Task 3**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_fallback_does_not_call_ollama_type_classifier -q
```

Expected: pass after `_fallback_document_chunk_pku` is used. If it fails, remove any remaining `_ollama_pku_type_decision` call from document settlement.

- [ ] **Step 3: Replace the obsolete Ollama test**

In `backend/tests/test_knowledge_governance_models.py`, delete the function:

```python
def test_document_pku_type_uses_ollama_decision(db_session, monkeypatch):
    ...
```

Replace it with:

```python
def test_document_pku_type_uses_local_fallback_when_llm_empty(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction([], []),
    )

    item = KnowledgeItem(
        title="Retrieval definition",
        content="Metadata filter is defined as a retrieval candidate constraint.",
        source_type="manual",
        category="RAG",
        tags=["metadata"],
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="Metadata filter is defined as a retrieval candidate constraint.",
            chunk_type="parent",
        )
    )
    db_session.flush()

    settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").one()
    assert pku.unit_type == "definition"
    assert pku.llm_model == ""
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py::test_document_chunk_fallback_does_not_call_ollama_type_classifier backend\tests\test_knowledge_governance_models.py::test_document_pku_type_uses_local_fallback_when_llm_empty -q
```

Expected: both pass.

- [ ] **Step 5: Commit**

```powershell
git add backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_knowledge_governance_models.py
git commit -m "test: make document fallback independent of ollama"
```

---

### Task 7: Keep Ingest Governance Deterministic

**Files:**
- Modify: `engine/tests/test_ingestion_governance.py`
- Test: `engine/tests/test_ingestion_governance.py`

- [ ] **Step 1: Update the ingest test to monkeypatch document extraction**

In `engine/tests/test_ingestion_governance.py`, inside `test_ingest_item_settles_document_chunks_into_governance_layer`, add this import near the other imports:

```python
from backend.app.services import knowledge_governance as kg
```

Before `count = pipeline.ingest_item(item_id)`, add:

```python
    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="Metadata filtering allows retrieval systems to restrict results by project.",
                    unit_type="method",
                    evidence_span="Metadata filtering allows retrieval systems to restrict results by project.",
                    keywords=["metadata", "retrieval"],
                    concepts=["metadata filtering"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.9,
                    reason="test extraction",
                    llm_model="test-model",
                )
            ],
            relations=[],
            llm_model="test-model",
        ),
    )
```

Update assertions:

```python
        assert pkus[0].llm_model == "test-model"
```

- [ ] **Step 2: Run the ingest governance test**

Run:

```powershell
python -m pytest engine\tests\test_ingestion_governance.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```powershell
git add engine\tests\test_ingestion_governance.py
git commit -m "test: keep document ingest governance deterministic"
```

---

### Task 8: Verify Existing Graph And Governance Behavior

**Files:**
- Modify only if tests reveal a real regression: `backend/tests/test_knowledge_graph_api.py`, `engine/app/agent/tools/governed_knowledge.py`
- Test: governance and graph suites

- [ ] **Step 1: Run governance-related backend tests**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_knowledge_graph_api.py -q
```

Expected: all pass.

- [ ] **Step 2: Fix only real regressions**

If `backend/tests/test_knowledge_graph_api.py` fails because a test relies on one fallback document PKU, monkeypatch `_extract_document_chunk_pkus_with_llm` in that test to return deterministic extraction:

```python
from backend.app.services import knowledge_governance as kg

monkeypatch.setattr(
    kg,
    "_extract_document_chunk_pkus_with_llm",
    lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
        pkus=[
            kg.ExtractedPKU(
                local_id="pku_1",
                statement=anchor_chunk.chunk_text,
                unit_type="claim",
                evidence_span=anchor_chunk.chunk_text,
                keywords=["metadata", "filter"],
                concepts=["metadata filter"],
                entities=[],
                domains=["RAG"],
                group="",
                confidence=0.8,
                reason="test extraction",
                llm_model="test-model",
            )
        ],
        relations=[],
        llm_model="test-model",
    ),
)
```

- [ ] **Step 3: Re-run governance-related backend tests**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_knowledge_graph_api.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit if any test files changed**

```powershell
git add backend\tests\test_knowledge_graph_api.py engine\app\agent\tools\governed_knowledge.py
git commit -m "test: align graph tests with document pku extraction"
```

If no files changed in this task, do not create a commit.

---

### Task 9: Final Verification

**Files:**
- No code files unless fixing verification failures.

- [ ] **Step 1: Run the focused verification suite**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_knowledge_graph_api.py engine\tests\test_ingestion_governance.py -q
```

Expected: all pass.

- [ ] **Step 2: Run broader backend tests**

Run:

```powershell
python -m pytest backend\tests -q
```

Expected: all pass.

- [ ] **Step 3: Inspect the diff**

Run:

```powershell
git diff --stat
git diff -- backend\app\prompts\asset_parse.py backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_knowledge_governance_models.py engine\tests\test_ingestion_governance.py
```

Expected: changes are limited to document chunk PKU extraction prompt, governance settlement, and tests.

- [ ] **Step 4: Final commit**

If there are uncommitted implementation changes after verification, commit them:

```powershell
git add backend\app\prompts\asset_parse.py backend\app\services\knowledge_governance.py backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_knowledge_governance_models.py backend\tests\test_knowledge_graph_api.py engine\tests\test_ingestion_governance.py
git commit -m "feat: extract pkus from document chunks with context"
```

If every task already committed its changes, do not create an empty commit.

---

## Self-Review

- Spec coverage: Tasks cover prompt contract, anchor context window, main LLM extraction, multi-PKU persistence, PKU relations, CKP reuse through existing helpers, deterministic fallback without Ollama, ingest trigger, and verification.
- Placeholder scan: No task uses open-ended placeholders; every behavior has a test, code target, and command.
- Type consistency: The plan consistently uses existing `ExtractedPKU`, `ExtractedPKURelation`, `AssetUnitPKUExtraction`, `GovernanceResult`, `PKURelation`, and `source_kind="document_chunk"`.

