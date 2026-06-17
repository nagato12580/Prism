# prism/backend/app/api/assets.py
import json
import re
from collections import Counter
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from openai import OpenAI
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models.asset import AssetDraft, AssetRelation, ExtensionPoint, KnowledgeDraft, PersonalAsset, PersonalAssetItem
from ..models.inbox import InboxRawItem, MemoryEntry
from ..models.knowledge_item import KnowledgeItem
from ..services.knowledge_governance import settle_personal_asset_item_to_governance
from .upload import _trigger_ingestion
from ..schemas.asset import (
    AssetConfirmRequest,
    AssetConfirmResponse,
    AssetDraftCreate,
    AssetDraftOut,
    AssetDraftUpdate,
    AssetOverviewOut,
    AssetSearchResult,
    KnowledgeDraftConfirmRequest,
    KnowledgeDraftConfirmResponse,
    KnowledgeDraftCreate,
    KnowledgeDraftOut,
    KnowledgeDraftUpdate,
    PersonalAssetItemCreate,
    PersonalAssetItemOut,
    PersonalAssetItemUpdate,
    PersonalAssetOut,
)

router = APIRouter(prefix="/assets", tags=["assets"])
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
    raw = re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", text or "")
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


def _ai_parse_asset(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
) -> dict[str, Any] | None:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return None
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    request = {
        "task": "把用户丢进 Prism 的任意材料解析成可编辑知识资产草稿。只返回 JSON。",
        "source": {
            "title": title,
            "content": content[:6000],
            "source_type": source_type,
            "source_platform": source_platform,
            "source_url": source_url,
        },
        "json_shape": {
            "title": "短标题，不超过40字",
            "asset_kind": "开放字符串，例如 knowledge/opinion/resource/task/idea",
            "source": {"type": "来源类型", "platform": "来源平台", "url": "来源链接"},
            "summary": "一句话摘要",
            "extracts": [{"type": "claim/knowledge/action/question/summary", "content": "提取内容", "confidence": 0.0}],
            "tags": ["2-6个标签"],
            "category": "主题分类",
            "suggested_relations": [{"target_asset_id": "", "relation_type": "similar_to/supports/contradicts/extends/mentions", "reason": "", "confidence": 0.0}],
            "suggested_extensions": [{"title": "值得拓展的知识点", "reason": "为什么值得拓展", "confidence": 0.0}],
            "confidence": {
                "overall": 0.0,
                "classification": 0.0,
                "source": 0.0,
                "extraction": 0.0,
                "relation": 0.0,
                "extension": 0.0,
            },
            "rationale": "为什么这样解析",
        },
        "rules": [
            "不要直接写入正式知识库，只生成草稿建议。",
            "如果来源无法确定，source confidence 要低。",
            "suggested_relations 只能基于输入内容提出候选，不要编造 target_asset_id。",
            "扩展点是值得继续研究的问题或知识点。",
        ],
    }
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是 Prism 的 AI 知识资产解析器。输出严格 JSON，不要 Markdown。"},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        return _parse_json_object(resp.choices[0].message.content or "")
    except Exception:
        return None


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


def _draft_body(draft: AssetDraft, raw: InboxRawItem | None) -> str:
    if raw and raw.content:
        return raw.content
    extract_text = "\n".join(str(item.get("content", "")) for item in (draft.extracts or []) if isinstance(item, dict))
    return extract_text or draft.summary or ""


def _asset_result(asset: PersonalAsset, score: float) -> AssetSearchResult:
    return AssetSearchResult(
        asset_id=asset.id,
        asset_kind=asset.asset_kind,
        title=asset.title,
        summary=asset.summary,
        source_type=asset.source_type,
        source_platform=asset.source_platform,
        tags=asset.tags or [],
        category=asset.category,
        score=score,
    )


def _asset_text(asset: PersonalAsset) -> str:
    return "\n".join(
        part
        for part in [
            f"标题：{asset.title}",
            f"类型：{asset.asset_kind}",
            f"分类：{asset.category}",
            f"标签：{', '.join(asset.tags or [])}",
            f"摘要：{asset.summary or ''}",
            f"正文：{asset.body or ''}",
        ]
        if part.strip()
    )


