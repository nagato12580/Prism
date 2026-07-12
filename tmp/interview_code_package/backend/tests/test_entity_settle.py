import os

# database.py creates the engine at import time using settings.DATABASE_URL;
# set a sqlite default before any backend import so import never fails.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_entity_settle_test.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityMention, EntityRelation, KnowledgeEntity
from backend.app.services.entity_extraction import EntityCandidate, settle_entity_candidates


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    return session


def test_settle_entity_candidates_persists_entity_and_mention_from_prebuilt_candidate():
    db = _db()
    try:
        candidate = EntityCandidate(
            kind="entity",
            entity_type="concept",
            surface_text="混合检索",
            normalized_key="混合检索",
            aliases=["混合检索"],
            confidence=0.85,
            evidence_span="应结合 metadata filter",
            extraction_method="llm_stage_a:INFERRED",
        )

        settle_entity_candidates(
            db,
            [candidate],
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            chunk_id="chunk-1",
            user_id="default-user",
        )
        db.commit()

        entity = (
            db.query(KnowledgeEntity)
            .filter_by(
                user_id="default-user",
                entity_type="concept",
                normalized_key="混合检索",
            )
            .one()
        )
        assert entity.entity_type == "concept"
        assert entity.canonical_name == "混合检索"

        mention = (
            db.query(EntityMention)
            .filter_by(
                entity_id=entity.id,
                source_id="chunk-1",
                extraction_method="llm_stage_a:INFERRED",
            )
            .one()
        )
        assert mention.source_kind == "document_chunk"
        assert mention.chunk_id == "chunk-1"
        assert mention.item_id == "item-1"
        assert mention.surface_text == "混合检索"
    finally:
        db.close()


def test_entity_candidate_default_confidence_is_zero():
    c = EntityCandidate(kind="entity", entity_type="concept", surface_text="x", normalized_key="x")
    assert c.confidence == 0.0


def test_settle_entity_candidates_persists_concept_relation():
    from backend.app.database import Base, engine as _engine
    from backend.app.models import EntityRelation, KnowledgeEntity
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        db.query(EntityRelation).delete()
        db.query(EntityMention).delete()
        db.query(KnowledgeEntity).delete()
        db.commit()
        candidates = [
            EntityCandidate(kind="entity", entity_type="concept", surface_text="混合检索",
                            normalized_key="混合检索", aliases=["混合检索"], confidence=1.0,
                            extraction_method="llm_stage_a:EXTRACTED"),
            EntityCandidate(kind="entity", entity_type="method", surface_text="RRF融合",
                            normalized_key="rrf融合", aliases=["rrf融合"], confidence=1.0,
                            extraction_method="llm_stage_a:EXTRACTED"),
            EntityCandidate(kind="relation", confidence=0.85,
                            evidence_span="混合检索 uses RRF融合",
                            extraction_method="llm_stage_a:INFERRED",
                            subject_surface="混合检索", predicate="uses",
                            object_surface="RRF融合", object_entity_type=""),
        ]
        settle_entity_candidates(db, candidates, source_kind="document_chunk", source_id="c1",
                                 item_id="i1", chunk_id="c1", user_id="default-user")
        db.commit()
        rels = db.query(EntityRelation).all()
        assert len(rels) == 1
        subj = db.query(KnowledgeEntity).filter_by(canonical_name="混合检索").one()
        obj = db.query(KnowledgeEntity).filter_by(canonical_name="RRF融合").one()
        assert rels[0].subject_entity_id == subj.id
        assert rels[0].object_entity_id == obj.id
        assert rels[0].predicate == "uses"
    finally:
        db.close()
