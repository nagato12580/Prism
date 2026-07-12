"""Unified GraphRAG search: hybrid recall + graph expansion + RRF + rerank.

Returns the same SearchHit shape as hybrid_search ({chunk_id, item_id, score,
...}) so it drops into AgenticRagRunner as the `search` fn unchanged.
"""
import logging

from ..config import settings
from .graph_expand import expand_candidates, match_seed_entities
from .hybrid import RRF_K, hybrid_search
from .rerank import rerank

logger = logging.getLogger("uvicorn.error")

VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4
GRAPH_WEIGHT = 0.5   # graph-expanded hits weighted slightly below vector
COMMUNITY_WEIGHT = 0.45
SURPRISING_WEIGHT = 0.42
GOD_WEIGHT = 0.48

GRAPH_MARKER_WEIGHTS = {
    "community": COMMUNITY_WEIGHT,
    "surprising": SURPRISING_WEIGHT,
    "god": GOD_WEIGHT,
}


def _filter_stale_hits(db, hits: list[dict]) -> list[dict]:
    """Drop retrieval hits that no longer resolve to live primary records."""
    if db is None or not hits:
        return hits

    try:
        from backend.app.models import KnowledgeChunk, PersonalAssetUnit
    except Exception as exc:
        logger.warning("[unified] stale_filter_import_failed err=%s", exc)
        return hits

    chunk_ids = [str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")]
    asset_unit_ids = [
        str(hit["source_id"])
        for hit in hits
        if hit.get("source_kind") == "personal_asset_unit" and hit.get("source_id")
    ]

    live_chunk_ids: set[str] = set()
    live_asset_unit_ids: set[str] = set()

    try:
        if chunk_ids:
            live_chunk_ids = {
                row[0]
                for row in db.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.id.in_(chunk_ids))
                .all()
            }
        if asset_unit_ids:
            live_asset_unit_ids = {
                row[0]
                for row in db.query(PersonalAssetUnit.id)
                .filter(PersonalAssetUnit.id.in_(asset_unit_ids))
                .all()
            }
    except Exception as exc:
        logger.warning("[unified] stale_filter_query_failed err=%s", exc)
        return hits

    filtered: list[dict] = []
    dropped = 0
    for hit in hits:
        chunk_id = hit.get("chunk_id")
        if chunk_id:
            if str(chunk_id) in live_chunk_ids:
                filtered.append(hit)
            else:
                dropped += 1
            continue

        if hit.get("source_kind") == "personal_asset_unit" and hit.get("source_id"):
            if str(hit["source_id"]) in live_asset_unit_ids:
                filtered.append(hit)
            else:
                dropped += 1
            continue

        filtered.append(hit)

    if dropped:
        logger.info("[unified] stale_hits_filtered dropped=%s kept=%s", dropped, len(filtered))
    return filtered


def _hit_key(hit: dict) -> str:
    chunk_id = hit.get("chunk_id")
    if chunk_id:
        return f"document_chunk:{chunk_id}"
    source_kind = hit.get("source_kind")
    source_id = hit.get("source_id")
    if source_kind and source_id:
        return f"{source_kind}:{source_id}"
    return f"unknown:{id(hit)}"


def _merge_source_marker(existing: dict, incoming: dict) -> None:
    marker = incoming.get("source_marker")
    if not marker:
        return
    current = existing.get("source_marker")
    if not current:
        existing["source_marker"] = marker
    elif marker not in current:
        existing["source_marker"] = f"{current}+{marker}"


def _merge_missing_fields(existing: dict, incoming: dict) -> None:
    for key, value in incoming.items():
        if existing.get(key) in (None, "") and value not in (None, ""):
            existing[key] = value


def _graph_rag_route_list(hit: dict) -> list[dict]:
    path = list(hit.get("path") or [])
    explain = dict(hit.get("explain") or {})
    source_marker = str(
        explain.get("source_marker")
        or hit.get("source_marker")
        or ""
    )
    matched_entity_ids = list(explain.get("matched_entity_ids") or [])
    if path and isinstance(path[0], dict) and "steps" in path[0]:
        return [dict(route) for route in path]
    return [{
        "source_marker": source_marker,
        "matched_entity_ids": matched_entity_ids,
        "steps": path,
    }]


