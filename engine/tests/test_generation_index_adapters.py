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
        "content": "text", "embedding": [0.1, 0.2],
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
