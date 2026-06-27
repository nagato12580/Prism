from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

os.environ.setdefault("DATABASE_URL", "sqlite:///./_deep_search_eval_import.db")

from engine.app.agent.deep_search.orchestrator import DeepSearchOrchestrator, config_for_depth
from engine.app.chat.answer import _Session


DEFAULT_DATASET = _project_root / "evaluation" / "datasets" / "deep_knowledge_search_v1.example.json"
DEFAULT_OUTPUT_ROOT = _project_root / "evaluation" / "runs" / "deep_search"


def _recall_at(retrieved: list[str], expected: list[str], k: int) -> float:
    expected_set = {item for item in expected if item}
    if not expected_set:
        return 1.0
    retrieved_set = set(retrieved[:k])
    return round(len(retrieved_set & expected_set) / len(expected_set), 4)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * 0.95), len(ordered) - 1)
    return round(ordered[index], 4)


def _ids_from_result(payload: dict[str, Any]) -> dict[str, list[str]]:
    evidence = payload.get("evidence") or []
    sources = payload.get("sources") or []
    return {
        "ckp_ids": [str(item.get("ckp_id")) for item in evidence if item.get("ckp_id")],
        "pku_ids": [str(item.get("pku_id")) for item in evidence if item.get("pku_id")],
        "source_ids": [
            str(item.get("source_id") or item.get("chunk_id"))
            for item in sources
            if item.get("source_id") or item.get("chunk_id")
        ],
    }


def evaluate_case(case: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    question = str(case["question"])
    depth = str(case.get("depth") or "standard")
    limit = int(case.get("limit") or max(top_k, 12))
    orchestrator = DeepSearchOrchestrator(_Session, config=config_for_depth(depth, limit))
    started = time.perf_counter()
    result = orchestrator.run(question)
    latency_ms = (time.perf_counter() - started) * 1000
    payload = result.to_payload()
    retrieved = _ids_from_result(payload)
    answerable = bool(case.get("answerable", True))
    judged_complete = payload.get("judge", {}).get("status") == "complete"
    expected_complete = answerable

    return {
        "id": case.get("id", question[:40]),
        "question": question,
        "depth": depth,
        "status": payload.get("status"),
        "iterations": payload.get("iterations", 0),
        "latency_ms": round(latency_ms, 2),
        "fallback_used": any(item.get("strategy") == "global_fallback" for item in payload.get("evidence", [])),
        "judged_complete": judged_complete,
        "expected_complete": expected_complete,
        "judge_correct": judged_complete == expected_complete,
        "ckp_recall_at_k": _recall_at(retrieved["ckp_ids"], [str(x) for x in case.get("expected_ckp_ids", [])], top_k),
        "pku_recall_at_k": _recall_at(retrieved["pku_ids"], [str(x) for x in case.get("expected_pku_ids", [])], top_k),
        "source_recall_at_k": _recall_at(retrieved["source_ids"], [str(x) for x in case.get("expected_source_ids", [])], top_k),
        "judge": payload.get("judge"),
        "retrieved": retrieved,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    latencies = [float(row["latency_ms"]) for row in rows]
    return {
        "case_count": len(rows),
        "ckp_recall_at_k_mean": round(statistics.mean(row["ckp_recall_at_k"] for row in rows), 4),
        "pku_recall_at_k_mean": round(statistics.mean(row["pku_recall_at_k"] for row in rows), 4),
        "source_recall_at_k_mean": round(statistics.mean(row["source_recall_at_k"] for row in rows), 4),
        "judge_completeness_accuracy": round(sum(1 for row in rows if row["judge_correct"]) / len(rows), 4),
        "avg_iterations": round(statistics.mean(float(row["iterations"]) for row in rows), 4),
        "avg_latency_ms": round(statistics.mean(latencies), 2),
        "p95_latency_ms": _p95(latencies),
        "fallback_rate": round(sum(1 for row in rows if row["fallback_used"]) / len(rows), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Prism deep governed knowledge search")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Dataset JSON path")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Output directory root")
    parser.add_argument("--top-k", type=int, default=10, help="Recall cutoff")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = dataset.get("cases", [])
    run_dir = Path(args.output_root) / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = [evaluate_case(case, top_k=args.top_k) for case in cases]
    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "top_k": args.top_k,
        },
        "metrics": aggregate(rows),
        "cases": rows,
    }
    output = run_dir / "summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output}")
    print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