def _fallback_knowledge_draft(assets: list[PersonalAsset], title: str = "", instruction: str = "") -> dict[str, Any]:
    categories = Counter(asset.category or "未分类" for asset in assets)
    tags: Counter[str] = Counter()
    for asset in assets:
        tags.update(asset.tags or [])
    content_parts = []
    for index, asset in enumerate(assets, start=1):
        content_parts.append(
            f"## {index}. {asset.title}\n\n"
            f"{asset.summary or asset.body or ''}\n\n"
            f"- 类型：{asset.asset_kind}\n"
            f"- 分类：{asset.category or '未分类'}\n"
            f"- 标签：{', '.join(asset.tags or [])}"
        )
    leading_category = categories.most_common(1)[0][0] if categories else "知识整理"
    return {
        "title": title or f"{leading_category}知识整理",
        "summary": f"基于 {len(assets)} 条个人知识资产整理出的知识草稿。",
        "content": "\n\n".join(content_parts),
        "category": leading_category,
        "tags": [name for name, _ in tags.most_common(8)] or [leading_category],
        "outline": [{"title": asset.title, "asset_id": asset.id} for asset in assets[:12]],
        "confidence": {"overall": 0.45, "synthesis": 0.45},
        "rationale": "AI 汇编不可用，使用资产摘要兜底生成可编辑知识草稿。",
    }


def _ai_synthesize_knowledge(assets: list[Any], title: str = "", instruction: str = "") -> dict[str, Any] | None:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return None
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    request = {
        "task": "把一组已确认的个人知识资产汇编成一篇稳定知识库草稿。只返回 JSON。",
        "instruction": instruction,
        "preferred_title": title,
        "assets": [
            {
                "id": asset.id,
                "title": asset.title,
                "asset_kind": asset.asset_kind,
                "summary": asset.summary,
                "body": (asset.body or "")[:1600],
                "category": asset.category,
                "tags": asset.tags or [],
                "source_platform": asset.source_platform,
            }
            for asset in assets[:30]
        ],
        "json_shape": {
            "title": "知识草稿标题",
            "summary": "一句话摘要",
            "content": "Markdown 正文，结构化组织多个资产中的稳定知识",
            "category": "主题分类",
            "tags": ["标签"],
            "outline": [{"title": "章节标题", "asset_ids": ["来源资产 id"]}],
            "confidence": {"overall": 0.0, "synthesis": 0.0},
            "rationale": "为什么这样汇编",
        },
        "rules": [
            "不要把碎片逐条堆砌，应该归纳成稳定知识。",
            "不要编造资产中没有的信息。",
            "如果存在冲突观点，要在正文中标注冲突或适用边界。",
            "这是草稿，用户确认后才进入正式知识库。",
        ],
    }
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是 Prism 的知识沉淀编辑器。输出严格 JSON，不要 Markdown 包裹。"},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=2400,
        )
        return _parse_json_object(resp.choices[0].message.content or "")
    except Exception:
        return None


def _normalize_knowledge_draft(
    assets: list[Any],
    parsed: dict[str, Any] | None,
    *,
    title: str = "",
    instruction: str = "",
) -> dict[str, Any]:
    fallback = _fallback_knowledge_draft(assets, title=title, instruction=instruction)
    data = parsed if isinstance(parsed, dict) else fallback
    return {
        "title": _short_title(str(data.get("title") or fallback["title"]), "知识草稿"),
        "summary": str(data.get("summary") or fallback["summary"]).strip()[:1200],
        "content": str(data.get("content") or fallback["content"]).strip(),
        "category": str(data.get("category") or fallback["category"]).strip()[:128],
        "tags": _clean_tags(data.get("tags")) or fallback["tags"],
        "outline": _clean_dict_list(data.get("outline")) or fallback["outline"],
        "confidence": data.get("confidence") if isinstance(data.get("confidence"), dict) else fallback["confidence"],
        "rationale": str(data.get("rationale") or fallback["rationale"]).strip()[:1200],
    }


def _item_body(item: PersonalAssetItem) -> str:
    extract_text = "\n".join(str(entry.get("content", "")) for entry in (item.extracts or []) if isinstance(entry, dict))
    return item.body or extract_text or item.summary or item.raw_text


def _item_result(item: PersonalAssetItem, score: float) -> AssetSearchResult:
    return AssetSearchResult(
        asset_id=item.id,
        asset_kind=item.asset_kind,
        title=item.title,
        summary=item.summary,
        source_type=item.source_type,
        source_platform=item.source_platform,
        tags=item.tags or [],
        category=item.category,
        score=score,
    )


