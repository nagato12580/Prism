from engine.app.retrieval.contracts import SearchScope


def _scope(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "kb_uid": "kb-a",
        "index_generation": "index-a",
        "graph_generation": "graph-a",
        "file_uids": ("file-a",),
        "source_types": ("document",),
    }
    values.update(overrides)
    return SearchScope(**values)


def test_dense_passes_complete_native_scope_to_milvus(monkeypatch):
    from engine.app.retrieval import vector_search as module

    seen = {}

    def search_index(**kwargs):
        seen.update(kwargs)
        return [{"chunk_uid": "chunk-a", "item_id": "item-a", "file_uid": "file-a", "score": 0.9}]

    monkeypatch.setattr(module, "search_index", search_index)
    scope = _scope()
    result = module.vector_search([0.1, 0.2], scope, top_k=50)

    assert seen == {"query_embedding": [0.1, 0.2], "scope": scope, "top_k": 50}
    assert result.health == "ok"
    assert result.candidates[0].metadata["kb_uid"] == "kb-a"


def test_dense_caps_milvus_timeout_to_remaining_execution_budget(monkeypatch):
    from engine.app.retrieval import vector_search as module
    from engine.app.retrieval.execution_control import RetrievalExecutionControl

    seen = {}
    monkeypatch.setattr(module, "search_index", lambda **kwargs: seen.update(kwargs) or [])
    control = RetrievalExecutionControl.with_timeout(60)
    module.vector_search([0.1], _scope(), 10, control=control)

    assert 0 < seen["timeout"] <= 15


def test_dense_failure_is_typed(monkeypatch):
    from engine.app.retrieval import vector_search as module

    def search_index(**kwargs):
        raise TimeoutError("client retries exhausted")

    monkeypatch.setattr(module, "search_index", search_index)
    result = module.vector_search([0.1], _scope(), top_k=10)
    assert result.health == "failed"
    assert result.problem.code == "VECTOR_INDEX_UNAVAILABLE"
    assert result.problem.retryable is True


def test_dense_empty_embedding_is_typed_as_embedding_unavailable():
    from engine.app.retrieval import vector_search as module

    result = module.vector_search([], _scope(), top_k=10)

    assert result.health == "failed"
    assert result.problem.code == "EMBEDDING_UNAVAILABLE"
    assert result.problem.retryable is True
    assert "keyword retrieval" in result.problem.message


def test_dense_malformed_response_is_typed(monkeypatch):
    from engine.app.retrieval import vector_search as module
    monkeypatch.setattr(module, "search_index", lambda **kwargs: [{"score": "bad"}])
    result = module.vector_search([0.1], _scope(), top_k=10)
    assert result.health == "failed"
    assert result.problem.code == "VECTOR_RESPONSE_INVALID"


def test_bm25_uses_bool_scope_filters_and_routing(monkeypatch):
    from engine.app.retrieval import es_search as module

    seen = {}

    class ES:
        def search(self, **kwargs):
            seen.update(kwargs)
            return {"hits": {"hits": [{"_score": 2.0, "_source": {
                "chunk_uid": "chunk-a", "item_id": "item-a", "file_uid": "file-a",
                "kb_uid": "kb-a", "source_type": "document",
            }}]}}

    monkeypatch.setattr(module, "get_es", lambda: ES())
    result = module.es_fulltext_search("same text", _scope(), top_k=20)

    assert seen["routing"] == "kb-a"
    terms = seen["query"]["bool"]["filter"]
    assert {next(iter(term.get("term", term.get("terms")))) for term in terms} == {
        "tenant_id", "kb_uid", "generation", "file_uid", "source_type",
    }
    assert result.health == "ok"


def test_bm25_failure_is_typed(monkeypatch):
    from engine.app.retrieval import es_search as module

    class ES:
        def search(self, **kwargs):
            raise ConnectionError("client retries exhausted")

    monkeypatch.setattr(module, "get_es", lambda: ES())
    result = module.es_fulltext_search("query", _scope(), top_k=10)
    assert result.health == "failed"
    assert result.problem.code == "FULLTEXT_INDEX_UNAVAILABLE"
    assert result.problem.retryable is True


