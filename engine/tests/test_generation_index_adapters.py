from engine.app.indexing.publisher import GenerationScope


class FakeMilvusCollection:
    def __init__(self):
        self.inserted = []
        self.queries = []
        self.deleted = []

    def insert(self, rows, **kwargs):
        self.inserted.extend(rows)

    def flush(self, **kwargs):
        pass

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
