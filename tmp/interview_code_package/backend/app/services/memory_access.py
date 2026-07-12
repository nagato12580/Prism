from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.memory import MemoryEntry, MemoryStatement, MemoryStatus
from backend.app.utils.time import local_now


def bump_memory_access(
    db: Session,
    *,
    memory_ids: list[tuple[str, str]],
    user_id: str = "default-user",
) -> int:
    """召回命中后回写 access_count + last_accessed_at，用于巩固提权依据。

    memory_ids: [(memory_id, kind), ...] kind ∈ {"entry", "statement"}
    返回成功回写的条数。失败静默跳过。
    """
    if not memory_ids:
        return 0
    entry_ids = [mid for mid, kind in memory_ids if kind == "entry"]
    statement_ids = [mid for mid, kind in memory_ids if kind == "statement"]
    now = local_now()
    updated = 0
    if entry_ids:
        for rec in db.query(MemoryEntry).filter(MemoryEntry.id.in_(entry_ids), MemoryEntry.user_id == user_id).all():
            rec.access_count = (rec.access_count or 0) + 1
            rec.last_accessed_at = now
            updated += 1
    if statement_ids:
        for rec in (
            db.query(MemoryStatement)
            .filter(MemoryStatement.id.in_(statement_ids), MemoryStatement.user_id == user_id)
            .all()
        ):
            rec.access_count = (rec.access_count or 0) + 1
            rec.last_accessed_at = now
            updated += 1
    if updated:
        try:
            db.commit()
        except Exception:
            db.rollback()
            return 0
    return updated


__all__ = ["bump_memory_access"]
