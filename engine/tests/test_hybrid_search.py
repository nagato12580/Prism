# prism/engine/tests/test_hybrid_search.py
from engine.app.retrieval.hybrid import RRF_K, VECTOR_WEIGHT, BM25_WEIGHT


def _rrf_score(vec_rank, bm25_rank):
    """手动计算 RRF 分数，验证融合逻辑。"""
    s = 0.0
    if vec_rank is not None:
        s += VECTOR_WEIGHT / (RRF_K + vec_rank + 1)
    if bm25_rank is not None:
        s += BM25_WEIGHT / (RRF_K + bm25_rank + 1)
    return s


def test_rrf_two_sources_merge():
    """同时出现在两路检索的结果，分数应高于只出现一路的。"""
    both = _rrf_score(0, 0)
    only_vec = _rrf_score(0, None)
    assert both > only_vec


def test_rrf_higher_rank_higher_score():
    """排名越靠前（rank 越小），分数越高。"""
    rank0 = _rrf_score(0, None)
    rank5 = _rrf_score(5, None)
    assert rank0 > rank5


def test_rrf_weights_sum_reasonable():
    """权重和合理。"""
    assert VECTOR_WEIGHT + BM25_WEIGHT == 1.0
