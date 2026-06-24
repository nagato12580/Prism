from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.memory import MemoryEntity, MemoryRelation, MemoryStatus

DEFAULT_USER_ID = "default-user"
MAX_ENTITIES = 4


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:255]


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except Exception:
        return {}


def _call_entity_llm(content: str) -> list[dict[str, str]]:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return []
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    prompt = (
        "你是 Prism 的记忆实体抽取器。从一条用户记忆中抽取 1-4 个核心实体（人、项目、技术、主题、产品等）。\n"
        "只输出严格 JSON：{\"entities\": [{\"name\": \"实体名\", \"type\": \"project/technology/topic/person/product/other\", \"description\": \"一句话描述\"}]}\n"
        "不要抽取过于宽泛的词（如'用户''记忆''偏好'）。"
    )
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": content[:2000]},
            ],
            temperature=0.1,
        )
    except Exception:
        return []
    data = _extract_json(resp.choices[0].message.content or "")
    entities = data.get("entities") if isinstance(data, dict) else []
    if not isinstance(entities, list):
        return []
    result: list[dict[str, str]] = []
    for item in entities[:MAX_ENTITIES]:
        if not isinstance(item, dict):
            continue
        name = _normalize_name(str(item.get("name") or ""))
        if not name:
            continue
        result.append({
            "name": name,
            "type": str(item.get("type") or "topic").strip()[:64] or "topic",
            "description": str(item.get("description") or "").strip()[:500],
        })
    return result


def _upsert_entity(db: Session, user_id: str, name: str, entity_type: str, description: str, source_id: str) -> MemoryEntity | None:
    name_norm = _normalize_name(name)
    if not name_norm:
        return None
    existing = (
        db.query(MemoryEntity)
        .filter(MemoryEntity.user_id == user_id, MemoryEntity.name == name_norm)
        .first()
    )
    if existing:
        existing.mention_count = (existing.mention_count or 1) + 1
        if description and not existing.description:
            existing.description = description
        existing.source_ids = list({*(existing.source_ids or []), source_id})
        existing.status = MemoryStatus.CONFIRMED
        db.flush()
        return existing
    entity = MemoryEntity(
        user_id=user_id,
        name=name_norm,
        entity_type=entity_type,
        description=description,
        source_ids=[source_id],
        status=MemoryStatus.CONFIRMED,
        mention_count=1,
    )
    db.add(entity)
    db.flush()
    return entity


def extract_and_link_entities(
    db: Session,
    *,
    content: str,
    source_id: str,
    statement_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
    llm_call=None,
) -> list[MemoryEntity]:
    """从一条记忆抽取核心实体，upsert MemoryEntity，并在实体间挂 related_to 关系。
    抽取失败静默返回空列表，不阻塞记忆确认。
    """
    text = (content or "").strip()
    if not text:
        return []

    call = llm_call or _call_entity_llm
    try:
        raw_entities = call(text)
    except Exception:
        return []
    if not raw_entities:
        return []

    linked: list[MemoryEntity] = []
    for ent in raw_entities:
        entity = _upsert_entity(db, user_id, ent["name"], ent["type"], ent["description"], source_id)
        if entity:
            linked.append(entity)

    # 实体间挂 related_to 关系（共享同一条记忆的实体天然相关）
    for i in range(len(linked)):
        for j in range(i + 1, len(linked)):
            a, b = linked[i], linked[j]
            exists = (
                db.query(MemoryRelation)
                .filter(
                    MemoryRelation.user_id == user_id,
                    MemoryRelation.subject_entity_id == a.id,
                    MemoryRelation.object_entity_id == b.id,
                    MemoryRelation.predicate == "related_to",
                )
                .first()
            )
            if not exists:
                db.add(MemoryRelation(
                    user_id=user_id,
                    subject_entity_id=a.id,
                    object_entity_id=b.id,
                    predicate="related_to",
                    statement_id=statement_id,
                    status=MemoryStatus.CONFIRMED,
                    confidence=0.6,
                ))
                db.flush()
    return linked


__all__ = ["extract_and_link_entities"]
