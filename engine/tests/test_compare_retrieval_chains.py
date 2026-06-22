from pathlib import Path

from engine.eval import compare_retrieval_chains as eval_compare


def test_compute_metrics_reports_recall_precision_hit_ndcg_and_mrr():
    metrics = eval_compare._compute_metrics(
        ["a", "x", "b", "c"],
        {"a", "b", "c", "d"},
        k_values=[1, 2, 4],
    )

    assert metrics["first_relevant_rank"] == 1
    assert metrics["mrr"] == 1.0
    assert metrics["recall@1"] == 0.25
    assert metrics["precision@1"] == 1.0
    assert metrics["hit@1"] == 1
    assert metrics["recall@2"] == 0.25
    assert metrics["precision@2"] == 0.5
    assert metrics["hit@2"] == 1
    assert metrics["recall@4"] == 0.75
    assert metrics["precision@4"] == 0.75
    assert 0 < metrics["ndcg@4"] <= 1


def test_default_results_dir_is_under_independent_evaluation_workspace():
    expected = Path(eval_compare._project_root) / "evaluation" / "runs" / "retrieval"

    assert eval_compare.RESULTS_DIR == expected
