# prism/engine/app/retrieval/vector_search.py
"""Milvus 向量检索。"""
from ..ingestion.vectorizer import embed_query
from ..milvus_client import search_vectors


def vector_search(query: str, top_k: int = 10) -> list[dict]:
    """语义向量检索，返回 [{chunk_id, item_id, score}]。"""
    query_emb = embed_query(query)
    return search_vectors(query_emb, top_k=top_k)
