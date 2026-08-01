from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.asset import AssetRelation, PersonalAssetItem
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.config import settings


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

_STOP_WORDS = {
    "and",
    "or",
    "the",
    "with",
    "about",
    "for",
    "方案",
    "经验",
    "相关",
    "关于",
    "我的",
    "是否",
    "有没有",
    "资料",
    "内容",
}

_DOMAIN_PHRASES = [
    "ui自动化",
    "自动化测试",
    "提示词优化",
    "提示词",
    "ai测试",
    "ai辅助",
    "自动化",
    "测试",
    "个人知识库",
    "知识库",
    "知识治理",
    "知识图谱",
    "图谱设计",
    "图谱",
    "检索",
    "搜索",
    "召回",
    "设计原则",
    "原则",
    "ckp",
    "pku",
    "rag",
    "metadata",
    "filter",
]

_FIELD_WEIGHTS = {
    "title": 5.0,
    "tags": 4.0,
    "category": 3.0,
    "summary": 2.0,
    "rewritten_content": 1.5,
    "body": 1.0,
    "raw_text": 1.0,
    "raw_keywords": 2.5,
    "keyword_index_text": 1.5,
    "asset_kind": 0.8,
    "source_platform": 0.5,
}


class AssetSearchInput(BaseModel):
    query: str = Field(..., description="Natural-language query for confirmed personal assets.")
    limit: int = Field(10, ge=1, le=30, description="Maximum number of assets to return.")


class AssetOverviewInput(BaseModel):
    query: str = Field("", description="Optional topic or filter for the overview.")
    limit: int = Field(50, ge=1, le=100, description="Maximum number of assets to inspect.")


class AssetRelatedInput(BaseModel):
    query: str = Field(..., description="Content, idea, or topic to relate to confirmed assets.")
    asset_id: str | None = Field(None, description="Optional existing asset id as the relation anchor.")
    limit: int = Field(10, ge=1, le=30, description="Maximum number of related assets to return.")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_normalize_text(item) for item in value)
    return str(value).lower()


def _append_term(terms: list[str], term: str) -> None:
    term = term.strip().strip("._-").lower()
    if len(term) < 2 or term in _STOP_WORDS:
        return
    if term not in terms:
        terms.append(term)


def _query_terms(query: str) -> list[str]:
    normalized = re.sub(r"([A-Za-z0-9+#.-]+)([\u4e00-\u9fff])", r"\1 \2", query or "")
    normalized = re.sub(r"([\u4e00-\u9fff])([A-Za-z0-9+#.-]+)", r"\1 \2", normalized)
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]+", normalized):
        raw = raw.lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw) and len(raw) > 6:
            for phrase in _DOMAIN_PHRASES:
                if phrase in raw:
                    _append_term(terms, phrase)
            for size in (4, 3, 2):
                for index in range(0, max(len(raw) - size + 1, 0)):
                    _append_term(terms, raw[index : index + size])
                    if len(terms) >= 12:
                        return terms
        else:
            _append_term(terms, raw)

    compact = re.sub(r"\s+", "", query or "").lower()
    for phrase in _DOMAIN_PHRASES:
        if phrase in compact:
            _append_term(terms, phrase)
    return terms[:12]


def _asset_fields(asset: PersonalAsset) -> dict[str, str]:
    return {
        "title": _normalize_text(asset.title),
        "tags": _normalize_text(asset.tags or []),
        "category": _normalize_text(asset.category),
        "summary": _normalize_text(asset.summary),
        "rewritten_content": _normalize_text(asset.rewritten_content),
        "body": _normalize_text(asset.body),
        "raw_text": _normalize_text(asset.raw_text),
        "raw_keywords": _normalize_text(asset.raw_keywords or []),
        "keyword_index_text": _normalize_text(asset.keyword_index_text),
        "asset_kind": _normalize_text(asset.asset_kind),
        "source_platform": _normalize_text(asset.source_platform),
    }


def _score_asset(asset: PersonalAssetItem, terms: list[str]) -> tuple[float, list[str], list[str]]:
    if not terms:
        return float(asset.importance or 0.5), [], ["no query terms; ranked by importance and recency"]

    fields = _asset_fields(asset)
    matched_terms: list[str] = []
    reasons: list[str] = []
    score = 0.0
    for term in terms:
        matched_fields: list[str] = []
        term_score = 0.0
        for field, text in fields.items():
            if term in text:
                matched_fields.append(field)
                term_score += _FIELD_WEIGHTS[field]
        if matched_fields:
            matched_terms.append(term)
            score += term_score
            reasons.append(f"{term} matched {', '.join(matched_fields)}")

    if matched_terms:
        coverage = len(matched_terms) / max(len(terms), 1)
        score += coverage * 3.0
        score += min(float(asset.importance or 0.0), 1.0)
    return round(score, 4), matched_terms, reasons[:8]


