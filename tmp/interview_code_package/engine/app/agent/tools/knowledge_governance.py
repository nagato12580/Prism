from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeFile, KnowledgeItem
from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools import governed_knowledge
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.evidence import normalize_evidence_items
from engine.app.config import settings


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)
_UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_SOURCE_ID_LABEL_PATTERN = re.compile(r"\b(?:chunk_id|source_id)\b\s*[:=]\s*([0-9a-fA-F-]{12,36})\b")
_HEX_ALPHA_PATTERN = re.compile(r"[a-fA-F]")
_UUID_HYPHEN_POSITIONS = {8, 13, 18, 23}


class KnowledgeTopicSearchInput(BaseModel):
    query: str = Field(..., description="Topic, concept, or theme to search in CKP topic hubs.")
    limit: int = Field(8, ge=1, le=20, description="Maximum number of CKP topics to return.")


class KnowledgeEvidenceSearchInput(BaseModel):
    query: str = Field(..., description="Question or concept to search for PKU-level evidence.")
    evidence_types: list[str] = Field(
        default_factory=list,
        description="Optional PKU unit_type filters such as claim, definition, rule, opinion, method, or observation.",
    )
    source_kinds: list[str] = Field(
        default_factory=list,
        description="Optional source filters such as document_chunk, personal_asset_unit, or personal_asset_item.",
    )
    limit: int = Field(12, ge=1, le=40, description="Maximum number of PKU evidence items to return.")


class KnowledgeMaterialSearchInput(BaseModel):
    query: str = Field(..., description="Topic or material description to find across governed knowledge sources.")
    intent: str = Field(
        "summary",
        description="Answer intent: opinions, facts, summary, or evidence. Use opinions for questions about viewpoints.",
    )
    limit: int = Field(8, ge=1, le=20, description="Maximum number of source materials to return.")


class RawDocumentSearchInput(BaseModel):
    query: str = Field(..., description="Raw document query for uploaded document chunks and original passages.")


def _source_key(source: dict[str, Any]) -> tuple[str, str]:
    return (
        str(source.get("source_kind") or source.get("ref_type") or ""),
        str(source.get("source_id") or source.get("ref_id") or source.get("chunk_id") or source.get("asset_id") or ""),
    )


def _pku_key(pku: dict[str, Any]) -> tuple[str, str]:
    return (str(pku.get("source_kind") or ""), str(pku.get("source_id") or ""))


def _canonical_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in bundle.items()
        if key not in {"linked_pkus", "raw_sources"}
    }


def _all_sources(bundles: list[dict[str, Any]], knowledge_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for bundle in bundles:
        sources.extend(bundle.get("raw_sources") or [])
    sources.extend(knowledge_results)
    return sources


def _result_status(*collections: list[Any]) -> str:
    return "success" if any(collections) else "insufficient"


def _query(query: str, limit: int) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    return governed_knowledge._query_governed_knowledge(query, limit)


def _new_db_session():
    return _Session()


def _is_valid_direct_chunk_token(token: str) -> bool:
    if _UUID_PATTERN.fullmatch(token):
        return True
    if not (12 <= len(token) < 36):
        return False
    for index, char in enumerate(token):
        if index in _UUID_HYPHEN_POSITIONS:
            if char != "-":
                return False
        elif not char.isdigit() and char.lower() not in {"a", "b", "c", "d", "e", "f"}:
            return False
    if token.endswith("-"):
        return False
    return bool(_HEX_ALPHA_PATTERN.search(token))


def _extract_chunk_id_token(query: str) -> str | None:
    prefix_match = _SOURCE_ID_LABEL_PATTERN.search(query or "")
    if prefix_match:
        token = prefix_match.group(1)
        if _is_valid_direct_chunk_token(token):
            return token
    return None


def _build_knowledge_topic_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 8) -> str:
        terms, bundles, knowledge_results = _query(query, limit)
        sources = _all_sources(bundles, knowledge_results)
        governed_knowledge._append_unique_citations(ctx.citations, sources)
        topics = [_canonical_summary(bundle) for bundle in bundles]
        ctx.stats_holder["knowledge_topic_search"] = {
            "hit_count": len(topics),
            "source_count": len(sources),
            "query_terms": terms,
        }
        payload = {
            "status": _result_status(topics, knowledge_results),
            "summary": f"Found {len(topics)} CKP topics and {len(knowledge_results)} synthesized knowledge items.",
            "query_terms": terms,
            "topics": topics,
            "synthesized_knowledge": knowledge_results,
            "sources": sources,
        }
        payload["evidence_items"] = normalize_evidence_items("knowledge_topic_search", payload)
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="knowledge_topic_search",
        description=(
            "Search CKP topic hubs and governed knowledge themes. Use when the user asks what topics, "
            "knowledge points, structures, relationships, or stable themes exist about a subject."
        ),
        args_schema=KnowledgeTopicSearchInput,
    )


