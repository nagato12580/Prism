import argparse

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.knowledge_governance import PersonalKnowledgeUnit
from backend.app.services.pku_vectors import upsert_pku_vector


Stats = dict[str, int]


def _empty_stats() -> Stats:
    return {"scanned": 0, "updated": 0, "skipped": 0, "failed": 0}


def _should_skip(pku: PersonalKnowledgeUnit, *, force: bool) -> bool:
    if force:
        return False
    return pku.embedding_status == "done" and bool(pku.embedding_ref)


def _refresh_pku(pku: PersonalKnowledgeUnit) -> bool:
    embedding_ref = upsert_pku_vector(pku)
    if not embedding_ref:
        pku.embedding_status = "pending"
        return False
    pku.embedding_ref = embedding_ref
    pku.embedding_model = settings.EMBEDDING_MODEL
    pku.embedding_status = "done"
    return True


def backfill_pku_vectors(
    db: Session,
    *,
    user_id: str | None = None,
    limit: int = 500,
    force: bool = False,
    batch_size: int = 100,
) -> Stats:
    stats = _empty_stats()
    query = db.query(PersonalKnowledgeUnit).filter(PersonalKnowledgeUnit.status == "active")
    if user_id:
        query = query.filter(PersonalKnowledgeUnit.user_id == user_id)
    pkus = query.order_by(PersonalKnowledgeUnit.created_at.asc()).limit(limit).all()

    for index, pku in enumerate(pkus, start=1):
        stats["scanned"] += 1
        if _should_skip(pku, force=force):
            stats["skipped"] += 1
        else:
            try:
                if _refresh_pku(pku):
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                pku.embedding_status = "failed"
                stats["failed"] += 1
        if batch_size > 0 and index % batch_size == 0:
            db.commit()
    db.commit()
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill vectors for PersonalKnowledgeUnit rows.")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    db = SessionLocal()
    try:
        stats = backfill_pku_vectors(
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
