# prism/engine/app/retrieval/hybrid.py
"""混合检索：向量 + BM25，RRF 融合。"""
from .vector_search import vector_search
from .bm25_search import bm25_search

RRF_K = 60
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4


def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """混合检索，返回融合后的 [{chunk_id, item_id, score}]。"""
    vec_results = vector_search(query, top_k=top_k * 2)
    bm_results = bm25_search(query, top_k=top_k * 2)

    # RRF 融合
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for rank, r in enumerate(vec_results):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0) + VECTOR_WEIGHT / (RRF_K + rank + 1)
        meta[cid] = r

    for rank, r in enumerate(bm_results):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0) + BM25_WEIGHT / (RRF_K + rank + 1)
        if cid not in meta:
            meta[cid] = r

    merged = [
        {"chunk_id": cid, "item_id": meta[cid].get("item_id"), "score": sc}
        for cid, sc in scores.items()
    ]
    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:top_k]
