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

    # 3) RRF fusion of hybrid + graph candidates
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for rank, h in enumerate(hybrid_hits):
        cid = h["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + VECTOR_WEIGHT / (RRF_K + rank + 1)  # hybrid already fused; treat as primary
        meta.setdefault(cid, h)
    for rank, h in enumerate(graph_hits):
        cid = h["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + GRAPH_WEIGHT / (RRF_K + rank + 1)
        if cid in meta:
            # Merge source_marker so graph contribution is visible even when
            # the same chunk appeared in hybrid results.
            gm = h.get("source_marker")
            if gm:
                existing = meta[cid].get("source_marker")
                meta[cid]["source_marker"] = f"{existing}+{gm}" if existing else gm
        else:
            meta[cid] = {**h, "score": 0.0}
    merged = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    candidates = [{**meta[cid], "chunk_id": cid, "score": sc} for cid, sc in merged]

    # 4) rerank (degrades gracefully if unavailable)
    top_n = max(top_k, settings.RERANK_TOP_N)
    reranked = rerank(query, candidates, top_n=top_n)
    return reranked[:top_k]


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