def _asset_to_source(
    asset: PersonalAssetItem,
    score: float,
    matched_terms: list[str] | None = None,
    match_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "asset_id": asset.id,
        "ref_type": "personal_asset",
        "ref_id": asset.id,
        "asset_kind": asset.asset_kind,
        "title": asset.title,
        "summary": asset.summary,
        "rewritten_content": asset.rewritten_content,
        "source_type": asset.source_type,
        "source_platform": asset.source_platform,
        "tags": asset.tags or [],
        "category": asset.category,
        "score": score,
        "matched_terms": matched_terms or [],
        "match_reasons": match_reasons or [],
    }


def _query_assets(query: str, limit: int) -> list[tuple[PersonalAssetItem, float, list[str], list[str]]]:
    terms = _query_terms(query)
    db = _Session()
    try:
        stmt = db.query(PersonalAssetItem).filter(
            PersonalAssetItem.user_id == "default-user",
            PersonalAssetItem.status == "confirmed",
        )
        candidates = stmt.order_by(PersonalAssetItem.updated_at.desc()).limit(max(limit * 8, 80)).all()
        scored: list[tuple[PersonalAssetItem, float, list[str], list[str]]] = []
        for asset in candidates:
            score, matched_terms, reasons = _score_asset(asset, terms)
            if not terms or matched_terms:
                scored.append((asset, score, matched_terms, reasons))
        scored.sort(key=lambda item: (item[1], item[0].importance or 0.0, item[0].updated_at), reverse=True)
        return scored[:limit]
    finally:
        db.close()


