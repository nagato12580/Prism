from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.memory import MemoryEntry, MemoryInsight, MemoryStatement, MemoryStatus

DEFAULT_USER_ID = "default-user"
MAX_SOURCE_MEMORIES = 60
MIN_MEMORIES = 4


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        return {}


def _call_reflection_llm(memory_block: str) -> list[dict[str, Any]]:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return []
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    prompt = (
        "你是 Prism 的记忆反思引擎。回看用户已确认的长期记忆，归纳 2-4 条高层洞察（Insight）。\n"
        "洞察应是对用户画像的概括性理解，而非单条记忆的复述。\n"
        '只输出严格 JSON：{"insights": [{"theme": "主题(如:技术偏好/学习习惯/项目目标)", "content": "一句概括洞察", "importance": 0.0-1.0}]}\n'
        "content 不超过 120 字。"
    )
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": memory_block},
            ],
            temperature=0.4,
        )
    except Exception:
        return []
    data = _extract_json(resp.choices[0].message.content or "")
    insights = data.get("insights") if isinstance(data, dict) else []
    if not isinstance(insights, list):
        return []
    result: list[dict[str, Any]] = []
    for item in insights[:4]:
        if not isinstance(item, dict):
            continue
        theme = str(item.get("theme") or "").strip()[:128]
        content = str(item.get("content") or "").strip()[:500]
        if not theme or not content:
            continue
        importance = 0.6
        try:
            importance = max(0.0, min(1.0, float(item.get("importance", 0.6))))
        except (TypeError, ValueError):
            pass
        result.append({"theme": theme, "content": content, "importance": importance})
    return result


def _gather_source_memories(db: Session, user_id: str) -> tuple[list[tuple[str, str]], list[str]]:
    """收集已确认记忆（entry + statement），返回 [(id, text)] 和 id 列表。"""
    entries = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.user_id == user_id)
        .order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc())
        .limit(MAX_SOURCE_MEMORIES)
        .all()
    )
    statements = (
        db.query(MemoryStatement)
        .filter(MemoryStatement.user_id == user_id, MemoryStatement.status == MemoryStatus.CONFIRMED)
        .order_by(MemoryStatement.importance.desc(), MemoryStatement.updated_at.desc())
        .limit(MAX_SOURCE_MEMORIES)
        .all()
    )
    sources: list[tuple[str, str]] = []
    for e in entries:
        sources.append((e.id, f"[偏好/目标] {e.title}：{e.content}"))
    for s in statements:
        sources.append((s.id, f"[{s.statement_type}] {s.content}"))
    return sources, [sid for sid, _ in sources]


def run_reflection(
    db: Session,
    *,
    user_id: str = DEFAULT_USER_ID,
    llm_call=None,
) -> dict[str, Any]:
    """手动触发反思：归纳已确认记忆为 Insight，按 theme upsert 写入 MemoryInsight。
    返回 {insights, skipped, error}。记忆太少或 LLM 不可用则跳过。
    """
    sources, _ = _gather_source_memories(db, user_id)
    if len(sources) < MIN_MEMORIES:
        return {"insights": 0, "skipped": "too_few_memories"}

    memory_block = "\n".join(text for _, text in sources[:MAX_SOURCE_MEMORIES])
    call = llm_call or _call_reflection_llm
    try:
        raw_insights = call(memory_block)
    except Exception:
        return {"insights": 0, "skipped": "no_llm_or_empty"}
    if not raw_insights:
        return {"insights": 0, "skipped": "no_llm_or_empty"}

    source_ids = [sid for sid, _ in sources]
    created = 0
    to_index: list[MemoryInsight] = []
    for ins in raw_insights:
        theme = ins["theme"]
        existing = (
            db.query(MemoryInsight)
            .filter(MemoryInsight.user_id == user_id, MemoryInsight.theme == theme)
            .first()
        )
        if existing:
            existing.content = ins["content"]
            existing.importance = ins["importance"]
            existing.source_statement_ids = source_ids
            to_index.append(existing)
            created += 1
        else:
            insight = MemoryInsight(
                user_id=user_id,
                theme=theme,
                content=ins["content"],
                insight_type="reflection",
                source_statement_ids=source_ids,
                importance=ins["importance"],
                status=MemoryStatus.CONFIRMED,
            )
            db.add(insight)
            db.flush()
            to_index.append(insight)
            created += 1
    db.commit()
    # 反思产出后向量化 Insight，供召回链路使用；失败不阻塞
    for insight in to_index:
        _index_insight_vector(db, insight)
    db.commit()
    return {"insights": created, "skipped": None}


def _index_insight_vector(db: Session, insight: MemoryInsight) -> None:
    try:
        from backend.app.services.memory_vectors import upsert_insight_vector
        vector_id = upsert_insight_vector(insight)
    except Exception:
        vector_id = ""
    if vector_id:
        insight.embedding_ref = vector_id
        insight.embedding_model = settings.EMBEDDING_MODEL
        insight.embedding_status = "done"
    else:
        insight.embedding_status = "pending"


def list_insights(db: Session, *, user_id: str = DEFAULT_USER_ID, limit: int = 20) -> list[MemoryInsight]:
    return (
        db.query(MemoryInsight)
        .filter(MemoryInsight.user_id == user_id, MemoryInsight.status == MemoryStatus.CONFIRMED)
        .order_by(MemoryInsight.importance.desc(), MemoryInsight.updated_at.desc())
        .limit(limit)
        .all()
    )


__all__ = ["run_reflection", "list_insights"]
