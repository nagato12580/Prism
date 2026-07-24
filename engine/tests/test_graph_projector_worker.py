"""Task 3 (Graph): worker manager spawns a neo4j projector thread that drains
due receipts and stops cleanly."""
import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_projector_worker_test.db"

import threading
from datetime import timedelta

import engine.app.jobs.worker as worker_mod
from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt
from backend.app.services.graph_outbox import GraphOutboxService
from engine.app.graph.outbox_projector import GraphProjectionReceiptStore


class _RecordingProjector:
    """Stand-in for Neo4jOutboxProjector that records apply calls."""
    name = "neo4j"

    def __init__(self, receipts):
        self.receipts = receipts
        self.applied = []

    def apply(self, event, receipt=None):
        self.applied.append(event.event_id)
        self.receipts.mark_applied(event.event_id, self.name, int(event.sequence))


def test_build_graph_projector_returns_none_when_disabled(db_session, monkeypatch):
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", False)
    assert worker_mod._build_graph_projector(db_session) is None


def test_build_graph_projector_wires_neo4j_projector(db_session, monkeypatch):
    """With GRAPH_PROJECTOR_ENABLED and a reachable GraphClient the factory
    returns a Neo4jOutboxProjector."""
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    # Stub GraphClient so we don't need a real Neo4j in unit tests.
    import backend.app.services.graph_client as gc_mod

    class _StubGraph:
        def __init__(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(gc_mod, "GraphClient", lambda: _StubGraph())
    projector = worker_mod._build_graph_projector(db_session)
    assert projector is not None
    assert projector.name == "neo4j"


def test_drain_graph_projector_batch_applies_due_events(db_session, monkeypatch):
    """_drain_graph_projector_batch claims + applies due receipts in one pass."""
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_BATCH_LIMIT", 100)
    scope = {"tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"}
    svc = GraphOutboxService(db_session)
    svc.append(
        tenant_id=scope["tenant_id"],
        kb_uid=scope["kb_uid"],
        graph_generation=scope["graph_generation"],
        aggregate_type="entity",
        aggregate_id="entity-1",
        event_type="entity.upserted",
        payload={
            "entity_id": "entity-1",
            "entity_type": "concept",
            "canonical_name": "Prism",
            "normalized_key": "prism",
            "aliases": [],
            "confidence": 0.9,
        },
    )
    db_session.commit()

    store = GraphProjectionReceiptStore(db_session)
    recorder = _RecordingProjector(store)
    n = worker_mod._drain_graph_projector_batch(
        db_session, projector=recorder, worker_id="w-test"
    )
    assert n == 1
    assert len(recorder.applied) == 1
    # receipt is now applied
    event = db_session.query(GraphOutboxEvent).one()
    receipt = (
        db_session.query(GraphProjectionReceipt)
        .filter_by(event_id=event.event_id, projector="neo4j")
        .one()
    )
    assert receipt.status == "applied"


def test_drain_graph_projector_batch_returns_zero_when_no_receipts(
    db_session, monkeypatch,
):
    monkeypatch.setattr(worker_mod.settings, "GRAPH_PROJECTOR_ENABLED", True)
    store = GraphProjectionReceiptStore(db_session)
    recorder = _RecordingProjector(store)
    assert (
        worker_mod._drain_graph_projector_batch(
            db_session, projector=recorder, worker_id="w-test"
        )
        == 0
    )
    assert recorder.applied == []
