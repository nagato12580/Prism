"""Governed Knowledge Search V2 — 向量优先检索：chunk 向量召回 → 反查 PKU → 聚合 CKP。

与 V1（governed_knowledge.py）的区别：
  V1: MySQL 拉 CKP → 子串匹配打分 → 回溯 PKU/source（无向量、无语义、召回上限 80）
  V2: chunk 向量召回 → child→parent → 反查 PKU → 聚合 CKP → 证据包（语义匹配、无召回上限）

设计文档：docs/superpowers/specs/2026-06-24-governed-knowledge-v2-vector-first-design.md
"""
from __future__ import annotations

import json
import socket
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.governed_knowledge import (
    _KNOWLEDGE_FIELD_WEIGHTS,
    _append_unique_citations,
    _build_evidence_bundle,
    _personal_asset_unit_fields,
    _personal_asset_unit_result,
    _query_terms,
    _score_fields,
    _source_for_pku,
)
from engine.app.config import settings
from engine.app.ingestion.vectorizer import embed_query
from engine.app.milvus_client import connect as milvus_connect, search_vectors


KEY = "governed_knowledge_v2"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class GovernedKnowledgeV2Input(BaseModel):
    query: str = Field(..., description="Natural-language query for governed personal knowledge.")
    limit: int = Field(8, ge=1, le=20, description="Maximum number of canonical knowledge points to return.")
    top_k_chunks: int = Field(20, ge=5, le=50, description="Number of chunks to retrieve from vector store before aggregation.")


def _map_child_to_parent_ids(db, child_chunk_ids: list[str]) -> dict[str, str]:
    """child chunk_id → 用于反查 PKU 的 source_id（parent_id 或自身）。

    Milvus 只存 child chunk，PKU 从 parent chunk 抽取（source_id=parent_id）。
    若 chunk 无 parent_id（自身就是 parent 或独立块），则用自身 id。
    """
    if not child_chunk_ids:
        return {}
    chunks = db.query(KnowledgeChunk.id, KnowledgeChunk.parent_id).filter(
        KnowledgeChunk.id.in_(child_chunk_ids)
    ).all()
    return {c.id: (c.parent_id or c.id) for c in chunks}


def _reverse_lookup_pkus(db, source_ids: set[str]) -> list[PersonalKnowledgeUnit]:
    """source_id 集合 → active PKU 列表（source_kind='document_chunk'）。"""
    if not source_ids:
        return []
    return (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id.in_(list(source_ids)),
            PersonalKnowledgeUnit.status == "active",
        )
        .all()
    )


def _aggregate_ckps(
    db,
    pkus: list[PersonalKnowledgeUnit],
    chunk_score_by_source: dict[str, float],
) -> list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]]:
    """PKU 列表 → 按 CKP 聚合 → 打分排序。

    返回 [(ckp, score, matched_terms, reasons), ...]
    """
    if not pkus:
        return []

    pku_ids = [p.id for p in pkus]
    links = (
        db.query(PKUCanonicalLink)
        .filter(PKUCanonicalLink.pku_id.in_(pku_ids))
        .all()
    )

    # 按 canonical_id 聚合
    ckp_pkus: dict[str, list[PKUCanonicalLink]] = {}
    for link in links:
        ckp_pkus.setdefault(link.canonical_id, []).append(link)

    if not ckp_pkus:
        return []

    ckp_ids = list(ckp_pkus.keys())
    ckp_rows = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.id.in_(ckp_ids),
            CanonicalKnowledgePoint.user_id == "default-user",
            CanonicalKnowledgePoint.status != "deprecated",
        )
        .all()
    )
    ckp_map = {c.id: c for c in ckp_rows}

    scored: list[tuple[CanonicalKnowledgePoint, float, list[str], list[str]]] = []
    for canonical_id, canonical_links in ckp_pkus.items():
        ckp = ckp_map.get(canonical_id)
        if not ckp:
            continue

        # 收集追溯到该 CKP 的 chunk 分数
        chunk_scores: list[float] = []
        matched_terms: list[str] = []
        for link in canonical_links:
            pku = link.pku
            if not pku or pku.status != "active":
                continue
            src_score = chunk_score_by_source.get(pku.source_id, 0.0)
            if src_score > 0:
                chunk_scores.append(src_score)
            matched_terms.append(pku.source_id[:8])

        max_chunk_score = max(chunk_scores) if chunk_scores else 0.0
        pku_hit_count = len({link.pku_id for link in canonical_links if link.pku and link.pku.status == "active"})
        link_confidences = [float(link.confidence or 0) for link in canonical_links if link.pku and link.pku.status == "active"]
        avg_link_conf = sum(link_confidences) / len(link_confidences) if link_confidences else 0.0

        score = (
            max_chunk_score
            + pku_hit_count * 0.15
            + avg_link_conf * 0.10
            + min(float(ckp.confidence or 0), 1.0) * 0.10
        )

        reasons = [
            f"vector_score={max_chunk_score:.4f}",
            f"pku_hits={pku_hit_count}",
            f"avg_link_conf={avg_link_conf:.2f}",
        ]
        scored.append((ckp, round(score, 4), matched_terms[:8], reasons))

    scored.sort(key=lambda item: (item[1], item[0].confidence or 0.0, item[0].updated_at), reverse=True)
    return scored


_milvus_checked = False
_milvus_reachable = False


