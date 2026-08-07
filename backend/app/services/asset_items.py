# prism/backend/app/services/asset_items.py
"""Shared PersonalAssetItem creation pipeline.

Extracted from ``backend/app/api/assets.py`` so both the Backend API and the
Engine process (which shares the same MySQL database) can create asset items
through one code path.

This module MUST stay FastAPI-free AND LLM-free: the Engine imports it directly.
LLM orchestration (AI parse) stays in the API layer; callers here pass a
``parsed`` dict or let the rule-based fallback produce the draft fields.
"""
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.asset import PersonalAssetItem

DEFAULT_USER_ID = "default-user"


def _short_title(text: str, fallback: str = "未命名资产") -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return fallback
    return text[:40] + ("..." if len(text) > 40 else "")


def _clean_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value[:12]:
        tag = str(item).strip().strip("#")
        if tag and tag not in tags:
            tags.append(tag[:32])
    return tags


def _clean_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:20]:
        if isinstance(item, dict):
            result.append(item)
    return result


def _extract_keywords(text: str, tags: list[str] | None = None) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_+#.-]+|[一-鿿]{2,}", text or "")
    keywords: list[str] = []
    for item in [*(tags or []), *raw]:
        word = str(item).strip().strip("#").lower()
        if len(word) < 2 or word in keywords:
            continue
        keywords.append(word[:48])
        if len(keywords) >= 24:
            break
    return keywords


def _keyword_index_text(*parts: Any) -> str:
    values: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            values.extend(str(item) for item in part)
        elif isinstance(part, dict):
            values.extend(str(value) for value in part.values())
        else:
            values.append(str(part))
    return " ".join(value.strip() for value in values if value and value.strip())[:10000]


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _fallback_parse(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    has_url = bool(source_url) or "http://" in content or "https://" in content
    lowered = content.lower()
    if has_url:
        kind = "resource"
        category = "资源"
    elif any(key in lowered for key in ["观点", "认为", "看法", "评论", "启发"]):
        kind = "opinion"
        category = "观点"
    elif len(content) > 180 or any(key in lowered for key in ["技术", "知识", "教程", "原理", "系统"]):
        kind = "knowledge"
        category = "知识点"
    else:
        kind = "idea"
        category = "灵感"
    summary = _short_title(content, "暂无摘要")
    return {
        "title": title or _short_title(content),
        "asset_kind": kind,
        "source": {
            "type": source_type or "manual",
            "platform": source_platform or "",
            "url": source_url or "",
        },
        "summary": summary,
        "rewritten_content": "",
        "extracts": [{"type": "summary", "content": summary, "confidence": 0.4}],
        "tags": [category],
        "category": category,
        "suggested_relations": [],
        "suggested_extensions": [],
        "confidence": {
            "overall": 0.4,
            "classification": 0.45,
            "source": 0.4,
            "extraction": 0.4,
            "relation": 0.0,
            "extension": 0.0,
        },
        "rationale": "AI 解析不可用，使用规则兜底生成最低可用草稿。",
    }


def _normalize_parse(
    *,
    content: str,
    title: str,
    source_type: str,
    source_platform: str,
    source_url: str,
    parsed: dict[str, Any] | None,
) -> dict[str, Any]:
    fallback = _fallback_parse(
        content=content,
        title=title,
        source_type=source_type,
        source_platform=source_platform,
        source_url=source_url,
    )
    data = parsed if isinstance(parsed, dict) else fallback
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    confidence = data.get("confidence") if isinstance(data.get("confidence"), dict) else fallback["confidence"]
    return {
        "title": _short_title(str(data.get("title") or fallback["title"])),
        "summary": str(data.get("summary") or fallback["summary"]).strip()[:1200],
        "rewritten_content": str(data.get("rewritten_content") or fallback["rewritten_content"] or "").strip(),
        "asset_kind": str(data.get("asset_kind") or fallback["asset_kind"]).strip()[:64] or "idea",
        "source_type": str(source.get("type") or source_type or fallback["source"]["type"]).strip()[:64],
        "source_platform": str(source.get("platform") or source_platform or "").strip()[:128],
        "source_url": str(source.get("url") or source_url or "").strip()[:1000],
        "media_type": str(data.get("media_type") or "text").strip()[:64] or "text",
        "category": str(data.get("category") or fallback["category"]).strip()[:128],
        "tags": _clean_tags(data.get("tags")) or fallback["tags"],
        "extracts": _clean_dict_list(data.get("extracts")) or fallback["extracts"],
        "suggested_relations": _clean_dict_list(data.get("suggested_relations")),
        "suggested_extensions": _clean_dict_list(data.get("suggested_extensions")),
        "confidence": confidence,
        "rationale": str(data.get("rationale") or fallback["rationale"]).strip()[:1200],
    }


def create_asset_item_from_raw(
    db: Session,
    *,
    raw_text: str,
    raw_title: str = "",
    raw_source_type: str = "manual",
    raw_source_platform: str = "",
    raw_source_url: str = "",
    raw_author: str = "",
    raw_tags: list[str] | None = None,
    raw_metadata: dict[str, Any] | None = None,
    parsed: dict[str, Any] | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> PersonalAssetItem:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Content is required")

    data = _normalize_parse(
        content=raw_text,
        title=raw_title,
        source_type=raw_source_type,
        source_platform=raw_source_platform,
        source_url=raw_source_url,
        parsed=parsed,
    )
    raw_tags = _clean_tags(raw_tags or [])
    keywords = _extract_keywords(raw_text, [*raw_tags, *data["tags"]])
    item = PersonalAssetItem(
        user_id=user_id,
        raw_text=raw_text,
        raw_title=(raw_title or "")[:255],
        raw_source_type=(raw_source_type or "manual")[:64],
        raw_source_platform=(raw_source_platform or "")[:128],
        raw_source_url=(raw_source_url or "")[:1000],
        raw_author=(raw_author or "")[:255],
        raw_tags=raw_tags,
        raw_metadata=raw_metadata or {},
        raw_keywords=keywords,
        keyword_index_text=_keyword_index_text(
            raw_title,
            raw_text,
            raw_tags,
            keywords,
            data["title"],
            data["summary"],
            data["rewritten_content"],
            data["tags"],
            data["category"],
        ),
        raw_embedding_status="pending",
        title=data["title"],
        summary=data["summary"],
        asset_kind=data["asset_kind"],
        source_type=data["source_type"],
        source_platform=data["source_platform"],
        source_url=data["source_url"],
        media_type=data["media_type"],
        category=data["category"],
        tags=data["tags"],
        extracts=data["extracts"],
        suggested_relations=data["suggested_relations"],
        suggested_extensions=data["suggested_extensions"],
        confidence=data["confidence"],
        rationale=data["rationale"],
        rewritten_content=data["rewritten_content"],
        extra_meta={"raw_metadata": raw_metadata or {}},
        capabilities=["searchable", "summarizable"],
        source_ref_type="fragment",
        importance=float((data["confidence"] or {}).get("overall", 0.5) or 0.5),
        status="pending_review",
    )
    db.add(item)
    db.flush()
    item.source_ref_id = item.id
    db.commit()
    db.refresh(item)
    return item
