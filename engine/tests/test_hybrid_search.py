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


def test_weighted_rrf_uses_bm25_when_dense_fails():
    from engine.app.retrieval.contracts import Candidate, ChannelResult
    dense = ChannelResult.failed("dense", "X", True)
    bm25 = ChannelResult.ok("bm25", [
        Candidate(chunk_uid="c1", item_id="i1", file_uid="f1", channel="bm25", raw_score=3.0, raw_rank=1)
    ])
    assert hybrid.weighted_rrf([dense, bm25], {"dense": 0.6, "bm25": 0.4})[0]["chunk_uid"] == "c1"


def test_weighted_rrf_is_a_pure_helper(monkeypatch):
    from engine.app.retrieval.contracts import ChannelResult
    assert not hasattr(hybrid, "vector_search")
    assert not hasattr(hybrid, "es_fulltext_search")
    assert hybrid.weighted_rrf(
        [ChannelResult.ok("dense", []), ChannelResult.ok("bm25", [])],
        {"dense": 0.6, "bm25": 0.4},
    ) == []
