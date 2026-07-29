# prism/engine/tests/test_run_retrieval_v2.py
import json
from pathlib import Path
import sys

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_compute_retrieval_metrics_perfect_retrieval():
    """Perfect retrieval should yield recall=1.0, precision=1.0, mrr=1.0."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3", "c4", "c5"]
    relevant = {"c1", "c3"}
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5, 10))

    assert metrics["recall@5"] == 1.0
    assert metrics["recall@10"] == 1.0
    assert metrics["precision@5"] == 2 / 5
    assert metrics["mrr"] == 1.0  # c1 is at rank 1
    assert metrics["first_relevant_rank"] == 1
    assert metrics["hit@5"] == 1


def test_compute_retrieval_metrics_empty_gold():
    """Empty gold set should yield all zeros."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3"]
    relevant = set()
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5,))

    assert metrics["recall@5"] == 0.0
    assert metrics["precision@5"] == 0.0
    assert metrics["mrr"] == 0.0
    assert metrics["first_relevant_rank"] is None


def test_compute_retrieval_metrics_no_hit():
    """No relevant chunks retrieved should yield recall=0, mrr=0."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3"]
    relevant = {"c4", "c5"}
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5,))

    assert metrics["recall@5"] == 0.0
    assert metrics["precision@5"] == 0.0
    assert metrics["mrr"] == 0.0
    assert metrics["first_relevant_rank"] is None


def test_aggregate_metrics_by_dimension():
    """Aggregation should compute mean/median/std/min/max per metric per group."""
    from engine.eval.run_retrieval_v2 import aggregate_by_dimension

    results = [
        {"query_id": "q1", "question_type": "fact", "paper_title": "Paper A",
         "recall@10": 0.8, "mrr": 1.0},
        {"query_id": "q2", "question_type": "fact", "paper_title": "Paper A",
         "recall@10": 0.6, "mrr": 0.5},
        {"query_id": "q3", "question_type": "concept", "paper_title": "Paper B",
         "recall@10": 0.4, "mrr": 0.3},
    ]

    by_type = aggregate_by_dimension(results, "question_type", ["recall@10", "mrr"])
    assert "fact" in by_type
    assert "concept" in by_type
    assert by_type["fact"]["recall@10"]["mean"] == 0.7
    assert by_type["fact"]["count"] == 2
