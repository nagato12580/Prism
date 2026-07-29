# prism/engine/tests/test_generate_report.py
import csv
import io
import json
from pathlib import Path
import sys

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_load_data_reads_all_files(tmp_path):
    """Should load and merge all input JSON/CSV files."""
    from engine.eval.generate_report import load_data

    # Write mock files
    (tmp_path / "golden_dataset_v2.json").write_text(json.dumps({
        "meta": {"total_questions": 3, "version": "2.0"},
        "queries": [
            {"id": "q1", "question": "Q1?", "question_type": "fact"},
            {"id": "q2", "question": "Q2?", "question_type": "concept"},
        ]
    }), encoding="utf-8")
    (tmp_path / "retrieval_summary.json").write_text(json.dumps({
        "aggregates": {"recall@10": {"mean": 0.72}},
        "zero_recall": ["q2"],
    }), encoding="utf-8")
    (tmp_path / "answer_summary.json").write_text(json.dumps({
        "judge_aggregates": {"overall": {"mean": 4.1}},
        "by_type": {"fact": {"mean": 4.2, "count": 1}},
    }), encoding="utf-8")
    # Write answer_detailed.csv
    csv_path = tmp_path / "answer_detailed.csv"
    with open(csv_path, "w", encoding="utf-8-sig") as f:
        f.write("query_id,question,judge_faithfulness,judge_relevance,judge_completeness,judge_overall\n")
        f.write("q1,Q1?,4,5,4,4.3\n")
        f.write("q2,Q2?,3,3,2,2.7\n")

    data = load_data(tmp_path)
    assert data["dataset_meta"]["total_questions"] == 3
    assert data["retrieval"]["aggregates"]["recall@10"]["mean"] == 0.72
    assert data["answer"]["judge_aggregates"]["overall"]["mean"] == 4.1
    assert "q2" in data["retrieval"]["zero_recall"]
    assert len(data["answer_detail"]) == 2
    assert data["answer_detail"][0]["query_id"] == "q1"


def test_load_data_handles_missing_files(tmp_path):
    """Gracefully handle missing files returning empty placeholders."""
    from engine.eval.generate_report import load_data

    # No files at all — should not crash
    data = load_data(tmp_path)
    assert data["run_ts"] == tmp_path.name
    assert data["answer_detail"] == []
    assert data["low_scores_count"] == 0


def test_render_report_includes_all_sections():
    """Rendered report should contain all major sections."""
    from engine.eval.generate_report import render_report

    data = {
        "run_ts": "2026-07-29_1430",
        "dataset_meta": {"total_questions": 3, "version": "2.0", "papers": []},
        "retrieval": {
            "aggregates": {"recall@10": {"mean": 0.72, "median": 0.80}},
            "by_paper": {},
            "by_type": {},
            "zero_recall": [],
            "latency": {"p50": 1200, "p95": 3500},
        },
        "answer": {
            "judge_aggregates": {
                "overall": {"mean": 4.1, "median": 4.0},
                "faithfulness": {"mean": 4.2, "median": 4.0},
                "relevance": {"mean": 4.3, "median": 4.0},
                "completeness": {"mean": 3.9, "median": 4.0},
            },
            "by_type": {},
            "by_paper": {},
            "latency": {"total_p50": 8000, "total_p95": 15000},
        },
        "low_scores_count": 5,
        "answer_detail": [],
    }

    report = render_report(data)

    assert "# Prism" in report
    assert "执行摘要" in report
    assert "数据概览" in report
    assert "论文清单" in report
    assert "问题类型分布" in report
    assert "检索层" in report
    assert "端到端问答" in report
    assert "交叉分析" in report
    assert "改进建议" in report
    assert "recall@10" in report
    assert "0.72" in report  # mean recall
    assert "4.1" in report   # mean overall


def test_fmt_val_formats_properly():
    """Helper _fmt_val should format values correctly."""
    from engine.eval.generate_report import _fmt_val

    assert _fmt_val(None) == "N/A"
    assert _fmt_val(3.14159, 2) == "3.14"
    assert _fmt_val(3.14159, 3) == "3.142"
    assert _fmt_val(5) == "5"
    assert _fmt_val("hello") == "hello"


def test_per_group_table_renders_correctly():
    """_per_group_table should render markdown table with expected headers."""
    from engine.eval.generate_report import _per_group_table

    groups = {
        "fact": {"recall@10": {"mean": 0.75}, "mrr": {"mean": 0.80}, "count": 2},
        "concept": {"recall@10": {"mean": 0.60}, "mrr": {"mean": 0.50}, "count": 1},
    }
    table = _per_group_table(groups, ["recall@10", "mrr"])
    assert "Group" in table
    assert "recall@10" in table
    assert "mrr" in table
    assert "fact" in table
    assert "concept" in table
    assert "0.75" in table
    assert "0.60" in table
    assert "2" in table  # count


def test_per_group_table_empty():
    """Empty groups should return placeholder message."""
    from engine.eval.generate_report import _per_group_table

    table = _per_group_table({}, ["recall@10"])
    assert "No data available" in table
