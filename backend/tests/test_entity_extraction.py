from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityAlias, EntityMention, EntityRelation, KnowledgeEntity
from backend.app.services.entity_extraction import (
    extract_and_settle_entities,
    extract_entity_candidates_from_text,
)


OPENVIEWER_FRONT_MATTER = (
    "OpenViewer: Openness-Aware Multi-View Learning\n"
    "Shide Du1,2, Zihan Fang1,2, Yanchao Tan1,2, Changwei Wang3, Shiping Wang1,2\n"
    "1 College of Computer and Data Science, Fuzhou University, Fuzhou, China\n"
    "dushidems@gmail.com, fzihan11@163.com, yctan@fzu.edu.cn, shipingwangphd@163.com\n"
)


def test_extracts_paper_authors_email_and_organizations_from_paper_front_matter():
    candidates = extract_entity_candidates_from_text(OPENVIEWER_FRONT_MATTER, source_kind="document_chunk")

    by_name = {(item.entity_type, item.surface_text) for item in candidates if item.kind == "entity"}

    assert ("paper", "OpenViewer: Openness-Aware Multi-View Learning") in by_name
    assert ("person", "Yanchao Tan") in by_name
    assert ("person", "Shiping Wang") in by_name
    assert ("organization", "Fuzhou University") in by_name
    assert ("email", "yctan@fzu.edu.cn") in by_name


def test_extracts_author_relations_to_paper():
    text = "OpenViewer: Openness-Aware Multi-View Learning\nYanchao Tan, Shiping Wang\n"

    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")

    relations = [item for item in candidates if item.kind == "relation"]
    assert any(
        item.subject_surface == "Yanchao Tan"
        and item.predicate == "authored"
        and item.object_surface == "OpenViewer: Openness-Aware Multi-View Learning"
        for item in relations
    )


def test_extracts_paper_title_after_preface_lines():
    text = (
        "Preface line one\n"
        "Preface line two\n"
        "Preface line three\n"
        "Preface line four\n"
        "Preface line five\n"
        "Preface line six\n"
        "OpenViewer: Openness-Aware Multi-View Learning\n"
        "Yanchao Tan, Shiping Wang\n"
    )

    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")

    assert any(
        item.kind == "entity"
        and item.entity_type == "paper"
        and item.surface_text == "OpenViewer: Openness-Aware Multi-View Learning"
        for item in candidates
    )


def test_extracts_affiliation_relation_to_fuzhou_university():
    candidates = extract_entity_candidates_from_text(OPENVIEWER_FRONT_MATTER, source_kind="document_chunk")

    relations = [item for item in candidates if item.kind == "relation"]
    assert any(
        item.subject_surface == "Yanchao Tan"
        and item.predicate == "affiliated_with"
        and item.object_surface == "Fuzhou University"
        and item.object_entity_type == "organization"
        for item in relations
    )


def test_extract_and_settle_entities_is_idempotent_for_entities_mentions_and_relations():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(engine)
    db = TestingSessionLocal()
    try:
        extract_and_settle_entities(
            db,
            source_kind="document_chunk",
            source_id="chunk-1",
            text=OPENVIEWER_FRONT_MATTER,
            item_id="item-1",
            chunk_id="chunk-1",
        )
        extract_and_settle_entities(
            db,
            source_kind="document_chunk",
            source_id="chunk-1",
            text=OPENVIEWER_FRONT_MATTER,
            item_id="item-1",
            chunk_id="chunk-1",
        )
        db.commit()

        yanchao_tan = (
            db.query(KnowledgeEntity)
            .filter_by(user_id="default-user", entity_type="person", normalized_key="yanchaotan")
            .one()
        )
        paper = (
            db.query(KnowledgeEntity)
            .filter_by(
                user_id="default-user",
                entity_type="paper",
                normalized_key="openvieweropennessawaremultiviewlearning",
            )
            .one()
        )

        mention_count = (
            db.query(EntityMention)
            .filter_by(
                entity_id=yanchao_tan.id,
                source_kind="document_chunk",
                source_id="chunk-1",
                surface_text="Yanchao Tan",
            )
            .count()
        )
        relation_count = (
            db.query(EntityRelation)
            .filter_by(
                subject_entity_id=yanchao_tan.id,
                object_entity_id=paper.id,
                predicate="authored",
            )
            .count()
        )

        assert mention_count == 1
        assert relation_count == 1
    finally:
        db.close()