def _build_knowledge_evidence_search(ctx: ToolContext) -> StructuredTool:
    def run(
        query: str,
        evidence_types: list[str] | None = None,
        source_kinds: list[str] | None = None,
        limit: int = 12,
    ) -> str:
        terms, bundles, knowledge_results = _query(query, limit)
        evidence_type_set = {item.lower() for item in (evidence_types or []) if item}
        source_kind_set = {item.lower() for item in (source_kinds or []) if item}
        raw_source_by_key = {
            _source_key(source): source
            for source in _all_sources(bundles, knowledge_results)
        }

        evidence: list[dict[str, Any]] = []
        for bundle in bundles:
            canonical = _canonical_summary(bundle)
            for pku in bundle.get("linked_pkus") or []:
                unit_type = str(pku.get("unit_type") or "").lower()
                source_kind = str(pku.get("source_kind") or "").lower()
                if evidence_type_set and unit_type not in evidence_type_set:
                    continue
                if source_kind_set and source_kind not in source_kind_set:
                    continue
                source = raw_source_by_key.get(_pku_key(pku))
                evidence.append(
                    {
                        **pku,
                        "canonical": canonical,
                        "source": source,
                    }
                )
                if len(evidence) >= limit:
                    break
            if len(evidence) >= limit:
                break

        sources = [item["source"] for item in evidence if item.get("source")]
        governed_knowledge._append_unique_citations(ctx.citations, sources)
        ctx.stats_holder["knowledge_evidence_search"] = {
            "hit_count": len(evidence),
            "source_count": len(sources),
            "query_terms": terms,
            "evidence_types": sorted(evidence_type_set),
            "source_kinds": sorted(source_kind_set),
        }
        payload = {
            "status": _result_status(evidence),
            "summary": f"Found {len(evidence)} PKU evidence items across governed knowledge sources.",
            "query_terms": terms,
            "evidence": evidence,
            "sources": sources,
        }
        payload["evidence_items"] = normalize_evidence_items("knowledge_evidence_search", payload)
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="knowledge_evidence_search",
        description=(
            "Search PKU evidence across uploaded documents and personal knowledge units. Use when the "
            "user asks for concrete opinions, facts, rules, claims, methods, or evidence about a subject."
        ),
        args_schema=KnowledgeEvidenceSearchInput,
    )


def _build_knowledge_material_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, intent: str = "summary", limit: int = 8) -> str:
        terms, bundles, knowledge_results = _query(query, limit)
        source_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        materials_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for source in _all_sources(bundles, knowledge_results):
            key = _source_key(source)
            source_by_key[key] = source
            materials_by_key[key] = {
                "source": source,
                "matched_topics": [],
                "matched_pkus": [],
                "raw_evidence": [source],
                "extracted_opinions": [],
            }

        for bundle in bundles:
            topic = _canonical_summary(bundle)
            for pku in bundle.get("linked_pkus") or []:
                key = _pku_key(pku)
                if key not in materials_by_key:
                    continue
                material = materials_by_key[key]
                material["matched_topics"].append(topic)
                material["matched_pkus"].append(pku)
                unit_type = str(pku.get("unit_type") or "").lower()
                if intent.lower() == "opinions" or unit_type in {"claim", "opinion", "observation"}:
                    material["extracted_opinions"].append(
                        {
                            "statement": pku.get("statement"),
                            "unit_type": pku.get("unit_type"),
                            "canonical_title": topic.get("title"),
                            "source_kind": pku.get("source_kind"),
                            "source_id": pku.get("source_id"),
                        }
                    )

        materials = list(materials_by_key.values())[:limit]
        sources = [material["source"] for material in materials if material.get("source")]
        governed_knowledge._append_unique_citations(ctx.citations, sources)
        ctx.stats_holder["knowledge_material_search"] = {
            "hit_count": len(materials),
            "source_count": len(sources),
            "query_terms": terms,
            "intent": intent,
        }
        payload = {
            "status": _result_status(materials),
            "summary": f"Found {len(materials)} source materials through CKP/PKU backtracking.",
            "query_terms": terms,
            "intent": intent,
            "materials": materials,
            "sources": sources,
        }
        payload["evidence_items"] = normalize_evidence_items("knowledge_material_search", payload)
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="knowledge_material_search",
        description=(
            "Find source materials by first searching PKU/CKP, then backtracking to raw document chunks "
            "and personal knowledge sources. Use for questions like 'what did my previous materials say "
            "about X' or 'what opinions are in my materials about X'."
        ),
        args_schema=KnowledgeMaterialSearchInput,
    )


