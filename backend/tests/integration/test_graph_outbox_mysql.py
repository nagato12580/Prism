"""Task 1 (Graph) MySQL integration: scoped unique constraints + monotonic
outbox sequence on real MySQL."""

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import (
    GraphOutboxEvent,
    GraphProjectionReceipt,
    KnowledgeEntity,
)


pytestmark = pytest.mark.mysql


def test_scoped_entity_unique_rejects_same_scope_duplicate(mysql_session):
    mysql_session.add(
        KnowledgeEntity(
            tenant_id="t1", kb_uid="k1", graph_generation="g1",
            entity_type="concept", normalized_key="prism", canonical_name="Prism",
        )
    )
    mysql_session.flush()
    mysql_session.add(
        KnowledgeEntity(
            tenant_id="t1", kb_uid="k1", graph_generation="g1",
            entity_type="concept", normalized_key="prism", canonical_name="Prism 2",
        )
    )
    with pytest.raises(IntegrityError):
        mysql_session.commit()
    mysql_session.rollback()


def test_scoped_entity_allows_same_key_in_different_kb(mysql_session):
    mysql_session.add_all(
        [
            KnowledgeEntity(
                tenant_id="t1", kb_uid="k1", graph_generation="g1",
                entity_type="concept", normalized_key="prism", canonical_name="Prism",
            ),
            KnowledgeEntity(
                tenant_id="t1", kb_uid="k2", graph_generation="g1",
                entity_type="concept", normalized_key="prism", canonical_name="Prism",
            ),
        ]
    )
    mysql_session.commit()
    assert mysql_session.query(KnowledgeEntity).count() == 2


def test_outbox_sequence_is_monotonic(mysql_session):
    events = []
    for i in range(3):
        event = GraphOutboxEvent(
            tenant_id="t1", kb_uid="k1", graph_generation="g1",
            aggregate_type="mention", aggregate_id=f"m-{i}", event_type="mention.upserted",
            payload={"mention_id": f"m-{i}"},
        )
        mysql_session.add(event)
        events.append(event)
    mysql_session.commit()
    sequences = sorted(event.sequence for event in events)
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == 3
    assert all(s > 0 for s in sequences)


def test_projection_receipt_unique_per_event_and_projector(mysql_session):
    event = GraphOutboxEvent(
        tenant_id="t1", kb_uid="k1", graph_generation="g1",
        aggregate_type="mention", aggregate_id="m-1", event_type="mention.upserted",
        payload={"mention_id": "m-1"},
    )
    mysql_session.add(event)
    mysql_session.flush()
    mysql_session.add_all(
        [
            GraphProjectionReceipt(event_id=event.event_id, projector="neo4j"),
            GraphProjectionReceipt(event_id=event.event_id, projector="neo4j"),
        ]
    )
    with pytest.raises(IntegrityError):
        mysql_session.commit()
    mysql_session.rollback()
