"""Task 1 (Graph): scoped graph facts, generations, and outbox schema."""

from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    GraphExtractionRevision,
    GraphOutboxEvent,
    GraphProjectionCursor,
    GraphProjectionReceipt,
    KnowledgeEntity,
    KnowledgeGraphGeneration,
)


def test_entity_identity_is_scoped_by_tenant_kb_and_generation(db_session):
    common = dict(entity_type="concept", normalized_key="prism", canonical_name="Prism")
    db_session.add_all(
        [
            KnowledgeEntity(tenant_id="t1", kb_uid="k1", graph_generation="g1", **common),
            KnowledgeEntity(tenant_id="t1", kb_uid="k2", graph_generation="g1", **common),
        ]
    )
    db_session.commit()
    assert db_session.query(KnowledgeEntity).count() == 2


def test_same_scope_duplicate_entity_is_rejected(db_session):
    db_session.add_all(
        [
            KnowledgeEntity(
                tenant_id="t1", kb_uid="k1", graph_generation="g1",
                entity_type="concept", normalized_key="prism", canonical_name="Prism",
            ),
            KnowledgeEntity(
                tenant_id="t1", kb_uid="k1", graph_generation="g1",
                entity_type="concept", normalized_key="prism", canonical_name="Prism 2",
            ),
        ]
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("same-scope duplicate entity was accepted")


def test_graph_generation_scope_is_unique(db_session):
    db_session.add_all(
        [
            KnowledgeGraphGeneration(
                tenant_id="t1", kb_uid="k1", generation="g1", extractor_config_hash="abc123",
            ),
            KnowledgeGraphGeneration(
                tenant_id="t1", kb_uid="k1", generation="g1", extractor_config_hash="abc123",
            ),
        ]
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate graph generation scope was accepted")


def test_projection_receipt_is_unique_per_event_and_projector(db_session):
    event = GraphOutboxEvent(
        event_id="evt-1", tenant_id="t1", kb_uid="k1", graph_generation="g1",
        aggregate_type="mention", aggregate_id="mention-1", event_type="mention.upserted",
        payload={"mention_id": "mention-1"},
    )
    db_session.add(event)
    db_session.flush()
    db_session.add_all(
        [
            GraphProjectionReceipt(event_id="evt-1", projector="neo4j"),
            GraphProjectionReceipt(event_id="evt-1", projector="neo4j"),
        ]
    )
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate projection receipt was accepted")


def test_extraction_revision_key_is_unique(db_session):
    common = dict(
        tenant_id="t1", kb_uid="k1", file_uid="f1", item_id="i1", chunk_uid="c1",
        graph_generation="g1", content_hash="a" * 64, extractor_config_hash="b" * 64,
        model_version="m1", prompt_version="p1",
    )
    db_session.add_all([GraphExtractionRevision(**common), GraphExtractionRevision(**common)])
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
    else:
        raise AssertionError("duplicate extraction revision was accepted")


def test_projection_cursor_advances_through_sequence(db_session):
    cursor = GraphProjectionCursor(
        tenant_id="t1", kb_uid="k1", graph_generation="g1", projector="neo4j",
        applied_through_sequence=42,
    )
    db_session.add(cursor)
    db_session.commit()
    loaded = db_session.query(GraphProjectionCursor).one()
    assert loaded.applied_through_sequence == 42
