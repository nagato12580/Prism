import pytest


def test_retrieval_metrics_known_example():
    from engine.app.evaluation.metrics import retrieval_metrics

    result = retrieval_metrics(["c2", "c1", "c3"], {"c1"}, ks=(1, 3))
    assert result == {"recall@1": 0.0, "recall@3": 1.0, "mrr": 0.5, "ndcg": pytest.approx(1 / 1.5849625007)}


def test_retrieval_metrics_deduplicates_ranked_chunks():
    from engine.app.evaluation.metrics import retrieval_metrics

    result = retrieval_metrics(["c2", "c2", "c1"], {"c1"}, ks=(2,))
    assert result["recall@2"] == 1.0
    assert result["mrr"] == 0.5


def test_retrieval_metrics_empty_gold_is_explicitly_zero():
    from engine.app.evaluation.metrics import retrieval_metrics

    assert retrieval_metrics(["c1"], set(), ks=(1,)) == {"recall@1": 0.0, "mrr": 0.0, "ndcg": 0.0}


@pytest.mark.parametrize("ks", [(), (0,), (-1,), (1, 1)])
def test_retrieval_metrics_rejects_invalid_k(ks):
    from engine.app.evaluation.metrics import retrieval_metrics

    with pytest.raises(ValueError):
        retrieval_metrics([], {"c1"}, ks=ks)
