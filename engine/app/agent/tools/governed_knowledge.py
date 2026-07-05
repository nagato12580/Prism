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
from backend.app.services.ckp_vectors import search_ckp_vectors
from backend.app.services.pku_vectors import search_pku_vectors
from engine.app.agent.tools.base import ToolContext
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

_GOVERNED_EVIDENCE_RRF_K = 60
_GOVERNED_EVIDENCE_VECTOR_WEIGHT = 0.45
_GOVERNED_EVIDENCE_LEXICAL_WEIGHT = 0.30
_GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT = 0.25
_GOVERNED_EVIDENCE_CANDIDATE_MIN = 50


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
    text = unit.summary or unit.content
    return {
        "source_kind": "personal_asset_unit",
        "ref_type": "personal_asset_unit",
        "ref_id": unit.id,
        "source_id": unit.id,
        "personal_asset_unit_id": unit.id,
        "display_type": "personal_asset_unit",
        "display_id": unit.id,
        "display_title": unit.title,
        "display_label": "知识单元",
        "snippet": text,
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
        text = asset.summary or asset.body or asset.raw_text
        return {
            "source_kind": "personal_asset_item",
            "source_id": asset.id,
            "ref_type": "personal_asset",
            "ref_id": asset.id,
            "asset_id": asset.id,
            "display_type": "personal_asset_item",
            "display_id": asset.id,
            "display_title": asset.title,
            "display_label": "来源碎片",
            "snippet": text,
            "title": asset.title,
            "text": text,
            "source_type": asset.source_type,
            "source_platform": asset.source_platform,
            "category": asset.category,
            "tags": asset.tags or [],
        }

    if pku.source_kind == "personal_asset_unit":
        unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == pku.source_id).first()
        if not unit:
            return None
        text = unit.summary or unit.content
        return {
            "source_kind": "personal_asset_unit",
            "source_id": unit.id,
            "ref_type": "personal_asset_unit",
            "ref_id": unit.id,
            "personal_asset_unit_id": unit.id,
            "display_type": "personal_asset_unit",
            "display_id": unit.id,
            "display_title": unit.title,
            "display_label": "知识单元",
            "snippet": text,
            "title": unit.title,
            "text": text,
            "category": unit.category,
            "tags": unit.tags or [],
            "source_asset_ids": unit.source_asset_ids or [],
        }

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if not chunk:
            return None
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
        title = item.title if item else ""
        return {
            "source_kind": "document_chunk",
            "source_id": chunk.id,
            "ref_type": "knowledge_chunk",
            "ref_id": chunk.id,
            "chunk_id": chunk.id,
            "item_id": chunk.item_id,
            "display_type": "knowledge_item",
            "display_id": chunk.item_id,
            "display_title": title,
            "display_label": "知识文档",
            "snippet": chunk.chunk_text,
            "title": title,
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


def _safe_search_ckp_vectors(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        return search_ckp_vectors(text=query, user_id="default-user", top_k=limit)
    except Exception:
        return []


def _safe_search_pku_vectors(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        return search_pku_vectors(text=query, user_id="default-user", top_k=limit)
    except Exception:
        return []


def _lexical_ckp_candidates(db, terms: list[str], limit: int) -> list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]]:
    ckp_rows = (
        db.query(CanonicalKnowledgePoint)
        .filter(CanonicalKnowledgePoint.user_id == "default-user", CanonicalKnowledgePoint.status != "deprecated")
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
    return scored[:limit]


def _fuse_ckp_candidates(
    db,
    *,
    vector_hits: list[dict[str, Any]],
    pku_vector_hits: list[dict[str, Any]],
    lexical_hits: list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]],
    limit: int,
) -> list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]]:
    ckp_ids = {str(hit.get("ckp_id") or "") for hit in vector_hits if hit.get("ckp_id")}
    ckp_ids.update(str(ckp.id) for ckp, _score, _terms, _reasons in lexical_hits)
    pku_ids = [str(hit.get("pku_id") or "") for hit in pku_vector_hits if hit.get("pku_id")]
    pku_vector_score_by_ckp_id: dict[str, float] = {}
    pku_vector_rank_by_ckp_id: dict[str, int] = {}
    if pku_ids:
        links = (
            db.query(PKUCanonicalLink)
            .filter(PKUCanonicalLink.pku_id.in_(pku_ids))
            .all()
        )
        pku_rank_by_id = {str(hit.get("pku_id")): rank for rank, hit in enumerate(pku_vector_hits)}
        pku_score_by_id = {
            str(hit.get("pku_id")): float(hit.get("score") or 0.0)
            for hit in pku_vector_hits
            if hit.get("pku_id")
        }
        for link in links:
            if not link.pku or link.pku.status != "active":
                continue
            ckp_id = str(link.canonical_id)
            pku_id = str(link.pku_id)
            ckp_ids.add(ckp_id)
            score = pku_score_by_id.get(pku_id, 0.0)
            rank = pku_rank_by_id.get(pku_id, len(pku_vector_hits))
            if score > pku_vector_score_by_ckp_id.get(ckp_id, -1.0):
                pku_vector_score_by_ckp_id[ckp_id] = score
                pku_vector_rank_by_ckp_id[ckp_id] = rank
    if not ckp_ids:
        return []

    ckps = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.id.in_(ckp_ids)).all()
    ckp_by_id = {str(ckp.id): ckp for ckp in ckps}
    fused: dict[str, dict[str, Any]] = {
        ckp_id: {"score": 0.0, "matched_terms": [], "reasons": []}
        for ckp_id in ckp_by_id
    }

    for rank, hit in enumerate(vector_hits):
        ckp_id = str(hit.get("ckp_id") or "")
        if ckp_id not in fused:
            continue
        vector_score = float(hit.get("score") or 0.0)
        fused[ckp_id]["score"] += _GOVERNED_EVIDENCE_VECTOR_WEIGHT / (_GOVERNED_EVIDENCE_RRF_K + rank + 1)
        fused[ckp_id]["score"] += min(max(vector_score, 0.0), 1.0) * 0.01
        fused[ckp_id]["reasons"].append(f"ckp_vector rank={rank + 1} score={vector_score:.4f}")

    for rank, (ckp, lexical_score, matched_terms, reasons) in enumerate(lexical_hits):
        ckp_id = str(ckp.id)
        if ckp_id not in fused:
            continue
        fused[ckp_id]["score"] += _GOVERNED_EVIDENCE_LEXICAL_WEIGHT / (_GOVERNED_EVIDENCE_RRF_K + rank + 1)
        fused[ckp_id]["score"] += min(max(float(lexical_score or 0.0), 0.0), 20.0) / 200.0
        fused[ckp_id]["matched_terms"] = list(dict.fromkeys([*fused[ckp_id]["matched_terms"], *matched_terms]))
        fused[ckp_id]["reasons"].extend(reasons)

    for ckp_id, pku_vector_score in pku_vector_score_by_ckp_id.items():
        if ckp_id not in fused:
            continue
        rank = pku_vector_rank_by_ckp_id.get(ckp_id, 0)
        fused[ckp_id]["score"] += _GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT / (_GOVERNED_EVIDENCE_RRF_K + rank + 1)
        fused[ckp_id]["score"] += min(max(pku_vector_score, 0.0), 1.0) * 0.01
        fused[ckp_id]["reasons"].append(f"pku_vector rank={rank + 1} score={pku_vector_score:.4f}")

    ranked = []
    for ckp_id, payload in fused.items():
        ckp = ckp_by_id[ckp_id]
        score = float(payload["score"]) + min(float(ckp.confidence or 0.0), 1.0) * 0.01
        ranked.append((ckp, round(score, 4), payload["matched_terms"], payload["reasons"][:8]))
    ranked.sort(key=lambda item: (item[1], item[0].confidence or 0.0, item[0].updated_at), reverse=True)
    return ranked[:limit]


