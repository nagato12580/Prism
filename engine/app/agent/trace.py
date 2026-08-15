from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
import hashlib
import math
import json
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.utils.time import local_now
from engine.app.config import settings
from engine.app.observability import logger, quoted


_Session: Callable[[], Any] | None = None
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "secret",
    "token",
)


def _default_session_factory() -> Any:
    global _Session
    if _Session is None:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
        _Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _Session()


class AgentTraceRecorder:
    def __init__(
        self,
        *,
        session_id: str | None,
        user_message_id: str | None,
        user_query: str,
        model: str,
        session_factory: Callable[[], Any] = _default_session_factory,
    ) -> None:
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.user_query = user_query
        self.model = model
        self._session_factory = session_factory
        self._trace_id: str | None = None
        self._next_step_index = 0
        self._enabled = True

    @property
    def trace_id(self) -> str | None:
        return self._trace_id

    @staticmethod
    def tool_dedupe_key(trace_id: str, tool_name: str, args: Any) -> str:
        payload = {
            "trace_id": trace_id,
            "tool_name": tool_name,
            "args": _dedupe_json_identity(args),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def start(self) -> str | None:
        if not self._enabled:
            return None

        db = None
        try:
            from backend.app.models import AgentTrace

            db = self._session_factory()
            trace = AgentTrace(
                session_id=self.session_id,
                user_message_id=self.user_message_id,
                user_query=self.user_query,
                status="running",
                model=self.model,
            )
            db.add(trace)
            db.flush()
            trace_id = trace.id
            db.commit()
            try:
                db.refresh(trace)
                trace_id = trace.id or trace_id
            except Exception as exc:
                logger.warning(
                    "[agent.trace] start refresh failed; continuing trace_id=%s error=%s",
                    quoted(str(trace_id), limit=80),
                    quoted(str(exc), limit=300),
                )
            self._trace_id = trace_id
            return trace_id
        except Exception as exc:
            self._disable("start", exc, db)
            return None
        finally:
            if db is not None:
                self._close_safely("start", db)

    def record_step(
        self,
        *,
        step_type: str,
        input_json: dict[str, Any] | None = None,
        output_json: dict[str, Any] | None = None,
        status: str = "success",
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        dedupe_key: str | None = None,
        latency_ms: int | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> str | None:
        if not self._enabled or not self._trace_id:
            return None

        db = None
        try:
            from backend.app.models import AgentTraceStep

            db = self._session_factory()
            step = AgentTraceStep(
                trace_id=self._trace_id,
                step_index=self._next_step_index,
                step_type=step_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                dedupe_key=dedupe_key,
                input_json=_json_safe(input_json),
                output_json=_json_safe(output_json),
                status=status,
                latency_ms=latency_ms,
                ended_at=local_now(),
            )
            db.add(step)
            db.flush()
            step_id = step.id

            for item in evidence_items or []:
                db.add(_evidence_from_item(step_id, item))

            db.commit()
            try:
                db.refresh(step)
            except Exception as exc:
                logger.warning(
                    "[agent.trace] record_step refresh failed; continuing step_id=%s error=%s",
                    quoted(str(step_id), limit=80),
                    quoted(str(exc), limit=300),
                )
            self._next_step_index += 1
            return step_id
        except Exception as exc:
            self._disable("record_step", exc, db)
            return None
        finally:
            if db is not None:
                self._close_safely("record_step", db)

    def save_checkpoint(self, checkpoint: dict[str, Any], *, resume_status: str = "checkpointed") -> bool:
        if not self._enabled or not self._trace_id:
            return False

        db = None
        try:
            from backend.app.models import AgentTrace

            db = self._session_factory()
            trace = db.query(AgentTrace).filter(AgentTrace.id == self._trace_id).first()
            if trace is None:
                raise LookupError("trace not found")
            trace.checkpoint_json = _json_safe(checkpoint)
            trace.resume_status = resume_status
            trace.last_event_seq = (trace.last_event_seq or 0) + 1
            db.commit()
            return True
        except Exception as exc:
            self._disable("save_checkpoint", exc, db)
            return False
        finally:
            if db is not None:
                self._close_safely("save_checkpoint", db)

    @classmethod
    def load_checkpoint(
        cls,
        trace_id: str,
        *,
        session_factory: Callable[[], Any] = _default_session_factory,
    ) -> dict[str, Any] | None:
        db = None
        try:
            from backend.app.models import AgentTrace

            db = session_factory()
            trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
            if trace is None or trace.status not in {"running", "error"}:
                return None
            checkpoint = trace.checkpoint_json
            return checkpoint if isinstance(checkpoint, dict) else None
        except Exception as exc:
            logger.warning(
                "[agent.trace] load_checkpoint failed error=%s",
                quoted(str(exc), limit=300),
            )
            return None
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as exc:
                    logger.warning(
                        "[agent.trace] load_checkpoint close failed error=%s",
                        quoted(str(exc), limit=300),
                    )

    @classmethod
    def for_existing_trace(
        cls,
        trace_id: str,
        *,
        session_factory: Callable[[], Any] = _default_session_factory,
    ) -> "AgentTraceRecorder | None":
        db = None
        try:
            from backend.app.models import AgentTrace, AgentTraceStep

            db = session_factory()
            trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).first()
            if trace is None:
                return None

            last_step = (
                db.query(AgentTraceStep)
                .filter(AgentTraceStep.trace_id == trace_id)
                .order_by(AgentTraceStep.step_index.desc())
                .first()
            )
            recorder = cls(
                session_id=trace.session_id,
                user_message_id=trace.user_message_id,
                user_query=str(trace.user_query or ""),
                model=str(trace.model or ""),
                session_factory=session_factory,
            )
            recorder._trace_id = trace_id
            recorder._enabled = True
            recorder._next_step_index = (
                int(last_step.step_index) + 1
                if last_step is not None and isinstance(last_step.step_index, int)
                else 0
            )
            return recorder
        except Exception as exc:
            logger.warning(
                "[agent.trace] attach existing trace failed trace_id=%s error=%s",
                quoted(trace_id, limit=80),
                quoted(str(exc), limit=300),
            )
            return None
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception as exc:
                    logger.warning(
                        "[agent.trace] attach existing trace close failed error=%s",
                        quoted(str(exc), limit=300),
                    )

    def find_successful_tool_result(self, *, tool_name: str, args: Any) -> dict[str, Any] | None:
        if not self._enabled or not self._trace_id:
            return None

        db = None
        try:
            from backend.app.models import AgentTraceStep

            dedupe_key = self.tool_dedupe_key(
                trace_id=self._trace_id,
                tool_name=tool_name,
                args=args,
            )
            db = self._session_factory()
            step = (
                db.query(AgentTraceStep)
                .filter(
                    AgentTraceStep.trace_id == self._trace_id,
                    AgentTraceStep.tool_name == tool_name,
                    AgentTraceStep.dedupe_key == dedupe_key,
                    AgentTraceStep.step_type == "tool_result",
                    AgentTraceStep.status == "success",
                )
                .order_by(AgentTraceStep.step_index.desc())
                .first()
            )
            if step is None:
                return None
            return {"dedupe_key": dedupe_key, "output_json": step.output_json}
        except Exception as exc:
            self._disable("find_successful_tool_result", exc, db)
            return None
        finally:
            if db is not None:
                self._close_safely("find_successful_tool_result", db)

    def record_evidence_snapshot(
        self,
        *,
        evidence_items: list[dict[str, Any]],
        invalid_citations: tuple[str, ...] | list[str] | None = None,
    ) -> str | None:
        """Persist the run-local Evidence snapshot before answer completion.

        Stores the canonical Evidence DTO together with its assigned short id
        (``K1``, ...) as a dedicated ``evidence_snapshot`` step. The snapshot is
        taken from the in-memory :class:`CitationRegistry` at answer time and is
        never re-resolved against a later active generation. Unknown citations
        are recorded as trace warnings, not as source cards.
        """
        if not self._enabled or not self._trace_id:
            return None
        return self.record_step(
            step_type="evidence_snapshot",
            output_json={
                "evidence_count": len(evidence_items),
                "invalid_citations": list(invalid_citations or []),
            },
            evidence_items=evidence_items,
        )

    def finish(self, status: str) -> None:
        if not self._enabled or not self._trace_id:
            return

        db = None
        try:
            from backend.app.models import AgentTrace

            db = self._session_factory()
            trace = db.query(AgentTrace).filter(AgentTrace.id == self._trace_id).first()
            if trace is None:
                raise LookupError("trace not found")
            trace.status = status
            trace.ended_at = local_now()
            db.commit()
        except Exception as exc:
            self._disable("finish", exc, db)
        finally:
            if db is not None:
                self._close_safely("finish", db)

    def _disable(self, operation: str, exc: Exception, db: Any | None = None) -> None:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        self._enabled = False
        logger.warning(
            "[agent.trace] %s failed; trace recorder disabled error=%s",
            operation,
            quoted(str(exc), limit=300),
        )

    def _close_safely(self, operation: str, db: Any) -> None:
        try:
            db.close()
        except Exception as exc:
            self._enabled = False
            logger.warning(
                "[agent.trace] %s close failed; trace recorder disabled error=%s",
                operation,
                quoted(str(exc), limit=300),
            )


def _evidence_from_item(step_id: str, item: dict[str, Any]) -> Any:
    from backend.app.models import AgentTraceEvidence

    metadata = item.get("metadata")

    return AgentTraceEvidence(
        trace_step_id=step_id,
        evidence_id=str(item.get("evidence_id") or ""),
        source_kind=str(item.get("source_kind") or ""),
        source_id=str(item.get("source_id") or ""),
        chunk_id=str(item.get("chunk_id") or ""),
        parent_chunk_id=str(item.get("parent_chunk_id") or ""),
        item_id=str(item.get("item_id") or ""),
        display_title=str(item.get("display_title") or ""),
        excerpt=str(item.get("excerpt") or ""),
        hit_reason=str(item.get("hit_reason") or ""),
        score=_float_or_none(item.get("score")),
        retrieval_path_json=_json_safe(item.get("retrieval_path") or []),
        metadata_json=_json_safe(metadata if isinstance(metadata, Mapping) else {}),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        coerced = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return coerced if math.isfinite(coerced) else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        try:
            coerced = float(value)
        except (OverflowError, ValueError):
            return None
        return coerced if math.isfinite(coerced) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return _safe_repr(value)
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(_json_safe(key))
            safe[safe_key] = "[REDACTED]" if _is_sensitive_key(safe_key) else _json_safe(item)
        return safe
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return _safe_repr(value)


def _dedupe_json_identity(value: Any, *, sensitive: bool = False) -> Any:
    if sensitive and (
        value is None
        or isinstance(value, (bool, int, str, float, Decimal, datetime, date, UUID, bytes))
    ):
        return _sensitive_identity_for_value(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        try:
            coerced = float(value)
        except (OverflowError, ValueError):
            return None
        return coerced if math.isfinite(coerced) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError:
            decoded = _safe_repr(value)
        return decoded
    if isinstance(value, Mapping):
        identity: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(_dedupe_json_identity(key))
            child_sensitive = sensitive or _is_sensitive_key(safe_key)
            output_key = _sensitive_key_identity(key) if sensitive else safe_key
            identity[output_key] = _dedupe_json_identity(item, sensitive=child_sensitive)
        return identity
    if isinstance(value, (set, frozenset)):
        items = [_dedupe_json_identity(item, sensitive=sensitive) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if isinstance(value, (list, tuple)):
        return [_dedupe_json_identity(item, sensitive=sensitive) for item in value]
    if sensitive:
        return _sensitive_identity_for_value(value)
    return _safe_repr(value)


def _sensitive_identity_for_value(value: Any) -> dict[str, str]:
    identity = _dedupe_json_identity(value, sensitive=False)
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"__sensitive_sha256__": hashlib.sha256(serialized.encode("utf-8")).hexdigest()}


def _sensitive_key_identity(value: Any) -> str:
    return f"sensitive:{_sensitive_identity_for_value(value)['__sensitive_sha256__']}"


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<{type(value).__name__}>"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