def _create_asset_item_from_raw(
    *,
    db: Session,
    raw_text: str,
    raw_title: str = "",
    raw_source_type: str = "manual",
    raw_source_platform: str = "",
    raw_source_url: str = "",
    raw_author: str = "",
    raw_tags: list[str] | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> PersonalAssetItem:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail={"code": "empty_content", "message": "Content is required"})

    parsed = _ai_parse_asset(
        content=raw_text,
        title=raw_title,
        source_type=raw_source_type,
        source_platform=raw_source_platform,
        source_url=raw_source_url,
    )
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
        user_id=DEFAULT_USER_ID,
        raw_text=raw_text,
        raw_title=(raw_title or "")[:255],
        raw_source_type=(raw_source_type or "manual")[:64],
        raw_source_platform=(raw_source_platform or "")[:128],
        raw_source_url=(raw_source_url or "")[:1000],
        raw_author=(raw_author or "")[:255],
        raw_tags=raw_tags,
        raw_metadata=raw_metadata or {},
        raw_keywords=keywords,
        keyword_index_text=_keyword_index_text(raw_title, raw_text, raw_tags, keywords, data["title"], data["summary"], data["tags"], data["category"]),
        raw_embedding_status="pending",
        title=data["title"],
        summary=data["summary"],
        body=raw_text,
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


@router.post("/items", response_model=PersonalAssetItemOut)
def create_asset_item(payload: PersonalAssetItemCreate, db: Session = Depends(get_db)):
    return _create_asset_item_from_raw(
        db=db,
        raw_text=payload.raw_text,
        raw_title=payload.raw_title or "",
        raw_source_type=payload.raw_source_type,
        raw_source_platform=payload.raw_source_platform or "",
        raw_source_url=payload.raw_source_url or "",
        raw_author=payload.raw_author or "",
        raw_tags=payload.raw_tags,
        raw_metadata=payload.raw_metadata,
    )


@router.get("/items", response_model=list[PersonalAssetItemOut])
def list_asset_items(status: Optional[str] = Query("pending_review"), db: Session = Depends(get_db)):
    query = db.query(PersonalAssetItem).filter(PersonalAssetItem.user_id == DEFAULT_USER_ID)
    if status:
        query = query.filter(PersonalAssetItem.status == status)
    return query.order_by(PersonalAssetItem.updated_at.desc()).all()


@router.put("/items/{item_id}", response_model=PersonalAssetItemOut)
def update_asset_item(item_id: str, payload: PersonalAssetItemUpdate, db: Session = Depends(get_db)):
    item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id, PersonalAssetItem.user_id == DEFAULT_USER_ID).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status not in {"pending_review", "confirmed"}:
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Personal asset item cannot be edited"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if key in {"tags", "raw_tags", "raw_keywords"}:
            value = _clean_tags(value)
        elif key in {"extracts", "suggested_relations", "suggested_extensions"}:
            value = _clean_dict_list(value)
        setattr(item, key, value)
    item.edited_at = datetime.utcnow()
    item.keyword_index_text = _keyword_index_text(
        item.raw_title,
        item.raw_text,
        item.raw_tags,
        item.raw_keywords,
        item.title,
        item.summary,
        item.body,
        item.tags,
        item.category,
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/items/{item_id}/confirm", response_model=AssetConfirmResponse)
def confirm_asset_item(item_id: str, payload: AssetConfirmRequest, db: Session = Depends(get_db)):
    item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id, PersonalAssetItem.user_id == DEFAULT_USER_ID).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status != "pending_review":
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Personal asset item is already closed"})

    relation_count = 0
    for relation in payload.confirm_relations:
        target_id = str(relation.get("target_asset_id") or relation.get("to_asset_id") or "")
        if not target_id:
            continue
        target = db.query(PersonalAssetItem.id).filter(PersonalAssetItem.id == target_id, PersonalAssetItem.user_id == DEFAULT_USER_ID).first()
        if not target:
            continue
        db.add(
            AssetRelation(
                user_id=DEFAULT_USER_ID,
                from_asset_id=item.id,
                to_asset_id=target_id,
                relation_type=str(relation.get("relation_type") or "related")[:64],
                reason=str(relation.get("reason") or "")[:1000],
                confidence=float(relation.get("confidence") or 0.5),
                source_draft_id=item.id,
            )
        )
        relation_count += 1

    extension_count = 0
    for extension in payload.confirm_extensions:
        title = str(extension.get("title") or "").strip()
        if not title:
            continue
        db.add(
            ExtensionPoint(
                user_id=DEFAULT_USER_ID,
                asset_id=item.id,
                title=title[:255],
                reason=str(extension.get("reason") or "")[:1000],
                suggested_kind=str(extension.get("suggested_kind") or "knowledge")[:64],
                confidence=float(extension.get("confidence") or 0.5),
            )
        )
        extension_count += 1

    if payload.create_memory:
        db.add(
            MemoryEntry(
                user_id=DEFAULT_USER_ID,
                title=item.title,
                content=item.summary or item.raw_text,
                memory_type="context",
                category=item.category,
                tags=item.tags or [],
                importance=max(0.6, float((item.confidence or {}).get("overall", 0.6) or 0.6)),
                source_raw_item_id=item.id,
                source_review_id=item.id,
            )
        )

    item.status = "confirmed"
    item.reviewed_at = datetime.utcnow()
    item.confirmed_at = item.reviewed_at
    governance = settle_personal_asset_item_to_governance(db, item)
    db.commit()
    db.refresh(item)
    return AssetConfirmResponse(
        item=item,
        draft=item,
        asset=item,
        relation_count=relation_count,
        extension_count=extension_count,
        pku_count=governance.pku_count,
        canonical_count=governance.canonical_count,
        governance_link_count=governance.link_count,
    )