def test_bm25_passes_remaining_budget_as_request_timeout(monkeypatch):
    from engine.app.retrieval import es_search as module
    from engine.app.retrieval.execution_control import RetrievalExecutionControl
    seen = {}
    class ScopedES:
        def search(self, **kwargs):
            seen.update(kwargs)
            return {"hits": {"hits": []}}
    class ES:
        def options(self, **kwargs):
            seen["options"] = kwargs
            return ScopedES()
    monkeypatch.setattr(module, "get_es", lambda: ES())
    module.es_fulltext_search("q", _scope(), 10, RetrievalExecutionControl.with_timeout(60))
    assert 0 < seen["options"]["request_timeout"] <= 30
    assert seen["options"]["max_retries"] == 0
    assert seen["options"]["retry_on_timeout"] is False
    assert "request_timeout" not in seen


def test_bm25_malformed_response_is_typed(monkeypatch):
    from engine.app.retrieval import es_search as module
    class ES:
        def search(self, **kwargs):
            return {"hits": {"hits": [{"_score": "bad", "_source": {}}]}}
    monkeypatch.setattr(module, "get_es", lambda: ES())
    result = module.es_fulltext_search("query", _scope(), top_k=10)
    assert result.health == "failed"
    assert result.problem.code == "FULLTEXT_RESPONSE_INVALID"


class RecordingGraph:
    def __init__(self):
        self.calls = []

    def _execute_read(self, query, params):
        self.calls.append((query, params))
        if "seed_entities" in query:
            return [{"entity_id": "entity-a"}]
        if "source_paths" in query:
            return [{"chunk_uid": "chunk-a", "item_id": "item-a", "file_uid": "file-a",
                     "source_type": "document", "score": 1.0, "path": ["entity-a", "chunk-a"]}]
        return []


def test_graph_every_seed_community_and_path_query_is_fully_scoped():
    from engine.app.retrieval.graph_expand import graph_search

    graph = RecordingGraph()
    result = graph_search("query", _scope(), graph, top_k=30, hops=2)

    assert result.health == "ok"
    assert len(graph.calls) == 2
    assert not any("community" in query.lower() for query, _ in graph.calls)
    for query, params in graph.calls:
        assert params["tenant_id"] == "tenant-a"
        assert params["kb_uid"] == "kb-a"
        assert params["generation"] == "graph-a"
        assert params["file_uids"] == ["file-a"]
        assert params["source_types"] == ["document"]
        assert "tenant_id" in query and "kb_uid" in query and "generation" in query
    path_query = next(query for query, _ in graph.calls if "source_paths" in query)
    assert "s.chunk_uid AS chunk_uid" in path_query
    assert "s.source_id AS chunk_uid" not in path_query


def test_graph_requires_graph_generation_without_calling_client():
    from engine.app.retrieval.graph_expand import graph_search

    graph = RecordingGraph()
    result = graph_search("query", _scope(graph_generation=None), graph, top_k=10, hops=1)
    assert result.health == "failed"
    assert result.problem.code == "GRAPH_GENERATION_REQUIRED"
    assert graph.calls == []


def test_graph_passes_managed_transaction_timeout(monkeypatch):
    from engine.app.retrieval.execution_control import RetrievalExecutionControl
    from engine.app.retrieval.graph_expand import graph_search
    timeouts = []
    class Graph:
        def _execute_read(self, query, _params, *, timeout):
            timeouts.append(timeout)
            return [{"entity_id": "e"}] if "seed_entities" in query else []
    graph_search("query", _scope(), Graph(), 10, 1, RetrievalExecutionControl.with_timeout(60))
    assert len(timeouts) == 2
    assert all(0 < timeout <= 30 for timeout in timeouts)


def test_graph_malformed_response_is_typed():
    class Graph(RecordingGraph):
        def _execute_read(self, query, params):
            if "seed_entities" in query:
                return [{"entity_id": "entity-a"}]
            if "source_paths" in query:
                return [{"score": "bad"}]
            return []
    result = __import__("engine.app.retrieval.graph_expand", fromlist=["graph_search"]).graph_search(
        "query", _scope(), Graph(), 10, 1
    )
    assert result.health == "failed"
    assert result.problem.code == "GRAPH_RESPONSE_INVALID"
