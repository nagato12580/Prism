from pathlib import Path

from engine.eval import compare_retrieval_chains as eval_compare


def test_evaluation_modules_import_scoped_text_hybrid_adapter():
    from engine.app.retrieval.unified import scoped_text_hybrid_search
    from engine.eval import run_governed_eval, run_retrieval

    assert eval_compare.scoped_text_hybrid_search is scoped_text_hybrid_search
    assert run_retrieval.scoped_text_hybrid_search is scoped_text_hybrid_search
    assert run_governed_eval.scoped_text_hybrid_search is scoped_text_hybrid_search


def test_traditional_hybrid_uses_scoped_text_hybrid_adapter(monkeypatch):
    from engine.app.retrieval.contracts import SearchScope

    scope = SearchScope(
        tenant_id="tenant",
        kb_uid="kb",
        index_generation="index-v1",
    )
    calls = []

    def scoped_search(query, actual_scope, top_k):
        calls.append((query, actual_scope, top_k))
        return [{"chunk_id": "chunk-1", "item_id": "item-1", "score": 0.75}]

    monkeypatch.setattr(eval_compare, "_EVAL_SCOPE", scope)
    monkeypatch.setattr(eval_compare, "scoped_text_hybrid_search", scoped_search)

    assert eval_compare._traditional_hybrid("question", 7) == [
        {
            "chunk_id": "chunk-1",
            "item_id": "item-1",
            "score": 0.75,
            "source": "traditional_hybrid",
        }
    ]
    assert calls == [("question", scope, 7)]


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


def test_chain_map_supports_bottom_up():
    assert "bottom_up" in eval_compare._chain_map()


def test_chain_map_supports_governed_v2():
    assert "governed_v2" in eval_compare._chain_map()


def test_chain_map_supports_page_index():
    assert "page_index" in eval_compare._chain_map()


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


def test_bottom_up_preserves_pku_source_chunk(monkeypatch):
    monkeypatch.setattr(
        eval_compare,
        "_query_bottom_up",
        lambda query, limit: [
            {
                "pku_id": "pku-1",
                "statement": "Bottom-up PKU evidence.",
                "source_kind": "document_chunk",
                "source_id": "parent-1",
                "item_id": "item-1",
                "score": 0.91,
                "canonical_ids": ["ckp-1"],
                "canonical_titles": ["Bottom-up CKP"],
            }
        ],
    )

    hits = eval_compare._bottom_up("question", 10)

    assert hits[0]["chunk_id"] == "parent-1"
    assert hits[0]["item_id"] == "item-1"
    assert hits[0]["source"] == "bottom_up"
    assert hits[0]["pku_id"] == "pku-1"
    assert hits[0]["canonical_ids"] == ["ckp-1"]


def test_governed_v2_returns_vector_first_chunk_hits(monkeypatch):
    monkeypatch.setattr(
        eval_compare,
        "_query_governed_v2",
        lambda query, limit, top_k_chunks: (
            [{"chunk_id": "child-1", "item_id": "item-1", "score": 0.88}],
            [
                {
                    "canonical_id": "ckp-1",
                    "title": "V2 CKP",
                    "score": 1.2,
                }
            ],
            [],
            [],
        ),
    )

    hits = eval_compare._governed_v2("question", 10)

    assert hits[0]["chunk_id"] == "child-1"
    assert hits[0]["source"] == "governed_v2"
    assert hits[0]["canonical_ids"] == ["ckp-1"]


def test_page_index_returns_page_level_hits(monkeypatch):
    class FakePageIndexService:
        def __init__(self, session_factory):
            pass

        def search_pages(self, query, top_k):
            return [
                {
                    "chunk_id": "child-1",
                    "item_id": "item-1",
                    "doc_id": "item-1",
                    "doc_name": "Doc",
                    "page": 2,
                    "score": 3.0,
                    "source": "page_index",
                    "chunk_ids": ["child-1", "child-2"],
                }
            ]

    monkeypatch.setattr(eval_compare, "PageIndexService", FakePageIndexService)

    hits = eval_compare._page_index("question", 10)

    assert hits[0]["chunk_id"] == "child-1"
    assert hits[0]["source"] == "page_index"
    assert hits[0]["page"] == 2
    assert hits[0]["chunk_ids"] == ["child-1", "child-2"]