def test_extract_and_settle_entities_reuses_preseeded_alias_mention_and_relation():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(engine)
    db = TestingSessionLocal()
    try:
        yanchao_tan = KnowledgeEntity(
            user_id="default-user",
            entity_type="person",
            canonical_name="Yanchao Tan",
            normalized_key="yanchaotan",
            aliases=["yanchaotan", "tanyanchao"],
            confidence=0.9,
            status="active",
        )
        paper = KnowledgeEntity(
            user_id="default-user",
            entity_type="paper",
            canonical_name="OpenViewer: Openness-Aware Multi-View Learning",
            normalized_key="openvieweropennessawaremultiviewlearning",
            aliases=["openvieweropennessawaremultiviewlearning"],
            confidence=0.9,
            status="active",
        )
        db.add_all([yanchao_tan, paper])
        db.flush()

        db.add_all(
            [
                EntityAlias(
                    entity_id=yanchao_tan.id,
                    alias="yanchaotan",
                    normalized_key="yanchaotan",
                    confidence=0.9,
                    extraction_method="preseed",
                ),
                EntityMention(
                    entity_id=yanchao_tan.id,
                    source_kind="document_chunk",
                    source_id="chunk-1",
                    item_id="item-1",
                    chunk_id="chunk-1",
                    surface_text="Yanchao Tan",
                    normalized_key="yanchaotan",
                    evidence_span="Yanchao Tan",
                    confidence=0.9,
                    extraction_method="preseed",
                ),
                EntityRelation(
                    subject_entity_id=yanchao_tan.id,
                    predicate="authored",
                    object_entity_id=paper.id,
                    source_kind="document_chunk",
                    source_id="chunk-1",
                    evidence_span="Yanchao Tan authored OpenViewer",
                    confidence=0.9,
                    extraction_method="preseed",
                ),
            ]
        )
        db.commit()

        extract_and_settle_entities(
            db,
            source_kind="document_chunk",
            source_id="chunk-1",
            text=OPENVIEWER_FRONT_MATTER,
            item_id="item-1",
            chunk_id="chunk-1",
            user_id="default-user",
        )
        db.commit()

        yanchao_tan = (
            db.query(KnowledgeEntity)
            .filter_by(user_id="default-user", entity_type="person", normalized_key="yanchaotan")
            .one()
        )
        paper = (
            db.query(KnowledgeEntity)
            .filter_by(
                user_id="default-user",
                entity_type="paper",
                normalized_key="openvieweropennessawaremultiviewlearning",
            )
            .one()
        )

        assert db.query(EntityAlias).filter_by(entity_id=yanchao_tan.id, normalized_key="yanchaotan").count() == 1
        assert (
            db.query(EntityMention)
            .filter_by(
                entity_id=yanchao_tan.id,
                source_kind="document_chunk",
                source_id="chunk-1",
                surface_text="Yanchao Tan",
            )
            .count()
            == 1
        )
        assert (
            db.query(EntityRelation)
            .filter_by(
                subject_entity_id=yanchao_tan.id,
                predicate="authored",
                object_entity_id=paper.id,
                source_kind="document_chunk",
                source_id="chunk-1",
            )
            .count()
            == 1
        )
    finally:
        db.close()


# --- Task 12: governance integration (entity extraction during document settlement) ---


def test_document_governance_extracts_entities_from_chunks(monkeypatch):
    """Fresh document governance must populate entity audit rows from chunk text."""
    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    item = KnowledgeItem(
        user_id="default-user",
        title="OpenViewer",
        content="OpenViewer paper front matter.",
        source_type="document",
    )
    db.add(item)
    db.flush()
    db.add(
        KnowledgeChunk(
            item_id=item.id,
            chunk_text=(
                "OpenViewer: Openness-Aware Multi-View Learning\n"
                "Shide Du, Zihan Fang, Yanchao Tan, Changwei Wang, Shiping Wang\n"
                "College of Computer and Data Science, Fuzhou University\n"
                "yctan@fzu.edu.cn, shipingwangphd@163.com\n"
            ),
            chunk_type="parent",
        )
    )
    db.commit()

    # Avoid real LLM PKU extraction; governance should still extract entities.
    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda *args, **kwargs: kg.AssetUnitPKUExtraction([], []),
    )

    kg.settle_document_item_to_governance(db, item.id)

    entity = (
        db.query(KnowledgeEntity)
        .filter_by(user_id="default-user", entity_type="person", normalized_key="yanchaotan")
        .first()
    )
    assert entity is not None
    assert entity.canonical_name == "Yanchao Tan"
    # An authored relation from this person to the paper should also be wired.
    authored = (
        db.query(EntityRelation)
        .filter_by(
            subject_entity_id=entity.id,
            predicate="authored",
            source_kind="document_chunk",
        )
        .all()
    )
    assert authored, "expected an authored relation from Yanchao Tan to the paper"
    paper = (
        db.query(KnowledgeEntity)
        .filter_by(entity_type="paper", normalized_key="openvieweropennessawaremultiviewlearning")
        .first()
    )
    assert paper is not None
    assert any(rel.object_entity_id == paper.id for rel in authored)
