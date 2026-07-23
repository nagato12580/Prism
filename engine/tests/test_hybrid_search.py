# prism/engine/tests/test_hybrid_search.py
from engine.app.retrieval import hybrid
from engine.app.retrieval.hybrid import BM25_WEIGHT, RRF_K, VECTOR_WEIGHT


def _rrf_score(vec_rank, bm25_rank):
    s = 0.0
    if vec_rank is not None:
        s += VECTOR_WEIGHT / (RRF_K + vec_rank + 1)
    if bm25_rank is not None:
        s += BM25_WEIGHT / (RRF_K + bm25_rank + 1)
    return s


def test_rrf_two_sources_merge():
    both = _rrf_score(0, 0)
    only_vec = _rrf_score(0, None)
    assert both > only_vec


def test_rrf_higher_rank_higher_score():
    rank0 = _rrf_score(0, None)
    rank5 = _rrf_score(5, None)
    assert rank0 > rank5


def test_rrf_weights_sum_reasonable():
    assert VECTOR_WEIGHT + BM25_WEIGHT == 1.0


def test_hybrid_search_falls_back_to_bm25_when_vector_search_fails(monkeypatch):
    from engine.app.retrieval.contracts import Candidate, ChannelResult, SearchScope
    scope = SearchScope(tenant_id="t", kb_uid="k", index_generation="g")
    monkeypatch.setattr(hybrid, "embed_query", lambda query: [0.1])
    monkeypatch.setattr(hybrid, "vector_search", lambda *args: ChannelResult.failed("dense", "X", True))
    monkeypatch.setattr(hybrid, "es_fulltext_search", lambda *args: ChannelResult.ok("bm25", [
        Candidate(chunk_uid="c1", item_id="i1", file_uid="f1", channel="bm25", raw_score=3.0, raw_rank=1)
    ]))
    assert hybrid.hybrid_search("phase 2", scope, top_k=5)[0]["chunk_id"] == "c1"


def test_hybrid_embedding_failure_still_runs_scoped_bm25(monkeypatch):
    from engine.app.retrieval.contracts import Candidate, ChannelResult, SearchScope
    scope = SearchScope(tenant_id="t", kb_uid="k", index_generation="g")
    monkeypatch.setattr(hybrid, "embed_query", lambda query: (_ for _ in ()).throw(ConnectionError()))
    seen = {}
    def bm25(query, actual_scope, top_k):
        seen["scope"] = actual_scope
        return ChannelResult.ok("bm25", [Candidate(chunk_uid="c", item_id="i", file_uid="f", channel="bm25", raw_score=1, raw_rank=1)])
    monkeypatch.setattr(hybrid, "es_fulltext_search", bm25)
    assert hybrid.hybrid_search("q", scope, 5)[0]["chunk_id"] == "c"
    assert seen["scope"] == scope
