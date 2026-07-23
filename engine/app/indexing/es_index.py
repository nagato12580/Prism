# engine/app/indexing/es_index.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from elasticsearch import Elasticsearch


def _client(host: str = "http://127.0.0.1:9200"):
    try:
        return Elasticsearch([host])
    except Exception:
        raise RuntimeError("ELASTICSEARCH_UNAVAILABLE")


INDEX_NAME = "prism_knowledge_dev"


def ensure_index(es=None):
    es = es or _client()
    if es.indices.exists(index=INDEX_NAME):
        return es
    es.indices.create(
        index=INDEX_NAME,
        body={
            "mappings": {
                "properties": {
                    "kb_uid": {"type": "keyword"},
                    "file_uid": {"type": "keyword"},
                    "chunk_uid": {"type": "keyword"},
                    "generation": {"type": "keyword"},
                    "chunk_text": {"type": "text"},
                }
            }
        },
    )
    return es


def write_chunks(
    es,
    kb_uid: str,
    file_uid: str,
    generation: str,
    chunks: list[dict],
):
    if not chunks:
        return
    from elasticsearch.helpers import bulk
    actions = [
        {
            "_index": INDEX_NAME,
            "_id": f"{chunk['chunk_uid']}:{generation}",
            "_source": {
                "kb_uid": kb_uid,
                "file_uid": file_uid,
                "chunk_uid": chunk["chunk_uid"],
                "generation": generation,
                "chunk_text": chunk["chunk_text"],
            },
        }
        for chunk in chunks
    ]
    bulk(es, actions)


def delete_by_file_uid(es, file_uid: str):
    es.delete_by_query(
        index=INDEX_NAME,
        body={"query": {"term": {"file_uid": file_uid}}},
    )
