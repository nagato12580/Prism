"""Task 3 (Graph): Neo4j outbox projector is idempotent and retries transient
failures terminally vs. with backoff.

Uses an in-memory SQLite session with the real ``GraphOutboxService`` +
``GraphProjectionReceiptStore`` and a ``FakeGraph`` that records scoped
writes so we can assert convergence without a real Neo4j.
"""
import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_neo4j_projector_test.db"

from datetime import timedelta

import pytest

from backend.app.models import GraphOutboxEvent, GraphProjectionReceipt
from backend.app.services.graph_outbox import GraphOutboxService
from engine.app.graph.neo4j_projector import Neo4jOutboxProjector
from engine.app.graph.outbox_projector import (
    GraphProjectionReceiptStore,
    OutboxProjectorLoop,
    classify_neo4j_error,
    retry_delay,
)


SCOPE = {"tenant_id": "t1", "kb_uid": "k1", "graph_generation": "g1"}


class FakeGraph:
    """Records scoped entity/source/relationship writes for assertion.

    Mirrors Neo4j ``MERGE`` semantics: upserts are keyed by (id, scope) and
    relationships by (start_id, rel_type, end_id, scope, fact-id prop) so
    repeated delivery of the same event converges to one node/edge, exactly
    as the real projector must.
    """

    def __init__(self):
        self.entities = {}
        self.sources = {}
        self.relationships = {}  # dedupe_key -> dict
        self._fail_with = None

    def fail_next(self, exc):
        self._fail_with = exc

    def _maybe_fail(self):
        if self._fail_with is not None:
            exc = self._fail_with
            self._fail_with = None
            raise exc

    def upsert_scoped_entity(self, data):
        self._maybe_fail()
        self.entities[self._entity_key(data)] = dict(data)

    def upsert_scoped_source(self, data):
        self._maybe_fail()
        self.sources[self._source_key(data)] = dict(data)

    def relate_scoped(self, start_label, start_id, rel_type, end_label, end_id, props=None, *, scope):
        self._maybe_fail()
        props = dict(props or {})
        key = self._rel_key(rel_type, start_id, end_id, scope, props)
        self.relationships[key] = {
            "start_label": start_label,
            "start_id": start_id,
            "rel_type": rel_type,
            "end_label": end_label,
            "end_id": end_id,
            "props": props,
            "scope": dict(scope),
        }

    def remove_scoped_mention(self, tenant_id, kb_uid, generation, mention_id):
        self._maybe_fail()
        for key in list(self.relationships):
            r = self.relationships[key]
            if r["rel_type"] != "MENTIONED_IN":
                continue
            if r["scope"].get("graph_generation") != generation:
                continue
            if r["props"].get("mention_id") == mention_id:
                del self.relationships[key]

    def remove_scoped_relation(self, tenant_id, kb_uid, generation, relation_id):
        self._maybe_fail()
        for key in list(self.relationships):
            r = self.relationships[key]
            if r["rel_type"] != "RELATED_TO":
                continue
            if r["scope"].get("graph_generation") != generation:
                continue
            if r["props"].get("relation_id") == relation_id:
                del self.relationships[key]

    def remove_scoped_entity(self, tenant_id, kb_uid, generation, entity_id):
        self._maybe_fail()
        for key in list(self.entities):
            if self.entities[key].get("id") == entity_id:
                del self.entities[key]
        for key in list(self.relationships):
            r = self.relationships[key]
            if r["start_id"] == entity_id or r["end_id"] == entity_id:
                del self.relationships[key]

    def count_relationships(self, rel_type, **match):
        count = 0
        for r in self.relationships.values():
            if r["rel_type"] != rel_type:
                continue
            if all(r["props"].get(k) == v for k, v in match.items()):
                count += 1
        return count

    @staticmethod
    def _entity_key(data):
        return (data["id"], data.get("tenant_id"), data.get("kb_uid"), data.get("graph_generation"))

    @staticmethod
    def _source_key(data):
        return (data["id"], data.get("tenant_id"), data.get("kb_uid"), data.get("graph_generation"))

    @staticmethod
    def _rel_key(rel_type, start_id, end_id, scope, props):
        # Fact-id (mention_id / relation_id) is the deterministic edge identity;
        # falls back to (start, end) when absent so non-fact edges still dedupe.
        fact_id = props.get("mention_id") or props.get("relation_id")
        return (rel_type, start_id, end_id, scope.get("graph_generation"), fact_id)


