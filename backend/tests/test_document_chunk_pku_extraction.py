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


def test_document_chunk_pku_prompt_requires_chinese_natural_language_fields():
    system_prompt, user_message = build_document_chunk_pku_extraction_messages(
        item_id="item-1",
        title="LLM fine-tuning guide",
        summary="LoRA and evaluation practices.",
        category="AI",
        tags=["fine-tuning"],
        source_type="manual",
        anchor_chunk={
            "id": "chunk-1",
            "text": "LoRA reduces trainable parameters.",
            "index": 0,
        },
    )

    request = json.loads(user_message)
    contract_text = json.dumps(
        {
            "system": system_prompt,
            "rules": request["rules"],
            "shape": request["json_shape"],
        },
        ensure_ascii=False,
    )

    assert "自然语言字段" in contract_text
    assert "中文" in contract_text
    assert "JSON key" in contract_text
    assert "枚举" in contract_text
    assert "证据" in contract_text
    assert "原文" in contract_text
    assert request["json_shape"]["pkus"][0]["statement"] == "用中文表达的原子知识陈述"
    assert request["json_shape"]["pkus"][0]["evidence"] == "来自 anchor chunk 的原文证据摘录，不翻译"


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
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(kg, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 2
    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").all()
    assert len(pkus) == 2
    assert {pku.source_id for pku in pkus} == {anchor.id}
    assert {pku.llm_model for pku in pkus} == {"qwen-plus"}
    assert {pku.unit_type for pku in pkus} == {"method"}
    assert {pku.embedding_ref for pku in pkus} == {f"pku:{pku.id}" for pku in pkus}
    assert {pku.embedding_model for pku in pkus} == {kg.settings.EMBEDDING_MODEL}
    assert {pku.embedding_status for pku in pkus} == {"done"}


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
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(kg, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_relation_count == 1
    relation = db_session.query(PKURelation).one()
    assert relation.source_kind == "document_chunk"
    assert relation.source_id == anchor.id
    assert relation.relation_type == "prerequisite_of"
    assert relation.llm_model == "qwen-plus"


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

    def fake_extract_topics(**kwargs):
        member_refs = [pku["ref"] for pku in kwargs["pkus"]]
        return kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=member_refs,
                    confidence=0.9,
                    reason="document-level topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        )

    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        fake_extract_topics,
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(kg, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            parent_topics=[
                kg.ExtractedCKPParentTopic(
                    local_id="parent_without_members",
                    title="Skipped parent",
                    description="No referenced children.",
                    keywords=[],
                    concepts=[],
                    entities=[],
                    domains=[],
                    member_child_refs=[],
                    confidence=0.1,
                    reason="test isolation",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 2
    assert result.canonical_count == 1
    assert result.link_count == 2
    ckp = db_session.query(CanonicalKnowledgePoint).one()
    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    assert {link.relation_type for link in db_session.query(PKUCanonicalLink).all()} == {"about"}


def test_document_settlement_qualifies_duplicate_local_ids_across_chunks(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(
        title="Retrieval operations",
        summary="Different chunks mention different retrieval practices.",
        category="RAG",
        tags=["retrieval"],
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    first_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filters narrow retrieval candidates.",
        chunk_type="parent",
        chunk_index=0,
    )
    second_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Rerankers reorder retrieval candidates.",
        chunk_type="parent",
        chunk_index=1,
    )
    db_session.add_all([first_chunk, second_chunk])
    db_session.flush()

    def fake_extract(item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None):
        if anchor_chunk.id == first_chunk.id:
            statement = "Metadata filters narrow retrieval candidates."
            keywords = ["metadata", "retrieval"]
        else:
            statement = "Rerankers reorder retrieval candidates."
            keywords = ["reranker", "retrieval"]
        return kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement=statement,
                    unit_type="method",
                    evidence_span=statement,
                    keywords=keywords,
                    concepts=["retrieval"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.9,
                    reason="chunk evidence",
                    llm_model="qwen-plus",
                )
            ],
            relations=[],
            llm_model="qwen-plus",
        )

    def fake_extract_topics(**kwargs):
        refs = [pku["ref"] for pku in kwargs["pkus"]]
        assert len(refs) == 2
        assert len(set(refs)) == 2
        return kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="Retrieval operations",
                    description="Methods for narrowing and reordering retrieval candidates.",
                    keywords=["retrieval"],
                    concepts=["metadata", "reranker"],
                    entities=[],
                    domains=["RAG"],
                    member_pku_refs=refs,
                    confidence=0.92,
                    reason="document-level topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        )

    monkeypatch.setattr(kg, "_extract_document_chunk_pkus_with_llm", fake_extract)
    monkeypatch.setattr(kg, "_extract_ckp_topics_with_llm", fake_extract_topics)
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(kg, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            parent_topics=[
                kg.ExtractedCKPParentTopic(
                    local_id="parent_without_members",
                    title="Skipped parent",
                    description="No referenced children.",
                    keywords=[],
                    concepts=[],
                    entities=[],
                    domains=[],
                    member_child_refs=[],
                    confidence=0.1,
                    reason="test isolation",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 2
    assert result.link_count == 2
    assert result.canonical_count == 1
    assert db_session.query(CanonicalKnowledgePoint).one().canonical_type == "topic"
    links = db_session.query(PKUCanonicalLink).all()
    assert {link.relation_type for link in links} == {"about"}
    assert len({link.pku_id for link in links}) == 2


def test_document_settlement_passes_previous_and_next_parent_chunks(db_session, monkeypatch):
    from datetime import datetime, timedelta

    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    base = datetime(2026, 1, 1, 12, 0, 0)
    item = KnowledgeItem(title="Chunk context", category="RAG", tags=[], user_id="default-user")
    db_session.add(item)
    db_session.flush()
    first = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Previous parent context.",
        chunk_type="parent",
        created_at=base,
    )
    second = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Anchor parent content.",
        chunk_type="parent",
        created_at=base + timedelta(seconds=1),
    )
    third = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Next parent context.",
        chunk_type="parent",
        created_at=base + timedelta(seconds=2),
    )
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
    monkeypatch.setattr(kg, "_fallback_document_chunk_pku", lambda item, chunk: None)
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_document_item_to_governance(db_session, item.id)

    assert calls == [
        {"anchor": first.id, "previous": None, "next": second.id, "index": 0},
        {"anchor": second.id, "previous": first.id, "next": third.id, "index": 1},
        {"anchor": third.id, "previous": second.id, "next": None, "index": 2},
    ]


def test_document_settlement_orders_neighbor_context_by_chunk_index(db_session, monkeypatch):
    from datetime import datetime

    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Chunk source order", category="RAG", tags=[], user_id="default-user")
    db_session.add(item)
    db_session.flush()
    first = KnowledgeChunk(
        item_id=item.id,
        chunk_text="First parent source context.",
        chunk_type="parent",
        chunk_index=0,
        created_at=datetime(2026, 1, 1, 12, 0, 2),
    )
    second = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Second parent anchor context.",
        chunk_type="parent",
        chunk_index=1,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    third = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Third parent source context.",
        chunk_type="parent",
        chunk_index=2,
        created_at=datetime(2026, 1, 1, 12, 0, 1),
    )
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
    monkeypatch.setattr(kg, "_fallback_document_chunk_pku", lambda item, chunk: None)
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_document_item_to_governance(db_session, item.id)

    assert calls == [
        {"anchor": first.id, "previous": None, "next": second.id, "index": 0},
        {"anchor": second.id, "previous": first.id, "next": third.id, "index": 1},
        {"anchor": third.id, "previous": second.id, "next": None, "index": 2},
    ]


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
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            [], []
        ),
    )
    monkeypatch.setattr(
        kg,
        "_ollama_pku_type_decision",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Document fallback must not call Ollama")),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    result = kg.settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").one()
    assert pku.statement == "Metadata filter is defined as a constraint on retrieval candidates."
    assert pku.unit_type == "definition"
    assert pku.llm_model == ""


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


