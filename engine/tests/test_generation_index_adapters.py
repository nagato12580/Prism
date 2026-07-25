import pytest

from engine.app.indexing.publisher import GenerationScope


class FakeMilvusCollection:
    def __init__(self):
        self.inserted = []
        self.queries = []
        self.deleted = []
        self.flush_calls = []

    def insert(self, rows, **kwargs):
        self.inserted.extend(rows)

    def flush(self, **kwargs):
        self.flush_calls.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return [{"count(*)": len(self.inserted)}]

    def delete(self, expr, **kwargs):
        self.deleted.append(expr)


def test_milvus_write_omits_indexed_at_for_legacy_schema():
    from engine.app.indexing.milvus_index import MilvusGenerationIndex
    fields = ("id", "tenant_id", "kb_uid", "file_uid", "item_id", "chunk_uid",
              "source_type", "generation", "embedding_model_version", "content", "embedding")
    collection = FakeMilvusCollection()
    collection.schema = type("Schema", (), {"fields": [type("F", (), {"name": n})() for n in fields]})()
    row = {name: name for name in fields if name != "id"}
    row["indexed_at"] = "2026-07-23T00:00:00"
    row["embedding"] = [0.1]
    MilvusGenerationIndex(collection).write([row])
    assert "indexed_at" not in collection.inserted[0]


