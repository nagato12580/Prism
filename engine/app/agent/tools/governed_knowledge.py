from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.asset import PersonalAssetItem, PersonalAssetUnit
from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.config import settings


KEY = "governed_knowledge_search"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

_STOP_WORDS = {
    "and",
    "or",
    "the",
    "with",
    "about",
    "for",
    "我的",
    "之前",
    "保存",
    "资料",
    "内容",
    "相关",
    "关于",
    "有没有",
    "是什么",
}

_DOMAIN_PHRASES = [
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
    "canonical_statement": 4.0,
    "summary": 2.0,
    "aliases": 2.5,
    "domains": 2.0,
    "concepts": 3.0,
    "keywords": 3.0,
    "pku": 2.0,
}

_KNOWLEDGE_FIELD_WEIGHTS = {
    "title": 5.0,
    "summary": 3.0,
    "content": 2.0,
    "category": 2.0,
    "tags": 3.0,
    "outline": 1.5,
}


class GovernedKnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Natural-language query for governed personal knowledge.")
    limit: int = Field(8, ge=1, le=20, description="Maximum number of canonical knowledge points to return.")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_normalize_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_normalize_text(item) for item in value.values())
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
    compact = re.sub(r"\s+", "", query or "").lower()
    for phrase in _DOMAIN_PHRASES:
        if phrase in compact:
            _append_term(terms, phrase)
    for raw in re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]+", normalized):
        raw = raw.lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw) and len(raw) > 6:
            for size in (4, 3, 2):
                for index in range(0, max(len(raw) - size + 1, 0)):
                    _append_term(terms, raw[index : index + size])
                    if len(terms) >= 16:
                        return terms
        else:
            _append_term(terms, raw)
    return terms[:16]


def _canonical_fields(ckp: CanonicalKnowledgePoint, pku_text: str = "") -> dict[str, str]:
    return {
        "title": _normalize_text(ckp.title),
        "canonical_statement": _normalize_text(ckp.canonical_statement),
        "summary": _normalize_text(ckp.summary),
        "aliases": _normalize_text(ckp.aliases or []),
        "domains": _normalize_text(ckp.domains or []),
        "concepts": _normalize_text(ckp.concepts or []),
        "keywords": _normalize_text(ckp.keywords or []),
        "pku": _normalize_text(pku_text),
    }


def _score_canonical(ckp: CanonicalKnowledgePoint, terms: list[str], pku_text: str = "") -> tuple[float, list[str], list[str]]:
    if not terms:
        return float(ckp.confidence or 0.5), [], ["no query terms; ranked by confidence and recency"]

    fields = _canonical_fields(ckp, pku_text)
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
        score += coverage * 4.0
        score += min(float(ckp.confidence or 0.0), 1.0)
    return round(score, 4), matched_terms, reasons[:8]


def _score_fields(fields: dict[str, str], terms: list[str], weights: dict[str, float]) -> tuple[float, list[str], list[str]]:
    matched_terms: list[str] = []
    reasons: list[str] = []
    score = 0.0
    for term in terms:
        matched_fields: list[str] = []
        term_score = 0.0
        for field, text in fields.items():
            if term in text:
                matched_fields.append(field)
                term_score += weights.get(field, 1.0)
        if matched_fields:
            matched_terms.append(term)
            score += term_score
            reasons.append(f"{term} matched {', '.join(matched_fields)}")
    if matched_terms:
        score += len(matched_terms) / max(len(terms), 1) * 3.0
    return round(score, 4), matched_terms, reasons[:8]


def _personal_asset_unit_fields(unit: PersonalAssetUnit) -> dict[str, str]:
    return {
        "title": _normalize_text(unit.title),
        "summary": _normalize_text(unit.summary),
        "content": _normalize_text(unit.content),
        "category": _normalize_text(unit.category),
        "tags": _normalize_text(unit.tags or []),
        "outline": _normalize_text(unit.outline or []),
    }


def _knowledge_item_fields(item: KnowledgeItem) -> dict[str, str]:
    return {
        "title": _normalize_text(item.title),
        "summary": _normalize_text(item.summary),
        "content": _normalize_text(item.content),
        "category": _normalize_text(item.category),
        "tags": _normalize_text(item.tags or []),
        "outline": "",
    }


def _personal_asset_unit_result(unit: PersonalAssetUnit, score: float, matched_terms: list[str], reasons: list[str]) -> dict[str, Any]:
    return {
        "source_kind": "personal_asset_unit",
        "ref_type": "personal_asset_unit",
        "ref_id": unit.id,
        "personal_asset_unit_id": unit.id,
        "title": unit.title,
        "summary": unit.summary,
        "text": unit.content,
        "category": unit.category,
        "tags": unit.tags or [],
        "status": unit.status,
        "source_asset_ids": unit.source_asset_ids or [],
        "score": score,
        "matched_terms": matched_terms,
        "match_reasons": reasons,
    }


