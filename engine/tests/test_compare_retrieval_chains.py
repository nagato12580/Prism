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


def test_chain_map_supports_governed_evidence():
    assert "governed_evidence" in eval_compare._chain_map()


def test_governed_evidence_meta_documents_pku_vector_recall():
    params = eval_compare._governed_evidence_params()

    assert params["pku_vector_recall"] is True
    assert params["pku_vector_weight"] == eval_compare.GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT
    assert params["pku_evidence_boost"] == eval_compare.GOVERNED_EVIDENCE_PKU_EVIDENCE_BOOST


def test_governed_evidence_preserves_raw_parent_sources_for_expanded_metrics(monkeypatch):
    monkeypatch.setattr(
        eval_compare,
        "_query_governed_evidence",
        lambda query, limit: (
            [],
            [
                {
                    "canonical_id": "ckp-1",
                    "title": "Test CKP",
                    "score": 1.0,
                    "raw_sources": [
                        {
                            "source_kind": "document_chunk",
                            "chunk_id": "parent-1",
                            "item_id": "item-1",
                            "score": 0.8,
                        }
                    ],
                    "expanded_sources": [
                        {
                            "source_kind": "document_chunk",
                            "chunk_id": "child-1",
                            "item_id": "item-1",
                            "score": 0.9,
                        }
                    ],
                }
            ],
            [],
        ),
    )

    hits = eval_compare._governed_evidence("question", 10)

    assert hits[0]["chunk_id"] == "parent-1"
    assert hits[0]["source"] == "governed_evidence"
    assert hits[0]["expanded_child_ids"] == ["child-1"]