def _pku_fields(pku: PersonalKnowledgeUnit) -> dict[str, str]:
    return {
        "statement": _normalize_text(pku.statement),
        "normalized_statement": _normalize_text(pku.normalized_statement),
        "evidence_span": _normalize_text(pku.evidence_span),
        "keywords": _normalize_text(pku.keywords or []),
        "concepts": _normalize_text(pku.concepts or []),
        "entities": _normalize_text(pku.entities or []),
    }


def _score_pku_evidence(
    pku: PersonalKnowledgeUnit,
    terms: list[str],
    ckp_score: float,
    link_confidence: float | None,
    pku_vector_score: float = 0.0,
) -> tuple[float, list[str], list[str]]:
    if not terms:
        return float(link_confidence or 0.0), [], ["no query terms; ranked by link confidence"]
    score, matched_terms, reasons = _score_fields(
        _pku_fields(pku),
        terms,
        {
            "statement": 4.0,
            "normalized_statement": 4.0,
            "evidence_span": 5.0,
            "keywords": 3.0,
            "concepts": 2.0,
            "entities": 2.0,
        },
    )
    text_score = min(float(score or 0.0) / 20.0, 1.0)
    normalized_ckp_score = min(float(ckp_score or 0.0), 1.0)
    combined = (
        0.50 * text_score
        + 0.25 * normalized_ckp_score
        + 0.15 * min(float(link_confidence or 0.0), 1.0)
        + 0.10 * min(float(pku.confidence or 0.0), 1.0)
        + 0.05 * min(max(float(pku_vector_score or 0.0), 0.0), 1.0)
    )
    if pku_vector_score:
        reasons = [*reasons, f"pku_vector score={float(pku_vector_score):.4f}"]
    return round(combined, 4), matched_terms, reasons[:8]