def _raw_document_payload(result: AgenticRagResult) -> dict[str, Any]:
    sources = list(getattr(result, "sources", [])) or list(getattr(result, "evidence", []))
    normalized_sources = [
        {
            **source,
            "source_kind": source.get("source_kind") or "document_chunk",
            "display_type": source.get("display_type") or "knowledge_item",
            "display_id": source.get("display_id") or source.get("item_id") or source.get("chunk_id") or "",
            "display_title": source.get("display_title") or source.get("doc_name") or source.get("title") or source.get("item_id") or "",
            "display_label": source.get("display_label") or "知识文档",
            "snippet": source.get("snippet") or source.get("text") or "",
        }
        for source in sources
        if isinstance(source, dict)
    ]
    payload = {
        "status": getattr(result, "status", "insufficient"),
        "summary": getattr(result, "summary", ""),
        "missing": getattr(result, "missing", []),
        "clarify": getattr(result, "clarify", None),
        "sources": normalized_sources,
        "evidence": getattr(result, "evidence", []),
    }
    payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)
    return payload


def _raw_chunk_payload_from_query(query: str) -> dict[str, Any] | None:
    token = _extract_chunk_id_token(query)
    if not token:
        return None

    db = None
    try:
        db = _new_db_session()
        if _UUID_PATTERN.fullmatch(token):
            chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == token).first()
        else:
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.id.like(f"{token}%"))
                .order_by(KnowledgeChunk.id.asc())
                .limit(2)
                .all()
            )
            if len(chunks) != 1:
                return None
            chunk = chunks[0]
        if chunk is None:
            return None

        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
        file = db.query(KnowledgeFile).filter(KnowledgeFile.item_id == chunk.item_id).first()
        title = (
            getattr(item, "title", None)
            or getattr(file, "title", None)
            or getattr(file, "original_filename", None)
            or str(getattr(chunk, "item_id", ""))
        )
        source = {
            "source_kind": "document_chunk",
            "source_id": chunk.id,
            "chunk_id": chunk.id,
            "item_id": chunk.item_id,
            "display_type": "knowledge_item",
            "display_id": chunk.item_id,
            "display_title": title,
            "display_label": "鐭ヨ瘑鏂囨。",
            "snippet": chunk.chunk_text,
            "text": chunk.chunk_text,
            "chunk_index": chunk.chunk_index,
            "chunk_type": chunk.chunk_type,
            "parent_id": chunk.parent_id,
            "parent_chunk_id": chunk.parent_id,
            "score": 1.0,
        }
        payload = {
            "status": "sufficient",
            "summary": "Found the requested raw document chunk by source_id.",
            "sources": [source],
            "evidence": [{**source}],
            "missing": [],
        }
        payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)
        return payload
    except Exception:
        return None
    finally:
        if db is not None:
            db.close()


def _build_raw_document_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        direct_payload = _raw_chunk_payload_from_query(query)
        if direct_payload is not None:
            governed_knowledge._append_unique_citations(ctx.citations, direct_payload["sources"])
            ctx.stats_holder["raw_document_search"] = {
                "hit_count": len(direct_payload["sources"]),
                "iterations": 0,
                "direct_lookup": True,
            }
            return json.dumps(direct_payload, ensure_ascii=False)

        if ctx.rag_runner is None:
            ctx.stats_holder["raw_document_search"] = {"hit_count": 0, "iterations": 0}
            return json.dumps(
                {
                    "status": "insufficient",
                    "summary": "Raw document search is not configured.",
                    "missing": ["No RAG runner is available."],
                    "sources": [],
                    "evidence": [],
                    "evidence_items": [],
                },
                ensure_ascii=False,
            )
        result = ctx.rag_runner.run(query)
        payload = _raw_document_payload(result)
        governed_knowledge._append_unique_citations(ctx.citations, payload["sources"])
        ctx.stats_holder["raw_document_search"] = {
            "hit_count": len(payload["sources"]),
            "iterations": getattr(result, "iterations", 0),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="raw_document_search",
        description=(
            "Search raw uploaded document chunks and original passages. Use only when the user needs "
            "exact document wording, paragraph-level details, parameters, or when governed PKU/CKP evidence is insufficient."
        ),
        args_schema=RawDocumentSearchInput,
    )


register_tool(
    ToolSpec(
        key="knowledge_topic_search",
        name="knowledge_topic_search",
        description="Search CKP topic hubs and governed knowledge themes.",
        builder=_build_knowledge_topic_search,
        default_enabled=True,
    )
)

register_tool(
    ToolSpec(
        key="knowledge_evidence_search",
        name="knowledge_evidence_search",
        description="Search PKU evidence across documents and personal knowledge units.",
        builder=_build_knowledge_evidence_search,
        default_enabled=True,
    )
)

register_tool(
    ToolSpec(
        key="knowledge_material_search",
        name="knowledge_material_search",
        description="Find source materials through CKP/PKU backtracking.",
        builder=_build_knowledge_material_search,
        default_enabled=True,
    )
)

register_tool(
    ToolSpec(
        key="raw_document_search",
        name="raw_document_search",
        description="Search raw uploaded document chunks and original passages.",
        builder=_build_raw_document_search,
        default_enabled=True,
    )
)
