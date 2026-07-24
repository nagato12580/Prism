"""Task 3 (Graph) real-Neo4j integration: outbox projector converges events to
scoped nodes/edges and recovers after a transient failure.

Requires real MySQL (prism_test) + Neo4j. Marked ``mysql`` so it only runs when
PRISM_TEST_DATABASE_URL points at the dedicated test database.
"""
from datetime import timedelta
from uuid import uuid4

import pytest

from backend.app.models import GraphOutboxEvent
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_outbox import GraphOutboxService
from backend.app.utils.time import local_now
from engine.app.graph.neo4j_projector import Neo4jOutboxProjector
from engine.app.graph.outbox_projector import GraphProjectionReceiptStore


pytestmark = pytest.mark.mysql

SCOPE = {
    "tenant_id": "t-projector-recover",
    "kb_uid": "kb-projector-recover",
    "graph_generation": "g-projector-recover",
}


@pytest.fixture()
def graph():
    client = GraphClient()
    yield client
    # Clean up everything we wrote, scoped by tenant_id.
    client._execute_write(
        "MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n",
        {"tenant_id": SCOPE["tenant_id"]},
    )
    client.close()


def _append_entity_event(db, entity_id):
    svc = GraphOutboxService(db)
    return svc.append(
        tenant_id=SCOPE["tenant_id"],
        kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"],
        aggregate_type="entity",
        aggregate_id=entity_id,
        event_type="entity.upserted",
        payload={
            "entity_id": entity_id,
            "entity_type": "concept",
            "canonical_name": "Prism",
            "normalized_key": "prism",
            "aliases": [],
            "confidence": 0.9,
        },
    )


def _append_mention_event(db, mention_id, entity_id, chunk_uid, file_uid="f-1"):
    svc = GraphOutboxService(db)
    return svc.append(
        tenant_id=SCOPE["tenant_id"],
        kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"],
        aggregate_type="mention",
        aggregate_id=mention_id,
        event_type="mention.upserted",
        payload={
            "mention_id": mention_id,
            "entity_id": entity_id,
            "file_uid": file_uid,
            "chunk_uid": chunk_uid,
            "surface_text": "Prism",
            "normalized_key": "prism",
            "evidence_span": "Prism is a tool",
            "confidence": 0.9,
            "extraction_method": "llm_stage_a:INFERRED",
        },
    )