def _knowledge_item_result(item: KnowledgeItem, score: float, matched_terms: list[str], reasons: list[str]) -> dict[str, Any]:
    return {
        "source_kind": "knowledge_item",
        "ref_type": "knowledge_item",
        "ref_id": item.id,
        "knowledge_item_id": item.id,
        "title": item.title,
        "summary": item.summary,
        "text": item.content,
        "category": item.category,
        "tags": item.tags or [],
        "status": item.status,
        "source_type": item.source_type,
        "source_ref": item.source_ref,
        "score": score,
        "matched_terms": matched_terms,
        "match_reasons": reasons,
    }


def _source_for_pku(db, pku: PersonalKnowledgeUnit) -> dict[str, Any] | None:
    if pku.source_kind == "personal_asset_item":
        asset = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == pku.source_id).first()
        if not asset:
            return None
        return {
            "source_kind": "personal_asset_item",
            "source_id": asset.id,
            "ref_type": "personal_asset",
            "ref_id": asset.id,
            "asset_id": asset.id,
            "title": asset.title,
            "text": asset.summary or asset.body or asset.raw_text,
            "source_type": asset.source_type,
            "source_platform": asset.source_platform,
            "category": asset.category,
            "tags": asset.tags or [],
        }

    if pku.source_kind == "personal_asset_unit":
        unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == pku.source_id).first()
        if not unit:
            return None
        return {
            "source_kind": "personal_asset_unit",
            "source_id": unit.id,
            "ref_type": "personal_asset_unit",
            "ref_id": unit.id,
            "personal_asset_unit_id": unit.id,
            "title": unit.title,
            "text": unit.summary or unit.content,
            "category": unit.category,
            "tags": unit.tags or [],
            "source_asset_ids": unit.source_asset_ids or [],
        }

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if not chunk:
            return None
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
        return {
            "source_kind": "document_chunk",
            "source_id": chunk.id,
            "ref_type": "knowledge_chunk",
            "ref_id": chunk.id,
            "chunk_id": chunk.id,
            "item_id": chunk.item_id,
            "title": item.title if item else "",
            "text": chunk.chunk_text,
            "chunk_type": chunk.chunk_type,
            "category": item.category if item else "",
            "tags": item.tags if item else [],
        }
    return None


def _canonical_to_result(ckp: CanonicalKnowledgePoint, score: float, matched_terms: list[str], reasons: list[str]) -> dict[str, Any]:
    return {
        "canonical_id": ckp.id,
        "canonical_type": ckp.canonical_type,
        "title": ckp.title,
        "canonical_statement": ckp.canonical_statement,
        "summary": ckp.summary,
        "status": ckp.status,
        "confidence": ckp.confidence,
        "score": score,
        "matched_terms": matched_terms,
        "match_reasons": reasons,
    }


def _build_evidence_bundle(db, ckp: CanonicalKnowledgePoint, score: float, matched_terms: list[str], reasons: list[str]) -> dict[str, Any]:
    links = (
        db.query(PKUCanonicalLink)
        .filter(PKUCanonicalLink.canonical_id == ckp.id)
        .order_by(PKUCanonicalLink.confidence.desc(), PKUCanonicalLink.created_at.desc())
        .limit(12)
        .all()
    )
    linked_pkus: list[dict[str, Any]] = []
    raw_sources: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str]] = set()
    for link in links:
        pku = link.pku
        if not pku or pku.status != "active":
            continue
        linked_pkus.append(
            {
                "pku_id": pku.id,
                "statement": pku.statement,
                "normalized_statement": pku.normalized_statement,
                "unit_type": pku.unit_type,
                "modality": pku.modality,
                "source_kind": pku.source_kind,
                "source_id": pku.source_id,
                "relation_type": link.relation_type,
                "role": link.role,
                "confidence": link.confidence,
                "evidence_span": pku.evidence_span,
            }
        )
        source = _source_for_pku(db, pku)
        if source:
            source_key = (source["source_kind"], source["source_id"])
            if source_key not in seen_sources:
                raw_sources.append(source)
                seen_sources.add(source_key)

    return {
        **_canonical_to_result(ckp, score, matched_terms, reasons),
        "linked_pkus": linked_pkus,
        "raw_sources": raw_sources,
    }


