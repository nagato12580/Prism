"""Scoped dense + BM25 retrieval and RRF compatibility adapter."""
from ..ingestion.vectorizer import embed_query
from .contracts import SearchScope
from .es_search import es_fulltext_search
from .vector_search import vector_search

RRF_K = 60
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4


def hybrid_search(query: str, scope: SearchScope, top_k: int = 10) -> list[dict]:
    """Fuse only natively-scoped channels; no SQL/post-filter fallback."""
    try:
        dense = vector_search(embed_query(query), scope, top_k * 3)
    except Exception:
        from .contracts import ChannelResult
        dense = ChannelResult.failed("dense", "EMBEDDING_UNAVAILABLE", retryable=True)
    bm25 = es_fulltext_search(query, scope, top_k * 2)
    if dense.health == "failed" and bm25.health == "failed":
        raise RuntimeError("RETRIEVAL_CHANNELS_UNAVAILABLE")
    scores, meta = {}, {}
    for weight, result in ((VECTOR_WEIGHT, dense), (BM25_WEIGHT, bm25)):
        if result.health == "failed":
            continue
        for rank, candidate in enumerate(result.candidates):
            key = candidate.chunk_uid
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank + 1)
            meta.setdefault(key, candidate)
    merged = [{"chunk_id": key, "item_id": meta[key].item_id, "file_uid": meta[key].file_uid,
               "score": score, "raw_score": meta[key].raw_score} for key, score in scores.items()]
    return sorted(merged, key=lambda item: item["score"], reverse=True)[:top_k]
