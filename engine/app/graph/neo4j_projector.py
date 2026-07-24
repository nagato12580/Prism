# prism/engine/app/graph/neo4j_projector.py
"""Idempotent Neo4j projection of scoped graph outbox events.

Each ``GraphOutboxEvent`` is translated into scoped, ``MERGE``-based Cypher so
repeated delivery converges to one node/edge. Every node key and every
traversal clause repeats ``(tenant_id, kb_uid, graph_generation)`` so two KBs
sharing an entity id never cross. Fact ids (``mention_id``/``relation_id``)
are stored as relationship properties to make ``MERGE`` idempotent per fact.
"""
from __future__ import annotations

import logging
from typing import Any

from .outbox_projector import GraphProjectionReceiptStore, ProjectionFailure, classify_neo4j_error

logger = logging.getLogger("uvicorn.error")


class Neo4jOutboxProjector:
    """Applies graph outbox events to Neo4j idempotently."""

    name = "neo4j"

    def __init__(self, graph, receipts: GraphProjectionReceiptStore) -> None:
        self.graph = graph
        self.receipts = receipts

    def apply(self, event, receipt=None) -> None:
        handler = self._dispatch.get(event.event_type)
        if handler is None:
            self.receipts.fail(
                event.event_id, self.name, "GRAPH_EVENT_UNSUPPORTED", retryable=False,
            )
            return
        try:
            handler(self, event)
        except Exception as exc:
            failure = self._classify(exc)
            self.receipts.record_failure(event.event_id, self.name, failure)
            return
        self.receipts.mark_applied(event.event_id, self.name, int(event.sequence))

    # -- handlers -------------------------------------------------------- #

    def _upsert_entity(self, event) -> None:
        p = event.payload or {}
        scope = self._scope(event)
        self.graph.upsert_scoped_entity({
            "id": p.get("entity_id"),
            "user_id": p.get("user_id", "default-user"),
            "tenant_id": scope["tenant_id"],
            "kb_uid": scope["kb_uid"],
            "graph_generation": scope["graph_generation"],
            "entity_type": p.get("entity_type", ""),
            "canonical_name": p.get("canonical_name", ""),
            "normalized_key": p.get("normalized_key", ""),
            "status": p.get("status", "active"),
            "confidence": float(p.get("confidence") or 0.0),
        })

    def _upsert_mention(self, event) -> None:
        p = event.payload or {}
        scope = self._scope(event)
        entity_id = p.get("entity_id")
        source_kind = "document_chunk"
        source_id = p.get("chunk_uid") or p.get("source_id") or p.get("mention_id")
        source_node_id = f"{source_kind}:{source_id}"
        self.graph.upsert_scoped_source({
            "id": source_node_id,
            "tenant_id": scope["tenant_id"],
            "kb_uid": scope["kb_uid"],
            "graph_generation": scope["graph_generation"],
            "file_uid": p.get("file_uid", ""),
            "chunk_uid": p.get("chunk_uid", ""),
            "source_type": p.get("source_type", ""),
            "source_kind": source_kind,
            "source_id": source_id,
            "item_id": p.get("item_id", ""),
            "title": p.get("title", ""),
        })
        self.graph.relate_scoped(
            "ScopedEntity", entity_id, "MENTIONED_IN", "ScopedSource", source_node_id,
            {
                "mention_id": p.get("mention_id"),
                "chunk_uid": p.get("chunk_uid", ""),
                "confidence": float(p.get("confidence") or 0.0),
                "evidence_span": (p.get("evidence_span") or "")[:500],
                "extraction_method": p.get("extraction_method", ""),
                "source_kind": source_kind,
                "source_id": source_id,
            },
            scope=scope,
        )

    def _upsert_relation(self, event) -> None:
        p = event.payload or {}
        scope = self._scope(event)
        self.graph.relate_scoped(
            "ScopedEntity", p.get("subject_entity_id"), "RELATED_TO",
            "ScopedEntity", p.get("object_entity_id"),
            {
                "relation_id": p.get("relation_id"),
                "predicate": p.get("predicate", ""),
                "chunk_uid": p.get("chunk_uid", ""),
                "confidence": float(p.get("confidence") or 0.0),
                "evidence_span": (p.get("evidence_span") or "")[:500],
                "extraction_method": p.get("extraction_method", ""),
            },
            scope=scope,
        )

    def _remove_mention(self, event) -> None:
        scope = self._scope(event)
        self.graph.remove_scoped_mention(
            scope["tenant_id"], scope["kb_uid"], scope["graph_generation"],
            (event.payload or {}).get("mention_id"),
        )

    def _remove_relation(self, event) -> None:
        scope = self._scope(event)
        self.graph.remove_scoped_relation(
            scope["tenant_id"], scope["kb_uid"], scope["graph_generation"],
            (event.payload or {}).get("relation_id"),
        )

    def _remove_entity(self, event) -> None:
        scope = self._scope(event)
        self.graph.remove_scoped_entity(
            scope["tenant_id"], scope["kb_uid"], scope["graph_generation"],
            (event.payload or {}).get("entity_id"),
        )

    def _update_analysis(self, event) -> None:
        # Community/god/cohesion updates are written by run_analysis today;
        # the analysis.updated event is reserved for the generation plan (Task 5)
        # to switch analysis writes off direct Neo4j mutation. Acknowledge it
        # so receipts advance without double-writing.
        return

    # -- helpers --------------------------------------------------------- #

    _dispatch = {
        "entity.upserted": _upsert_entity,
        "mention.upserted": _upsert_mention,
        "relation.upserted": _upsert_relation,
        "mention.removed": _remove_mention,
        "relation.removed": _remove_relation,
        "entity.removed": _remove_entity,
        "analysis.updated": _update_analysis,
    }

    @staticmethod
    def _scope(event) -> dict[str, str]:
        return {
            "tenant_id": event.tenant_id,
            "kb_uid": event.kb_uid,
            "graph_generation": event.graph_generation,
        }

    @staticmethod
    def _classify(exc: Exception) -> ProjectionFailure:
        return classify_neo4j_error(exc)