def _build_asset_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 10) -> str:
        terms = _query_terms(query)
        matches = _query_assets(query, limit)
        sources = [_asset_to_source(asset, score, matched_terms, reasons) for asset, score, matched_terms, reasons in matches]
        ctx.citations.extend(sources)
        ctx.stats_holder["asset_search"] = {"hit_count": len(sources), "query_terms": terms}
        explanation = (
            f"Search terms: {', '.join(terms)}. Results are ranked by weighted matches in title, tags, "
            "category, summary, and body."
            if terms
            else "No effective search terms; results are ranked by importance and recency."
        )
        return json.dumps(
            {
                "status": "success" if sources else "insufficient",
                "summary": f"Found {len(sources)} confirmed personal assets." if sources else "No matching confirmed personal assets were found.",
                "query_terms": terms,
                "explanation": explanation,
                "sources": sources,
                "assets": sources,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=run,
        name="asset_search",
        description=(
            "Search confirmed personal knowledge assets such as saved knowledge, notes, opinions, "
            "resources, and Inbox-settled content. Uses multi-term recall and explains matched terms. "
            "Use when the user asks about saved materials, past notes, collected opinions, resources, "
            "or personal knowledge assets."
        ),
        args_schema=AssetSearchInput,
    )


def _build_asset_overview(ctx: ToolContext) -> StructuredTool:
    def run(query: str = "", limit: int = 50) -> str:
        matches = _query_assets(query, limit)
        assets = [asset for asset, _, _, _ in matches]
        category_counts = Counter(asset.category or "uncategorized" for asset in assets)
        tag_counts: Counter[str] = Counter()
        for asset in assets:
            tag_counts.update(asset.tags or [])
        categories = [{"name": name, "count": count} for name, count in category_counts.most_common(8)]
        tags = [{"name": name, "count": count} for name, count in tag_counts.most_common(12)]
        sources = [
            _asset_to_source(asset, score, matched_terms, reasons)
            for asset, score, matched_terms, reasons in matches[:8]
        ]
        ctx.citations.extend(sources)
        ctx.stats_holder["asset_overview"] = {"hit_count": len(assets), "query_terms": _query_terms(query)}
        leading = ", ".join(item["name"] for item in categories[:4])
        summary = (
            f"Found {len(assets)} confirmed personal assets, mainly in: {leading}."
            if assets
            else "No confirmed personal assets were available for overview."
        )
        return json.dumps(
            {
                "status": "success" if assets else "insufficient",
                "summary": summary,
                "categories": categories,
                "tags": tags,
                "sources": sources,
                "representative_assets": sources,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=run,
        name="asset_overview",
        description=(
            "Summarize and group confirmed personal assets by topic, category, and tags. "
            "Use for questions like what saved comments are about, recent collection themes, "
            "or how a user's personal assets are distributed."
        ),
        args_schema=AssetOverviewInput,
    )


def _build_asset_related(ctx: ToolContext) -> StructuredTool:
    def run(query: str, asset_id: str | None = None, limit: int = 10) -> str:
        db = _Session()
        try:
            related_assets: list[PersonalAssetItem] = []
            if asset_id:
                relation_rows = (
                    db.query(AssetRelation)
                    .filter(
                        AssetRelation.user_id == "default-user",
                        AssetRelation.from_asset_id == asset_id,
                        AssetRelation.status == "confirmed",
                    )
                    .limit(limit)
                    .all()
                )
                target_ids = [row.to_asset_id for row in relation_rows]
                if target_ids:
                    related_assets.extend(
                        db.query(PersonalAssetItem)
                        .filter(PersonalAssetItem.id.in_(target_ids), PersonalAssetItem.status == "confirmed")
                        .all()
                    )

            remaining = max(0, limit - len(related_assets))
            if remaining:
                seen = {asset.id for asset in related_assets}
                for asset, _, _, _ in _query_assets(query, remaining):
                    if asset.id not in seen:
                        related_assets.append(asset)
                        seen.add(asset.id)

            terms = _query_terms(query)
            sources = []
            for asset in related_assets[:limit]:
                score, matched_terms, reasons = _score_asset(asset, terms)
                sources.append(_asset_to_source(asset, score, matched_terms, reasons))
            ctx.citations.extend(sources)
            ctx.stats_holder["asset_related"] = {"hit_count": len(sources), "query_terms": terms}
            return json.dumps(
                {
                    "status": "success" if sources else "insufficient",
                    "summary": f"Found {len(sources)} related personal assets." if sources else "No related personal assets were found.",
                    "sources": sources,
                    "related_assets": sources,
                },
                ensure_ascii=False,
            )
        finally:
            db.close()

    return StructuredTool.from_function(
        func=run,
        name="asset_related",
        description=(
            "Find confirmed assets related to an idea, topic, pasted content, or existing asset. "
            "Uses confirmed relations and weighted multi-term matching."
        ),
        args_schema=AssetRelatedInput,
    )


register_tool(
    ToolSpec(
        key="asset_search",
        name="asset_search",
        description="Search confirmed personal knowledge assets.",
        builder=_build_asset_search,
        default_enabled=False,
    )
)

register_tool(
    ToolSpec(
        key="asset_overview",
        name="asset_overview",
        description="Overview and group confirmed personal knowledge assets.",
        builder=_build_asset_overview,
        default_enabled=False,
    )
)

register_tool(
    ToolSpec(
        key="asset_related",
        name="asset_related",
        description="Find confirmed personal assets related to a topic or asset.",
        builder=_build_asset_related,
        default_enabled=False,
    )
)


class CaptureThoughtInput(BaseModel):
    text: str = Field(..., description="The thought/idea/opinion content to record.")
    title: str | None = Field(None, description="Optional short title.")


def _build_capture_thought(ctx: ToolContext) -> StructuredTool:
    def run(text: str, title: str | None = None) -> str:
        from backend.app.services.asset_items import create_asset_item_from_raw

        text = (text or "").strip()
        if not text:
            return json.dumps({"status": "error", "message": "没有可记录的内容。"}, ensure_ascii=False)
        db = _Session()
        try:
            item = create_asset_item_from_raw(
                db,
                raw_text=text,
                raw_title=title or "",
                raw_source_type="chat",
                raw_metadata={"entrypoint": "chat_capture"},
                parsed=None,
            )
        finally:
            db.close()
        ctx.stats_holder["capture_thought"] = {"item_id": item.id, "title": item.title}
        return json.dumps(
            {
                "status": "ok",
                "item_id": item.id,
                "title": item.title,
                "summary": f"已记录「{item.title}」，等待你在审核台确认入库。",
                "message": f"已记录「{item.title}」，等待你在审核台确认入库。",
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=run,
        name="capture_thought",
        description=(
            "Record a thought, idea, opinion, snippet, to-do, or resource the user explicitly asks to save. "
            "Creates a pending item that the user confirms later in the review station. "
            "Use when the user says things like '帮我记一下', '记下来', '收藏这个', '记录：...'."
        ),
        args_schema=CaptureThoughtInput,
    )


register_tool(
    ToolSpec(
        key="capture_thought",
        name="capture_thought",
        description="Record a thought/idea the user asks to save into the review station.",
        builder=_build_capture_thought,
        default_enabled=True,
    )
)
