import json
from pathlib import Path

from engine.eval.answer_artifacts import write_jsonl
from engine.eval.run_ragas_on_artifacts import (
    build_ragas_rows,
    normalize_metric_row,
    run_ragas_report,
)


def test_build_ragas_rows_maps_artifact_fields():
    artifacts = [
        {
            "query_id": "q1",
            "question": "What is Prism?",
            "answer": "A RAG system.",
            "retrieved_contexts": ["ctx"],
            "reference": "ref",
        }
    ]

    rows, skipped = build_ragas_rows(artifacts)

    assert skipped == []
    assert rows == [
        {
            "user_input": "What is Prism?",
            "response": "A RAG system.",
            "retrieved_contexts": ["ctx"],
            "reference": "ref",
        }
    ]


def test_build_ragas_rows_skips_missing_required_fields():
    rows, skipped = build_ragas_rows(
        [
            {
                "query_id": "q1",
                "question": "q",
                "answer": "",
                "retrieved_contexts": [],
                "reference": "",
            }
        ]
    )

    assert rows == []
    assert skipped == [
        {
            "query_id": "q1",
            "reason": "missing answer, retrieved_contexts, reference",
        }
    ]


def test_normalize_metric_row_maps_answer_relevancy_to_response_relevancy():
    normalized = normalize_metric_row({"faithfulness": 1.0, "answer_relevancy": 0.75})

    assert normalized == {"faithfulness": 1.0, "response_relevancy": 0.75}


def test_run_ragas_report_writes_outputs_with_mock_evaluator(tmp_path: Path):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
    write_jsonl(
        artifacts_path,
        [
            {
                "query_id": "q1",
                "question": "What is Prism?",
                "answer": "A RAG system.",
                "sources": [{"chunk_uid": "c1"}],
                "retrieved_contexts": ["ctx"],
                "reference": "ref",
                "metadata": {
                    "status": "done",
                    "question_type": "single",
                    "total_latency_ms": 20,
                },
            }
        ],
    )
    thresholds_path.write_text(
        json.dumps(
            {
                "faithfulness": 0.8,
                "response_relevancy": 0.75,
                "context_precision": 0.65,
                "context_recall": 0.65,
            }
        ),
        encoding="utf-8",
    )

    def evaluator(rows, judge_model):
        assert judge_model == "mock-model"
        assert rows[0]["user_input"] == "What is Prism?"
        return [
            {
                "faithfulness": 0.6,
                "answer_relevancy": 0.8,
                "context_precision": 0.4,
                "context_recall": 0.9,
            }
        ]

    summary = run_ragas_report(
        artifacts_path,
        thresholds_path,
        "mock-model",
        evaluator=evaluator,
    )

    assert summary["meta"]["total"] == 1
    assert summary["meta"]["evaluated"] == 1
    assert summary["bad_case_counts"] == {"hallucination_risk": 1, "noisy_context": 1}
    assert (tmp_path / "ragas_detailed.csv").exists()
    assert (tmp_path / "ragas_summary.json").exists()
    assert (tmp_path / "ragas_low_scores.csv").exists()
    assert (tmp_path / "bad_cases" / "q1_ragas_bad_case.md").exists()


def test_run_ragas_report_records_evaluator_failures_and_continues(tmp_path: Path):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    write_jsonl(
        artifacts_path,
        [
            {
                "query_id": "q1",
                "question": "q",
                "answer": "a",
                "sources": [],
                "retrieved_contexts": ["ctx"],
                "reference": "ref",
                "metadata": {"status": "done", "question_type": "single"},
            },
            {
                "query_id": "q2",
                "question": "q",
                "answer": "",
                "sources": [],
                "retrieved_contexts": [],
                "reference": "",
                "metadata": {"status": "error", "question_type": "single"},
            },
        ],
    )

    def evaluator(rows, judge_model):
        raise RuntimeError("judge unavailable")

    summary = run_ragas_report(artifacts_path, None, None, evaluator=evaluator)

    assert summary["meta"]["total"] == 2
    assert summary["meta"]["evaluated"] == 0
    assert summary["meta"]["failed"] == 2
    assert summary["failures"] == [
        {"query_id": "q2", "reason": "missing answer, retrieved_contexts, reference"},
        {"query_id": "q1", "reason": "ragas evaluation failed: judge unavailable"},
    ]
    assert (tmp_path / "ragas_summary.json").exists()
