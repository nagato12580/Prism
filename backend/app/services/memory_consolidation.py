from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.memory import MemoryEntry, MemoryStatement, MemoryStatus
from backend.app.utils.time import local_now

DEFAULT_USER_ID = "default-user"

ACCESS_PROMOTE_THRESHOLD = 3
IMPORTANCE_PROMOTE_TARGET = 0.85
IMPORTANCE_CAP = 0.95
MAX_PROMOTE = 30


def run_consolidation(
    db: Session,
    *,
    user_id: str = DEFAULT_USER_ID,
    access_threshold: int = ACCESS_PROMOTE_THRESHOLD,
    target_importance: float = IMPORTANCE_PROMOTE_TARGET,
    max_promote: int = MAX_PROMOTE,
) -> dict[str, Any]:
    """手动触发巩固：将高频被召回但重要度偏低的记忆提升重要度。

    策略（区别 Comet 自动定时巩固）：
    - 仅提升 access_count >= threshold 且 importance < target 的记忆
    - 提升到 target，不超过 cap
    - 不自动改 status/分层（Prism 无 short/long 分层），只提权
    - 返回提升明细，供前端展示"已巩固 N 条高频记忆"
    """
    now = local_now()
    promoted_entries: list[dict[str, Any]] = []
    promoted_statements: list[dict[str, Any]] = []

    entries = (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.user_id == user_id,
            MemoryEntry.access_count >= access_threshold,
            MemoryEntry.importance < target_importance,
        )
        .order_by(MemoryEntry.access_count.desc())
        .limit(max_promote)
        .all()
    )
    for entry in entries:
        old_imp = float(entry.importance or 0)
        entry.importance = min(target_importance, IMPORTANCE_CAP)
        entry.last_accessed_at = entry.last_accessed_at or now
        promoted_entries.append({
            "id": entry.id,
            "title": entry.title,
            "access_count": entry.access_count,
            "old_importance": round(old_imp, 2),
            "new_importance": round(float(entry.importance), 2),
        })

    statements = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == user_id,
            MemoryStatement.status == MemoryStatus.CONFIRMED,
            MemoryStatement.access_count >= access_threshold,
            MemoryStatement.importance < target_importance,
        )
        .order_by(MemoryStatement.access_count.desc())
        .limit(max_promote)
        .all()
    )
    for stmt in statements:
        old_imp = float(stmt.importance or 0)
        stmt.importance = min(target_importance, IMPORTANCE_CAP)
        stmt.last_accessed_at = stmt.last_accessed_at or now
        promoted_statements.append({
            "id": stmt.id,
            "content": stmt.content[:60],
            "access_count": stmt.access_count,
            "old_importance": round(old_imp, 2),
            "new_importance": round(float(stmt.importance), 2),
        })

    db.commit()
    return {
        "promoted_entries": len(promoted_entries),
        "promoted_statements": len(promoted_statements),
        "total_promoted": len(promoted_entries) + len(promoted_statements),
        "details": {"entries": promoted_entries, "statements": promoted_statements},
    }


def consolidation_candidates(
    db: Session,
    *,
    user_id: str = DEFAULT_USER_ID,
    access_threshold: int = ACCESS_PROMOTE_THRESHOLD,
    target_importance: float = IMPORTANCE_PROMOTE_TARGET,
    max_promote: int = MAX_PROMOTE,
) -> dict[str, Any]:
    """预览巩固候选（不修改），供前端展示"将提升哪些记忆"后再确认。"""
    entries = (
        db.query(MemoryEntry)
        .filter(
            MemoryEntry.user_id == user_id,
            MemoryEntry.access_count >= access_threshold,
            MemoryEntry.importance < target_importance,
        )
        .order_by(MemoryEntry.access_count.desc())
        .limit(max_promote)
        .all()
    )
    statements = (
        db.query(MemoryStatement)
        .filter(
            MemoryStatement.user_id == user_id,
            MemoryStatement.status == MemoryStatus.CONFIRMED,
            MemoryStatement.access_count >= access_threshold,
            MemoryStatement.importance < target_importance,
        )
        .order_by(MemoryStatement.access_count.desc())
        .limit(max_promote)
        .all()
    )
    return {
        "entries": [
            {"id": e.id, "title": e.title, "access_count": e.access_count, "importance": round(float(e.importance or 0), 2)}
            for e in entries
        ],
        "statements": [
            {"id": s.id, "content": s.content[:60], "access_count": s.access_count, "importance": round(float(s.importance or 0), 2)}
            for s in statements
        ],
    }


__all__ = ["run_consolidation", "consolidation_candidates"]
