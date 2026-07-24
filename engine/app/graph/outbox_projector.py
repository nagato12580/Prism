# prism/engine/app/graph/outbox_projector.py
"""Common outbox projector loop, receipt store, and retry classification.

The ``GraphProjectionReceipt`` table is itself the work queue: receipts in
``pending``/``retry`` with ``next_attempt_at <= now`` are claimed by a
projector worker (``FOR UPDATE SKIP LOCKED`` on MySQL, no-op lock on SQLite),
applied, and marked ``applied`` or rescheduled for retry. An out-of-order
success cannot jump over a failed event: ``GraphProjectionCursor`` only
advances across a contiguous run of applied receipts.

This module owns the durable retry/cursor state; the concrete Neo4j/Milvus
projectors (``neo4j_projector.py``, ``milvus_projector.py``) plug in the
idempotent target writes.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_

from backend.app.models.graph_outbox import (
    GraphOutboxEvent,
    GraphProjectionCursor,
    GraphProjectionReceipt,
)
from backend.app.utils.time import local_now

logger = logging.getLogger("uvicorn.error")

LEASE_SECONDS = 60
PENDING_OR_RETRY = ("pending", "retry")


@dataclass(frozen=True)
class ProjectionFailure:
    """Outcome of a failed projection attempt."""

    code: str
    retryable: bool


def retry_delay(attempt: int, jitter: float | None = None) -> timedelta:
    """Exponential backoff capped at 300s, plus optional deterministic jitter.

    ``jitter`` is accepted so tests can assert exact delays; production callers
    leave it ``None`` to get a small random spread.
    """
    seconds = min(2 ** max(attempt - 1, 0), 300)
    spread = random.random() if jitter is None else jitter
    return timedelta(seconds=seconds + spread)


def classify_neo4j_error(exc: Exception) -> ProjectionFailure:
    """Classify a Neo4j failure as retryable or terminal.

    Connection resets, service unavailability, timeouts, and 429-style rate
    limits are transient -> retry. Malformed payloads, unknown event types,
    and missing scope are programmer errors -> terminal ``failed``.
    """
    # neo4j driver raises ServiceUnavailable / ClientError; connection-level
    # errors surface as built-in ConnectionError/OSError. Treat all of these
    # as transient. Everything else (ValueError, KeyError on payload, schema
    # mismatch) is terminal.
    name = type(exc).__name__
    transient = (
        isinstance(exc, (ConnectionError, OSError, TimeoutError))
        or name in {"ServiceUnavailable", "ClientError", "CypherSyntaxError"}
        or "unavailable" in str(exc).lower()
        or "timeout" in str(exc).lower()
    )
    if transient:
        return ProjectionFailure(code="NEO4J_UNAVAILABLE", retryable=True)
    return ProjectionFailure(code="NEO4J_PROJECTION_ERROR", retryable=False)


class GraphProjectionReceiptStore:
    """Durable per-event, per-projector retry/cursor state.

    All mutations commit immediately so lease ownership and cursor advances
    survive across worker sessions. ``with_for_update()`` provides row-level
    locking on MySQL (``SKIP LOCKED`` semantics via the claim query) and is a
    no-op on SQLite for tests.
    """

    def __init__(self, db) -> None:
        self.db = db

    # -- claim ----------------------------------------------------------- #

    def claim_due(
        self,
        *,
        projector: str,
        worker_id: str,
        limit: int = 100,
        lease_seconds: int = LEASE_SECONDS,
    ) -> list[tuple[GraphOutboxEvent, GraphProjectionReceipt]]:
        """Claim up to ``limit`` due receipts for ``projector``.

        Returns ``(event, receipt)`` pairs with the receipt already moved to
        ``processing`` and leased to ``worker_id``. Uses
        ``FOR UPDATE SKIP LOCKED`` on MySQL so concurrent workers split the
        backlog; SQLite (tests) falls back to a plain lock-free update.
        """
        now = local_now()
        # Join receipts to their events in one query so the projector gets
        # both without a second round-trip per receipt.
        rows = (
            self.db.query(GraphProjectionReceipt, GraphOutboxEvent)
            .join(GraphOutboxEvent, GraphProjectionReceipt.event_id == GraphOutboxEvent.event_id)
            .filter(
                GraphProjectionReceipt.projector == projector,
                GraphProjectionReceipt.status.in_(PENDING_OR_RETRY),
                or_(
                    GraphProjectionReceipt.next_attempt_at.is_(None),
                    GraphProjectionReceipt.next_attempt_at <= now,
                ),
            )
            .order_by(GraphOutboxEvent.sequence.asc())
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        claimed: list[tuple[GraphOutboxEvent, GraphProjectionReceipt]] = []
        for receipt, event in rows:
            receipt.status = "processing"
            receipt.lease_owner = worker_id
            receipt.lease_expires_at = now + timedelta(seconds=lease_seconds)
            receipt.last_error_code = ""
            receipt.last_error_message = None
            claimed.append((event, receipt))
        if claimed:
            self.db.commit()
        return claimed

    # -- terminal transitions ------------------------------------------- #

    def mark_applied(self, event_id: str, projector: str, sequence: int) -> None:
        """Mark one receipt applied and advance the scope cursor contiguously.

        ``applied_sequence`` records the event sequence so the cursor only
        advances through a gap-free run; an out-of-order success cannot jump
        over a still-pending earlier event.
        """
        now = local_now()
        receipt = self._lock_receipt(event_id, projector)
        if receipt is None:
            return
        receipt.status = "applied"
        receipt.applied_at = now
        receipt.applied_sequence = sequence
        receipt.lease_owner = ""
        receipt.lease_expires_at = None
        self._advance_cursor(receipt, sequence)
        self.db.commit()

    def record_failure(
        self, event_id: str, projector: str, failure: ProjectionFailure
    ) -> None:
        """Reschedule a retryable failure or mark a terminal one ``failed``."""
        now = local_now()
        receipt = self._lock_receipt(event_id, projector)
        if receipt is None:
            return
        receipt.last_error_code = failure.code
        receipt.last_error_message = failure.code
        receipt.lease_owner = ""
        receipt.lease_expires_at = None
        if failure.retryable and receipt.attempt < receipt.max_attempts:
            receipt.status = "retry"
            receipt.attempt += 1
            receipt.next_attempt_at = now + retry_delay(receipt.attempt)
        else:
            receipt.status = "failed"
        self.db.commit()

    def fail(
        self, event_id: str, projector: str, code: str, *, retryable: bool = False
    ) -> None:
        """Explicit terminal/retryable failure (e.g. unsupported event type)."""
        self.record_failure(event_id, projector, ProjectionFailure(code=code, retryable=retryable))

    # -- read helpers ---------------------------------------------------- #

    def get(self, event_id: str, projector: str) -> GraphProjectionReceipt | None:
        return (
            self.db.query(GraphProjectionReceipt)
            .filter_by(event_id=event_id, projector=projector)
            .one_or_none()
        )

    def status(self, event_id: str, projector: str) -> str | None:
        receipt = self.get(event_id, projector)
        return receipt.status if receipt is not None else None

    def is_applied_through(
        self, tenant_id: str, kb_uid: str, generation: str, projector: str, barrier: int
    ) -> bool:
        """True iff ``projector`` has applied every event up to ``barrier``."""
        cursor = self._cursor(tenant_id, kb_uid, generation, projector)
        return cursor.applied_through_sequence >= int(barrier)

    # -- internals ------------------------------------------------------- #

    def _lock_receipt(self, event_id: str, projector: str) -> GraphProjectionReceipt | None:
        return (
            self.db.query(GraphProjectionReceipt)
            .filter_by(event_id=event_id, projector=projector)
            .with_for_update()
            .one_or_none()
        )

    def _cursor(
        self, tenant_id: str, kb_uid: str, generation: str, projector: str
    ) -> GraphProjectionCursor:
        cursor = (
            self.db.query(GraphProjectionCursor)
            .filter_by(
                tenant_id=tenant_id,
                kb_uid=kb_uid,
                graph_generation=generation,
                projector=projector,
            )
            .one_or_none()
        )
        if cursor is None:
            cursor = GraphProjectionCursor(
                tenant_id=tenant_id,
                kb_uid=kb_uid,
                graph_generation=generation,
                projector=projector,
                applied_through_sequence=0,
            )
            self.db.add(cursor)
            self.db.flush()
        return cursor

    def _advance_cursor(self, receipt: GraphProjectionReceipt, sequence: int) -> None:
        event = (
            self.db.query(GraphOutboxEvent)
            .filter_by(event_id=receipt.event_id)
            .one_or_none()
        )
        if event is None:
            return
        cursor = self._cursor(event.tenant_id, event.kb_uid, event.graph_generation, receipt.projector)
        # Only advance when this sequence is exactly the next contiguous one.
        # An out-of-order applied receipt (earlier event still pending) cannot
        # move the cursor past the gap.
        if int(sequence) == int(cursor.applied_through_sequence) + 1:
            cursor.applied_through_sequence = int(sequence)
            # Greedily extend over any already-applied later events.
            self._extend_cursor(cursor, event.tenant_id, event.kb_uid, event.graph_generation, receipt.projector)

    def _extend_cursor(
        self, cursor: GraphProjectionCursor, tenant_id: str, kb_uid: str, generation: str, projector: str
    ) -> None:
        next_seq = int(cursor.applied_through_sequence) + 1
        while True:
            applied = (
                self.db.query(GraphProjectionReceipt)
                .join(GraphOutboxEvent, GraphProjectionReceipt.event_id == GraphOutboxEvent.event_id)
                .filter(
                    GraphProjectionReceipt.projector == projector,
                    GraphProjectionReceipt.status == "applied",
                    GraphOutboxEvent.tenant_id == tenant_id,
                    GraphOutboxEvent.kb_uid == kb_uid,
                    GraphOutboxEvent.graph_generation == generation,
                    GraphOutboxEvent.sequence == next_seq,
                )
                .first()
            )
            if applied is None:
                break
            cursor.applied_through_sequence = next_seq
            next_seq += 1


class OutboxProjectorLoop:
    """Claims due receipts for one projector and applies them in sequence order."""

    def __init__(self, projector, receipts: GraphProjectionReceiptStore, worker_id: str) -> None:
        self.projector = projector
        self.receipts = receipts
        self.worker_id = worker_id

    def run_batch(self, limit: int = 100) -> int:
        """Claim and apply up to ``limit`` due events; returns the count claimed."""
        claimed = self.receipts.claim_due(
            projector=self.projector.name, worker_id=self.worker_id, limit=limit,
        )
        for event, receipt in claimed:
            self.projector.apply(event, receipt)
        return len(claimed)
