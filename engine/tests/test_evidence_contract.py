import pytest
from pydantic import ValidationError


def _evidence_values():
    from engine.app.retrieval.evidence import ChannelScore

    return {
        "evidence_id": None,
        "tenant_id": "tenant-a",
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "item_id": "item-a",
        "chunk_uid": "chunk-a",
        "parent_chunk_uid": "parent-a",
        "display_title": "Architecture",
        "original_filename": "architecture.pdf",
        "excerpt": "A bounded excerpt.",
        "page_start": 3,
        "page_end": 4,
        "char_start": 120,
        "char_end": 240,
        "channel_scores": {
            "dense": ChannelScore(raw_score=0.91, raw_rank=1),
            "bm25": ChannelScore(raw_score=7.4, raw_rank=2),
        },
        "rrf_score": 0.028,
        "rerank_score": 0.88,
        "rerank_model": "bge-reranker-v2",
        "retrieval_channels": ("dense", "bm25"),
        "graph_path": ({"entity_id": "entity-a", "relation": "mentions"},),
        "graph_explanation": "Matched the named architecture entity.",
        "evidence_type": "chunk",
        "index_generation": "index-v7",
        "degradation_flags": ("GRAPH_UNAVAILABLE",),
    }


def test_evidence_preserves_provenance_scores_and_generation_and_is_frozen():
    from engine.app.retrieval.evidence import Evidence

    evidence = Evidence(**_evidence_values())

    assert evidence.evidence_id is None
    assert evidence.channel_scores["dense"].raw_rank == 1
    assert evidence.retrieval_channels == ("dense", "bm25")
    assert evidence.graph_path[0]["entity_id"] == "entity-a"
    assert evidence.index_generation == "index-v7"
    with pytest.raises(ValidationError):
        evidence.excerpt = "changed"


def test_evidence_and_response_are_deeply_immutable_and_json_safe():
    from engine.app.retrieval.evidence import ChannelProblem, Evidence, RetrievalResponse

    evidence = Evidence(**_evidence_values())
    response = RetrievalResponse(
        status="degraded",
        evidence=[evidence],
        warnings=[ChannelProblem(code="GRAPH_TIMEOUT", message="timed out", retryable=True)],
    )

    with pytest.raises(TypeError):
        evidence.channel_scores["dense"] = evidence.channel_scores["bm25"]
    with pytest.raises(TypeError):
        evidence.graph_path[0]["entity_id"] = "changed"
    with pytest.raises((AttributeError, TypeError)):
        response.evidence.append(evidence)
    with pytest.raises((AttributeError, TypeError)):
        response.warnings.append(response.warnings[0])
    dumped = response.model_dump(mode="json")
    assert dumped["evidence"][0]["channel_scores"]["dense"]["raw_rank"] == 1
    assert dumped["evidence"][0]["graph_path"][0]["entity_id"] == "entity-a"


def test_evidence_rejects_storage_and_provider_payloads():
    from engine.app.retrieval.evidence import Evidence

    with pytest.raises(ValidationError):
        Evidence(**_evidence_values(), storage_path="/private/file.pdf")
    with pytest.raises(ValidationError):
        Evidence(**_evidence_values(), provider_payload={"milvus": "raw"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_id", "assigned-too-early"),
        ("retrieval_channels", ("vector",)),
        ("evidence_type", "document"),
        ("page_start", -1),
        ("char_end", -1),
    ],
)
def test_evidence_rejects_invalid_contract_values(field, value):
    from engine.app.retrieval.evidence import Evidence

    values = _evidence_values()
    values[field] = value
    with pytest.raises(ValidationError):
        Evidence(**values)


def test_retrieval_response_status_is_closed_enum():
    from engine.app.retrieval.evidence import ChannelProblem, RetrievalResponse

    assert RetrievalResponse(status="no_hits").evidence == ()
    warning = ChannelProblem(code="GRAPH_UNAVAILABLE", message="offline", retryable=True)
    response = RetrievalResponse(status="degraded", warnings=[warning])
    assert response.warnings[0].message == "offline"
    assert response.warnings[0].retryable is True
    with pytest.raises(ValidationError):
        RetrievalResponse(status="partial")