@router.post("/drafts", response_model=AssetDraftOut)
def create_draft(payload: AssetDraftCreate, db: Session = Depends(get_db)):
    raw: InboxRawItem | None = None
    if payload.raw_item_id:
        raw = (
            db.query(InboxRawItem)
            .filter(InboxRawItem.id == payload.raw_item_id, InboxRawItem.user_id == DEFAULT_USER_ID)
            .first()
        )
        if not raw:
            raise HTTPException(status_code=404, detail={"code": "raw_item_not_found", "message": "Raw item not found"})

    content = (payload.content or (raw.content if raw else "") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail={"code": "empty_content", "message": "Content is required"})

    title = (payload.title or (raw.title if raw else "") or "").strip()
    source_type = payload.source_type or (raw.source_type if raw else "manual")
    source_platform = (payload.source_platform or (raw.source_platform if raw else "") or "").strip()
    source_url = (payload.source_url or (raw.source_url if raw else "") or "").strip()

    return _create_asset_item_from_raw(
        db=db,
        raw_text=content,
        raw_title=title,
        raw_source_type=source_type,
        raw_source_platform=source_platform,
        raw_source_url=source_url,
        raw_metadata={"legacy_raw_item_id": raw.id if raw else ""},
    )


@router.get("/drafts", response_model=list[AssetDraftOut])
def list_drafts(status: Optional[str] = Query("pending"), db: Session = Depends(get_db)):
    mapped_status = "pending_review" if status in {"pending", "pending_review"} else status
    return list_asset_items(status=mapped_status, db=db)


@router.put("/drafts/{draft_id}", response_model=AssetDraftOut)
def update_draft(draft_id: str, payload: AssetDraftUpdate, db: Session = Depends(get_db)):
    return update_asset_item(draft_id, PersonalAssetItemUpdate(**payload.model_dump(exclude_unset=True)), db)


@router.post("/drafts/{draft_id}/confirm", response_model=AssetConfirmResponse)
def confirm_draft(draft_id: str, payload: AssetConfirmRequest, db: Session = Depends(get_db)):
    return confirm_asset_item(draft_id, payload, db)


