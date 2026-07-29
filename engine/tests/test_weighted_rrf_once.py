import inspect

import pytest

from engine.app.retrieval.contracts import Candidate, ChannelResult, SearchScope


def _scope(*, graph: bool = True) -> SearchScope:
    return SearchScope(
        tenant_id="tenant",
        kb_uid="kb",
        index_generation="index-v1",
        graph_generation="graph-v1" if graph else None,
    )


def _candidate(channel: str, chunk_uid: str, rank: int = 1) -> Candidate:
    return Candidate(
        chunk_uid=chunk_uid,
        item_id=f"item-{chunk_uid}",
        file_uid=f"file-{chunk_uid}",
        channel=channel,
        raw_score=1.0,
        raw_rank=rank,
    )


def test_unified_recall_calls_each_channel_once_and_rrf_once(monkeypatch):
    from engine.app.retrieval import unified

    calls = {"dense": 0, "bm25": 0, "graph": 0, "rrf": 0}

    def channel(name: str, chunk_uid: str) -> ChannelResult:
        calls[name] += 1
        return ChannelResult.ok(name, [_candidate(name, chunk_uid)])

    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: channel("dense", "c1"))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: channel("bm25", "c1"))
    monkeypatch.setattr(unified, "graph_search", lambda *a, **k: channel("graph", "c2"))
    original_rrf = unified.weighted_rrf

    def count_rrf(*args, **kwargs):
        calls["rrf"] += 1
        return original_rrf(*args, **kwargs)

    monkeypatch.setattr(unified, "weighted_rrf", count_rrf)

    result = unified.recall("query", [0.1], _scope(), graph_client=object())

    assert calls == {"dense": 1, "bm25": 1, "graph": 1, "rrf": 1}
    assert [row["chunk_uid"] for row in result["results"]] == ["c1", "c2"]


def test_scoped_text_hybrid_search_requires_search_scope(monkeypatch):
    from engine.app.retrieval import unified

    signature = inspect.signature(unified.scoped_text_hybrid_search)
    assert signature.parameters["scope"].default is inspect.Parameter.empty

    monkeypatch.setattr(
        unified,
        "embed_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unscoped retrieval reached embedding")
        ),
    )
    with pytest.raises(TypeError):
        unified.scoped_text_hybrid_search("query")
    with pytest.raises(ValueError, match="SearchScope is required"):
        unified.scoped_text_hybrid_search("query", None)


def test_scoped_text_hybrid_search_maps_single_fusion_without_graph(monkeypatch):
    from engine.app.retrieval import unified

    scope = _scope()
    calls = {"embed": 0, "dense": 0, "bm25": 0, "graph": 0, "rrf": 0}

    def embed(query):
        calls["embed"] += 1
        assert query == "query"
        return [0.25]

    def dense(query_embedding, actual_scope, top_k):
        calls["dense"] += 1
        assert query_embedding == [0.25]
        assert actual_scope is scope
        assert top_k == 1
        return ChannelResult.ok(
            "dense",
            [
                _candidate("dense", "dense-only", rank=1),
                Candidate(
                    chunk_uid="winner",
                    item_id="item-winner",
                    file_uid="file-winner",
                    channel="dense",
                    raw_score=0.8,
                    raw_rank=2,
                    metadata={"text": "winning text"},
                ),
            ],
        )

    def bm25(query, actual_scope, top_k):
        calls["bm25"] += 1
        assert query == "query"
        assert actual_scope is scope
        assert top_k == 1
        return ChannelResult.ok("bm25", [_candidate("bm25", "winner", rank=1)])

    def graph(*args, **kwargs):
        calls["graph"] += 1
        raise AssertionError("text hybrid adapter called graph search")

    original_rrf = unified.weighted_rrf

    def count_rrf(*args, **kwargs):
        calls["rrf"] += 1
        return original_rrf(*args, **kwargs)

    monkeypatch.setattr(unified, "embed_query", embed)
    monkeypatch.setattr(unified, "vector_search", dense)
    monkeypatch.setattr(unified, "es_fulltext_search", bm25)
    monkeypatch.setattr(unified, "graph_search", graph)
    monkeypatch.setattr(unified, "weighted_rrf", count_rrf)

    hits = unified.scoped_text_hybrid_search("query", scope, top_k=1)

    assert calls == {"embed": 1, "dense": 1, "bm25": 1, "graph": 0, "rrf": 1}
    assert hits == [
        {
            "text": "winning text",
            "chunk_id": "winner",
            "item_id": "item-winner",
            "file_uid": "file-winner",
            "score": pytest.approx((0.6 / 62) + (0.4 / 61)),
            "channels": {
                "dense": {"raw_rank": 2, "raw_score": 0.8},
                "bm25": {"raw_rank": 1, "raw_score": 1.0},
            },
        }
    ]


