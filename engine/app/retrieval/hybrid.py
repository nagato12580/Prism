"""Hybrid retrieval with vector search, BM25, and reciprocal rank fusion."""

from .bm25_search import bm25_search
from .vector_search import vector_search

RRF_K = 60
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4


def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """Return merged retrieval hits as [{chunk_id, item_id, score}]."""
    try:
        vec_results = vector_search(query, top_k=top_k * 2)
    except Exception:
        vec_results = []

    bm_results = bm25_search(query, top_k=top_k * 2)

    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for rank, result in enumerate(vec_results):
        chunk_id = result["chunk_id"]
        scores[chunk_id] = scores.get(chunk_id, 0.0) + VECTOR_WEIGHT / (RRF_K + rank + 1)
        meta[chunk_id] = result

    for rank, result in enumerate(bm_results):
        chunk_id = result["chunk_id"]
        scores[chunk_id] = scores.get(chunk_id, 0.0) + BM25_WEIGHT / (RRF_K + rank + 1)
        if chunk_id not in meta:
            meta[chunk_id] = result

    merged = [
        {"chunk_id": chunk_id, "item_id": meta[chunk_id].get("item_id"), "score": score}
        for chunk_id, score in scores.items()
    ]
    merged.sort(key=lambda item: item["score"], reverse=True)
    return merged[:top_k]
