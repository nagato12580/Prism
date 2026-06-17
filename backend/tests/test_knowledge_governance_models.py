from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PersonalAssetItem,
    PersonalKnowledgeUnit,
)
from backend.app.services.knowledge_governance import (
    settle_document_item_to_governance,
    settle_personal_asset_item_to_governance,
)


def test_governance_models_store_pku_ckp_links_and_relations(db_session):
    pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_item",
        source_id="asset-1",
        unit_type="claim",
        statement="我认为个人知识库需要混合检索。",
        normalized_statement="个人知识库需要混合检索",
        normalized_statement_hash="hash-mixed-retrieval",
        modality="opinion",
        keywords=["知识库", "混合检索"],
        confidence=0.8,
    )
    ckp = CanonicalKnowledgePoint(
        canonical_type="claim",
        title="个人知识库适合混合检索",
        canonical_statement="个人知识库适合使用混合检索提升召回质量。",
        keywords=["知识库", "混合检索"],
        confidence=0.8,
    )
    related = CanonicalKnowledgePoint(
        canonical_type="method",
        title="Metadata filter 辅助检索",
        canonical_statement="Metadata filter 可以缩小检索范围。",
        keywords=["metadata filter"],
    )
    db_session.add_all([pku, ckp, related])
    db_session.flush()

    link = PKUCanonicalLink(
        pku_id=pku.id,
        canonical_id=ckp.id,
        relation_type="same_as",
        role="personal_claim",
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

    loaded = db_session.query(CanonicalKnowledgePoint).filter_by(title="个人知识库适合混合检索").one()
    assert loaded.pku_links[0].pku.statement == "我认为个人知识库需要混合检索。"
    assert loaded.pku_links[0].role == "personal_claim"
    assert loaded.outgoing_relations[0].target.title == "Metadata filter 辅助检索"


def test_pku_dedupes_per_source_and_normalized_statement(db_session):
    first = PersonalKnowledgeUnit(
        source_kind="personal_asset_item",
        source_id="asset-1",
        unit_type="claim",
        statement="纯向量检索容易误召回。",
        normalized_statement="纯向量检索容易误召回",
        normalized_statement_hash="hash-vector-misrecall",
    )
    duplicate = PersonalKnowledgeUnit(
        source_kind="personal_asset_item",
        source_id="asset-1",
        unit_type="claim",
        statement="向量检索会误召回。",
        normalized_statement="纯向量检索容易误召回",
        normalized_statement_hash="hash-vector-misrecall",
    )
    db_session.add_all([first, duplicate])

    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate PKU should violate uq_pku_source_normalized")


def test_document_and_asset_pkus_can_share_ckp_with_distinct_roles(db_session):
    asset = PersonalAssetItem(
        raw_text="我认为个人知识库需要 metadata filter 辅助检索。",
        title="个人知识库检索观点",
        body="我认为个人知识库需要 metadata filter 辅助检索。",
        summary="个人知识库需要 metadata filter 辅助检索。",
        asset_kind="opinion",
        category="RAG",
        tags=["metadata", "filter"],
        extracts=[{"type": "claim", "content": "个人知识库需要 metadata filter 辅助检索。", "confidence": 0.9}],
        confidence={"overall": 0.9, "extraction": 0.9},
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
    db_session.add_all([asset, item])
    db_session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source, project, or category.",
        chunk_type="parent",
    )
    db_session.add(chunk)
    db_session.flush()

    asset_result = settle_personal_asset_item_to_governance(db_session, asset)
    doc_result = settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    assert asset_result.pku_count == 1
    assert doc_result.pku_count == 1
    assert db_session.query(CanonicalKnowledgePoint).count() == 1

    links = db_session.query(PKUCanonicalLink).all()
    assert {link.role for link in links} == {"personal_claim", "external_reference"}
    pkus = db_session.query(PersonalKnowledgeUnit).all()
    assert len(pkus) == 2
    assert {pku.source_kind for pku in pkus} == {"personal_asset_item", "document_chunk"}
    assert {pku.modality for pku in pkus} == {"opinion", "fact"}
