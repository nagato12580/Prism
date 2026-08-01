"""Unified GraphRAG search: hybrid recall + graph expansion + RRF + rerank.

Returns the same SearchHit shape as hybrid_search ({chunk_id, item_id, score,
...}) so it drops into AgenticRagRunner as the `search` fn unchanged.
"""
import logging

from ..config import settings
from .graph_expand import graph_search, expand_candidates, match_seed_entities
from .hybrid import BM25_WEIGHT, GRAPH_WEIGHT, RRF_K, VECTOR_WEIGHT, weighted_rrf
from .contracts import ChannelResult, SearchScope
from .es_search import es_fulltext_search
from .vector_search import vector_search
from ..ingestion.vectorizer import embed_query
from .rerank import rerank
from .execution_control import RetrievalExecutionAborted, RetrievalExecutionControl

logger = logging.getLogger("uvicorn.error")

COMMUNITY_WEIGHT = 0.45
SURPRISING_WEIGHT = 0.42
GOD_WEIGHT = 0.48

GRAPH_MARKER_WEIGHTS = {
    "community": COMMUNITY_WEIGHT,
    "surprising": SURPRISING_WEIGHT,
    "god": GOD_WEIGHT,
}

CHANNEL_WEIGHTS = {
    "dense": VECTOR_WEIGHT,
    "bm25": BM25_WEIGHT,
    "graph": GRAPH_WEIGHT,
}


def hybrid_search(
    query: str,
    top_k: int = 10,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
) -> list[dict]:
    """Best-effort adapter for legacy callers that have no authorized scope.

    Scoped production retrieval never calls this function. It intentionally
    stays in this module as a monkeypatch-compatible migration seam.
    """
    try:
        from .bm25_search import bm25_search

        rows = bm25_search(query, top_k=top_k)
    except Exception:
        return []
    if allowed_item_ids:
        rows = [row for row in rows if row.get("item_id") in allowed_item_ids]
    return rows[:top_k]


def recall(
    query: str,
    query_embedding: list[float],
    scope: SearchScope,
    *,
    graph_client=None,
    top_k: int = 30,
    hops: int = 1,
    control: RetrievalExecutionControl | None = None,
) -> dict:
    """Call each enabled raw channel once and fuse their results once."""
    if control: control.checkpoint()
    dense = vector_search(query_embedding, scope, top_k, **({"control": control} if control else {}))
    if control: control.checkpoint()
    bm25 = es_fulltext_search(query, scope, top_k, **({"control": control} if control else {}))
    if scope.graph_generation and graph_client is not None:
        graph = graph_search(query, scope, graph_client, top_k, hops, **({"control": control} if control else {}))
    else:
        graph = ChannelResult.failed("graph", "GRAPH_UNAVAILABLE", retryable=False)

    channels = [dense, bm25, graph]
    fused = weighted_rrf(channels, CHANNEL_WEIGHTS)
    failed = [result for result in channels if result.health == "failed"]
    if fused:
        status = "degraded" if failed else "ok"
    elif dense.health == "failed" and bm25.health == "failed" and graph.health == "failed":
        status = "unavailable"
    elif failed:
        status = "degraded"
    else:
        status = "no_hits"
    return {"status": status, "results": fused, "channels": channels}


def scoped_text_hybrid_search(
    query: str,
    scope: SearchScope,
    top_k: int = 10,
) -> list[dict]:
    """Return scoped dense + BM25 recall in the compatibility SearchHit shape."""
    if not isinstance(scope, SearchScope):
        raise ValueError("SearchScope is required for scoped text hybrid retrieval")

    try:
        query_embedding = embed_query(query)
    except Exception as exc:
        logger.warning("[unified] scoped_embedding_failed err=%s", exc)
        query_embedding = []

    recalled = recall(
        query,
        query_embedding,
        scope,
        graph_client=None,
        top_k=top_k,
    )
    hits = []
    for row in recalled["results"]:
        hits.append(
            {
                **dict(row.get("metadata") or {}),
                "chunk_id": row["chunk_uid"],
                "item_id": row["item_id"],
                "file_uid": row["file_uid"],
                "score": row["rrf_score"],
                "channels": row["channels"],
            }
        )
    return hits[:top_k]


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
                for row in db.query(KnowledgeChunk.chunk_uid)
                .filter(KnowledgeChunk.chunk_uid.in_(chunk_ids))
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