def _entity_count(graph):
    rows = graph._execute_read(
        "MATCH (e:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g}) "
        "RETURN count(e) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    return rows[0]["c"]


def _mention_edge_count(graph):
    rows = graph._execute_read(
        "MATCH (:ScopedEntity {tenant_id: $t, kb_uid: $k, graph_generation: $g})"
        "-[r:MENTIONED_IN]->(:ScopedSource {tenant_id: $t, kb_uid: $k, graph_generation: $g}) "
        "RETURN count(r) AS c",
        {"t": SCOPE["tenant_id"], "k": SCOPE["kb_uid"], "g": SCOPE["graph_generation"]},
    )
    return rows[0]["c"]


def _apply_claimed(projector, store):
    claimed = store.claim_due(
        projector=projector.name, worker_id="w-integration-test", limit=20,
    )
    for event, receipt in claimed:
        projector.apply(event, receipt)
    return len(claimed)


# -- test 1: full stack, uses claim_due + apply, works end-to-end -----------


def test_projector_converges_entity_and_mention_to_scoped_nodes_and_edges(
    mysql_session, graph,
):
    """Entity + mention events → 1 ScopedEntity, 1 ScopedSource, 1 MENTIONED_IN edge."""
    entity_id = f"e-{uuid4().hex[:8]}"
    mention_id = f"m-{uuid4().hex[:8]}"
    chunk_uid = f"c-{uuid4().hex[:8]}"

    _append_entity_event(mysql_session, entity_id)
    _append_mention_event(mysql_session, mention_id, entity_id, chunk_uid)
    mysql_session.commit()

    store = GraphProjectionReceiptStore(mysql_session)
    projector = Neo4jOutboxProjector(graph, store)
    events = list(
        mysql_session.query(GraphOutboxEvent)
        .order_by(GraphOutboxEvent.sequence)
        .all()
    )
    assert len(events) == 2

    # Apply each event — receipt moves to "applied".
    for event in events:
        projector.apply(event)
    assert store.status(events[0].event_id, "neo4j") == "applied"
    assert store.status(events[1].event_id, "neo4j") == "applied"

    assert _entity_count(graph) == 1
    assert _mention_edge_count(graph) == 1


# -- test 2: idempotency — replay same event → still 1 edge ------------------


def test_duplicate_delivery_leaves_single_edge(mysql_session, graph):
    """Replaying the same events via apply twice still yields 1 edge (idempotent MERGE)."""
    entity_id = f"e-{uuid4().hex[:8]}"
    mention_id = f"m-{uuid4().hex[:8]}"
    chunk_uid = f"c-{uuid4().hex[:8]}"

    _append_entity_event(mysql_session, entity_id)
    _append_mention_event(mysql_session, mention_id, entity_id, chunk_uid)
    mysql_session.commit()

    store = GraphProjectionReceiptStore(mysql_session)
    projector = Neo4jOutboxProjector(graph, store)
    events = list(
        mysql_session.query(GraphOutboxEvent)
        .order_by(GraphOutboxEvent.sequence)
        .all()
    )
    assert len(events) == 2

    # First pass: apply each event.
    for event in events:
        projector.apply(event)
    assert store.status(events[0].event_id, "neo4j") == "applied"
    assert store.status(events[1].event_id, "neo4j") == "applied"
    assert _entity_count(graph) == 1
    assert _mention_edge_count(graph) == 1

    # Second pass: same events → still 1 node, 1 edge (idempotent).
    for event in events:
        projector.apply(event)
    assert _entity_count(graph) == 1
    assert _mention_edge_count(graph) == 1


# -- test 3: transient failure → retry → convergence ------------------------


def test_transient_failure_then_retry_converges(mysql_session, graph, monkeypatch):
    """A transient Neo4j failure schedules a retry; re-applying after recovery converges."""
    entity_id = f"e-{uuid4().hex[:8]}"
    mention_id = f"m-{uuid4().hex[:8]}"
    chunk_uid = f"c-{uuid4().hex[:8]}"

    _append_entity_event(mysql_session, entity_id)
    _append_mention_event(mysql_session, mention_id, entity_id, chunk_uid)
    mysql_session.commit()

    store = GraphProjectionReceiptStore(mysql_session)
    events = list(
        mysql_session.query(GraphOutboxEvent)
        .order_by(GraphOutboxEvent.sequence)
        .all()
    )
    assert len(events) == 2  # entity first, then mention

    # First attempt: let entity upsert succeed but mention upsert fail transiently.
    original = graph.relate_scoped
    fail_on = {mention_id}

    def flaky(start_label, start_id, rel_type, end_label, end_id, props, *, scope=None):
        if props.get("mention_id") in fail_on:
            raise ConnectionError("neo4d transient connection reset")
        return original(start_label, start_id, rel_type, end_label, end_id, props, scope=scope)

    monkeypatch.setattr(graph, "relate_scoped", flaky)

    projector = Neo4jOutboxProjector(graph, store)

    # Entity event succeeds; mention event fails → receipt = retry.
    projector.apply(events[0])  # entity — should succeed
    projector.apply(events[1])  # mention — should fail

    assert store.status(events[0].event_id, "neo4j") == "applied"
    assert store.status(events[1].event_id, "neo4j") == "retry"

    assert _entity_count(graph) == 1
    # No MENTIONED_IN edge yet because mention apply failed.
    assert _mention_edge_count(graph) == 0

    # Force the retry receipt to be claimable now (bypass backoff delay).
    mention_receipt = store.get(events[1].event_id, "neo4j")
    mention_receipt.next_attempt_at = local_now() - timedelta(seconds=1)
    mysql_session.commit()

    # Second pass: monkeypatch restored → mention succeeds.
    monkeypatch.undo()
    projector.apply(events[1])
    assert store.status(events[1].event_id, "neo4j") == "applied"

    assert _entity_count(graph) == 1
    assert _mention_edge_count(graph) == 1
