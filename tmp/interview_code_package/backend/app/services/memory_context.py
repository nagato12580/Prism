from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.memory import MemoryEntry, MemoryStatement, MemoryStatus
from backend.app.services.memory_vectors import search_memory_vectors
from backend.app.utils.time import local_now

MIN_SCORE = 0.40
MAX_ITEMS = 5
MAX_CHARS = 600


def _touch_access(rec) -> None:
    """召回命中时累加 access_count（不 commit，随调用方事务提交）。"""
    rec.access_count = (rec.access_count or 0) + 1
    rec.last_accessed_at = local_now()


def recall_preference_context(
    db: Session,
    content: str,
    *,
    user_id: str = "default-user",
    min_score: float = MIN_SCORE,
    max_items: int = MAX_ITEMS,
    vector_search=None,
) -> str:
    """召回与待解析内容相关的用户偏好/目标/约束记忆，拼成上下文块供资产解析 prompt 使用。

    与对话侧 active_recall 的区别：
    - 无信号门控（资产解析是对任意内容的分类，需主动找相关偏好）
    - 优先 preference/goal/constraint 类型记忆（过滤 fact/context 等非偏好类）
    - 无命中返回空串，调用方决定是否注入
    """
    text = (content or "").strip()
    if not text or not settings.EMBEDDING_API_BASE or not settings.EMBEDDING_API_KEY:
        return ""

    search = vector_search or search_memory_vectors
    try:
        hits = search(text=text, user_id=user_id, top_k=max_items * 3)
    except Exception:
        return ""

    if not hits:
        return ""

    preference_types = {"preference", "goal", "constraint"}
    lines: list[str] = []
    fetched: set[str] = set()
    for hit in hits:
        if len(lines) >= max_items:
            break
        mid = hit.get("memory_id")
        kind = hit.get("kind")
        score = float(hit.get("score") or 0.0)
        mtype = (hit.get("memory_type") or "").lower()
        if score < min_score or not mid or mid in fetched:
            continue
        if mtype and mtype not in preference_types:
            continue
        if kind == "entry":
            rec = db.query(MemoryEntry).filter(MemoryEntry.id == mid, MemoryEntry.user_id == user_id).first()
            if rec:
                lines.append(f"- {rec.title or rec.content[:40]}：{rec.content}")
                fetched.add(mid)
                _touch_access(rec)
        elif kind == "statement":
            rec = (
                db.query(MemoryStatement)
                .filter(
                    MemoryStatement.id == mid,
                    MemoryStatement.user_id == user_id,
                    MemoryStatement.status == MemoryStatus.CONFIRMED,
                )
                .first()
            )
            if rec and rec.statement_type in preference_types:
                lines.append(f"- {rec.content}")
                fetched.add(mid)
                _touch_access(rec)

    if not lines:
        return ""

    block = "【用户长期偏好/目标/约束（分类与归类时请参考，但不强制遵循）】\n" + "\n".join(lines)
    if len(block) > MAX_CHARS:
        block = block[:MAX_CHARS] + "…"
    return block


__all__ = ["recall_preference_context"]
