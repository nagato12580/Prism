import argparse

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.memory import MemoryEntry, MemoryInsight, MemoryStatement, MemoryStatus
from backend.app.services.memory_vectors import upsert_entry_vector, upsert_insight_vector, upsert_statement_vector


Stats = dict[str, int]


def _empty_stats() -> Stats:
    return {"scanned": 0, "updated": 0, "skipped": 0, "failed": 0}


def _should_skip(embedding_status: str, embedding_ref: str, *, force: bool) -> bool:
    if force:
        return False
    return embedding_status == "done" and bool(embedding_ref)


def _mark_done(model, embedding_ref: str) -> None:
    model.embedding_ref = embedding_ref
    model.embedding_model = settings.EMBEDDING_MODEL
    model.embedding_status = "done"


def backfill_memory_vectors(
    db: Session,
    *,
    user_id: str | None = None,
    limit: int = 500,
    force: bool = False,
    batch_size: int = 100,
) -> Stats:
    stats = _empty_stats()
    index = 0

    entries_q = db.query(MemoryEntry)
    if user_id:
        entries_q = entries_q.filter(MemoryEntry.user_id == user_id)
    for entry in entries_q.order_by(MemoryEntry.created_at.asc()).limit(limit).all():
        index += 1
        stats["scanned"] += 1
        if _should_skip(entry.embedding_status, entry.embedding_ref, force=force):
            stats["skipped"] += 1
        else:
            try:
                ref = upsert_entry_vector(entry)
                if ref:
                    _mark_done(entry, ref)
                    stats["updated"] += 1
                else:
                    entry.embedding_status = "pending"
                    stats["skipped"] += 1
            except Exception:
                entry.embedding_status = "failed"
                stats["failed"] += 1
        if batch_size > 0 and index % batch_size == 0:
            db.commit()

    statements_q = db.query(MemoryStatement).filter(MemoryStatement.status == MemoryStatus.CONFIRMED)
    if user_id:
        statements_q = statements_q.filter(MemoryStatement.user_id == user_id)
    for statement in statements_q.order_by(MemoryStatement.created_at.asc()).limit(limit).all():
        index += 1
        stats["scanned"] += 1
        if _should_skip(statement.embedding_status, statement.embedding_ref, force=force):
            stats["skipped"] += 1
        else:
            try:
                ref = upsert_statement_vector(statement)
                if ref:
                    _mark_done(statement, ref)
                    stats["updated"] += 1
                else:
                    statement.embedding_status = "pending"
                    stats["skipped"] += 1
            except Exception:
                statement.embedding_status = "failed"
                stats["failed"] += 1
        if batch_size > 0 and index % batch_size == 0:
            db.commit()

    insights_q = db.query(MemoryInsight).filter(MemoryInsight.status == MemoryStatus.CONFIRMED)
    if user_id:
        insights_q = insights_q.filter(MemoryInsight.user_id == user_id)
    for insight in insights_q.order_by(MemoryInsight.created_at.asc()).limit(limit).all():
        index += 1
        stats["scanned"] += 1
        if _should_skip(insight.embedding_status, insight.embedding_ref, force=force):
            stats["skipped"] += 1
        else:
            try:
                ref = upsert_insight_vector(insight)
                if ref:
                    _mark_done(insight, ref)
                    stats["updated"] += 1
                else:
                    insight.embedding_status = "pending"
                    stats["skipped"] += 1
            except Exception:
                insight.embedding_status = "failed"
                stats["failed"] += 1
        if batch_size > 0 and index % batch_size == 0:
            db.commit()

    db.commit()
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill vectors for MemoryEntry and confirmed MemoryStatement rows.")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    db = SessionLocal()
    try:
        stats = backfill_memory_vectors(
            db,
            user_id=args.user_id,
            limit=args.limit,
            force=args.force,
            batch_size=args.batch_size,
        )
    finally:
        db.close()
    for key in ("scanned", "updated", "skipped", "failed"):
        print(f"{key}: {stats[key]}")


if __name__ == "__main__":
    main()