def test_private_retrieval_scope_is_dependency_injected_and_json_scope_is_rejected(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from engine.app.api import retrieval
    from engine.app.retrieval.evidence import RetrievalResponse

    app = FastAPI()
    app.include_router(retrieval.router)
    verified = retrieval.AuthorizedKnowledgeScope(
        tenant_id="tenant-a", kb_uid="kb-a", index_generation="index-a"
    )
    app.dependency_overrides[retrieval.verify_authorized_scope] = lambda: verified
    monkeypatch.setattr(
        retrieval,
        "execute_retrieval",
        lambda request, scope: RetrievalResponse(status="no_hits"),
    )

    client = TestClient(app)
    accepted = client.post("/internal/retrieval/query", json={"query": "safe"})
    assert accepted.status_code == 200
    rejected = client.post(
        "/internal/retrieval/query",
        json={"query": "unsafe", "scope": verified.model_dump()},
    )
    assert rejected.status_code == 422


def test_private_retrieval_fails_closed_without_scope_verifier():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from engine.app.api import retrieval

    app = FastAPI()
    app.include_router(retrieval.router)
    response = TestClient(app).post("/internal/retrieval/query", json={"query": "safe"})
    assert response.status_code == 503


def test_retrieval_overrides_reject_zero_graph_hops():
    from engine.app.api.retrieval import RetrievalOverrides

    with pytest.raises(ValidationError):
        RetrievalOverrides(graph_hops=0)


def test_execute_retrieval_uses_unified_graph_and_rerank_path(monkeypatch):
    from engine.app.api import retrieval

    scope = retrieval.AuthorizedKnowledgeScope(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        index_generation="index-a",
        graph_generation="graph-a",
    )
    request = retrieval.RetrievalRequest(
        query="architecture", mode="deep", config={"top_k": 3, "graph_hops": 2}
    )
    graph = object()
    db = object()
    captured = {}

    class Resources:
        def __enter__(self):
            return db, graph

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(retrieval, "open_retrieval_resources", lambda: Resources())

    def fake_unified(query, top_k, **kwargs):
        captured.update(query=query, top_k=top_k, **kwargs)
        kwargs["diagnostics"].update({
            "status": "degraded",
            "warnings": [{"code": "RERANK_SLOW", "message": "fallback used", "retryable": True}],
        })
        return [{
            "chunk_id": "chunk-a",
            "item_id": "item-a",
            "file_uid": "file-a",
            "display_title": "Architecture",
            "text": "reranked child body",
            "score": 0.031,
            "rerank_score": 0.92,
            "channels": {"dense": {"raw_score": 0.8, "raw_rank": 1}, "graph": {"raw_score": 0.7, "raw_rank": 2}},
            "graph_rag": {"path": [{"entity_id": "e1"}], "explain": {"explanation": "graph match"}},
        }]

    monkeypatch.setattr(retrieval, "unified_search", fake_unified)
    result = retrieval.execute_retrieval(request, scope)

    assert captured["scope"].graph_generation == "graph-a"
    assert captured["graph_client"] is graph
    assert captured["db"] is db
    assert captured["graph_hops"] == 2
    assert result.evidence[0].excerpt == "reranked child body"
    assert result.evidence[0].rerank_score == 0.92
    assert result.evidence[0].retrieval_channels == ("dense", "graph")
    assert result.warnings[0].message == "fallback used"


def test_execute_retrieval_surfaces_embedding_degrade_warning(monkeypatch):
    from engine.app.api import retrieval

    scope = retrieval.AuthorizedKnowledgeScope(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        index_generation="index-a",
    )
    request = retrieval.RetrievalRequest(query="architecture")

    class Resources:
        def __enter__(self):
            return object(), object()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(retrieval, "open_retrieval_resources", lambda: Resources())

    def degraded(*args, **kwargs):
        kwargs["diagnostics"].update({
            "status": "degraded",
            "warnings": [{
                "code": "EMBEDDING_UNAVAILABLE",
                "message": "Embedding service temporarily unavailable; fell back to keyword retrieval.",
                "retryable": True,
            }],
        })
        return [{
            "chunk_id": "chunk-a",
            "item_id": "item-a",
            "file_uid": "file-a",
            "display_title": "Architecture",
            "text": "fallback body",
            "score": 0.031,
            "channels": {"bm25": {"raw_score": 7.0, "raw_rank": 1}},
        }]

    monkeypatch.setattr(retrieval, "unified_search", degraded)
    result = retrieval.execute_retrieval(request, scope)

    assert result.status == "degraded"
    assert result.warnings[0].code == "EMBEDDING_UNAVAILABLE"
    assert "fell back to keyword retrieval" in result.warnings[0].message


def test_execute_retrieval_skips_hits_without_traceable_ids(monkeypatch):
    from engine.app.api import retrieval

    scope = retrieval.AuthorizedKnowledgeScope(
        tenant_id="tenant-a", kb_uid="kb-a", index_generation="index-a"
    )
    request = retrieval.RetrievalRequest(query="broken")

    class Resources:
        def __enter__(self):
            return object(), object()

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(retrieval, "open_retrieval_resources", lambda: Resources())

    def malformed(*args, **kwargs):
        kwargs["diagnostics"].update({"status": "ok", "warnings": []})
        return [
            {"chunk_id": None, "file_uid": "file-a", "score": 0.1, "channels": {}},
            {"chunk_id": "chunk-b", "file_uid": None, "score": 0.1, "channels": {}},
        ]

    monkeypatch.setattr(retrieval, "unified_search", malformed)
    result = retrieval.execute_retrieval(request, scope)

    assert result.status == "degraded"
    assert result.evidence == ()
    assert result.warnings[0].code == "MALFORMED_RETRIEVAL_HIT"
    assert "unknown" not in result.model_dump_json()
    assert "None" not in result.model_dump_json()


@pytest.mark.parametrize(
    "filters",
    [
        {"file_uids": [f"file-{i}" for i in range(101)]},
        {"file_uids": ["x" * 129]},
        {"file_uids": [""]},
        {"source_types": [f"type-{i}" for i in range(101)]},
        {"source_types": ["x" * 65]},
        {"source_types": [""]},
    ],
)
def test_engine_public_filters_are_bounded(filters):
    from engine.app.api.retrieval import PublicFilters

    with pytest.raises(ValidationError):
        PublicFilters(**filters)


def _install_resource_fakes(monkeypatch, retrieval, events, *, graph_init_error=None,
                            graph_close_error=None, db_close_error=None,
                            dispose_error=None):
    class Engine:
        def dispose(self):
            events.append("engine.dispose")
            if dispose_error:
                raise dispose_error

    class DB:
        def close(self):
            events.append("db.close")
            if db_close_error:
                raise db_close_error

    class Graph:
        def close(self):
            events.append("graph.close")
            if graph_close_error:
                raise graph_close_error

    engine = Engine()
    db = DB()
    monkeypatch.setattr(retrieval, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(retrieval, "sessionmaker", lambda **kwargs: lambda: db)

    def make_graph():
        events.append("graph.init")
        if graph_init_error:
            raise graph_init_error
        return Graph()

    monkeypatch.setattr(retrieval, "GraphClient", make_graph)
    return engine, db


def test_retrieval_resources_close_graph_db_and_dispose_engine_on_success(monkeypatch):
    from engine.app.api import retrieval

    events = []
    _install_resource_fakes(monkeypatch, retrieval, events)
    with retrieval.open_retrieval_resources():
        events.append("body")
    assert events == ["graph.init", "body", "graph.close", "db.close", "engine.dispose"]


def test_retrieval_resources_clean_up_when_body_raises(monkeypatch):
    from engine.app.api import retrieval

    events = []
    _install_resource_fakes(monkeypatch, retrieval, events)
    with pytest.raises(ValueError, match="primary"):
        with retrieval.open_retrieval_resources():
            raise ValueError("primary")
    assert events[-3:] == ["graph.close", "db.close", "engine.dispose"]


def test_retrieval_resources_clean_up_partial_init_when_graph_constructor_fails(monkeypatch):
    from engine.app.api import retrieval

    events = []
    _install_resource_fakes(monkeypatch, retrieval, events, graph_init_error=RuntimeError("graph init"))
    with pytest.raises(RuntimeError, match="graph init"):
        with retrieval.open_retrieval_resources():
            pass
    assert events == ["graph.init", "db.close", "engine.dispose"]


def test_retrieval_resource_cleanup_is_independent_and_does_not_mask_primary(monkeypatch):
    from engine.app.api import retrieval

    events = []
    _install_resource_fakes(
        monkeypatch,
        retrieval,
        events,
        graph_close_error=RuntimeError("graph close"),
        db_close_error=RuntimeError("db close"),
        dispose_error=RuntimeError("dispose"),
    )
    with pytest.raises(ValueError, match="primary"):
        with retrieval.open_retrieval_resources():
            raise ValueError("primary")
    assert events[-3:] == ["graph.close", "db.close", "engine.dispose"]

    events.clear()
    _install_resource_fakes(monkeypatch, retrieval, events, graph_close_error=RuntimeError("graph close"))
    with pytest.raises(RuntimeError, match="graph close"):
        with retrieval.open_retrieval_resources():
            pass
    assert events[-3:] == ["graph.close", "db.close", "engine.dispose"]
