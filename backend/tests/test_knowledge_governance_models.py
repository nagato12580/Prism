from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalAssetItem,
    PersonalAssetUnit,
    PersonalKnowledgeUnit,
)
from backend.app.services.knowledge_governance import (
    _ollama_pku_type_decision,
    settle_document_item_to_governance,
    settle_personal_asset_item_to_governance,
    settle_personal_asset_unit_to_governance,
)


def test_governance_models_store_pku_ckp_links_and_relations(db_session):
    pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="claim",
        statement="Personal knowledge bases benefit from hybrid retrieval.",
        normalized_statement="personal knowledge bases benefit from hybrid retrieval",
        normalized_statement_hash="hash-mixed-retrieval",
        modality="fact",
        keywords=["knowledge", "hybrid", "retrieval"],
        confidence=0.8,
    )
    ckp = CanonicalKnowledgePoint(
        canonical_type="claim",
        title="Hybrid retrieval improves personal knowledge search",
        canonical_statement="Personal knowledge bases benefit from hybrid retrieval.",
        keywords=["knowledge", "hybrid", "retrieval"],
        confidence=0.8,
    )
    related = CanonicalKnowledgePoint(
        canonical_type="method",
        title="Metadata filter assisted retrieval",
        canonical_statement="Metadata filters can narrow retrieval scope.",
        keywords=["metadata", "filter"],
    )
    db_session.add_all([pku, ckp, related])
    db_session.flush()

    link = PKUCanonicalLink(
        pku_id=pku.id,
        canonical_id=ckp.id,
        relation_type="same_as",
        role="synthesized_personal_knowledge",
        confidence=0.86,
    )
    relation = CanonicalRelation(
        source_canonical_id=ckp.id,
        target_canonical_id=related.id,
        relation_type="uses",
        confidence=0.7,
    )
    db_session.add_all([link, relation])
    db_session.commit()

    loaded = db_session.query(CanonicalKnowledgePoint).filter_by(title="Hybrid retrieval improves personal knowledge search").one()
    assert loaded.pku_links[0].pku.statement == "Personal knowledge bases benefit from hybrid retrieval."
    assert loaded.pku_links[0].role == "synthesized_personal_knowledge"
    assert loaded.outgoing_relations[0].target.title == "Metadata filter assisted retrieval"


def test_pku_dedupes_per_source_and_normalized_statement(db_session):
    first = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="claim",
        statement="Vector search alone can miss relevant evidence.",
        normalized_statement="vector search alone can miss relevant evidence",
        normalized_statement_hash="hash-vector-misrecall",
    )
    duplicate = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="claim",
        statement="Pure vector search may miss relevant evidence.",
        normalized_statement="vector search alone can miss relevant evidence",
        normalized_statement_hash="hash-vector-misrecall",
    )
    db_session.add_all([first, duplicate])

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate PKU should violate uq_pku_source_normalized")


def test_pku_relations_store_direct_pku_edges(db_session):
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


