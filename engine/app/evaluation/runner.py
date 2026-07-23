from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from engine.app.retrieval.evidence import Evidence

from .metrics import retrieval_metrics


@dataclass(frozen=True)
class EvaluationItem:
    item_id: str
    query: str
    gold_chunks: frozenset[str] = frozenset()
    gold_answer: str | None = None


@dataclass(frozen=True)
class EvaluationItemResult:
    item_id: str
    status: str
    evidence: tuple[dict[str, Any], ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    progress_current: int
    progress_total: int
    items: tuple[EvaluationItemResult, ...]
    metrics: dict[str, float]


def run_evaluation(
    items: Iterable[EvaluationItem],
    retrieve: Callable[[EvaluationItem], Iterable[dict[str, Any]]],
    *,
    ks=(1, 3, 5, 10),
    is_cancelled: Callable[[], bool] = lambda: False,
) -> EvaluationResult:
    items = tuple(items)
    results: list[EvaluationItemResult] = []
    canceled = False
    for item in items:
        if is_cancelled():
            canceled = True
            break
        try:
            validated = tuple(Evidence.model_validate(row) for row in retrieve(item))
            evidence = tuple(row.model_dump(mode="json") for row in validated)
            metrics = retrieval_metrics([row.chunk_uid for row in validated], item.gold_chunks, ks=ks)
            results.append(EvaluationItemResult(item.item_id, "succeeded", evidence, metrics))
        except Exception:
            results.append(EvaluationItemResult(item.item_id, "failed", error="evaluation item failed"))
    succeeded = [row for row in results if row.status == "succeeded"]
    failed = [row for row in results if row.status == "failed"]
    status = "canceled" if canceled else ("failed" if failed and not succeeded else "succeeded_with_errors" if failed else "succeeded")
    keys = {key for row in succeeded for key in row.metrics}
    overall = {key: sum(row.metrics[key] for row in succeeded if key in row.metrics) / len(succeeded) for key in keys} if succeeded else {}
    return EvaluationResult(status, len(results), len(items), tuple(results), overall)
