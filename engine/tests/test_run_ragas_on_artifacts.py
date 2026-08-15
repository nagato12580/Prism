import json
import math
from pathlib import Path

import pytest

from engine.eval.answer_artifacts import write_jsonl
from engine.eval.run_ragas_on_artifacts import (
    _default_ragas_evaluator,
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


def test_build_ragas_rows_includes_answer_when_contexts_and_reference_missing():
    rows, skipped = build_ragas_rows(
        [
            {
                "query_id": "q1",
                "question": "q",
                "answer": "a",
                "retrieved_contexts": [],
                "reference": "",
            }
        ]
    )

    assert skipped == []
    assert rows == [
        {
            "user_input": "q",
            "response": "a",
            "retrieved_contexts": [],
            "reference": "",
        }
    ]


def test_normalize_metric_row_maps_answer_relevancy_to_response_relevancy():
    normalized = normalize_metric_row({"faithfulness": 1.0, "answer_relevancy": 0.75})

    assert normalized == {"faithfulness": 1.0, "response_relevancy": 0.75}


def test_normalize_metric_row_maps_ragas_context_aliases():
    normalized = normalize_metric_row(
        {
            "llm_context_precision_with_reference": 0.81,
            "llm_context_recall": 0.72,
        }
    )

    assert normalized == {
        "context_precision": 0.81,
        "context_recall": 0.72,
    }

    normalized = normalize_metric_row(
        {
            "context_precision_without_reference": 0.63,
            "context_recall": 0.54,
        }
    )

    assert normalized == {
        "context_precision": 0.63,
        "context_recall": 0.54,
    }


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
    assert summary["bad_case_counts"] == {
        "hallucination_risk": 1,
        "noisy_context": 1,
        "below_threshold:faithfulness": 1,
        "below_threshold:context_precision": 1,
    }
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


def test_run_ragas_report_uses_thresholds_for_low_score_tags(tmp_path: Path):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    thresholds_path = tmp_path / "thresholds.json"
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
            }
        ],
    )
    thresholds_path.write_text(
        json.dumps({"response_relevancy": 0.95}),
        encoding="utf-8",
    )

    summary = run_ragas_report(
        artifacts_path,
        thresholds_path,
        None,
        evaluator=lambda rows, judge_model: [
            {
                "faithfulness": 1.0,
                "response_relevancy": 0.9,
                "context_precision": 1.0,
                "context_recall": 1.0,
            }
        ],
    )

    assert summary["bad_case_counts"] == {"below_threshold:response_relevancy": 1}
    assert "below_threshold:response_relevancy" in (
        tmp_path / "ragas_low_scores.csv"
    ).read_text(encoding="utf-8-sig")


def test_run_ragas_report_records_short_evaluator_results(tmp_path: Path):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    write_jsonl(
        artifacts_path,
        [
            {
                "query_id": "q1",
                "question": "q1",
                "answer": "a1",
                "sources": [],
                "retrieved_contexts": ["ctx"],
                "reference": "ref",
                "metadata": {"status": "done", "question_type": "single"},
            },
            {
                "query_id": "q2",
                "question": "q2",
                "answer": "a2",
                "sources": [],
                "retrieved_contexts": ["ctx"],
                "reference": "ref",
                "metadata": {"status": "done", "question_type": "single"},
            },
        ],
    )

    summary = run_ragas_report(
        artifacts_path,
        None,
        None,
        evaluator=lambda rows, judge_model: [{"faithfulness": 1.0}],
    )

    assert summary["meta"]["evaluated"] == 1
    assert summary["meta"]["failed"] == 2
    assert summary["failures"] == [
        {
            "query_id": "q1",
            "reason": (
                "missing finite metrics: response_relevancy, "
                "context_precision, context_recall"
            ),
        },
        {"query_id": "q2", "reason": "ragas returned no score row"}
    ]
    detailed = (tmp_path / "ragas_detailed.csv").read_text(encoding="utf-8-sig")
    assert "q2" in detailed
    assert "ragas returned no score row" in detailed


