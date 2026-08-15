import argparse
import csv
import json
import math
import numbers
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / ".env")

from engine.eval.answer_artifacts import (
    aggregate_numeric_metrics,
    bad_case_tags,
    read_jsonl,
)

METRIC_NAMES = (
    "faithfulness",
    "response_relevancy",
    "context_precision",
    "context_recall",
)
Evaluator = Callable[[list[dict[str, Any]], str | None], list[dict[str, Any]]]


def build_ragas_rows(
    artifacts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for artifact in artifacts:
        missing = _missing_required_fields(artifact)
        if missing:
            skipped.append(
                {
                    "query_id": str(artifact.get("query_id") or ""),
                    "reason": "missing " + ", ".join(missing),
                }
            )
            continue

        rows.append(
            {
                "user_input": artifact["question"],
                "response": artifact["answer"],
                "retrieved_contexts": artifact["retrieved_contexts"],
                "reference": artifact["reference"],
            }
        )

    return rows, skipped


def normalize_metric_row(row: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for metric in METRIC_NAMES:
        value = row.get(metric)
        if _is_number(value):
            normalized[metric] = float(value)

    answer_relevancy = row.get("answer_relevancy")
    if "response_relevancy" not in normalized and _is_number(answer_relevancy):
        normalized["response_relevancy"] = float(answer_relevancy)

    return normalized


def run_ragas_report(
    artifacts_path: Path,
    thresholds_path: Path | None,
    judge_model: str | None,
    *,
    evaluator: Evaluator | None = None,
) -> dict[str, Any]:
    artifacts = read_jsonl(artifacts_path)
    ragas_rows, skipped = build_ragas_rows(artifacts)
    valid_artifacts = [
        artifact for artifact in artifacts if not _missing_required_fields(artifact)
    ]
    failures = list(skipped)
    evaluator = evaluator or _default_ragas_evaluator

    raw_scores: list[dict[str, Any]] = []
    evaluator_failed = False
    if ragas_rows:
        try:
            raw_scores = evaluator(ragas_rows, judge_model)
        except Exception as exc:
            evaluator_failed = True
            failures.extend(
                {
                    "query_id": str(artifact.get("query_id") or ""),
                    "reason": f"ragas evaluation failed: {exc}",
                }
                for artifact in valid_artifacts
            )

    thresholds = _load_thresholds(thresholds_path)
    run_dir = artifacts_path.parent
    score_by_id, alignment_failures = (
        ({}, []) if evaluator_failed else _align_scores(valid_artifacts, raw_scores)
    )
    failures.extend(alignment_failures)
    failure_by_id = {
        str(failure.get("query_id") or ""): str(failure.get("reason") or "")
        for failure in failures
        if failure.get("query_id")
    }
    general_failures = [
        str(failure.get("reason") or "")
        for failure in failures
        if not failure.get("query_id")
    ]

    detailed: list[dict[str, Any]] = []
    low_scores: list[dict[str, Any]] = []
    bad_counts: Counter[str] = Counter()

    for artifact in artifacts:
        query_id = str(artifact.get("query_id") or "")
        scores = score_by_id.get(query_id, {})
        tags = bad_case_tags(artifact, scores)
        if query_id in failure_by_id and query_id not in score_by_id:
            tags.append(
                "ragas_failed"
                if not _missing_required_fields(artifact)
                else "ragas_skipped"
            )
        elif query_id in failure_by_id:
            tags.append("ragas_failed")
        tags.extend(_threshold_tags(scores, thresholds))
        tags = _dedupe(tags)

        for tag in tags:
            bad_counts[tag] += 1

        row = {
            "query_id": query_id,
            "question": artifact.get("question", ""),
            "question_type": artifact.get("metadata", {}).get("question_type", ""),
            "status": artifact.get("metadata", {}).get("status", ""),
            "bad_case_tags": ",".join(tags),
            "failure": failure_by_id.get(query_id, "; ".join(general_failures)),
            **scores,
        }
        detailed.append(row)
        if tags:
            low_scores.append(row)
            _write_bad_case(run_dir, artifact, scores, tags)

    _write_csv(run_dir / "ragas_detailed.csv", detailed)
    _write_csv(run_dir / "ragas_low_scores.csv", low_scores)

    summary = {
        "meta": {
            "artifacts": str(artifacts_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "judge_model": judge_model,
            "metric_names": list(METRIC_NAMES),
            "thresholds": thresholds,
            "total": len(artifacts),
            "evaluated": len(score_by_id),
            "failed": len(failures),
        },
        "aggregates": aggregate_numeric_metrics(detailed, METRIC_NAMES),
        "by_type": _aggregate_by_type(detailed),
        "bad_case_counts": dict(bad_counts),
        "failures": failures,
    }
    (run_dir / "ragas_summary.json").write_text(
        _json_dumps(summary),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run Ragas over previously collected Prism answer artifacts"
    )
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--thresholds", default=None)
    args = parser.parse_args(argv)

    summary = run_ragas_report(
        Path(args.artifacts),
        Path(args.thresholds) if args.thresholds else None,
        args.judge_model,
    )
    summary_path = Path(args.artifacts).parent / "ragas_summary.json"
    print(json.dumps(summary["meta"], ensure_ascii=False, indent=2))
    print(f"Summary: {summary_path}")


def _default_ragas_evaluator(
    rows: list[dict[str, Any]],
    judge_model: str | None,
) -> list[dict[str, Any]]:
    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import evaluate
        from ragas.metrics import (
            Faithfulness,
            LLMContextRecall,
            ResponseRelevancy,
        )
        try:
            from ragas.metrics import LLMContextPrecisionWithReference
        except ImportError:
            from ragas.metrics import (
                LLMContextPrecisionWithoutReference as LLMContextPrecisionWithReference,
            )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing optional Ragas evaluation dependencies. "
            "Install evaluation dependencies with "
            "`pip install ragas datasets pandas langchain-openai` or, "
            "after requirements-eval.txt is added, "
            "`pip install -r requirements-eval.txt`."
        ) from exc

    llm = ChatOpenAI(model=judge_model) if judge_model else None
    embeddings = OpenAIEmbeddings() if judge_model else None
    metrics = [
        Faithfulness(),
        ResponseRelevancy(),
        LLMContextPrecisionWithReference(),
        LLMContextRecall(),
    ]
    result = evaluate(
        Dataset.from_list(rows),
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
    )
    if hasattr(result, "to_pandas"):
        return result.to_pandas().to_dict(orient="records")
    if hasattr(result, "scores"):
        return list(result.scores)
    return list(result)


def _missing_required_fields(artifact: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(artifact.get("answer") or "").strip():
        missing.append("answer")
    if not artifact.get("retrieved_contexts"):
        missing.append("retrieved_contexts")
    if not str(artifact.get("reference") or "").strip():
        missing.append("reference")
    return missing


def _align_scores(
    artifacts: list[dict[str, Any]],
    raw_scores: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], list[dict[str, str]]]:
    scores: dict[str, dict[str, float]] = {}
    failures: list[dict[str, str]] = []

    matched_count = min(len(artifacts), len(raw_scores))
    for artifact, raw_score in zip(
        artifacts[:matched_count],
        raw_scores[:matched_count],
        strict=True,
    ):
        query_id = str(artifact.get("query_id") or "")
        normalized = normalize_metric_row(raw_score)
        scores[query_id] = normalized
        missing_metrics = _missing_finite_metrics(raw_score)
        if missing_metrics:
            failures.append(
                {
                    "query_id": query_id,
                    "reason": "missing finite metrics: " + ", ".join(missing_metrics),
                }
            )

    for artifact in artifacts[matched_count:]:
        failures.append(
            {
                "query_id": str(artifact.get("query_id") or ""),
                "reason": "ragas returned no score row",
            }
        )

    extra_count = len(raw_scores) - len(artifacts)
    if extra_count > 0:
        suffix = "row" if extra_count == 1 else "rows"
        failures.append(
            {
                "query_id": "",
                "reason": f"ragas returned {extra_count} extra score {suffix}",
            }
        )

    return scores, failures


def _load_thresholds(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(metric): float(threshold)
        for metric, threshold in raw.items()
        if _is_number(threshold)
    }


def _threshold_tags(scores: dict[str, float], thresholds: dict[str, float]) -> list[str]:
    tags: list[str] = []
    for metric, threshold in thresholds.items():
        value = scores.get(metric)
        if value is not None and value < threshold:
            tags.append(f"below_threshold:{metric}")
    return tags


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "query_id",
        "question",
        "question_type",
        "status",
        "faithfulness",
        "response_relevancy",
        "context_precision",
        "context_recall",
        "bad_case_tags",
        "failure",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_bad_case(
    run_dir: Path,
    artifact: dict[str, Any],
    scores: dict[str, float],
    tags: list[str],
) -> None:
    bad_dir = run_dir / "bad_cases"
    bad_dir.mkdir(parents=True, exist_ok=True)
    query_id = _safe_filename(str(artifact.get("query_id") or "unknown"))
    source_ids = [
        str(source.get("chunk_uid") or source.get("chunk_id") or "")
        for source in artifact.get("sources", [])
        if source.get("chunk_uid") or source.get("chunk_id")
    ]
    content = [
        f"# Ragas Bad Case: {artifact.get('query_id') or 'unknown'}",
        "",
        f"**Question:** {artifact.get('question', '')}",
        "",
        f"**Tags:** {', '.join(tags)}",
        "",
        "## Scores",
        "",
        _json_dumps(scores),
        "",
        "## Answer",
        "",
        str(artifact.get("answer") or "")[:3000],
        "",
        "## Retrieved Contexts",
        "",
        "\n\n---\n\n".join(
            str(context)[:1200] for context in artifact.get("retrieved_contexts", [])
        ),
        "",
        "## Reference Excerpt",
        "",
        str(artifact.get("reference") or "")[:2000],
        "",
        "## Source IDs",
        "",
        ", ".join(source_ids),
        "",
        "## Metadata",
        "",
        _json_dumps(artifact.get("metadata", {})),
    ]
    (bad_dir / f"{query_id}_ragas_bad_case.md").write_text(
        "\n".join(content),
        encoding="utf-8",
    )


def _aggregate_by_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("question_type") or "unknown")].append(row)
    return {
        question_type: aggregate_numeric_metrics(type_rows, METRIC_NAMES)
        for question_type, type_rows in sorted(grouped.items())
    }


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _safe_filename(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    return safe or "unknown"


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _missing_finite_metrics(row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for metric in METRIC_NAMES:
        if metric in row and not _is_number(row[metric]):
            missing.append(metric)
    if (
        "response_relevancy" not in row
        and "answer_relevancy" in row
        and not _is_number(row["answer_relevancy"])
    ):
        missing.append("response_relevancy")
    return missing


def _json_dumps(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return value if math.isfinite(float(value)) else None
    return value


if __name__ == "__main__":
    main()
