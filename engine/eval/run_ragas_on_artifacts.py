import argparse
import csv
import json
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
    if ragas_rows:
        try:
            raw_scores = evaluator(ragas_rows, judge_model)
        except Exception as exc:
            failures.extend(
                {
                    "query_id": str(artifact.get("query_id") or ""),
                    "reason": f"ragas evaluation failed: {exc}",
                }
                for artifact in valid_artifacts
            )

    thresholds = _load_thresholds(thresholds_path)
    run_dir = artifacts_path.parent
    failure_by_id = {
        str(failure.get("query_id") or ""): str(failure.get("reason") or "")
        for failure in failures
    }
    score_by_id = _scores_by_query_id(valid_artifacts, raw_scores)

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
        tags = _dedupe(tags)

        for tag in tags:
            bad_counts[tag] += 1

        row = {
            "query_id": query_id,
            "question": artifact.get("question", ""),
            "question_type": artifact.get("metadata", {}).get("question_type", ""),
            "status": artifact.get("metadata", {}).get("status", ""),
            "bad_case_tags": ",".join(tags),
            "failure": failure_by_id.get(query_id, ""),
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
        json.dumps(summary, ensure_ascii=False, indent=2),
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
    from datasets import Dataset
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithoutReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    llm = ChatOpenAI(model=judge_model) if judge_model else None
    embeddings = OpenAIEmbeddings() if judge_model else None
    metrics = [
        Faithfulness(),
        ResponseRelevancy(),
        LLMContextPrecisionWithoutReference(),
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


def _scores_by_query_id(
    artifacts: list[dict[str, Any]],
    raw_scores: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for artifact, raw_score in zip(artifacts, raw_scores, strict=False):
        query_id = str(artifact.get("query_id") or "")
        scores[query_id] = normalize_metric_row(raw_score)
    return scores


def _load_thresholds(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(metric): float(threshold)
        for metric, threshold in raw.items()
        if _is_number(threshold)
    }


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
        json.dumps(scores, ensure_ascii=False, indent=2),
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
        json.dumps(artifact.get("metadata", {}), ensure_ascii=False, indent=2),
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
    return isinstance(value, (int, float)) and not isinstance(value, bool)


if __name__ == "__main__":
    main()