def _graph_provenance_marker(hit: dict) -> str:
    explain = hit.get("explain") or {}
    if isinstance(explain, dict):
        marker = explain.get("source_marker")
        if marker:
            return str(marker)
    path = hit.get("path") or []
    if path and isinstance(path, list):
        first = path[0]
        if isinstance(first, dict) and first.get("source_marker"):
            markers: list[str] = []
            for route in path:
                if isinstance(route, dict):
                    marker = route.get("source_marker")
                    if marker and marker not in markers:
                        markers.append(str(marker))
            if markers:
                return "+".join(markers)
    marker = hit.get("source_marker")
    return str(marker) if marker else ""


def _graph_marker_weight(hit: dict) -> float:
    markers: list[str] = []
    marker = _graph_provenance_marker(hit)
    if marker:
        markers.extend(part for part in marker.split("+") if part)

    explain = hit.get("explain") or {}
    if isinstance(explain, dict):
        for item in explain.get("source_markers") or []:
            if item and item not in markers:
                markers.append(str(item))

    weighted_markers = [GRAPH_MARKER_WEIGHTS[item] for item in markers if item in GRAPH_MARKER_WEIGHTS]
    if not weighted_markers:
        return GRAPH_WEIGHT
    if any(item.startswith("graph_") for item in markers):
        return max([GRAPH_WEIGHT, *weighted_markers])
    return max(weighted_markers)


def _build_graph_rag_payload(hit: dict) -> dict:
    source_kind = hit.get("source_kind") or ("document_chunk" if hit.get("chunk_id") else "source")
    source_id = hit.get("source_id") or hit.get("chunk_id") or hit.get("item_id") or ""
    explain = dict(hit.get("explain") or {})
    source_marker = _graph_provenance_marker(hit)
    evidence_type = str(
        explain.get("evidence_type")
        or hit.get("evidence_type")
        or ("INFERRED" if source_marker.startswith("graph_") or "+" in source_marker or source_marker in {"community", "god", "surprising"} else "EXTRACTED")
    )
    explain["evidence_type"] = evidence_type
    explain["source_marker"] = source_marker
    return {
        "source": {
            "source_kind": source_kind,
            "source_id": source_id,
            "item_id": hit.get("item_id"),
            "chunk_id": hit.get("chunk_id"),
            "display_title": hit.get("display_title") or hit.get("title") or "",
        },
        "path": _graph_rag_route_list(hit),
        "explain": explain,
    }


def _restore_graph_source_marker(hit: dict) -> dict:
    graph_rag = hit.get("graph_rag")
    if not isinstance(graph_rag, dict):
        return hit
    explain = graph_rag.get("explain")
    if not isinstance(explain, dict):
        return hit
    marker = explain.get("source_marker")
    if marker:
        hit["source_marker"] = marker
    return hit


def _enrich_graph_hit(db, hit: dict) -> dict:
    if hit.get("source_kind") != "personal_asset_unit" or not hit.get("source_id"):
        return hit

    try:
        from backend.app.models import PersonalAssetUnit

        unit = (
            db.query(PersonalAssetUnit)
            .filter(PersonalAssetUnit.id == hit["source_id"])
            .first()
        )
    except Exception as exc:
        logger.warning("[unified] asset_unit_enrich_failed source_id=%s err=%s", hit.get("source_id"), exc)
        return hit

    if unit is None:
        return hit

    text = unit.content or unit.summary or unit.title or ""
    title = unit.title or ""
    summary = unit.summary or ""
    return {
        **hit,
        "title": title,
        "display_title": title,
        "text": text,
        "snippet": summary or text,
    }


