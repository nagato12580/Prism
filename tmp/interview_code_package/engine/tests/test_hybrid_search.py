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
    def fail_vector_search(query: str, top_k: int):
        raise RuntimeError("embedding endpoint unavailable")

    def fake_bm25_search(query: str, top_k: int):
        return [{"chunk_id": "c1", "item_id": "i1", "score": 3.0}]

    monkeypatch.setattr(hybrid, "vector_search", fail_vector_search)
    monkeypatch.setattr(hybrid, "bm25_search", fake_bm25_search)

    assert hybrid.hybrid_search("phase 2", top_k=5) == [
        {"chunk_id": "c1", "item_id": "i1", "score": BM25_WEIGHT / (RRF_K + 1)}
    ]