def test_scoped_text_hybrid_search_degrades_to_bm25_when_embedding_fails(monkeypatch):
    from engine.app.retrieval import unified

    scope = _scope()

    def embed(*args, **kwargs):
        raise RuntimeError("embedding provider unavailable")

    def dense(*args, **kwargs):
        return ChannelResult.failed("dense", "VECTOR_INDEX_UNAVAILABLE", retryable=True)

    def bm25(query, actual_scope, top_k):
        assert query == "query"
        assert actual_scope is scope
        assert top_k == 1
        return ChannelResult.ok(
            "bm25",
            [
                Candidate(
                    chunk_uid="bm25-only",
                    item_id="item-bm25",
                    file_uid="file-bm25",
                    channel="bm25",
                    raw_score=0.7,
                    raw_rank=1,
                    metadata={"text": "lexical fallback"},
                )
            ],
        )

    monkeypatch.setattr(unified, "embed_query", embed)
    monkeypatch.setattr(unified, "vector_search", dense)
    monkeypatch.setattr(unified, "es_fulltext_search", bm25)
    monkeypatch.setattr(
        unified,
        "graph_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("graph should stay disabled")),
    )

    hits = unified.scoped_text_hybrid_search("query", scope, top_k=1)

    assert hits == [
        {
            "text": "lexical fallback",
            "chunk_id": "bm25-only",
            "item_id": "item-bm25",
            "file_uid": "file-bm25",
            "score": pytest.approx(1 / 61),
            "channels": {
                "bm25": {"raw_rank": 1, "raw_score": 0.7},
            },
        }
    ]


def test_weighted_rrf_normalizes_weights_across_surviving_channels():
    from engine.app.retrieval.unified import weighted_rrf

    dense = ChannelResult.ok("dense", [_candidate("dense", "dense-only")])
    bm25 = ChannelResult.failed("bm25", "FULLTEXT_DOWN", retryable=True)
    graph = ChannelResult.ok("graph", [_candidate("graph", "graph-only")])

    rows = weighted_rrf(
        [dense, bm25, graph],
        {"dense": 0.6, "bm25": 0.4, "graph": 0.5},
    )

    by_id = {row["chunk_uid"]: row for row in rows}
    assert by_id["dense-only"]["rrf_score"] == (0.6 / 1.1) / 61
    assert by_id["graph-only"]["rrf_score"] == (0.5 / 1.1) / 61


def test_all_healthy_empty_is_no_hits(monkeypatch):
    from engine.app.retrieval import unified

    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: ChannelResult.ok("dense", []))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: ChannelResult.ok("bm25", []))
    monkeypatch.setattr(unified, "graph_search", lambda *a, **k: ChannelResult.ok("graph", []))

    assert unified.recall("q", [0.1], _scope(), graph_client=object())["status"] == "no_hits"


def test_one_failed_channel_with_results_is_degraded(monkeypatch):
    from engine.app.retrieval import unified

    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: ChannelResult.failed("dense", "DOWN", True))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: ChannelResult.ok("bm25", [_candidate("bm25", "c1")]))
    monkeypatch.setattr(unified, "graph_search", lambda *a, **k: ChannelResult.ok("graph", []))

    assert unified.recall("q", [0.1], _scope(), graph_client=object())["status"] == "degraded"


def test_text_channels_failed_and_graph_disabled_is_unavailable(monkeypatch):
    from engine.app.retrieval import unified

    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: ChannelResult.failed("dense", "DOWN", True))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: ChannelResult.failed("bm25", "DOWN", True))
    monkeypatch.setattr(
        unified,
        "graph_search",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("disabled graph was called")),
    )

    assert unified.recall("q", [0.1], _scope(graph=False))["status"] == "unavailable"


def test_graph_failure_with_text_results_is_degraded(monkeypatch):
    from engine.app.retrieval import unified

    monkeypatch.setattr(unified, "vector_search", lambda *a, **k: ChannelResult.ok("dense", [_candidate("dense", "c1")]))
    monkeypatch.setattr(unified, "es_fulltext_search", lambda *a, **k: ChannelResult.ok("bm25", []))
    monkeypatch.setattr(unified, "graph_search", lambda *a, **k: ChannelResult.failed("graph", "DOWN", True))

    assert unified.recall("q", [0.1], _scope(), graph_client=object())["status"] == "degraded"


def test_unified_search_without_scope_fails_closed_without_calling_legacy(monkeypatch):
    from engine.app.retrieval import unified

    def forbidden(*args, **kwargs):
        raise AssertionError("unscoped retrieval was called")

    monkeypatch.setattr(unified, "hybrid_search", forbidden)
    monkeypatch.setattr(unified, "match_seed_entities", forbidden)
    monkeypatch.setattr(unified, "expand_candidates", forbidden)

    assert unified.unified_search("query", top_k=5, scope=None) == []