def _ensure_milvus() -> bool:
    """快速 TCP 预检 Milvus 是否可达，避免无限阻塞。结果缓存。"""
    global _milvus_checked, _milvus_reachable
    if _milvus_checked:
        if _milvus_reachable:
            try:
                milvus_connect()
            except Exception:
                pass
        return _milvus_reachable
    _milvus_checked = True
    try:
        sock = socket.create_connection(
            (settings.MILVUS_HOST, settings.MILVUS_PORT), timeout=3
        )
        sock.close()
        milvus_connect()
        _milvus_reachable = True
    except Exception:
        _milvus_reachable = False
    return _milvus_reachable


def _query_governed_v2(
    query: str, limit: int, top_k_chunks: int = 20
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """向量优先 governed 检索主逻辑。

    Returns: (chunk_hits, bundles, knowledge_results, all_raw_sources)
    """
    # ① chunk 召回：优先向量，Milvus 不可达时回退到 hybrid_search（BM25）
    hits: list[dict[str, Any]] = []
    if _ensure_milvus():
        embedding = embed_query(query)
        hits = search_vectors(embedding, top_k=top_k_chunks)
    if not hits:
        # 向量不可用或无结果时，回退到 hybrid（BM25+向量 RRF）
        # No authoritative KB generation scope is available in this legacy
        # tool path, so it must not call the production hybrid adapter.
        hits = []
    # hits: [{chunk_id, item_id, score}]

    db = _Session()
    try:
        # ② child→parent 映射
        child_chunk_ids = [h["chunk_id"] for h in hits]
        child_to_source = _map_child_to_parent_ids(db, child_chunk_ids)

        # source_id → 最高 chunk 分数（多个 child 可能映射到同一 parent）
        chunk_score_by_source: dict[str, float] = {}
        for h in hits:
            src_id = child_to_source.get(h["chunk_id"], h["chunk_id"])
            chunk_score_by_source[src_id] = max(chunk_score_by_source.get(src_id, 0.0), h["score"])

        # ③ 反查 PKU
        source_ids = set(chunk_score_by_source.keys())
        pkus = _reverse_lookup_pkus(db, source_ids)

        # ④⑤ 聚合 CKP + 打分
        scored_ckps = _aggregate_ckps(db, pkus, chunk_score_by_source)

        # ⑥ 构建证据包（复用 _build_evidence_bundle）
        bundles = [
            _build_evidence_bundle(db, ckp, score, matched_terms, reasons)
            for ckp, score, matched_terms, reasons in scored_ckps[:limit]
        ]

        # ⑦ 资产兜底（复用现有打分逻辑）
        knowledge_results: list[dict[str, Any]] = []
        from backend.app.models.asset import PersonalAssetUnit
        unit_rows = (
            db.query(PersonalAssetUnit)
            .filter(PersonalAssetUnit.user_id == "default-user")
            .order_by(PersonalAssetUnit.updated_at.desc())
            .limit(max(limit * 8, 80))
            .all()
        )
        terms = _query_terms(query)
        for unit in unit_rows:
            score, matched, reasons = _score_fields(
                _personal_asset_unit_fields(unit), terms, _KNOWLEDGE_FIELD_WEIGHTS
            )
            if not terms or matched:
                knowledge_results.append(_personal_asset_unit_result(unit, score, matched, reasons))
        knowledge_results.sort(key=lambda item: (float(item.get("score") or 0), item.get("title") or ""), reverse=True)

        # 汇总 raw_sources
        all_raw_sources: list[dict[str, Any]] = []
        for bundle in bundles:
            all_raw_sources.extend(bundle["raw_sources"])
        all_raw_sources.extend(knowledge_results)

        return hits, bundles, knowledge_results[:limit], all_raw_sources
    finally:
        db.close()


def _build_governed_knowledge_v2(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 8, top_k_chunks: int = 20) -> str:
        chunk_hits, bundles, knowledge_results, raw_sources = _query_governed_v2(query, limit, top_k_chunks)

        _append_unique_citations(ctx.citations, raw_sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(bundles),
            "knowledge_hit_count": len(knowledge_results),
            "chunk_hit_count": len(chunk_hits),
            "source_count": len(raw_sources),
            "retrieval_path": "vector_first",
        }
        status = "success" if bundles or knowledge_results or chunk_hits else "insufficient"
        summary = (
            f"Found {len(bundles)} governed knowledge points (via vector-first), "
            f"{len(knowledge_results)} synthesized knowledge items, "
            f"{len(chunk_hits)} chunk hits, {len(raw_sources)} evidence items."
            if bundles or knowledge_results or chunk_hits
            else "No governed knowledge points, synthesized knowledge, or chunks matched the query."
        )
        return json.dumps(
            {
                "status": status,
                "summary": summary,
                "retrieval_path": "vector_first",
                "chunk_hits": chunk_hits,
                "canonical_results": [
                    {k: v for k, v in bundle.items() if k not in {"linked_pkus", "raw_sources"}}
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
            "Search Prism's governed personal knowledge layer using vector-first retrieval. "
            "It retrieves relevant document chunks via vector similarity, then traces back through "
            "personal knowledge units (PKU) to aggregate canonical knowledge points (CKP) with full "
            "evidence chains. Use when the user asks for stable conclusions, relationships between "
            "their saved knowledge and documents, evidence-backed personal knowledge, or cross-source "
            "synthesis. This tool provides semantic matching (not just keyword matching)."
        ),
        args_schema=GovernedKnowledgeV2Input,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Vector-first governed knowledge search: chunk vectors → PKU backtracking → CKP aggregation.",
        builder=_build_governed_knowledge_v2,
        default_enabled=False,
    )
)