def test_confirmed_asset_item_settles_into_pku_and_ckp(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: (_ for _ in ()).throw(AssertionError("asset item settlement must not call asset-unit LLM extraction")),
    )

    asset = PersonalAssetItem(
        raw_text="Metadata filters are useful for personal knowledge retrieval.",
        title="Metadata filter note",
        body="Metadata filters are useful for personal knowledge retrieval.",
        summary="Metadata filters are useful.",
        asset_kind="opinion",
        category="RAG",
        tags=["metadata", "filter"],
        extracts=[{"type": "claim", "content": "Metadata filters are useful.", "confidence": 0.9}],
        confidence={"overall": 0.9, "extraction": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(asset)
    db_session.flush()

    result = settle_personal_asset_item_to_governance(db_session, asset)
    db_session.commit()

    assert result.pku_count == 1
    assert result.canonical_count == 1
    assert result.link_count == 1

    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_item").all()
    assert len(pkus) == 1
    assert {pku.source_id for pku in pkus} == {asset.id}
    assert {pku.statement for pku in pkus} == {"Metadata filters are useful."}
    assert {pku.unit_type for pku in pkus} == {"claim"}
    assert {pku.modality for pku in pkus} == {"opinion"}

    ckps = db_session.query(CanonicalKnowledgePoint).all()
    assert len(ckps) == 1
    assert {ckp.extra_meta["created_from"] for ckp in ckps} == {"personal_asset_item"}
    assert {ckp.extra_meta["source_id"] for ckp in ckps} == {asset.id}

    links = db_session.query(PKUCanonicalLink).all()
    assert len(links) == 1
    assert {link.relation_type for link in links} == {"same_as"}
    assert {link.role for link in links} == {"personal_claim"}
    assert {link.reason for link in links} == {"Initial deterministic settlement from confirmed PersonalAssetItem."}
    assert {link.pku.source_kind for link in links} == {"personal_asset_item"}
    assert {link.pku.source_id for link in links} == {asset.id}


def test_document_and_asset_unit_pkus_can_share_ckp_with_distinct_roles(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    monkeypatch.setattr(kg, "_extract_asset_unit_pkus_with_llm", lambda unit: kg.AssetUnitPKUExtraction([], []))
    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            [], []
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(kg, "_extract_ckp_parent_topics_with_llm", lambda **kwargs: kg.CKPParentTopicAssignment([]))

    unit = PersonalAssetUnit(
        title="Metadata filter retrieval practice",
        content="Metadata filter can restrict retrieval results by source, project, or category.",
        summary="Metadata filter can restrict retrieval results by source, project, or category.",
        category="RAG",
        tags=["metadata", "filter"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval results by source, project, or category.",
        summary="Metadata filter can restrict retrieval results.",
        source_type="manual",
        category="RAG",
        tags=["metadata", "filter"],
        user_id="default-user",
    )
    db_session.add_all([unit, item])
    db_session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source, project, or category.",
        chunk_type="parent",
    )
    db_session.add(chunk)
    db_session.flush()

    unit_result = settle_personal_asset_unit_to_governance(db_session, unit)
    doc_result = settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert unit_result.pku_count == 1
    assert doc_result.pku_count == 1
    ckps = db_session.query(CanonicalKnowledgePoint).all()
    assert len(ckps) == 2
    assert {ckp.canonical_type for ckp in ckps} == {"topic"}
    child_ckps = [ckp for ckp in ckps if ckp.extra_meta["topic_level"] == "child"]
    parent_ckps = [ckp for ckp in ckps if ckp.extra_meta["topic_level"] == "parent"]
    assert len(child_ckps) == 1
    assert len(parent_ckps) == 1

    links = db_session.query(PKUCanonicalLink).all()
    assert {link.relation_type for link in links} == {"about"}
    assert {link.role for link in links} == {"topic_member"}
    assert {link.canonical_id for link in links} == {child_ckps[0].id}
    relation = db_session.query(CanonicalRelation).one()
    assert relation.source_canonical_id == child_ckps[0].id
    assert relation.target_canonical_id == parent_ckps[0].id
    assert relation.relation_type == "subtopic_of"
    pkus = db_session.query(PersonalKnowledgeUnit).all()
    assert len(pkus) == 2
    assert {pku.source_kind for pku in pkus} == {"personal_asset_unit", "document_chunk"}
    assert {pku.modality for pku in pkus} == {"fact"}


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
        lambda **kwargs: kg.CKPParentTopicAssignment([]),
    )

    unit = PersonalAssetUnit(
        title="LoRA fine-tuning methods",
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
    assert {ckp.title for ckp in ckps} == {"LoRA fine-tuning methods", "General: LoRA fine-tuning methods"}
    parent = next(ckp for ckp in ckps if ckp.title == "General: LoRA fine-tuning methods")
    child = next(ckp for ckp in ckps if ckp.title == "LoRA fine-tuning methods")
    assert parent.extra_meta["topic_level"] == "parent"
    assert child.extra_meta["topic_level"] == "child"

    relation = db_session.query(CanonicalRelation).one()
    assert relation.source_canonical_id == child.id
    assert relation.target_canonical_id == parent.id
    assert relation.relation_type == "subtopic_of"
    assert result.canonical_count == 2
    assert result.link_count == 2


def test_document_pku_type_uses_local_fallback_when_llm_empty(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            [], []
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

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


def test_document_settlement_commits_chunk_writes_before_next_llm_extraction(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    item = KnowledgeItem(
        title="Chunk settlement locks",
        content="First chunk. Second chunk.",
        source_type="manual",
        category="RAG",
        tags=["locks"],
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    chunks = [
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="First chunk creates a PKU.",
            chunk_index=0,
            chunk_type="parent",
        ),
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="Second chunk should not wait behind first chunk writes.",
            chunk_index=1,
            chunk_type="parent",
        ),
    ]
    db_session.add_all(chunks)
    db_session.commit()
    events = []
    original_commit = db_session.commit

    def commit_spy():
        events.append("commit")
        return original_commit()

    monkeypatch.setattr(db_session, "commit", commit_spy)
    monkeypatch.setattr(kg, "_refresh_pku_vector", lambda pku: None)
    monkeypatch.setattr(kg, "_settle_local_pku_topics", lambda *args, **kwargs: (0, 0))

    def fake_extract(item, anchor_chunk, previous_chunk=None, next_chunk=None, *, anchor_index=None):
        if anchor_index == 1 and "commit" not in events:
            raise AssertionError("previous chunk writes were not committed before next LLM extraction")
        events.append(f"extract:{anchor_index}")
        return kg.AssetUnitPKUExtraction(
            [
                kg.ExtractedPKU(
                    statement=f"Chunk {anchor_index} should commit promptly.",
                    unit_type="claim",
                    evidence_span=anchor_chunk.chunk_text,
                    keywords=["chunk", "commit"],
                    concepts=["governance"],
                    entities=[],
                    domains=["RAG"],
                    group="",
                    confidence=0.9,
                    reason="test",
                    local_id=f"pku_{anchor_index}",
                )
            ],
            [],
            llm_model="test-model",
        )

    monkeypatch.setattr(kg, "_extract_document_chunk_pkus_with_llm", fake_extract)

    result = settle_document_item_to_governance(db_session, item.id)

    assert result.pku_count == 2
    assert events[:3] == ["extract:0", "commit", "extract:1"]


def test_personal_asset_unit_pku_type_uses_summary_fallback_without_ollama(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg
    from backend.app.services.knowledge_governance import AssetUnitPKUExtraction

    monkeypatch.setattr(kg, "_extract_asset_unit_pkus_with_llm", lambda unit: AssetUnitPKUExtraction([], []))

    def fail_ollama(**kwargs):
        raise AssertionError("asset unit settlement must not call Ollama type classifier")

    monkeypatch.setattr(kg, "_ollama_pku_type_decision", fail_ollama)
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    unit = PersonalAssetUnit(
        title="Asset synthesis workflow",
        content="First select confirmed fragments, then synthesize them into an auditable unit.",
        summary="Synthesize confirmed fragments into a personal asset unit.",
        category="Knowledge",
        tags=["asset", "workflow"],
        source_asset_ids=["asset-1", "asset-2"],
        confidence={"overall": 0.86},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(unit)
    db_session.flush()

    result = settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_unit").one()
    assert pku.unit_type == "claim"
    assert pku.statement == "Synthesize confirmed fragments into a personal asset unit."
    assert pku.llm_model == ""
    assert pku.source_id == unit.id


def test_pku_type_ollama_falls_back_when_unavailable(monkeypatch):
    def fail_post(*args, **kwargs):
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr("backend.app.services.knowledge_governance.httpx.post", fail_post)

    decision = _ollama_pku_type_decision(
        text="This concept is defined as a stable knowledge point.",
        fallback="definition",
    )

    assert decision.unit_type == "definition"
    assert decision.llm_model == ""