def _expanded_sources_for_source(db, source: dict[str, Any]) -> list[dict[str, Any]]:
    if source.get("source_kind") != "document_chunk":
        return []
    chunk_id = source.get("chunk_id") or source.get("source_id")
    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
    if not chunk or chunk.chunk_type != "parent":
        return []
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
    children = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.parent_id == chunk.id, KnowledgeChunk.chunk_type == "child")
        .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
        .all()
    )
    title = item.title if item else ""
    return [
        {
            "source_kind": "document_chunk",
            "source_id": child.id,
            "ref_type": "knowledge_chunk",
            "ref_id": child.id,
            "chunk_id": child.id,
            "parent_chunk_id": chunk.id,
            "item_id": child.item_id,
            "display_type": "knowledge_item",
            "display_id": child.item_id,
            "display_title": title,
            "display_label": source.get("display_label", ""),
            "snippet": child.chunk_text,
            "title": title,
            "text": child.chunk_text,
            "chunk_type": child.chunk_type,
            "category": item.category if item else "",
            "tags": item.tags if item else [],
            "score": source.get("score"),
            "raw_score": source.get("raw_score"),
        }
        for child in children
    ]


def _build_evidence_bundle(
    db,
    ckp: CanonicalKnowledgePoint,
    score: float,
    matched_terms: list[str],
    reasons: list[str],
    *,
    query_terms: list[str] | None = None,
    pku_vector_scores: dict[str, float] | None = None,
    evidence_mode: bool = False,
) -> dict[str, Any]:
    link_query = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.canonical_id == ckp.id)
    if evidence_mode:
        links = link_query.all()
    else:
        links = link_query.order_by(PKUCanonicalLink.confidence.desc(), PKUCanonicalLink.created_at.desc()).limit(12).all()
    if evidence_mode:
        scored_links = []
        for link in links:
            if not link.pku or link.pku.status != "active":
                continue
            evidence_score, pku_terms, pku_reasons = _score_pku_evidence(
                link.pku,
                query_terms or [],
                score,
                link.confidence,
                (pku_vector_scores or {}).get(str(link.pku_id), 0.0),
            )
            scored_links.append((link, evidence_score, pku_terms, pku_reasons))
        scored_links.sort(key=lambda item: (item[1], item[0].confidence or 0.0, item[0].created_at), reverse=True)
        links_with_scores = scored_links[:12]
    else:
        links_with_scores = [(link, float(link.confidence or 0.0), [], []) for link in links]

    linked_pkus: list[dict[str, Any]] = []
    raw_sources: list[dict[str, Any]] = []
    expanded_sources: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str]] = set()
    seen_expanded_sources: set[tuple[str, str]] = set()
    for link, evidence_score, pku_terms, pku_reasons in links_with_scores:
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
                "evidence_score": evidence_score,
                "pku_vector_score": (pku_vector_scores or {}).get(str(pku.id), 0.0),
                "matched_terms": pku_terms,
                "match_reasons": pku_reasons,
                "evidence_span": pku.evidence_span,
            }
        )
        source = _source_for_pku(db, pku)
        if source:
            if evidence_mode:
                source["score"] = float(evidence_score or 0)
                source["raw_score"] = float(evidence_score or 0)
            else:
                source["score"] = max(float(score or 0), float(evidence_score or 0), float(link.confidence or 0))
                source["raw_score"] = float(evidence_score or link.confidence or 0)
            source_key = (source["source_kind"], source["source_id"])
            if source_key not in seen_sources:
                raw_sources.append(source)
                seen_sources.add(source_key)
            for expanded_source in _expanded_sources_for_source(db, source) if evidence_mode else []:
                expanded_key = (expanded_source["source_kind"], expanded_source["source_id"])
                if expanded_key not in seen_expanded_sources:
                    expanded_sources.append(expanded_source)
                    seen_expanded_sources.add(expanded_key)

    bundle = {
        **_canonical_to_result(ckp, score, matched_terms, reasons),
        "linked_pkus": linked_pkus,
        "raw_sources": raw_sources,
    }
    if evidence_mode:
        bundle["retrieval_mode"] = "governed_evidence"
        bundle["expanded_sources"] = expanded_sources
    return bundle


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


def _query_governed_evidence(query: str, limit: int) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    terms = _query_terms(query)
    candidate_limit = max(limit * 8, _GOVERNED_EVIDENCE_CANDIDATE_MIN)
    db = _Session()
    try:
        vector_hits = _safe_search_ckp_vectors(query, candidate_limit)
        pku_vector_hits = _safe_search_pku_vectors(query, candidate_limit)
        pku_vector_scores = {
            str(hit.get("pku_id")): float(hit.get("score") or 0.0)
            for hit in pku_vector_hits
            if hit.get("pku_id")
        }
        lexical_hits = _lexical_ckp_candidates(db, terms, candidate_limit)
        fused = _fuse_ckp_candidates(
            db,
            vector_hits=vector_hits,
            pku_vector_hits=pku_vector_hits,
            lexical_hits=lexical_hits,
            limit=limit,
        )
        bundles = [
            _build_evidence_bundle(
                db,
                ckp,
                score,
                matched_terms,
                reasons,
                query_terms=terms,
                pku_vector_scores=pku_vector_scores,
                evidence_mode=True,
            )
            for ckp, score, matched_terms, reasons in fused
        ]
        return terms, bundles, []
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
