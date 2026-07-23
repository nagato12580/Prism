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
V2_INDEX_NAME = "prism_chunks_v2"


V2_PROPERTIES = {
    "tenant_id": {"type": "keyword"},
    "kb_uid": {"type": "keyword"},
    "file_uid": {"type": "keyword"},
    "item_id": {"type": "keyword"},
    "chunk_uid": {"type": "keyword"},
    "source_type": {"type": "keyword"},
    "generation": {"type": "keyword"},
    "embedding_model_version": {"type": "keyword"},
    "content": {"type": "text"},
    "parent_text": {"type": "text"},
    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
    "page_start": {"type": "integer"},
    "page_end": {"type": "integer"},
    "indexed_at": {"type": "date"},
}


def ensure_v2_index(es, index_name=V2_INDEX_NAME):
    if not es.indices.exists(index=index_name):
        es.indices.create(
            index=index_name,
            mappings={"_routing": {"required": True}, "properties": V2_PROPERTIES},
        )
    return ElasticsearchGenerationIndex(es, index_name)


def _scope_filter(scope):
    return [
        {"term": {"tenant_id": scope.tenant_id}},
        {"term": {"kb_uid": scope.kb_uid}},
        {"term": {"generation": scope.generation}},
    ]


class ElasticsearchGenerationIndex:
    def __init__(self, client, index_name=V2_INDEX_NAME):
        self.client = client
        self.index_name = index_name

    def write(self, rows):
        operations = []
        for row in rows:
            operations.extend(
                [
                    {
                        "index": {
                            "_index": self.index_name,
                            "_id": f'{row["chunk_uid"]}:{row["generation"]}',
                            "routing": row["kb_uid"],
                        }
                    },
                    {key: value for key, value in row.items() if key != "embedding"},
                ]
            )
        if not operations:
            return 0
        response = self.client.bulk(operations=operations, refresh="wait_for")
        if response.get("errors"):
            raise RuntimeError("Elasticsearch generation bulk write failed")
        return len(rows)

    def count(self, scope):
        response = self.client.count(
            index=self.index_name,
            routing=scope.kb_uid,
            query={"bool": {"filter": _scope_filter(scope)}},
        )
        return int(response["count"])

    def sample(self, scope, chunk_uid):
        filters = _scope_filter(scope) + [{"term": {"chunk_uid": chunk_uid}}]
        response = self.client.search(
            index=self.index_name,
            routing=scope.kb_uid,
            size=1,
            query={"bool": {"filter": filters}},
        )
        return bool(response["hits"]["hits"])

    def delete_generation(self, scope):
        response = self.client.delete_by_query(
            index=self.index_name,
            routing=scope.kb_uid,
            refresh=True,
            query={"bool": {"filter": _scope_filter(scope)}},
        )
        if response.get("timed_out") or response.get("failures"):
            raise RuntimeError("Elasticsearch generation cleanup failed")
        return response

    def delete_file(self, tenant_id, kb_uid, file_uid):
        response = self.client.delete_by_query(
            index=self.index_name,
            routing=kb_uid,
            refresh=True,
            query={
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant_id}},
                        {"term": {"kb_uid": kb_uid}},
                        {"term": {"file_uid": file_uid}},
                    ]
                }
            },
        )
        if response.get("timed_out") or response.get("failures"):
            raise RuntimeError("Elasticsearch file cleanup failed")
        return response


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