def test_clear_document_item_governance_deprecates_legacy_source_item_orphan_topic_ckps(db_session):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Legacy fine-tuning guide", user_id="default-user")
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="QLoRA reduces memory.", chunk_type="parent")
    db_session.add(chunk)
    db_session.flush()
    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="QLoRA reduces memory.",
        normalized_statement="QLoRA reduces memory.",
        normalized_statement_hash="cleanup-legacy-topic-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Legacy LLM fine-tuning",
        canonical_statement="Legacy fine-tuning topic hub.",
        status="draft",
        extra_meta={"created_from": "document_chunk", "source_item_id": item.id},
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


def test_clear_document_item_governance_deprecates_preexisting_orphan_topic_ckps(db_session):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Already orphaned fine-tuning guide", user_id="default-user")
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="DoRA improves adapter tuning.", chunk_type="parent")
    db_session.add(chunk)
    db_session.flush()
    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="DoRA improves adapter tuning.",
        normalized_statement="DoRA improves adapter tuning.",
        normalized_statement_hash="cleanup-preexisting-orphan-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Already orphaned LLM fine-tuning",
        canonical_statement="Already orphaned fine-tuning topic hub.",
        status="draft",
        extra_meta={"created_from": "document_chunk", "source_item_id": item.id},
    )
    db_session.add_all([pku, ckp])
    db_session.commit()

    deleted = kg.clear_document_item_governance(db_session, item.id)
    db_session.commit()

    assert deleted == 1
    db_session.refresh(ckp)
    assert ckp.status == "deprecated"


def test_clear_document_item_governance_keeps_shared_document_topic_ckp_active(db_session):
    from backend.app.models import CanonicalKnowledgePoint, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(title="Shared fine-tuning guide", user_id="default-user")
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="Adapters support efficient tuning.", chunk_type="parent")
    db_session.add(chunk)
    db_session.flush()
    document_pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Adapters support efficient tuning.",
        normalized_statement="Adapters support efficient tuning.",
        normalized_statement_hash="cleanup-shared-document-pku",
        status="active",
    )
    surviving_pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="asset-unit-1",
        unit_type="method",
        statement="Adapter tuning is a reusable efficient tuning method.",
        normalized_statement="Adapter tuning is a reusable efficient tuning method.",
        normalized_statement_hash="cleanup-shared-surviving-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Shared LLM fine-tuning",
        canonical_statement="Shared fine-tuning topic hub.",
        status="draft",
        extra_meta={"created_from": "document_chunk", "source_id": item.id, "source_item_id": item.id},
    )
    db_session.add_all([document_pku, surviving_pku, ckp])
    db_session.flush()
    db_session.add_all(
        [
            PKUCanonicalLink(
                user_id="default-user",
                pku_id=document_pku.id,
                canonical_id=ckp.id,
                relation_type="about",
            ),
            PKUCanonicalLink(
                user_id="default-user",
                pku_id=surviving_pku.id,
                canonical_id=ckp.id,
                relation_type="about",
            ),
        ]
    )
    db_session.commit()

    deleted = kg.clear_document_item_governance(db_session, item.id)
    db_session.commit()

    assert deleted == 1
    db_session.refresh(ckp)
    assert ckp.status == "draft"
