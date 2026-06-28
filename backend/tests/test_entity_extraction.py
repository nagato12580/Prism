from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityMention, EntityRelation, KnowledgeEntity
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
            .filter_by(entity_type="person", normalized_key="yanchaotan")
            .one()
        )
        paper = (
            db.query(KnowledgeEntity)
            .filter_by(entity_type="paper", normalized_key="openvieweropennessawaremultiviewlearning")
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