def _load_child_texts(db, hits: list[dict], scope: SearchScope) -> list[dict]:
    """Attach child text by public chunk_uid before cross-encoder reranking."""
    if db is None or not hits:
        return hits
    from backend.app.models import KnowledgeChunk

    chunk_uids = [str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")]
    if not chunk_uids:
        return hits
    try:
        rows = (
            db.query(
                KnowledgeChunk.chunk_uid,
                KnowledgeChunk.file_uid,
                KnowledgeChunk.item_id,
                KnowledgeChunk.chunk_text,
            )
            .filter(
                KnowledgeChunk.chunk_uid.in_(chunk_uids),
                KnowledgeChunk.tenant_id == scope.tenant_id,
                KnowledgeChunk.kb_uid == scope.kb_uid,
                KnowledgeChunk.chunk_type == "child",
            )
            .all()
        )
    except Exception as exc:
        logger.warning("[unified] child_text_load_failed err=%s", exc)
        return hits
    texts = {
        (str(chunk_uid), str(file_uid or ""), str(item_id or "")): text
        for chunk_uid, file_uid, item_id, text in rows
    }
    fallback_texts = {
        str(chunk_uid): text
        for chunk_uid, _file_uid, _item_id, text in rows
    }
    loaded: list[dict] = []
    for hit in hits:
        chunk_id = hit.get("chunk_id")
        if not chunk_id:
            loaded.append(hit)
            continue
        key = (
            str(chunk_id),
            str(hit.get("file_uid") or ""),
            str(hit.get("item_id") or ""),
        )
        text = texts.get(key)
        if text is None:
            text = fallback_texts.get(str(chunk_id))
        loaded.append({**hit, "text": text} if text is not None else hit)
    return loaded


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


def _public_hit(hit: dict) -> dict:
    """Trim index-only duplicate fields before exposing retrieval hits."""
    if "text" in hit and "content" in hit:
        hit = dict(hit)
        hit.pop("content", None)
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


def _legacy_unscoped_search(
    query: str,
    top_k: int,
    *,
    mode: str,
    db,
    graph_client,
    topic_ids: list[str] | None,
    source_types: list[str] | None,
    allowed_item_ids: set[str] | None,
) -> list[dict]:
    """Preserve the pre-scope adapter without entering scoped production."""
    hybrid_hits = hybrid_search(
        query,
        top_k=top_k,
        topic_ids=topic_ids,
        source_types=source_types,
        allowed_item_ids=allowed_item_ids,
    ) or []
    hybrid_hits = _filter_stale_hits(db, hybrid_hits)

    graph_hits: list[dict] = []
    if graph_client is not None:
        hops = settings.GRAPH_EXPAND_FAST_HOPS if mode == "fast" else settings.GRAPH_EXPAND_DEEP_HOPS
        seeds = match_seed_entities(db, query, limit=settings.GRAPH_EXPAND_SEED_ENTITIES)
        graph_hits = expand_candidates(
            db,
            graph_client,
            seeds,
            mode=mode,
            hops=hops,
            max_candidates=settings.GRAPH_EXPAND_MAX_CANDIDATES,
            neighbors_per_node=settings.GRAPH_EXPAND_NEIGHBORS_PER_NODE,
            community_members=settings.GRAPH_EXPAND_COMMUNITY_MEMBERS,
            god_neighbors=settings.GRAPH_EXPAND_GOD_NEIGHBORS,
        )
    graph_hits = _filter_stale_hits(db, graph_hits)

    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, hit in enumerate(hybrid_hits, 1):
        key = _hit_key(hit)
        scores[key] = scores.get(key, 0.0) + VECTOR_WEIGHT / (RRF_K + rank)
        meta.setdefault(key, dict(hit))
    for rank, hit in enumerate(graph_hits, 1):
        enriched = _enrich_graph_hit(db, hit)
        key = _hit_key(enriched)
        scores[key] = scores.get(key, 0.0) + _graph_marker_weight(enriched) / (RRF_K + rank)
        if key in meta:
            _merge_source_marker(meta[key], enriched)
            _merge_missing_fields(meta[key], enriched)
        else:
            meta[key] = dict(enriched)

    candidates = []
    for key, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        hit = {**meta[key], "score": score}
        hit["graph_rag"] = _build_graph_rag_payload(hit)
        candidates.append(hit)
    reranked = rerank(query, candidates, top_n=max(top_k, settings.RERANK_TOP_N))
    return [_public_hit(_restore_graph_source_marker(hit)) for hit in reranked[:top_k]]


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
    scope: SearchScope | None = None,
    allow_legacy_unscoped: bool = False,
    graph_hops: int | None = None,
    diagnostics: dict | None = None,
    control: RetrievalExecutionControl | None = None,
) -> list[dict]:
    """Compatibility SearchHit adapter over the single-fusion recall path."""
    if scope is None:
        if not allow_legacy_unscoped:
            logger.warning("[unified] unscoped_retrieval_rejected")
            return []
        return _legacy_unscoped_search(
            query,
            top_k,
            mode=mode,
            db=db,
            graph_client=graph_client,
            topic_ids=topic_ids,
            source_types=source_types,
            allowed_item_ids=allowed_item_ids,
        )
    try:
        if control: control.checkpoint()
        embedding = embed_query(query, **({"timeout": control.remaining_timeout(30)} if control else {}))
        if control: control.checkpoint()
    except RetrievalExecutionAborted:
        raise
    except Exception as exc:
        logger.warning("[unified] embedding_failed err=%s", exc)
        embedding = []
    hops = graph_hops if graph_hops is not None else (
        settings.GRAPH_EXPAND_FAST_HOPS if mode == "fast" else settings.GRAPH_EXPAND_DEEP_HOPS
    )
    recalled = recall(
        query,
        embedding,
        scope,
        graph_client=graph_client,
        top_k=max(top_k, settings.RERANK_TOP_N),
        hops=hops,
        control=control,
    )
    channel_warnings = [
        result.problem.model_dump()
        for result in recalled["channels"]
        if result.problem is not None
    ]
    candidates = []
    for row in recalled["results"]:
        metadata = dict(row.get("metadata") or {})
        hit = {
            **metadata,
            "chunk_id": row["chunk_uid"],
            "item_id": row["item_id"],
            "file_uid": row["file_uid"],
            "score": row["rrf_score"],
            "channels": row["channels"],
        }
        if "graph" in row["channels"] and not hit.get("source_marker"):
            hit["source_marker"] = "graph_scoped"
        hit = _enrich_graph_hit(db, hit)
        hit["graph_rag"] = _build_graph_rag_payload(hit)
        candidates.append(hit)
    if control: control.checkpoint()
    candidates = _filter_stale_hits(db, candidates)
    if control: control.checkpoint()
    candidates = _load_child_texts(db, candidates, scope)
    if control: control.checkpoint()

    # Rerank child text here; the answer layer expands selected hits to parent
    # context later (small-to-big).
    top_n = max(top_k, settings.RERANK_TOP_N)
    rerank_warnings: list[dict] = []
    rerank_kwargs = {"warnings": rerank_warnings}
    if control: rerank_kwargs["control"] = control
    reranked = rerank(query, candidates, top_n=top_n, **rerank_kwargs)
    if rerank_warnings:
        reranked = [{**hit, "warnings": list(rerank_warnings)} for hit in reranked]
    if diagnostics is not None:
        warnings = [*channel_warnings, *rerank_warnings]
        status = recalled["status"]
        if rerank_warnings and status in {"ok", "no_hits"}:
            status = "degraded"
        diagnostics.update({"status": status, "warnings": warnings})
    return [_public_hit(_restore_graph_source_marker(hit)) for hit in reranked[:top_k]]


def make_unified_search(
    mode: str,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
    scope: SearchScope | None = None,
):
    """Return a SearchFn(query, top_k) closed over scope filters + graph client.

    Lazy-imports db session + GraphClient so module import stays cheap and tests
    can monkeypatch the helpers.
    """
    def _search(
        query: str,
        top_k: int,
        *,
        mode: str = mode,
        graph_hops: int | None = None,
    ) -> list[dict]:
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
                scope=scope, graph_hops=graph_hops,
            )
        finally:
            if db is not None:
                try: db.close()
                except Exception: pass
            if graph_client is not None:
                try: graph_client.close()
                except Exception: pass

    return _search
