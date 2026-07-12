# prism/engine/app/retrieval/vector_search.py
"""Milvus 向量检索，支持 item_id 后置过滤。"""
from ..ingestion.vectorizer import embed_query
from ..milvus_client import search_vectors


def vector_search(
    query: str,
    top_k: int = 10,
    allowed_item_ids: set[str] | None = None,
) -> list[dict]:
    """语义向量检索，返回 [{chunk_id, item_id, score}]。

    allowed_item_ids 不为空时，先召回 top_k * 3 再后置过滤到 top_k。
    """
    query_emb = embed_query(query)
    fetch_k = max(top_k * 3, top_k) if allowed_item_ids else top_k
    results = search_vectors(query_emb, top_k=fetch_k)

    if allowed_item_ids:
        results = [r for r in results if r["item_id"] in allowed_item_ids]

    return results[:top_k]