@router.post("/knowledge-drafts", response_model=KnowledgeDraftOut)
def create_knowledge_draft(payload: KnowledgeDraftCreate, db: Session = Depends(get_db)):
    asset_ids = list(dict.fromkeys(payload.asset_ids))
    assets = (
        db.query(PersonalAssetItem)
        .filter(
            PersonalAssetItem.user_id == DEFAULT_USER_ID,
            PersonalAssetItem.status == "confirmed",
            PersonalAssetItem.id.in_(asset_ids),
        )
        .all()
    )
    found_ids = {asset.id for asset in assets}
    missing = [asset_id for asset_id in asset_ids if asset_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "asset_not_found", "message": "Some assets were not found", "asset_ids": missing},
        )

    parsed = _ai_synthesize_knowledge(
        assets,
        title=payload.title or "",
        instruction=payload.instruction or "",
    )
    data = _normalize_knowledge_draft(
        assets,
        parsed,
        title=payload.title or "",
        instruction=payload.instruction or "",
    )
    draft = KnowledgeDraft(
        user_id=DEFAULT_USER_ID,
        source_asset_ids=asset_ids,
        **data,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/knowledge-drafts", response_model=list[KnowledgeDraftOut])
def list_knowledge_drafts(status: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(KnowledgeDraft).filter(KnowledgeDraft.user_id == DEFAULT_USER_ID)
    if status:
        query = query.filter(KnowledgeDraft.status == status)
    return query.order_by(KnowledgeDraft.updated_at.desc()).all()


@router.get("/knowledge-drafts/{draft_id}", response_model=KnowledgeDraftOut)
def get_knowledge_draft(draft_id: str, db: Session = Depends(get_db)):
    draft = db.query(KnowledgeDraft).filter(
        KnowledgeDraft.id == draft_id,
        KnowledgeDraft.user_id == DEFAULT_USER_ID,
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail={"code": "knowledge_draft_not_found", "message": "Knowledge draft not found"})
    return draft


@router.put("/knowledge-drafts/{draft_id}", response_model=KnowledgeDraftOut)
def update_knowledge_draft(draft_id: str, payload: KnowledgeDraftUpdate, db: Session = Depends(get_db)):
    draft = db.query(KnowledgeDraft).filter(KnowledgeDraft.id == draft_id, KnowledgeDraft.user_id == DEFAULT_USER_ID).first()
    if not draft:
        raise HTTPException(status_code=404, detail={"code": "knowledge_draft_not_found", "message": "Knowledge draft not found"})
    if draft.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "knowledge_draft_closed", "message": "Knowledge draft is already closed"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if key == "tags":
            value = _clean_tags(value)
        elif key == "outline":
            value = _clean_dict_list(value)
        setattr(draft, key, value)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/knowledge-drafts/{draft_id}/confirm", response_model=KnowledgeDraftConfirmResponse)
def confirm_knowledge_draft(draft_id: str, payload: KnowledgeDraftConfirmRequest, db: Session = Depends(get_db)):
    draft = db.query(KnowledgeDraft).filter(KnowledgeDraft.id == draft_id, KnowledgeDraft.user_id == DEFAULT_USER_ID).first()
    if not draft:
        raise HTTPException(status_code=404, detail={"code": "knowledge_draft_not_found", "message": "Knowledge draft not found"})
    if draft.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "knowledge_draft_closed", "message": "Knowledge draft is already closed"})

    item = KnowledgeItem(
        title=draft.title,
        content=draft.content,
        summary=draft.summary,
        source_type="asset_synthesis",
        source_ref=draft.id,
        tags=draft.tags or [],
        category=draft.category,
        user_id=DEFAULT_USER_ID,
    )
    db.add(item)
    db.flush()
    draft.status = "confirmed"
    draft.knowledge_item_id = item.id
    db.commit()
    db.refresh(draft)

    if payload.ingest:
        _trigger_ingestion(item.id)

    return KnowledgeDraftConfirmResponse(draft=draft, knowledge_item_id=item.id)


@router.get("", response_model=list[PersonalAssetOut])
def list_assets(db: Session = Depends(get_db)):
    return (
        db.query(PersonalAssetItem)
        .filter(PersonalAssetItem.user_id == DEFAULT_USER_ID, PersonalAssetItem.status == "confirmed")
        .order_by(PersonalAssetItem.updated_at.desc())
        .all()
    )


@router.get("/search", response_model=list[AssetSearchResult])
def search_assets(q: str = Query(""), limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    q_norm = q.strip()
    query = db.query(PersonalAssetItem).filter(PersonalAssetItem.user_id == DEFAULT_USER_ID, PersonalAssetItem.status == "confirmed")
    if q_norm:
        like = f"%{q_norm}%"
        query = query.filter(
            or_(
                PersonalAssetItem.title.like(like),
                PersonalAssetItem.summary.like(like),
                PersonalAssetItem.body.like(like),
                PersonalAssetItem.raw_text.like(like),
                PersonalAssetItem.keyword_index_text.like(like),
                PersonalAssetItem.category.like(like),
                PersonalAssetItem.source_platform.like(like),
            )
        )
    assets = query.order_by(PersonalAssetItem.importance.desc(), PersonalAssetItem.updated_at.desc()).limit(limit).all()
    return [_item_result(asset, 1.0 if q_norm else float(asset.importance or 0.5)) for asset in assets]


@router.get("/overview", response_model=AssetOverviewOut)
def overview_assets(q: str = Query(""), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    results = search_assets(q=q, limit=limit, db=db)
    category_counts = Counter(item.category or "未分类" for item in results)
    tag_counts: Counter[str] = Counter()
    for item in results:
        tag_counts.update(item.tags or [])
    categories = [{"name": name, "count": count} for name, count in category_counts.most_common(8)]
    tags = [{"name": name, "count": count} for name, count in tag_counts.most_common(12)]
    if results:
        leading = "、".join(item["name"] for item in categories[:4])
        summary = f"共找到 {len(results)} 条已确认知识资产，主要集中在：{leading}。"
    else:
        summary = "未找到匹配的已确认知识资产。"
    return AssetOverviewOut(
        summary=summary,
        categories=categories,
        tags=tags,
        representative_assets=results[:8],
    )
