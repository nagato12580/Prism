# prism/engine/app/retrieval/es_search.py
"""ES 全文检索：BM25 评分 + IK 中文分词 + topic 范围过滤。

ES match 查询默认使用 BM25 算法，支持 IK 分词器处理中文文本。
"""
from ..es_client import get_es, CHUNKS_INDEX
from ..config import settings


def es_fulltext_search(
    query: str,
    top_k: int = 10,
    topic_ids: list[str] | None = None,
    source_types: list[str] | None = None,
) -> list[dict]:
    """ES 全文检索（BM25），返回 [{chunk_id, item_id, score}]。

    Args:
        query: 检索查询文本
        top_k: 返回结果数
        topic_ids: 可选，限定检索的主题 ID 列表
        source_types: 可选，限定来源类型列表（document/image/audio/video）
    """
    es = get_es()
    filters: list[dict] = []
    if topic_ids:
        filters.append({"terms": {"topic_id": topic_ids}})
    if source_types:
        filters.append({"terms": {"source_type": source_types}})

    body: dict = {
        "size": top_k,
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "content": {
                                "query": query,
                                "analyzer": "ik_smart",
                            }
                        }
                    }
                ],
            }
        },
    }

    if filters:
        body["query"]["bool"]["filter"] = filters

    try:
        resp = es.search(index=CHUNKS_INDEX, body=body)
    except Exception:
        return []

    results = []
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        results.append(
            {
                "chunk_id": src.get("chunk_id", hit["_id"]),
                "item_id": src.get("item_id", ""),
                "score": float(hit["_score"]),
            }
        )
    return results
