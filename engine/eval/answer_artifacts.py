import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable


ChunkTextLookup = Callable[[str], str | None]


@dataclass(frozen=True)
class AnswerArtifact:
    query_id: str
    question: str
    answer: str
    sources: list[dict[str, Any]]
    retrieved_contexts: list[str]
    reference: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_ndjson_events(lines: Iterable[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "answer": "",
        "sources": [],
        "token_count": 0,
        "tool_calls": 0,
        "status": "unknown",
    }

    for line in lines:
        raw = line.strip()
        if not raw:
            continue

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        data = event.get("data", {})

        if event_type == "token":
            result["token_count"] += 1
            if isinstance(data, str):
                result["answer"] += data
            elif isinstance(data, dict):
                result["answer"] += str(data.get("token", ""))
        elif event_type == "sources":
            sources = data.get("sources", data) if isinstance(data, dict) else data
            if isinstance(sources, list):
                result["sources"] = sources
        elif event_type == "tool_call":
            result["tool_calls"] += 1
        elif event_type == "done":
            if result.get("status") != "error":
                result["status"] = "done"
            if isinstance(data, dict) and data.get("answer"):
                result["answer"] = str(data["answer"])
        elif event_type == "error":
            result["status"] = "error"
            result["error"] = (
                data.get("message", "unknown error")
                if isinstance(data, dict)
                else str(data)
            )

    return result


def build_reference_from_gold(
    q: dict[str, Any],
    lookup_chunk_text: ChunkTextLookup | None = None,
) -> str:
    texts: list[str] = []
    for child in q.get("relevant_children", []) or []:
        text = _clean_text(child.get("chunk_text"))
        if not text and lookup_chunk_text is not None:
            chunk_id = _clean_text(child.get("chunk_id") or child.get("chunk_uid"))
            if chunk_id:
                text = _clean_text(lookup_chunk_text(chunk_id))
        if text:
            texts.append(text)

    return "\n\n---\n\n".join(texts)


def extract_retrieved_contexts(
    sources: Iterable[dict[str, Any]],
    lookup_chunk_text: ChunkTextLookup | None = None,
) -> tuple[list[str], int]:
    contexts: list[str] = []
    missing_count = 0

    for source in sources:
        text = _clean_text(source.get("text"))
        if not text:
            text = _clean_text(source.get("snippet") or source.get("excerpt"))
        if not text and lookup_chunk_text is not None:
            chunk_id = _clean_text(source.get("chunk_uid") or source.get("chunk_id"))
            if chunk_id:
                text = _clean_text(lookup_chunk_text(chunk_id))

        if text:
            contexts.append(text)
        else:
            missing_count += 1

    return contexts, missing_count


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                rows.append(json.loads(raw))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def bad_case_tags(artifact: dict[str, Any], scores: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    if _score_below(scores, "faithfulness", 0.70):
        tags.append("hallucination_risk")
    if _score_below(scores, "response_relevancy", 0.65):
        tags.append("off_topic")
    if _score_below(scores, "context_precision", 0.50):
        tags.append("noisy_context")
    if _score_below(scores, "context_recall", 0.50):
        tags.append("missing_context")
    if (
        not _clean_text(artifact.get("answer"))
        or artifact.get("metadata", {}).get("status") != "done"
    ):
        tags.append("system_failure")
    if not artifact.get("retrieved_contexts"):
        tags.append("retrieval_failure")
    return tags


def aggregate_numeric_metrics(
    rows: Iterable[dict[str, Any]],
    metric_names: Iterable[str],
) -> dict[str, dict[str, float]]:
    row_list = list(rows)
    output: dict[str, dict[str, float]] = {}
    for metric in metric_names:
        values = [
            float(row[metric])
            for row in row_list
            if _is_number(row.get(metric))
        ]
        if values:
            output[metric] = {
                "mean": round(sum(values) / len(values), 4),
                "median": round(float(median(values)), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
    return output


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _score_below(scores: dict[str, Any], key: str, threshold: float) -> bool:
    value = scores.get(key)
    return _is_number(value) and float(value) < threshold


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
