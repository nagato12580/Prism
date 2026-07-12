# prism/engine/app/es_client.py
"""Elasticsearch 客户端封装（同步）与索引管理。

索引 prism_chunks: 存储文档 chunk 全文 + 元数据，IK 中文分词。
"""
from elasticsearch import Elasticsearch

from .config import settings

_client: Elasticsearch | None = None

CHUNKS_INDEX = "prism_chunks"

_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "topic_id": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},
            "parent_id": {"type": "keyword"},
            "content": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart",
            },
            "doc_name": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "created_at": {"type": "date"},
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
}


def get_es() -> Elasticsearch:
    """获取 ES 同步客户端单例。"""
    global _client
    if _client is None:
        auth = None
        if settings.ES_USERNAME:
            auth = (settings.ES_USERNAME, settings.ES_PASSWORD)
        _client = Elasticsearch(
            hosts=[settings.ES_HOST],
            basic_auth=auth,
            max_retries=3,
            retry_on_timeout=True,
            request_timeout=30,
        )
    return _client


def ensure_index() -> None:
    """确保 prism_chunks 索引存在，不存在则创建。"""
    es = get_es()
    if not es.indices.exists(index=CHUNKS_INDEX):
        es.indices.create(index=CHUNKS_INDEX, body=_INDEX_MAPPING)


def ping() -> bool:
    """ES 健康检查。"""
    try:
        return get_es().ping()
    except Exception:
        return False