def test_milvus_write_uses_configured_operation_timeout(monkeypatch):
    from engine.app.indexing import milvus_index
    from engine.app.indexing.milvus_index import MilvusGenerationIndex

    monkeypatch.setattr(milvus_index.settings, "MILVUS_OPERATION_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(milvus_index.settings, "MILVUS_FLUSH_AFTER_WRITE", True, raising=False)
    collection = FakeMilvusCollection()
    row = {
        "tenant_id": "tenant-a", "kb_uid": "kb-a", "file_uid": "file-a",
        "item_id": "item-a", "chunk_uid": "chunk-a", "source_type": "document",
        "generation": "gen-a", "embedding_model_version": "profile-a",
        "content": "text", "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1],
    }

    MilvusGenerationIndex(collection).write([row])

    assert collection.flush_calls == [{"timeout": 90}]


def test_milvus_write_can_skip_flush_when_explicitly_disabled(monkeypatch):
    from engine.app.indexing import milvus_index
    from engine.app.indexing.milvus_index import MilvusGenerationIndex

    monkeypatch.setattr(milvus_index.settings, "MILVUS_OPERATION_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(milvus_index.settings, "MILVUS_FLUSH_AFTER_WRITE", False, raising=False)
    collection = FakeMilvusCollection()
    row = {
        "tenant_id": "tenant-a", "kb_uid": "kb-a", "file_uid": "file-a",
        "item_id": "item-a", "chunk_uid": "chunk-a", "source_type": "document",
        "generation": "gen-a", "embedding_model_version": "profile-a",
        "content": "text", "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1],
    }

    MilvusGenerationIndex(collection).write([row])

    assert collection.flush_calls == []


def test_milvus_write_records_deadline_exceeded_and_allows_validation(monkeypatch):
    from engine.app.indexing.milvus_index import MilvusGenerationIndex

    class DeadlineExceededCollection(FakeMilvusCollection):
        def flush(self, **kwargs):
            raise RuntimeError(
                '<_MultiThreadedRendezvous of RPC that terminated with:\n'
                '\tstatus = StatusCode.DEADLINE_EXCEEDED\n'
                '\tdetails = "Deadline Exceeded"\n>'
            )

    row = {
        "tenant_id": "tenant-a", "kb_uid": "kb-a", "file_uid": "file-a",
        "item_id": "item-a", "chunk_uid": "chunk-a", "source_type": "document",
        "generation": "gen-a", "embedding_model_version": "profile-a",
        "content": "text", "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1],
    }

    from engine.app.indexing import milvus_index

    monkeypatch.setattr(milvus_index.settings, "MILVUS_FLUSH_AFTER_WRITE", True, raising=False)
    index = MilvusGenerationIndex(DeadlineExceededCollection())
    assert index.write([row]) == 1
    assert "Milvus flush timed out" in index.last_flush_warning


def test_milvus_generation_index_uses_native_full_scope_expression():
    from engine.app.indexing.milvus_index import MilvusGenerationIndex

    collection = FakeMilvusCollection()
    index = MilvusGenerationIndex(collection)
    scope = GenerationScope("tenant-a", "kb-a", "gen-a")

    index.count(scope)
    index.sample(scope, "chunk-a")
    index.delete_generation(scope)

    expressions = [call["expr"] for call in collection.queries] + collection.deleted
    assert all('tenant_id == "tenant-a"' in expr for expr in expressions)
    assert all('kb_uid == "kb-a"' in expr for expr in expressions)
    assert all('generation == "gen-a"' in expr for expr in expressions)
    assert 'chunk_uid == "chunk-a"' in expressions[1]


def test_ensure_existing_milvus_collection_is_loaded_without_reconnecting(monkeypatch):
    from engine.app.indexing import milvus_index
    calls = []
    collection = type("Existing", (), {"load": lambda self, timeout: calls.append(("load", timeout))})()
    monkeypatch.setattr(milvus_index.connections, "has_connection", lambda alias: True)
    monkeypatch.setattr(milvus_index.connections, "connect", lambda *a, **k: calls.append(("connect",)))
    monkeypatch.setattr(milvus_index.utility, "has_collection", lambda name: True)
    monkeypatch.setattr(milvus_index, "Collection", lambda name: collection)
    assert milvus_index.ensure_collection() is collection
    assert calls == [("load", 30)]


def test_env_selected_milvus_search_connects_and_loads_collection(monkeypatch):
    from engine.app.indexing import milvus_index
    from engine.app.retrieval.contracts import SearchScope
    calls = []
    class Collection:
        def load(self, timeout): calls.append(("load", timeout))
        def search(self, **kwargs): return [[]]
    monkeypatch.setenv("PRISM_RETRIEVAL_MILVUS_COLLECTION", "isolated")
    monkeypatch.setattr(milvus_index, "_connect", lambda: calls.append(("connect",)))
    monkeypatch.setattr(milvus_index, "Collection", lambda name: Collection())
    milvus_index.search_index(query_embedding=[0.1], scope=SearchScope(tenant_id="t", kb_uid="k", index_generation="g"), top_k=1)
    assert calls == [("connect",), ("load", 30)]


def test_real_milvus_generation_index_smoke(monkeypatch):
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

    try:
        connections.connect("smoke", host="127.0.0.1", port="19530")
        utility.list_collections(using="smoke", timeout=5)
    except Exception as exc:
        pytest.skip(f"Milvus is not available for smoke test: {exc}")

    from engine.app.indexing import milvus_index
    from engine.app.indexing.milvus_index import MilvusGenerationIndex

    collection_name = "prism_milvus_generation_smoke"
    if utility.has_collection(collection_name, using="smoke"):
        utility.drop_collection(collection_name, using="smoke")
    schema = CollectionSchema([
        FieldSchema("id", DataType.VARCHAR, max_length=100, is_primary=True),
        FieldSchema("tenant_id", DataType.VARCHAR, max_length=36),
        FieldSchema("kb_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("file_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("item_id", DataType.VARCHAR, max_length=36),
        FieldSchema("chunk_uid", DataType.VARCHAR, max_length=36),
        FieldSchema("source_type", DataType.VARCHAR, max_length=32),
        FieldSchema("generation", DataType.VARCHAR, max_length=36),
        FieldSchema("embedding_model_version", DataType.VARCHAR, max_length=32),
        FieldSchema("indexed_at", DataType.VARCHAR, max_length=40),
        FieldSchema("content", DataType.VARCHAR, max_length=65535),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=2),
    ])
    collection = Collection(collection_name, schema, using="smoke")
    try:
        collection.create_index(
            "embedding",
            {"metric_type": "COSINE", "index_type": "FLAT", "params": {}},
            timeout=30,
        )
        collection.load(timeout=30)
        monkeypatch.setattr(milvus_index.settings, "MILVUS_FLUSH_AFTER_WRITE", True, raising=False)
        index = MilvusGenerationIndex(collection)
        scope = GenerationScope("tenant-smoke", "kb-smoke", "gen-smoke")
        row = {
            "tenant_id": scope.tenant_id, "kb_uid": scope.kb_uid, "file_uid": "file-smoke",
            "item_id": "item-smoke", "chunk_uid": "chunk-smoke", "source_type": "document",
            "generation": scope.generation, "embedding_model_version": "smoke",
            "content": "smoke text", "indexed_at": "2026-07-25T00:00:00",
            "embedding": [1.0, 0.0],
        }

        assert index.write([row]) == 1
        assert index.count(scope) == 1
        assert index.sample(scope, "chunk-smoke") is True
        hits = collection.search(
            data=[[1.0, 0.0]],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=1,
            expr='tenant_id == "tenant-smoke" and kb_uid == "kb-smoke" and generation == "gen-smoke"',
            output_fields=["chunk_uid"],
            timeout=30,
        )
        assert hits and hits[0] and hits[0][0].entity.get("chunk_uid") == "chunk-smoke"
        index.delete_generation(scope)
    finally:
        if utility.has_collection(collection_name, using="smoke"):
            utility.drop_collection(collection_name, using="smoke")
        connections.disconnect("smoke")


class FakeES:
    def __init__(self):
        self.bulk_operations = None
        self.search_calls = []
        self.delete_calls = []

    def bulk(self, **kwargs):
        self.bulk_operations = kwargs["operations"]
        return {"errors": False}

    def count(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"count": 1}

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"hits": {"hits": [{"_id": "hit"}]}}

    def delete_by_query(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {"failures": [], "timed_out": False}


def test_es_generation_index_routes_and_filters_by_full_scope():
    from engine.app.indexing.es_index import ElasticsearchGenerationIndex

    es = FakeES()
    index = ElasticsearchGenerationIndex(es, "prism_chunks_v2")
    scope = GenerationScope("tenant-a", "kb-a", "gen-a")
    row = {
        "tenant_id": "tenant-a", "kb_uid": "kb-a", "file_uid": "file-a",
        "item_id": "item-a", "chunk_uid": "chunk-a", "source_type": "document",
        "generation": "gen-a", "embedding_model_version": "profile-a",
        "content": "text", "indexed_at": "2026-07-23T00:00:00",
        "embedding": [0.1, 0.2],
    }

    assert index.write([row]) == 1
    assert index.count(scope) == 1
    assert index.sample(scope, "chunk-a") is True
    index.delete_generation(scope)

    assert es.bulk_operations[0]["index"]["routing"] == "kb-a"
    assert all(call["routing"] == "kb-a" for call in es.search_calls)
    assert es.delete_calls[0]["routing"] == "kb-a"
    filters = es.search_calls[0]["query"]["bool"]["filter"]
    assert {next(iter(term["term"])) for term in filters} == {
        "tenant_id", "kb_uid", "generation"
    }