def test_duplicate_event_converges_to_one_mention(db_session):
    projector = Neo4jOutboxProjector(FakeGraph(), GraphProjectionReceiptStore(db_session))
    svc = GraphOutboxService(db_session)
    payload = {
        "mention_id": "mention-1", "entity_id": "entity-1",
        "file_uid": "f1", "chunk_uid": "c1", "surface_text": "Prism",
        "normalized_key": "prism", "evidence_span": "Prism is a tool", "confidence": 0.9,
    }
    event = svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id="mention-1", event_type="mention.upserted", payload=payload,
    )
    db_session.commit()

    projector.apply(event)
    projector.apply(event)

    fake = projector.graph
    assert fake.count_relationships("MENTIONED_IN", mention_id="mention-1") == 1
    store = projector.receipts
    assert store.status(event.event_id, "neo4j") == "applied"


def test_transient_neo4j_failure_is_scheduled_for_retry(db_session):
    fake = FakeGraph()
    fake.fail_next(ConnectionError("neo4j unavailable"))
    store = GraphProjectionReceiptStore(db_session)
    projector = Neo4jOutboxProjector(fake, store)

    svc = GraphOutboxService(db_session)
    event = svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id="mention-1", event_type="mention.upserted",
        payload={"mention_id": "mention-1", "entity_id": "entity-1", "file_uid": "f1",
                 "chunk_uid": "c1", "surface_text": "Prism", "normalized_key": "prism",
                 "evidence_span": "", "confidence": 0.9},
    )
    db_session.commit()

    projector.apply(event)
    receipt = store.get(event.event_id, "neo4j")
    assert receipt.status == "retry"
    assert receipt.attempt == 1
    assert receipt.next_attempt_at is not None
    assert receipt.last_error_code == "NEO4J_UNAVAILABLE"


def test_unknown_event_type_is_terminal_failure(db_session):
    fake = FakeGraph()
    store = GraphProjectionReceiptStore(db_session)
    projector = Neo4jOutboxProjector(fake, store)

    svc = GraphOutboxService(db_session)
    event = svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id="mention-1", event_type="mention.frobnicated",
        payload={"mention_id": "mention-1"},
    )
    db_session.commit()

    projector.apply(event)
    receipt = store.get(event.event_id, "neo4j")
    assert receipt.status == "failed"
    assert receipt.last_error_code == "GRAPH_EVENT_UNSUPPORTED"


def test_claim_due_picks_pending_and_retry_receipts(db_session):
    store = GraphProjectionReceiptStore(db_session)
    svc = GraphOutboxService(db_session)
    e1 = svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id="m-1", event_type="mention.upserted", payload={"mention_id": "m-1"},
    )
    e2 = svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="mention",
        aggregate_id="m-2", event_type="mention.upserted", payload={"mention_id": "m-2"},
    )
    db_session.commit()

    # Mark e1's receipt as retry with a future next_attempt_at so it is skipped
    # on the first claim, then becomes due.
    r1 = store.get(e1.event_id, "neo4j")
    r1.status = "retry"
    r1.attempt = 1
    from backend.app.utils.time import local_now
    r1.next_attempt_at = local_now() - timedelta(seconds=1)
    db_session.commit()

    claimed = store.claim_due(projector="neo4j", worker_id="w-1", limit=10)
    claimed_ids = {evt.event_id for evt, _ in claimed}
    assert e2.event_id in claimed_ids
    assert e1.event_id in claimed_ids
    for _, receipt in claimed:
        assert receipt.status == "processing"
        assert receipt.lease_owner == "w-1"


def test_loop_run_batch_applies_claimed_events(db_session):
    fake = FakeGraph()
    store = GraphProjectionReceiptStore(db_session)
    projector = Neo4jOutboxProjector(fake, store)
    loop = OutboxProjectorLoop(projector, store, worker_id="w-loop")

    svc = GraphOutboxService(db_session)
    svc.append(
        tenant_id=SCOPE["tenant_id"], kb_uid=SCOPE["kb_uid"],
        graph_generation=SCOPE["graph_generation"], aggregate_type="entity",
        aggregate_id="entity-1", event_type="entity.upserted",
        payload={"entity_id": "entity-1", "entity_type": "concept",
                 "canonical_name": "Prism", "normalized_key": "prism",
                 "aliases": [], "confidence": 0.9},
    )
    db_session.commit()

    n = loop.run_batch(limit=10)
    assert n == 1
    assert any(data.get("id") == "entity-1" for data in fake.entities.values())


def test_retry_delay_grows_and_is_bounded():
    assert retry_delay(1, jitter=0.0) == timedelta(seconds=1)
    assert retry_delay(3, jitter=0.0) == timedelta(seconds=4)
    # bounded at 300s + jitter
    assert retry_delay(20, jitter=0.0) <= timedelta(seconds=300)


def test_classify_neo4j_error_distinguishes_retryable_and_terminal():
    assert classify_neo4j_error(ConnectionError("down")).retryable is True
    assert classify_neo4j_error(ValueError("bad payload")).retryable is False