def _query_governed_knowledge(query: str, limit: int) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    terms = _query_terms(query)
    db = _Session()
    try:
        ckp_rows = (
            db.query(CanonicalKnowledgePoint)
            .filter(CanonicalKnowledgePoint.user_id == "default-user", CanonicalKnowledgePoint.status != "deprecated")
            .order_by(CanonicalKnowledgePoint.updated_at.desc())
            .limit(max(limit * 8, 80))
            .all()
        )
        ckp_ids = [row.id for row in ckp_rows]
        pku_text_by_ckp: dict[str, str] = {ckp_id: "" for ckp_id in ckp_ids}
        if ckp_ids:
            links = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.canonical_id.in_(ckp_ids)).all()
            for link in links:
                if link.pku and link.pku.status == "active":
                    pku_text_by_ckp[link.canonical_id] = f"{pku_text_by_ckp.get(link.canonical_id, '')} {link.pku.statement}"

        scored: list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]] = []
        for ckp in ckp_rows:
            score, matched_terms, reasons = _score_canonical(ckp, terms, pku_text_by_ckp.get(ckp.id, ""))
            if not terms or matched_terms:
                scored.append((ckp, score, matched_terms, reasons))
        scored.sort(key=lambda item: (item[1], item[0].confidence or 0.0, item[0].updated_at), reverse=True)
        bundles = [
            _build_evidence_bundle(db, ckp, score, matched_terms, reasons)
            for ckp, score, matched_terms, reasons in scored[:limit]
        ]

        knowledge_results: list[dict[str, Any]] = []
        unit_rows = (
            db.query(PersonalAssetUnit)
            .filter(PersonalAssetUnit.user_id == "default-user")
            .order_by(PersonalAssetUnit.updated_at.desc())
            .limit(max(limit * 8, 80))
            .all()
        )
        for unit in unit_rows:
            score, matched_terms, reasons = _score_fields(
                _personal_asset_unit_fields(unit),
                terms,
                _KNOWLEDGE_FIELD_WEIGHTS,
            )
            if not terms or matched_terms:
                knowledge_results.append(_personal_asset_unit_result(unit, score, matched_terms, reasons))

        knowledge_results.sort(key=lambda item: (float(item.get("score") or 0), item.get("title") or ""), reverse=True)
        return terms, bundles, knowledge_results[:limit]
    finally:
        db.close()


def _append_unique_citations(citations: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    seen = {
        (
            str(citation.get("source_kind") or citation.get("ref_type") or ""),
            str(citation.get("source_id") or citation.get("ref_id") or citation.get("chunk_id") or citation.get("asset_id") or ""),
        )
        for citation in citations
    }
    for source in sources:
        key = (
            str(source.get("source_kind") or source.get("ref_type") or ""),
            str(source.get("source_id") or source.get("ref_id") or source.get("chunk_id") or source.get("asset_id") or ""),
        )
        if key not in seen:
            citations.append(source)
            seen.add(key)


def _build_governed_knowledge_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 8) -> str:
        terms, bundles, knowledge_results = _query_governed_knowledge(query, limit)
        raw_sources: list[dict[str, Any]] = []
        for bundle in bundles:
            raw_sources.extend(bundle["raw_sources"])
        raw_sources.extend(knowledge_results)
        _append_unique_citations(ctx.citations, raw_sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(bundles),
            "knowledge_hit_count": len(knowledge_results),
            "source_count": len(raw_sources),
            "query_terms": terms,
        }
        status = "success" if bundles or knowledge_results else "insufficient"
        summary = (
            f"Found {len(bundles)} governed knowledge points and {len(knowledge_results)} synthesized knowledge items with {len(raw_sources)} evidence items."
            if bundles or knowledge_results
            else "No governed knowledge points or synthesized knowledge items matched the query."
        )
        return json.dumps(
            {
                "status": status,
                "summary": summary,
                "query_terms": terms,
                "canonical_results": [
                    {key: value for key, value in bundle.items() if key not in {"linked_pkus", "raw_sources"}}
                    for bundle in bundles
                ],
                "knowledge_results": knowledge_results,
                "evidence_bundle": bundles,
                "source_results": raw_sources,
                "sources": raw_sources,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Search Prism's governed personal knowledge layer. It searches canonical knowledge points first, "
            "then returns linked personal knowledge units and raw evidence from uploaded document chunks and "
            "confirmed personal assets. Use when the user asks for stable conclusions, relationships between "
            "their saved knowledge and documents, evidence-backed personal knowledge, or cross-source synthesis."
        ),
        args_schema=GovernedKnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Search governed canonical knowledge with PKU and source backtracking.",
        builder=_build_governed_knowledge_search,
        default_enabled=True,
    )
)
