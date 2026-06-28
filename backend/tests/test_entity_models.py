from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import KnowledgeEntity, EntityMention, EntityAlias, EntityRelation


def test_entity_models_persist_entities_aliases_mentions_and_relations():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(engine)
    db = TestingSessionLocal()
    try:
        person = KnowledgeEntity(
            entity_type="person",
            canonical_name="Yanchao Tan",
            normalized_key="yanchaotan",
            aliases=["yanchaotan"],
            confidence=0.95,
            status="active",
        )
        paper = KnowledgeEntity(
            entity_type="paper",
            canonical_name="OpenViewer",
            normalized_key="openviewer",
            confidence=0.9,
            status="active",
        )
        db.add_all([person, paper])
        db.flush()

        alias = EntityAlias(
            entity_id=person.id,
            alias="yanchaotan",
            normalized_key="yanchaotan",
            confidence=0.85,
            extraction_method="rule_author_list",
        )
        mention = EntityMention(
            entity_id=person.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            chunk_id="chunk-1",
            item_id="item-1",
            surface_text="Yanchao Tan",
            normalized_key="yanchaotan",
            evidence_span="Yanchao Tan, OpenViewer",
            confidence=0.92,
            extraction_method="rule_author_list",
        )
        relation = EntityRelation(
            subject_entity_id=person.id,
            predicate="authored",
            object_entity_id=paper.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            evidence_span="Yanchao Tan authored OpenViewer",
            confidence=0.88,
            extraction_method="rule_author_list",
        )
        db.add_all([alias, mention, relation])
        db.commit()

        assert db.query(KnowledgeEntity).count() == 2
        assert db.query(EntityAlias).count() == 1
        assert db.query(EntityMention).count() == 1
        assert db.query(EntityRelation).count() == 1

        loaded_person = db.query(KnowledgeEntity).filter_by(entity_type="person").one()
        assert loaded_person.canonical_name == "Yanchao Tan"
        assert loaded_person.aliases == ["yanchaotan"]
        assert loaded_person.confidence == 0.95
        assert loaded_person.status == "active"
        assert loaded_person.entity_aliases[0].normalized_key == "yanchaotan"
        assert loaded_person.mentions[0].source_kind == "document_chunk"
        assert loaded_person.mentions[0].source_id == "chunk-1"
        assert loaded_person.mentions[0].item_id == "item-1"
        assert loaded_person.mentions[0].chunk_id == "chunk-1"
        assert loaded_person.mentions[0].surface_text == "Yanchao Tan"
        assert loaded_person.mentions[0].evidence_span == "Yanchao Tan, OpenViewer"
        assert loaded_person.mentions[0].extraction_method == "rule_author_list"

        loaded_relation = db.query(EntityRelation).one()
        assert loaded_relation.subject_entity_id == loaded_person.id
        assert loaded_relation.object_entity_id == paper.id
        assert loaded_relation.predicate == "authored"
        assert loaded_relation.evidence_span == "Yanchao Tan authored OpenViewer"
        assert loaded_relation.confidence == 0.88
    finally:
        db.close()
