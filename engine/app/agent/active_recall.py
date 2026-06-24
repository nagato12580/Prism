from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from backend.app.models.memory import MemoryEntry, MemoryStatement, MemoryStatus
from backend.app.services.memory_vectors import search_memory_vectors
from engine.app.config import settings


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

RECALL_TIMEOUT_SECONDS = 3.5
MIN_VECTOR_SCORE = 0.45
MAX_RECALL_ITEMS = 6

_FIRST_PERSON_SIGNALS = ("我", "我的", "我喜欢", "我偏好", "我想", "我之前", "我习惯", "我打算", "我需要", "我希望", "我关心", "记得", "之前说", "上次")
_PREFERENCE_SIGNALS = ("偏好", "喜欢", "习惯", "目标", "打算", "希望", "约束", "倾向", "不想", "讨厌", "在意的", "优先")


def has_recall_signal(query: str) -> bool:
    """检测用户消息是否含第一人称或偏好信号，决定是否触发主动召回。
    克制策略：仅在用户谈论自身时召回，避免每次对话都查向量库。
    """
    text = (query or "").strip()
    if not text or len(text) < 2:
        return False
    return any(sig in text for sig in _FIRST_PERSON_SIGNALS + _PREFERENCE_SIGNALS)


def _entry_brief(entry: MemoryEntry) -> str:
    return f"- {entry.title or entry.content[:40]}：{entry.content}"


def _statement_brief(statement: MemoryStatement) -> str:
    return f"- {statement.content}"


def recall_memory_context(
    query: str,
    *,
    user_id: str = "default-user",
    timeout_seconds: float = RECALL_TIMEOUT_SECONDS,
    min_score: float = MIN_VECTOR_SCORE,
    max_items: int = MAX_RECALL_ITEMS,
    vector_search: Callable[..., list[dict[str, Any]]] | None = None,
) -> str:
    """主动召回与当前问题相关的记忆，拼成背景块注入 system prompt。
    无命中/超时/向量不可用返回空串，绝不拖累对话首字延迟。
    """
    query = (query or "").strip()
    if not query or not has_recall_signal(query):
        return ""

    search = vector_search or search_memory_vectors
    started = time.monotonic()

    try:
        vec_hits = search(text=query, user_id=user_id, top_k=max_items * 2)
    except Exception:
        return ""

    if not vec_hits:
        return ""

    if time.monotonic() - started > timeout_seconds:
        return ""

    db = _Session()
    lines: list[str] = []
    try:
        fetched: set[str] = set()
        hit_ids: list[tuple[str, str]] = []
        for hit in vec_hits:
            if len(lines) >= max_items:
                break
            mid = hit.get("memory_id")
            kind = hit.get("kind")
            score = float(hit.get("score") or 0.0)
            if score < min_score or not mid or mid in fetched:
                continue
            if kind == "entry":
                rec = db.query(MemoryEntry).filter(MemoryEntry.id == mid, MemoryEntry.user_id == user_id).first()
                if rec:
                    lines.append(_entry_brief(rec))
                    fetched.add(mid)
                    hit_ids.append((mid, "entry"))
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
                if rec:
                    lines.append(_statement_brief(rec))
                    fetched.add(mid)
                    hit_ids.append((mid, "statement"))
    except Exception:
        return ""
    finally:
        db.close()

    if not lines:
        return ""

    # 回写 access_count（失败不影响召回注入）
    if hit_ids:
        try:
            from backend.app.services.memory_access import bump_memory_access
            bump_session = _Session()
            try:
                bump_memory_access(bump_session, memory_ids=hit_ids)
            finally:
                bump_session.close()
        except Exception:
            pass

    block = "【关于用户的已知记忆（供参考，可自然融入回答，不必刻意提及）】\n" + "\n".join(lines)
    return block


__all__ = ["has_recall_signal", "recall_memory_context"]