def test_run_ragas_report_records_extra_evaluator_results(tmp_path: Path):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    write_jsonl(
        artifacts_path,
        [
            {
                "query_id": "q1",
                "question": "q1",
                "answer": "a1",
                "sources": [],
                "retrieved_contexts": ["ctx"],
                "reference": "ref",
                "metadata": {"status": "done", "question_type": "single"},
            }
        ],
    )

    summary = run_ragas_report(
        artifacts_path,
        None,
        None,
        evaluator=lambda rows, judge_model: [{"faithfulness": 1.0}, {"faithfulness": 0.5}],
    )

    assert summary["meta"]["evaluated"] == 1
    assert summary["meta"]["failed"] == 2
    assert summary["failures"] == [
        {
            "query_id": "q1",
            "reason": (
                "missing finite metrics: response_relevancy, "
                "context_precision, context_recall"
            ),
        },
        {"query_id": "", "reason": "ragas returned 1 extra score row"}
    ]


def test_non_finite_scores_are_missing_metric_failures(tmp_path: Path):
    normalized = normalize_metric_row(
        {
            "faithfulness": math.nan,
            "answer_relevancy": math.inf,
            "context_precision": 0.8,
        }
    )

    assert normalized == {"context_precision": 0.8}

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
            }
        ],
    )

    summary = run_ragas_report(
        artifacts_path,
        None,
        None,
        evaluator=lambda rows, judge_model: [{"faithfulness": math.nan}],
    )

    assert summary["failures"] == [
        {
            "query_id": "q1",
            "reason": (
                "missing finite metrics: faithfulness, response_relevancy, "
                "context_precision, context_recall"
            ),
        }
    ]
    summary_text = (tmp_path / "ragas_summary.json").read_text(encoding="utf-8")
    assert "NaN" not in summary_text
    assert "Infinity" not in summary_text


def test_absent_expected_metrics_are_missing_metric_failures(tmp_path: Path):
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
            }
        ],
    )

    summary = run_ragas_report(
        artifacts_path,
        None,
        None,
        evaluator=lambda rows, judge_model: [{"response_relevancy": 0.9}],
    )

    assert summary["failures"] == [
        {
            "query_id": "q1",
            "reason": "missing finite metrics: faithfulness, context_precision, context_recall",
        }
    ]
    detailed = (tmp_path / "ragas_detailed.csv").read_text(encoding="utf-8-sig")
    assert "missing finite metrics: faithfulness, context_precision, context_recall" in detailed


def test_run_ragas_report_evaluates_response_relevancy_without_contexts_or_reference(
    tmp_path: Path,
):
    artifacts_path = tmp_path / "answer_artifacts.jsonl"
    write_jsonl(
        artifacts_path,
        [
            {
                "query_id": "q1",
                "question": "q",
                "answer": "a",
                "sources": [],
                "retrieved_contexts": [],
                "reference": "",
                "metadata": {"status": "done", "question_type": "single"},
            }
        ],
    )

    seen_rows = []

    def evaluator(rows, judge_model):
        seen_rows.extend(rows)
        return [{"answer_relevancy": 0.88}]

    summary = run_ragas_report(artifacts_path, None, None, evaluator=evaluator)

    assert seen_rows == [
        {
            "user_input": "q",
            "response": "a",
            "retrieved_contexts": [],
            "reference": "",
        }
    ]
    assert summary["meta"]["evaluated"] == 1
    assert summary["failures"] == [
        {
            "query_id": "q1",
            "reason": "missing finite metrics: faithfulness, context_precision, context_recall",
        }
    ]
    detailed = (tmp_path / "ragas_detailed.csv").read_text(encoding="utf-8-sig")
    assert "q1" in detailed
    assert "0.88" in detailed
    assert "retrieval_failure" in detailed


def test_default_evaluator_reports_missing_optional_dependencies(monkeypatch):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name in {"datasets", "langchain_openai", "ragas"}:
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError) as exc_info:
        _default_ragas_evaluator([], None)

    message = str(exc_info.value)
    assert "pip install ragas datasets pandas langchain-openai" in message
    assert "pip install -r requirements-eval.txt" in message
