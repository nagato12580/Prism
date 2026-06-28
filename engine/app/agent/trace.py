from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
from backend.app.utils.time import local_now
from engine.app.config import settings
from engine.app.observability import logger, quoted


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


class AgentTraceRecorder:
    def __init__(
        self,
        *,
        session_id: str | None,
        user_message_id: str | None,
        user_query: str,
        model: str,
        session_factory: Callable[[], Any] = _Session,
    ) -> None:
        self.session_id = session_id
        self.user_message_id = user_message_id
        self.user_query = user_query
        self.model = model
        self._session_factory = session_factory
        self._trace_id: str | None = None
        self._next_step_index = 0
        self._enabled = True

    def start(self) -> str | None:
        if not self._enabled:
            return None

        db = None
        try:
            db = self._session_factory()
            trace = AgentTrace(
                session_id=self.session_id,
                user_message_id=self.user_message_id,
                user_query=self.user_query,
                status="running",
                model=self.model,
            )
            db.add(trace)
            db.commit()
            db.refresh(trace)
            self._trace_id = trace.id
            return trace.id
        except Exception as exc:
            self._disable("start", exc, db)
            return None
        finally:
            if db is not None:
                db.close()

    def record_step(
        self,
        *,
        step_type: str,
        input_json: dict[str, Any] | None = None,
        output_json: dict[str, Any] | None = None,
        status: str = "success",
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        latency_ms: int | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> str | None:
        if not self._enabled or not self._trace_id:
            return None

        db = None
        try:
            db = self._session_factory()
            step = AgentTraceStep(
                trace_id=self._trace_id,
                step_index=self._next_step_index,
                step_type=step_type,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                input_json=input_json,
                output_json=output_json,
                status=status,
                latency_ms=latency_ms,
                ended_at=local_now(),
            )
            db.add(step)
            db.flush()

            for item in evidence_items or []:
                db.add(_evidence_from_item(step.id, item))

            db.commit()
            db.refresh(step)
            self._next_step_index += 1
            return step.id
        except Exception as exc:
            self._disable("record_step", exc, db)
            return None
        finally:
            if db is not None:
                db.close()

    def finish(self, status: str) -> None:
        if not self._enabled or not self._trace_id:
            return

        db = None
        try:
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
                db.close()

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


def _evidence_from_item(step_id: str, item: dict[str, Any]) -> AgentTraceEvidence:
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
        score=item.get("score"),
        retrieval_path_json=item.get("retrieval_path") or [],
        metadata_json=item.get("metadata") or {},
    )
