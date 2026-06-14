# prism/engine/app/retrieval/hybrid.py
"""Hybrid retrieval: Milvus vector search + ES BM25 full-text → RRF fusion.

融合策略: Reciprocal Rank Fusion (k=60, 向量 0.6 / BM25 0.4)
ES match 查询默认使用 BM25 算法，支持 IK 中文分词。
ES 不可用时自动回退到 MySQL jieba BM25。
"""
from .es_search import es_fulltext_search
from .vector_search import vector_search

RRF_K = 60
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4

_es_available: bool | None = None


def _check_es() -> bool:
    """检查 ES 是否可用（缓存结果）。"""
    global _es_available
    if _es_available is None:
        try:
            from ..es_client import ping
            _es_available = ping()
        except Exception:
            _es_available = False
    return _es_available


def _bm25_fallback(
    query: str,
    top_k: int,
    allowed_item_ids: set[str] | None,
) -> list[dict]:
    """MySQL jieba BM25 回退检索，支持 item_id 过滤。"""
    from .bm25_search import bm25_search

    results = bm25_search(query, top_k=top_k * 2)
    if allowed_item_ids:
        results = [r for r in results if r["item_id"] in allowed_item_ids]
    return results[:top_k]


def hybrid_search(
    query: str,
    top_k: int = 10,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    allowed_item_ids: set[str] | None = None,
) -> list[dict]:
    """混合检索（RRF 融合），返回 [{chunk_id, item_id, score}]。

    Args:
        query: 检索查询文本
        top_k: 返回结果数
        topic_ids: 可选，限定 ES 检索的主题范围
        source_types: 可选，限定来源类型列表（document/image/audio/video）
        allowed_item_ids: 可选，向量检索后置过滤的 item_id 集合
    """
    # 向量召回
    try:
        vec_results = vector_search(
            query,
            top_k=top_k * 2,
            allowed_item_ids=allowed_item_ids,
        )
    except Exception:
        vec_results = []

    # BM25 全文召回：优先 ES（IK 分词 + topic 过滤），不可用时回退 MySQL jieba
    if _check_es():
        try:
            bm_results = es_fulltext_search(
                query,
                top_k=top_k * 2,
                topic_ids=topic_ids,
                source_types=source_types,
            )
        except Exception:
            bm_results = _bm25_fallback(query, top_k, allowed_item_ids)
    else:
        bm_results = _bm25_fallback(query, top_k, allowed_item_ids)

    # RRF 融合
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
        {
            "chunk_id": chunk_id,
            "item_id": meta[chunk_id].get("item_id"),
            "score": score,
        }
        for chunk_id, score in scores.items()
    ]
    merged.sort(key=lambda item: item["score"], reverse=True)
    return merged[:top_k]
