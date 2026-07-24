"""Task 2 (Graph): graph facts and outbox events commit atomically, and the
same extraction key is idempotent."""

import pytest

from backend.app.models import EntityMention, GraphOutboxEvent
from backend.app.services.graph_facts import GraphFactScope, GraphFactWriter


def _candidate(name="Prism"):
    from backend.app.services.entity_extraction import _entity_candidate

    return _entity_candidate("concept", name, 0.9, name, "rule")


def test_fact_and_outbox_roll_back_together(db_session, monkeypatch):
    writer = GraphFactWriter(db_session)
    scope = GraphFactScope("t1", "k1", "f1", "i1", "c1", "g1")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(writer.outbox, "append", boom)

    with pytest.raises(RuntimeError, match="boom"):
        with db_session.begin():
            writer.settle(
                scope,
                candidates=[_candidate()],
                content_hash="a" * 64,
                extractor_config_hash="b" * 64,
            )

    assert db_session.query(EntityMention).count() == 0
    assert db_session.query(GraphOutboxEvent).count() == 0


def test_same_extraction_key_returns_existing_revision(db_session):
    writer = GraphFactWriter(db_session)
    scope = GraphFactScope("t1", "k1", "f1", "i1", "c1", "g1")

    first = writer.settle(scope, [_candidate()], "a" * 64, "b" * 64)
    second = writer.settle(scope, [_candidate()], "a" * 64, "b" * 64)

    assert second.revision_id == first.revision_id
    # Second settle is a no-op (revision already succeeded): no new events.
    assert db_session.query(GraphOutboxEvent).count() == first.event_count


def test_settle_writes_scoped_facts_and_outbox_events(db_session):
    writer = GraphFactWriter(db_session)
    scope = GraphFactScope("t1", "k1", "f1", "i1", "c1", "g1")

    result = writer.settle(scope, [_candidate("Prism"), _candidate("Atlas")], "c" * 64, "d" * 64)

    assert result.event_count >= 1
    events = db_session.query(GraphOutboxEvent).all()
    assert all(e.tenant_id == "t1" and e.kb_uid == "k1" and e.graph_generation == "g1" for e in events)
    mentions = db_session.query(EntityMention).all()
    assert all(m.tenant_id == "t1" and m.kb_uid == "k1" and m.graph_generation == "g1" for m in mentions)
    assert all(m.active == "true" for m in mentions)
