import os
from uuid import uuid4

from elasticsearch import Elasticsearch
from pymilvus import utility

from backend.app.models import KnowledgeChunk, KnowledgeFile, KnowledgeItem, KnowledgeJob, KnowledgeTopic
from backend.app.services.knowledge_cleanup import KnowledgeCleanupService
from backend.app.storage.files import LocalFileStorage
from backend.app.utils.time import local_now
from engine.app.indexing.es_index import ensure_v2_index
from engine.app.indexing.milvus_index import MilvusGenerationIndex, ensure_collection
from engine.app.indexing.profiles import EmbeddingProfile


def test_real_cross_store_delete_is_idempotent(db_session, tmp_path):
    suffix = uuid4().hex[:10]
    profile = EmbeddingProfile("delete-gate", suffix, 2, "COSINE", True)
    collection = ensure_collection(
        profile,
        host=os.getenv("MILVUS_TEST_HOST", "127.0.0.1"),
        port=int(os.getenv("MILVUS_TEST_PORT", "19530")),
    )
    milvus = MilvusGenerationIndex(collection)
    es_client = Elasticsearch(["http://127.0.0.1:9200"], request_timeout=10)
    es_name = f"prism_chunks_v2_delete_{suffix}"
    es = ensure_v2_index(es_client, es_name)
    storage = LocalFileStorage(tmp_path / "storage")
    topic = KnowledgeTopic(tenant_id="tenant-real", owner_user_id="alice", name="Delete")
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id="tenant-real", kb_uid=topic.kb_uid, title="Doc", content="body"
    )
    db_session.add(item)
    db_session.flush()
    file_uid = f"file-{suffix}"
    staged = storage.stage("tenant-real", topic.kb_uid, file_uid, "source.md", b"body")
    uri = storage.commit(staged)
    file_row = KnowledgeFile(
        tenant_id="tenant-real", kb_uid=topic.kb_uid, file_uid=file_uid,
        item_id=item.id, storage_uri=uri, original_filename="source.md", deleted_at=local_now(),
    )
    chunk = KnowledgeChunk(
        tenant_id="tenant-real", kb_uid=topic.kb_uid, file_uid=file_uid,
        item_id=item.id, generation="gen-delete", chunk_uid=f"chunk-{suffix}",
        chunk_text="delete me", chunk_type="child",
    )
    job = KnowledgeJob(
        tenant_id="tenant-real", kb_uid=topic.kb_uid, file_uid=file_uid,
        idempotency_key=f"delete-{suffix}", job_type="delete", status="processing",
    )
    db_session.add_all([file_row, chunk, job])
    db_session.commit()
    row = {
        "tenant_id": "tenant-real", "kb_uid": topic.kb_uid, "file_uid": file_uid,
        "item_id": item.id, "chunk_uid": chunk.chunk_uid, "source_type": "document",
        "generation": "gen-delete", "embedding_model_version": profile.profile_id,
        "content": "delete me", "parent_text": None, "title": "Doc",
        "page_start": 1, "page_end": 1, "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1, 0.2],
    }
    try:
        milvus.write([row])
        es.write([row])
        cleanup = KnowledgeCleanupService(db_session, milvus, es, storage)

        assert cleanup.run(file_uid, job_id=job.id).status == "succeeded"
        assert cleanup.run(file_uid, job_id=job.id).status == "succeeded"
        assert storage.exists(uri) is False
        assert collection.query(
            expr=f'file_uid == "{file_uid}"', output_fields=["file_uid"]
        ) == []
        es_client.indices.refresh(index=es_name)
        assert es_client.count(
            index=es_name,
            query={"bool": {"filter": [
                {"term": {"tenant_id": "tenant-real"}},
                {"term": {"kb_uid": topic.kb_uid}},
                {"term": {"file_uid": file_uid}},
            ]}},
        )["count"] == 0
    finally:
        if utility.has_collection(profile.document_collection):
            utility.drop_collection(profile.document_collection)
        if es_client.indices.exists(index=es_name):
            es_client.indices.delete(index=es_name)
        es_client.close()
