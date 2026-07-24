# prism/backend/app/services/graph_outbox.py
"""Transactional Outbox for scoped graph facts.

Appends immutable ``GraphOutboxEvent`` rows together with the fact changes in
the *same* MySQL transaction, and creates per-projector receipts so the Engine
projectors (``neo4j``, ``milvus_graph``) can claim and replay them
independently. Payloads carry only public IDs, normalized names, evidence
positions, confidence, and version fields — never document text beyond the
bounded evidence span, credentials, provider responses, or ``storage_uri``.
"""
from __future__ import annotations

from typing import Any

from backend.app.models.graph_outbox import GraphOutboxEvent, GraphProjectionReceipt


REQUIRED_PROJECTORS = ("neo4j", "milvus_graph")


class GraphOutboxService:
    def __init__(self, db) -> None:
        self.db = db

    def append(
        self,
        *,
        tenant_id: str,
        kb_uid: str,
        graph_generation: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> GraphOutboxEvent:
        """Append one event + one pending receipt per required projector.

        ``payload`` must already be a sanitized public dict; this service only
        adds scope + identity. Flushes so the event_id is available to callers
        within the same transaction but never commits.
        """
        event = GraphOutboxEvent(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            graph_generation=graph_generation,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self.db.add(event)
        self.db.flush()
        for projector in REQUIRED_PROJECTORS:
            self.db.add(GraphProjectionReceipt(event_id=event.event_id, projector=projector))
        return event

    def append_fact_change(
        self,
        *,
        tenant_id: str,
        kb_uid: str,
        graph_generation: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> GraphOutboxEvent:
        """Convenience wrapper naming the fact-change event families."""
        return self.append(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            graph_generation=graph_generation,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