def unified_search(
    query: str,
    top_k: int,
    *,
    mode: str = "fast",
    db=None,
    graph_client=None,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
) -> list[dict]:
    """Hybrid recall + graph expansion + RRF fusion + rerank. Returns SearchHit list."""
    # 1) hybrid recall (vector + BM25 via existing RRF inside hybrid_search)
    try:
        hybrid_hits = hybrid_search(
            query, top_k=top_k, topic_ids=topic_ids, source_types=source_types, allowed_item_ids=allowed_item_ids
        ) or []
    except Exception as exc:
        logger.warning("[unified] hybrid_failed err=%s", exc)
        hybrid_hits = []
    hybrid_hits = _filter_stale_hits(db, hybrid_hits)

    # 2) graph expansion -> extra chunk candidates
    graph_hits: list[dict] = []
    if graph_client is not None and db is not None:
        try:
            seeds = match_seed_entities(db, query, limit=settings.GRAPH_EXPAND_SEED_ENTITIES)
            hops = settings.GRAPH_EXPAND_FAST_HOPS if mode == "fast" else settings.GRAPH_EXPAND_DEEP_HOPS
            graph_hits = expand_candidates(
                db, graph_client, seeds, mode=mode, hops=hops,
                max_candidates=settings.GRAPH_EXPAND_MAX_CANDIDATES,
                neighbors_per_node=settings.GRAPH_EXPAND_NEIGHBORS_PER_NODE,
                community_members=settings.GRAPH_EXPAND_COMMUNITY_MEMBERS,
                god_neighbors=settings.GRAPH_EXPAND_GOD_NEIGHBORS,
            )
        except Exception as exc:
            logger.warning("[unified] graph_expand_failed err=%s", exc)
    graph_hits = _filter_stale_hits(db, graph_hits)

    # 3) RRF fusion of hybrid + graph candidates
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, h in enumerate(hybrid_hits):
        key = _hit_key(h)
        scores[key] = scores.get(key, 0.0) + VECTOR_WEIGHT / (RRF_K + rank + 1)  # hybrid already fused; treat as primary
        meta.setdefault(key, dict(h))
    for rank, h in enumerate(graph_hits):
        enriched = _enrich_graph_hit(db, h)
        key = _hit_key(enriched)
        scores[key] = scores.get(key, 0.0) + _graph_marker_weight(enriched) / (RRF_K + rank + 1)
        if key in meta:
            # Merge source_marker so graph contribution is visible even when
            # the same source appeared in hybrid results.
            _merge_source_marker(meta[key], enriched)
            _merge_missing_fields(meta[key], enriched)
        else:
            meta[key] = {**enriched, "score": 0.0}
    merged = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    candidates = [{**meta[key], "score": sc, "graph_rag": _build_graph_rag_payload(meta[key])} for key, sc in merged]

    # 4) rerank (degrades gracefully if unavailable)
    top_n = max(top_k, settings.RERANK_TOP_N)
    reranked = rerank(query, candidates, top_n=top_n)
    return [_restore_graph_source_marker(hit) for hit in reranked[:top_k]]


def make_unified_search(
    mode: str,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
):
    """Return a SearchFn(query, top_k) closed over scope filters + graph client.

    Lazy-imports db session + GraphClient so module import stays cheap and tests
    can monkeypatch the helpers.
    """
    def _search(query: str, top_k: int) -> list[dict]:
        db = None
        graph_client = None
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from ..config import settings as _s
            db = sessionmaker(bind=create_engine(_s.DATABASE_URL, pool_pre_ping=True))()
            from backend.app.services.graph_client import GraphClient
            graph_client = GraphClient()
        except Exception as exc:
            logger.warning("[unified] db/graph_unavailable (graph expansion skipped) err=%s", exc)
        try:
            return unified_search(
                query, top_k, mode=mode, db=db, graph_client=graph_client,
                topic_ids=topic_ids, source_types=source_types, allowed_item_ids=allowed_item_ids,
            )
        finally:
            if db is not None:
                try: db.close()
                except Exception: pass
            if graph_client is not None:
                try: graph_client.close()
                except Exception: pass

    return _search
