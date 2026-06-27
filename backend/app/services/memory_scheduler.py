from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.memory import MemoryExtractionRun
from backend.app.services.memory_extraction import extract_session_memories_scheduled
from backend.app.utils.time import local_now

log = logging.getLogger(__name__)


class MemoryScheduler:
    """Manages the APScheduler lifecycle for periodic memory extraction."""

    def __init__(self):
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if not settings.MEMORY_SCHEDULED_ENABLED:
            log.info("[memory_scheduler] disabled by config, skipping")
            return

        self._scheduler = BackgroundScheduler()
        interval = settings.MEMORY_SCHEDULED_INTERVAL_MINUTES
        self._scheduler.add_job(
            func=_scheduled_extraction_round,
            trigger="interval",
            minutes=interval,
            id="memory_scheduled_extraction",
            replace_existing=True,
        )
        self._scheduler.start()
        log.info(f"[memory_scheduler] started, interval={interval}min")

    def shutdown(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("[memory_scheduler] stopped")

    def trigger_now(self) -> dict:
        """Manually trigger one extraction round. Returns round stats."""
        return _scheduled_extraction_round()


def _scheduled_extraction_round() -> dict:
    """
    One extraction round:
    1. Query candidate sessions with recent activity
    2. Filter by watermark
    3. Serial extraction per session
    4. Log results to MemoryExtractionRun
    """
    db = SessionLocal()
    start_time = datetime.now()
    stats = {
        "trigger_type": "scheduled",
        "sessions_scanned": 0,
        "sessions_extracted": 0,
        "candidates_found": 0,
        "auto_confirmed": 0,
        "inbox_created": 0,
        "skipped": 0,
        "errors": 0,
        "details": [],
    }

    try:
        interval = settings.MEMORY_SCHEDULED_INTERVAL_MINUTES
        max_sessions = settings.MEMORY_SCHEDULED_MAX_SESSIONS
        cutoff = local_now() - timedelta(minutes=interval * 3)

        # Step 1: Query candidate sessions
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.updated_at >= cutoff)
            .order_by(ChatSession.updated_at.desc())
            .limit(max_sessions)
            .all()
        )
        stats["sessions_scanned"] = len(sessions)

        # Step 2: Filter & extract
        for session in sessions:
            session_stats = {
                "session_id": session.id,
                "session_title": session.title or "",
                "status": "skipped",
            }
            try:
                # Check watermark
                latest_msg = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.session_id == session.id)
                    .order_by(ChatMessage.created_at.desc())
                    .first()
                )
                if not latest_msg:
                    session_stats["reason"] = "no_messages"
                    stats["details"].append(session_stats)
                    continue

                if latest_msg.id == session.last_extracted_message_id:
                    session_stats["reason"] = "watermark_up_to_date"
                    stats["details"].append(session_stats)
                    continue

                # Run extraction
                result = extract_session_memories_scheduled(
                    db,
                    session_id=session.id,
                    last_extracted_message_id=session.last_extracted_message_id or "",
                    context_window=settings.MEMORY_SCHEDULED_CONTEXT_WINDOW,
                )

                session_stats["status"] = "extracted"
                session_stats["candidates_found"] = result.candidates_found
                session_stats["auto_confirmed"] = result.auto_confirmed
                session_stats["inbox_created"] = result.drafts_created
                session_stats["skipped"] = result.candidates_skipped

                stats["sessions_extracted"] += 1
                stats["candidates_found"] += result.candidates_found
                stats["auto_confirmed"] += result.auto_confirmed
                stats["inbox_created"] += result.drafts_created
                stats["skipped"] += result.candidates_skipped

            except Exception as exc:
                stats["errors"] += 1
                session_stats["status"] = "error"
                session_stats["error"] = str(exc)
                log.error(f"[memory_scheduler] session={session.id} error: {exc}")

            stats["details"].append(session_stats)

        # Step 3: Persist run log
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        run = MemoryExtractionRun(
            trigger_type="scheduled",
            sessions_scanned=stats["sessions_scanned"],
            sessions_extracted=stats["sessions_extracted"],
            candidates_found=stats["candidates_found"],
            auto_confirmed=stats["auto_confirmed"],
            inbox_created=stats["inbox_created"],
            skipped=stats["skipped"],
            errors=stats["errors"],
            duration_ms=duration,
            details=stats["details"],
        )
        db.add(run)
        db.commit()

        log.info(
            f"[memory_scheduler] round done: scanned={stats['sessions_scanned']}, "
            f"extracted={stats['sessions_extracted']}, "
            f"auto_confirmed={stats['auto_confirmed']}, "
            f"inbox={stats['inbox_created']}, skipped={stats['skipped']}, "
            f"errors={stats['errors']}, duration={duration}ms"
        )

    finally:
        db.close()

    return stats
