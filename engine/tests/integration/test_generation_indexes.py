"""Real Milvus and Elasticsearch contract gate for generation isolation."""
import os
from uuid import uuid4

from elasticsearch import Elasticsearch
from pymilvus import utility

from engine.app.indexing.es_index import ensure_v2_index
from engine.app.indexing.milvus_index import MilvusGenerationIndex, ensure_collection
from engine.app.indexing.profiles import EmbeddingProfile
from engine.app.indexing.publisher import GenerationScope


def _row(tenant, kb, generation, chunk):
    return {
        "tenant_id": tenant,
        "kb_uid": kb,
        "file_uid": "file-real",
        "item_id": "item-real",
        "chunk_uid": chunk,
        "source_type": "document",
        "generation": generation,
        "embedding_model_version": "integration-profile",
        "content": "generation isolated content",
        "parent_text": "parent",
        "title": "Real service gate",
        "page_start": 1,
        "page_end": 1,
        "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1, 0.2],
    }


def test_real_milvus_generation_index_is_scoped_and_deletable():
    suffix = uuid4().hex[:10]
    profile = EmbeddingProfile("integration", suffix, 2, "COSINE", True)
    collection = ensure_collection(
        profile,
        host=os.getenv("MILVUS_TEST_HOST", "127.0.0.1"),
        port=int(os.getenv("MILVUS_TEST_PORT", "19530")),
    )
    milvus = MilvusGenerationIndex(collection)
    wanted = GenerationScope("tenant-real", f"kb-{suffix}", "gen-new")
    other = GenerationScope("tenant-real", f"kb-other-{suffix}", "gen-new")
    try:
        milvus.write([
            _row(wanted.tenant_id, wanted.kb_uid, wanted.generation, "chunk-wanted"),
            _row(other.tenant_id, other.kb_uid, other.generation, "chunk-other"),
        ])
        assert milvus.count(wanted) == 1
        assert milvus.sample(wanted, "chunk-wanted") is True

        milvus.delete_generation(wanted)
        assert milvus.count(wanted) == 0
        assert milvus.count(other) == 1
    finally:
        if utility.has_collection(profile.document_collection):
            utility.drop_collection(profile.document_collection)


def test_real_elasticsearch_generation_index_is_scoped_and_deletable():
    suffix = uuid4().hex[:10]
    es_client = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=10)
    es_name = f"prism_chunks_v2_test_{suffix}"
    es = ensure_v2_index(es_client, es_name)
    wanted = GenerationScope("tenant-real", f"kb-{suffix}", "gen-new")
    other = GenerationScope("tenant-real", f"kb-other-{suffix}", "gen-new")
    try:
        es.write([
            _row(wanted.tenant_id, wanted.kb_uid, wanted.generation, "chunk-wanted"),
            _row(other.tenant_id, other.kb_uid, other.generation, "chunk-other"),
        ])
        assert es.count(wanted) == 1
        assert es.sample(wanted, "chunk-wanted") is True
        es.delete_generation(wanted)
        assert es.count(wanted) == 0
        assert es.count(other) == 1
    finally:
        if es_client.indices.exists(index=es_name):
            es_client.indices.delete(index=es_name)
        es_client.close()
