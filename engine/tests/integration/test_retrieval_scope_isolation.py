"""Real Milvus, Elasticsearch, and Neo4j scope-isolation gate."""
import os
from uuid import uuid4

from elasticsearch import Elasticsearch
from pymilvus import utility

from backend.app.services.graph_client import GraphClient
from engine.app.indexing.es_index import ensure_v2_index
from engine.app.indexing.milvus_index import MilvusGenerationIndex, ensure_collection
from engine.app.indexing.profiles import EmbeddingProfile
from engine.app.retrieval.contracts import SearchScope
from engine.app.retrieval.graph_expand import graph_search
from engine.app.retrieval.vector_search import vector_search
from engine.app.retrieval.es_search import es_fulltext_search


def _row(tenant, kb, generation, chunk, file_uid, source_type):
    return {"tenant_id": tenant, "kb_uid": kb, "generation": generation,
            "chunk_uid": chunk, "item_id": f"item-{chunk}", "file_uid": file_uid,
            "source_type": source_type, "content": "identical scoped text",
            "embedding_model_version": "scope-test", "indexed_at": "2026-07-23T00:00:00",
            "embedding": [1.0, 0.0]}


def test_real_retrieval_scope_isolation():
    suffix = uuid4().hex[:10]
    tenant, generation, graph_generation = f"t-{suffix}", "g1", "gg1"
    k1, k2, es_name = f"k1-{suffix}", f"k2-{suffix}", f"scope_test_{suffix}"
    rows = [_row(tenant, k1, generation, f"c1-{suffix}", "f1", "document"),
            _row(tenant, k1, generation, f"c2-{suffix}", "f2", "url"),
            _row(tenant, k2, generation, f"c3-{suffix}", "f1", "document")]
    scope = SearchScope(tenant_id=tenant, kb_uid=k1, index_generation=generation,
                        graph_generation=graph_generation, file_uids=("f1",), source_types=("document",))
    profile = EmbeddingProfile("scope-test", suffix, 2, "COSINE", True)
    collection = ensure_collection(profile, host=os.getenv("MILVUS_TEST_HOST", "127.0.0.1"),
                                   port=int(os.getenv("MILVUS_TEST_PORT", "19530")))
    es_client = Elasticsearch([os.getenv("ES_TEST_HOST", "http://127.0.0.1:9200")], request_timeout=10)
    es = ensure_v2_index(es_client, es_name)
    graph = GraphClient()
    old_milvus = os.environ.get("PRISM_RETRIEVAL_MILVUS_COLLECTION")
    old_es = os.environ.get("PRISM_RETRIEVAL_ES_INDEX")
    os.environ["PRISM_RETRIEVAL_MILVUS_COLLECTION"] = profile.document_collection
    os.environ["PRISM_RETRIEVAL_ES_INDEX"] = es_name
    try:
        MilvusGenerationIndex(collection).write(rows)
        dense = vector_search([1.0, 0.0], scope, 10)
        assert [candidate.chunk_uid for candidate in dense.candidates] == [rows[0]["chunk_uid"]]

        es.write(rows)
        bm25 = es_fulltext_search("identical scoped text", scope, 10)
        assert [candidate.chunk_uid for candidate in bm25.candidates] == [rows[0]["chunk_uid"]]

        for row in rows:
            entity_id = "shared-entity"
            common = {"tenant_id": tenant, "kb_uid": row["kb_uid"], "graph_generation": graph_generation}
            graph.upsert_scoped_entity({"id": entity_id, "user_id": "test", **common, "entity_type": "concept",
                "canonical_name": "identical scoped text", "normalized_key": "identical scoped text",
                "status": "active", "confidence": 1.0})
            internal_source_id = f"internal-{row['chunk_uid']}"
            graph.upsert_scoped_source({"id": f"document_chunk:{internal_source_id}", **common,
                "chunk_uid": row["chunk_uid"],
                "file_uid": row["file_uid"], "source_type": row["source_type"],
                "source_kind": "document_chunk", "source_id": internal_source_id,
                "item_id": row["item_id"], "title": "scope test"})
            graph.relate_scoped("ScopedEntity", entity_id, "MENTIONED_IN", "ScopedSource", f"document_chunk:{internal_source_id}", scope=common)
        graph_result = graph_search("identical scoped text", scope, graph, 10, 1)
        assert graph_result.health == "ok", graph_result.problem
        assert [candidate.chunk_uid for candidate in graph_result.candidates] == [rows[0]["chunk_uid"]]
    finally:
        graph._execute_write("MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n", {"tenant_id": tenant})
        graph.close()
        if es_client.indices.exists(index=es_name): es_client.indices.delete(index=es_name)
        es_client.close()
        if utility.has_collection(profile.document_collection): utility.drop_collection(profile.document_collection)
        if old_milvus is None: os.environ.pop("PRISM_RETRIEVAL_MILVUS_COLLECTION", None)
        else: os.environ["PRISM_RETRIEVAL_MILVUS_COLLECTION"] = old_milvus
        if old_es is None: os.environ.pop("PRISM_RETRIEVAL_ES_INDEX", None)
        else: os.environ["PRISM_RETRIEVAL_ES_INDEX"] = old_es
