# Ragas Answer Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-stage offline Ragas answer-quality evaluation pipeline for Prism RAG answers.

**Architecture:** The pipeline separates answer collection from answer judging. `collect_answer_artifacts.py` calls Prism once and writes reusable JSONL artifacts; `run_ragas_on_artifacts.py` reads those artifacts and computes Ragas metrics offline. Shared parsing, context extraction, reference construction, JSONL IO, aggregation, and bad-case tagging live in focused helper modules.

**Tech Stack:** Python 3, pytest, httpx, SQLAlchemy, existing Prism Engine config/auth helpers, optional evaluation-only `ragas`, `datasets`, and `pandas`.

---

## File Structure

- Create `engine/eval/answer_artifacts.py`: shared artifact dataclass, NDJSON stream parsing, reference construction, context extraction, JSONL IO, summary aggregation, bad-case tagging.
- Create `engine/eval/collect_answer_artifacts.py`: CLI that reads a golden dataset, signs the knowledge scope, calls `/api/v1/chat/answer`, writes `answer_artifacts.jsonl` and `answer_summary.json`.
- Create `engine/eval/run_ragas_on_artifacts.py`: CLI and helper functions that load artifacts, call Ragas, normalize metric names, write CSV/JSON/bad-case files.
- Create `evaluation/ragas_thresholds.json`: first-version advisory thresholds.
- Create `requirements-eval.txt`: evaluation-only dependencies.
- Create `engine/tests/test_answer_artifacts.py`: unit tests for stream parsing, reference/context extraction, JSONL IO, aggregation, and bad-case tagging.
- Create `engine/tests/test_run_ragas_on_artifacts.py`: unit tests for artifact-to-Ragas mapping, metric normalization, mocked report writing, and failure handling.

## Task 1: Shared Artifact Helpers

**Files:**
- Create: `engine/eval/answer_artifacts.py`
- Test: `engine/tests/test_answer_artifacts.py`

- [ ] **Step 1: Write failing tests for stream parsing, reference construction, contexts, JSONL, and tags**

Create `engine/tests/test_answer_artifacts.py` with:

```python
from pathlib import Path

from engine.eval.answer_artifacts import (
    AnswerArtifact,
    aggregate_numeric_metrics,
    bad_case_tags,
    build_reference_from_gold,
    extract_retrieved_contexts,
    parse_ndjson_events,
    read_jsonl,
    write_jsonl,
)


def test_parse_ndjson_events_handles_tokens_sources_done_and_error():
    lines = [
        '{"type":"token","data":{"token":"hello "}}\n',
        '{"type":"token","data":"world"}\n',
        '{"type":"sources","data":{"sources":[{"chunk_uid":"c1","text":"ctx"}]}}\n',
        '{"type":"tool_call","data":{"name":"knowledge"}}\n',
        '{"type":"done","data":{"answer":"final answer"}}\n',
        '{"type":"error","data":{"message":"late warning"}}\n',
        'not json\n',
    ]

    parsed = parse_ndjson_events(lines)

    assert parsed["answer"] == "final answer"
    assert parsed["sources"] == [{"chunk_uid": "c1", "text": "ctx"}]
    assert parsed["token_count"] == 2
    assert parsed["tool_calls"] == 1
    assert parsed["status"] == "error"
    assert parsed["error"] == "late warning"


def test_build_reference_from_gold_uses_inline_chunk_texts():
    question = {
        "relevant_children": [
            {"chunk_id": "c1", "chunk_text": "first gold"},
            {"chunk_id": "c2", "chunk_text": "second gold"},
        ]
    }

    reference = build_reference_from_gold(question)

    assert "first gold" in reference
    assert "second gold" in reference
    assert "\n\n---\n\n" in reference


def test_build_reference_from_gold_falls_back_to_lookup():
    question = {"relevant_children": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]}

    reference = build_reference_from_gold(question, lookup_chunk_text=lambda cid: {"c1": "from db"}.get(cid))

    assert reference == "from db"


def test_extract_retrieved_contexts_prefers_text_then_snippet_then_lookup():
    sources = [
        {"chunk_uid": "c1", "text": "full text"},
        {"chunk_uid": "c2", "snippet": "snippet text"},
        {"chunk_uid": "c3"},
        {"chunk_uid": "c4"},
    ]

    contexts, missing = extract_retrieved_contexts(
        sources,
        lookup_chunk_text=lambda cid: {"c3": "lookup text"}.get(cid),
    )

    assert contexts == ["full text", "snippet text", "lookup text"]
    assert missing == 1


def test_jsonl_round_trip(tmp_path: Path):
    path = tmp_path / "artifacts.jsonl"
    artifact = AnswerArtifact(
        query_id="q1",
        question="What is Prism?",
        answer="A RAG system.",
        sources=[{"chunk_uid": "c1"}],
        retrieved_contexts=["ctx"],
        reference="ref",
        metadata={"status": "done"},
    )

    write_jsonl(path, [artifact.to_dict()])

    assert read_jsonl(path) == [artifact.to_dict()]


def test_bad_case_tags_detect_failures_and_low_scores():
    artifact = {
        "answer": "",
        "retrieved_contexts": [],
        "metadata": {"status": "error"},
    }
    scores = {
        "faithfulness": 0.69,
        "response_relevancy": 0.64,
        "context_precision": 0.49,
        "context_recall": 0.49,
    }

    tags = bad_case_tags(artifact, scores)

    assert tags == [
        "hallucination_risk",
        "off_topic",
        "noisy_context",
        "missing_context",
        "system_failure",
        "retrieval_failure",
    ]


def test_aggregate_numeric_metrics_ignores_missing_values():
    aggregate = aggregate_numeric_metrics(
        [
            {"faithfulness": 1.0, "response_relevancy": 0.5},
            {"faithfulness": 0.0},
        ],
        ["faithfulness", "response_relevancy"],
    )

    assert aggregate["faithfulness"]["mean"] == 0.5
    assert aggregate["faithfulness"]["median"] == 0.5
    assert aggregate["faithfulness"]["min"] == 0.0
    assert aggregate["faithfulness"]["max"] == 1.0
    assert aggregate["response_relevancy"]["mean"] == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest engine/tests/test_answer_artifacts.py -v
```

Expected: FAIL because `engine.eval.answer_artifacts` does not exist.

- [ ] **Step 3: Implement `engine/eval/answer_artifacts.py`**

Create `engine/eval/answer_artifacts.py` with:

```python
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
            result["sources"] = sources if isinstance(sources, list) else []
        elif event_type == "tool_call":
            result["tool_calls"] += 1
        elif event_type == "done":
            result["status"] = "done"
            if isinstance(data, dict) and data.get("answer"):
                result["answer"] = str(data["answer"])
        elif event_type == "error":
            result["status"] = "error"
            result["error"] = data.get("message", "unknown error") if isinstance(data, dict) else str(data)
    return result


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def build_reference_from_gold(q: dict[str, Any], lookup_chunk_text: ChunkTextLookup | None = None) -> str:
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
    missing = 0
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
            missing += 1
    return contexts, missing


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


def bad_case_tags(artifact: dict[str, Any], scores: dict[str, float | None]) -> list[str]:
    tags: list[str] = []
    if _score_below(scores, "faithfulness", 0.70):
        tags.append("hallucination_risk")
    if _score_below(scores, "response_relevancy", 0.65):
        tags.append("off_topic")
    if _score_below(scores, "context_precision", 0.50):
        tags.append("noisy_context")
    if _score_below(scores, "context_recall", 0.50):
        tags.append("missing_context")
    if not _clean_text(artifact.get("answer")) or artifact.get("metadata", {}).get("status") != "done":
        tags.append("system_failure")
    if not artifact.get("retrieved_contexts"):
        tags.append("retrieval_failure")
    return tags


def _score_below(scores: dict[str, float | None], key: str, threshold: float) -> bool:
    value = scores.get(key)
    return isinstance(value, int | float) and float(value) < threshold


def aggregate_numeric_metrics(rows: Iterable[dict[str, Any]], metric_names: Iterable[str]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for metric in metric_names:
        values = [
            float(row[metric])
            for row in rows
            if isinstance(row.get(metric), int | float)
        ]
        if values:
            output[metric] = {
                "mean": round(sum(values) / len(values), 4),
                "median": round(float(median(values)), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
    return output
```

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```powershell
pytest engine/tests/test_answer_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add engine/eval/answer_artifacts.py engine/tests/test_answer_artifacts.py
git commit -m "feat: add answer artifact helpers"
```

## Task 2: Answer Artifact Collection CLI

**Files:**
- Create: `engine/eval/collect_answer_artifacts.py`
- Modify: `engine/tests/test_answer_artifacts.py`

- [ ] **Step 1: Add failing tests for artifact construction and summary**

Append to `engine/tests/test_answer_artifacts.py`:

```python
from engine.eval.collect_answer_artifacts import build_artifact, summarize_artifacts


def test_build_artifact_maps_dataset_and_events():
    question = {
        "id": "q1",
        "question": "What is Prism?",
        "question_type": "single",
        "item_title": "Doc",
        "relevant_children": [{"chunk_id": "gold1", "chunk_text": "gold text"}],
    }
    events = {
        "answer": "Prism is a RAG system.",
        "sources": [{"chunk_uid": "c1", "text": "context text"}],
        "token_count": 5,
        "tool_calls": 1,
        "status": "done",
    }

    artifact = build_artifact(question, events, ttfb_ms=11, total_latency_ms=22)

    assert artifact.query_id == "q1"
    assert artifact.question == "What is Prism?"
    assert artifact.answer == "Prism is a RAG system."
    assert artifact.retrieved_contexts == ["context text"]
    assert artifact.reference == "gold text"
    assert artifact.metadata["paper_title"] == "Doc"
    assert artifact.metadata["missing_context_count"] == 0
    assert artifact.metadata["ttfb_ms"] == 11
    assert artifact.metadata["total_latency_ms"] == 22


def test_summarize_artifacts_counts_statuses():
    artifacts = [
        AnswerArtifact("q1", "q", "a", [], ["ctx"], "ref", {"status": "done"}).to_dict(),
        AnswerArtifact("q2", "q", "", [], [], "", {"status": "error"}).to_dict(),
    ]

    summary = summarize_artifacts("dataset.json", artifacts, failures=[{"query_id": "q2"}])

    assert summary["meta"]["dataset"] == "dataset.json"
    assert summary["meta"]["total_artifacts"] == 2
    assert summary["meta"]["failed"] == 1
    assert summary["status_counts"] == {"done": 1, "error": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest engine/tests/test_answer_artifacts.py -v
```

Expected: FAIL because `engine.eval.collect_answer_artifacts` does not exist.

- [ ] **Step 3: Implement `engine/eval/collect_answer_artifacts.py`**

Create `engine/eval/collect_answer_artifacts.py` with:

```python
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / ".env")

from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
from engine.app.config import settings
from engine.eval.answer_artifacts import (
    AnswerArtifact,
    build_reference_from_gold,
    extract_retrieved_contexts,
    parse_ndjson_events,
    write_jsonl,
)

RESULTS_DIR = _project_root / "evaluation" / "runs" / "answer"
SCOPE_TTL_SECONDS = 600


def _lookup_chunk_text(chunk_id: str) -> str | None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.models.knowledge_item import KnowledgeChunk

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    session = sessionmaker(bind=engine)()
    try:
        chunk = session.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
        if chunk is None:
            chunk = session.query(KnowledgeChunk).filter(KnowledgeChunk.chunk_uid == chunk_id).first()
        return chunk.chunk_text if chunk is not None else None
    finally:
        session.close()


def build_artifact(
    q: dict[str, Any],
    events: dict[str, Any],
    *,
    ttfb_ms: int,
    total_latency_ms: int,
) -> AnswerArtifact:
    sources = list(events.get("sources") or [])
    contexts, missing = extract_retrieved_contexts(sources, lookup_chunk_text=_lookup_chunk_text)
    reference = build_reference_from_gold(q, lookup_chunk_text=_lookup_chunk_text)
    paper_title = (q.get("paper_titles") or [q.get("item_title", "")])[0]
    return AnswerArtifact(
        query_id=str(q.get("id") or q.get("query_id") or ""),
        question=str(q.get("question") or ""),
        answer=str(events.get("answer") or ""),
        sources=sources,
        retrieved_contexts=contexts,
        reference=reference,
        metadata={
            "question_type": q.get("question_type", ""),
            "paper_title": paper_title,
            "ttfb_ms": ttfb_ms,
            "total_latency_ms": total_latency_ms,
            "tool_calls": int(events.get("tool_calls") or 0),
            "token_count": int(events.get("token_count") or 0),
            "status": events.get("status", "unknown"),
            "missing_context_count": missing,
        },
    )


def summarize_artifacts(dataset_path: str, artifacts: list[dict[str, Any]], failures: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(str(row.get("metadata", {}).get("status", "unknown")) for row in artifacts)
    missing_contexts = sum(int(row.get("metadata", {}).get("missing_context_count") or 0) for row in artifacts)
    return {
        "meta": {
            "dataset": dataset_path,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_artifacts": len(artifacts),
            "failed": len(failures),
        },
        "status_counts": dict(status_counts),
        "missing_context_count": missing_contexts,
        "failures": failures,
    }


def _sign_scope(tenant_id: str, kb_uid: str) -> str:
    now = int(time.time())
    scope = AuthorizedKnowledgeScope(
        actor_id="eval-runner",
        tenant_id=tenant_id,
        allowed_kb_uids=(kb_uid,),
        run_id=f"ragas-answer-eval-{now}",
        expires_at=now + SCOPE_TTL_SECONDS,
    )
    return sign_scope(scope, settings.KNOWLEDGE_SCOPE_SECRET)


def _collect_one(client: httpx.Client, engine_url: str, question: str, scope_token: str, deep_search: bool) -> tuple[dict[str, Any], int, int]:
    t0 = time.perf_counter()
    lines: list[str] = []
    ttfb_ms = 0
    with client.stream(
        "POST",
        f"{engine_url}/api/v1/chat/answer",
        json={
            "query": question,
            "history": [],
            "deep_search_enabled": deep_search,
            "deep_search_depth": "standard",
            "rag_max_iterations": 5,
        },
        headers={"x-prism-knowledge-scope": scope_token},
    ) as response:
        response.raise_for_status()
        first = True
        for line in response.iter_lines():
            if first:
                ttfb_ms = round((time.perf_counter() - t0) * 1000)
                first = False
            lines.append(line + "\n")
    total_latency_ms = round((time.perf_counter() - t0) * 1000)
    return parse_ndjson_events(lines), ttfb_ms, total_latency_ms


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect Prism answer artifacts for offline Ragas evaluation")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--tenant-id", default="default-tenant")
    parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--engine-url", default=f"http://localhost:{settings.ENGINE_PORT}")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = list(dataset.get("queries") or dataset.get("cases") or [])
    if args.dry_run:
        queries = queries[:3]

    run_dir = RESULTS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    artifacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    token_cache = {"token": None, "last": 0.0}

    def scope_token() -> str:
        if token_cache["token"] is None or time.time() - float(token_cache["last"]) > 500:
            token_cache["token"] = _sign_scope(args.tenant_id, args.kb_uid)
            token_cache["last"] = time.time()
        return str(token_cache["token"])

    with httpx.Client(timeout=300.0) as client:
        for i, q in enumerate(queries, start=1):
            question = str(q.get("question") or "")
            qid = str(q.get("id") or q.get("query_id") or i)
            print(f"[{i}/{len(queries)}] {qid} {question[:80]}", flush=True)
            try:
                events, ttfb_ms, total_latency_ms = _collect_one(
                    client,
                    args.engine_url,
                    question,
                    scope_token(),
                    deep_search=q.get("question_type") == "cross_paper" or q.get("depth") == "deep",
                )
                artifacts.append(build_artifact(q, events, ttfb_ms=ttfb_ms, total_latency_ms=total_latency_ms).to_dict())
            except Exception as exc:
                failures.append({"query_id": qid, "question": question, "error": str(exc)})
                error_events = {"answer": "", "sources": [], "token_count": 0, "tool_calls": 0, "status": "error", "error": str(exc)}
                artifacts.append(build_artifact(q, error_events, ttfb_ms=0, total_latency_ms=0).to_dict())

    artifact_path = run_dir / "answer_artifacts.jsonl"
    summary_path = run_dir / "answer_summary.json"
    write_jsonl(artifact_path, artifacts)
    summary_path.write_text(
        json.dumps(summarize_artifacts(str(dataset_path), artifacts, failures), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Artifacts: {artifact_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest engine/tests/test_answer_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add engine/eval/collect_answer_artifacts.py engine/tests/test_answer_artifacts.py
git commit -m "feat: collect answer eval artifacts"
```

## Task 3: Ragas Offline Evaluation Module

**Files:**
- Create: `engine/eval/run_ragas_on_artifacts.py`
- Test: `engine/tests/test_run_ragas_on_artifacts.py`

- [ ] **Step 1: Write failing tests with a mocked evaluator**

Create `engine/tests/test_run_ragas_on_artifacts.py` with:

```python
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
        [{"query_id": "q1", "question": "q", "answer": "", "retrieved_contexts": [], "reference": ""}]
    )

    assert rows == []
    assert skipped[0]["query_id"] == "q1"
    assert skipped[0]["reason"] == "missing answer, retrieved_contexts, reference"


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
                "metadata": {"status": "done", "question_type": "single", "total_latency_ms": 20},
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

    summary = run_ragas_report(artifacts_path, thresholds_path, "mock-model", evaluator=evaluator)

    assert summary["meta"]["total"] == 1
    assert summary["meta"]["evaluated"] == 1
    assert summary["bad_case_counts"] == {"hallucination_risk": 1, "noisy_context": 1}
    assert (tmp_path / "ragas_detailed.csv").exists()
    assert (tmp_path / "ragas_summary.json").exists()
    assert (tmp_path / "ragas_low_scores.csv").exists()
    assert (tmp_path / "bad_cases" / "q1_ragas_bad_case.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest engine/tests/test_run_ragas_on_artifacts.py -v
```

Expected: FAIL because `engine.eval.run_ragas_on_artifacts` does not exist.

- [ ] **Step 3: Implement `engine/eval/run_ragas_on_artifacts.py` with injectable evaluator**

Create `engine/eval/run_ragas_on_artifacts.py` with:

```python
import argparse
import csv
import json
import sys
from collections import Counter
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

METRIC_NAMES = ("faithfulness", "response_relevancy", "context_precision", "context_recall")
Evaluator = Callable[[list[dict[str, Any]], str | None], list[dict[str, Any]]]


def build_ragas_rows(artifacts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for artifact in artifacts:
        missing: list[str] = []
        if not str(artifact.get("answer") or "").strip():
            missing.append("answer")
        if not artifact.get("retrieved_contexts"):
            missing.append("retrieved_contexts")
        if not str(artifact.get("reference") or "").strip():
            missing.append("reference")
        if missing:
            skipped.append({"query_id": str(artifact.get("query_id") or ""), "reason": "missing " + ", ".join(missing)})
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
    for key in METRIC_NAMES:
        if isinstance(row.get(key), int | float):
            normalized[key] = float(row[key])
    if "response_relevancy" not in normalized and isinstance(row.get("answer_relevancy"), int | float):
        normalized["response_relevancy"] = float(row["answer_relevancy"])
    return normalized


def _default_ragas_evaluator(rows: list[dict[str, Any]], judge_model: str | None) -> list[dict[str, Any]]:
    from datasets import Dataset
    from ragas import evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, LLMContextRecall, ResponseRelevancy
    from langchain_openai import ChatOpenAI

    llm = LangchainLLMWrapper(ChatOpenAI(model=judge_model)) if judge_model else None
    dataset = Dataset.from_list(rows)
    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm),
        LLMContextPrecisionWithoutReference(llm=llm),
        LLMContextRecall(llm=llm),
    ]
    result = evaluate(dataset, metrics=metrics)
    if hasattr(result, "to_pandas"):
        return result.to_pandas().to_dict(orient="records")
    if hasattr(result, "to_list"):
        return result.to_list()
    return list(result)


def _load_thresholds(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    return {key: float(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


def _write_bad_case(run_dir: Path, artifact: dict[str, Any], scores: dict[str, float], tags: list[str]) -> None:
    bad_dir = run_dir / "bad_cases"
    bad_dir.mkdir(parents=True, exist_ok=True)
    query_id = str(artifact.get("query_id") or "unknown")
    source_ids = [
        str(source.get("chunk_uid") or source.get("chunk_id") or "")
        for source in artifact.get("sources", [])
        if source.get("chunk_uid") or source.get("chunk_id")
    ]
    md = [
        f"# Ragas Bad Case: {query_id}",
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
        "\n\n---\n\n".join(str(text)[:1200] for text in artifact.get("retrieved_contexts", [])),
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
    (bad_dir / f"{query_id}_ragas_bad_case.md").write_text("\n".join(md), encoding="utf-8")


def run_ragas_report(
    artifacts_path: Path,
    thresholds_path: Path | None,
    judge_model: str | None,
    *,
    evaluator: Evaluator = _default_ragas_evaluator,
) -> dict[str, Any]:
    artifacts = read_jsonl(artifacts_path)
    ragas_rows, skipped = build_ragas_rows(artifacts)
    raw_scores = evaluator(ragas_rows, judge_model) if ragas_rows else []
    thresholds = _load_thresholds(thresholds_path)
    run_dir = artifacts_path.parent

    detailed: list[dict[str, Any]] = []
    low_scores: list[dict[str, Any]] = []
    bad_counts: Counter[str] = Counter()
    score_index = 0
    skipped_by_id = {row["query_id"]: row["reason"] for row in skipped}

    for artifact in artifacts:
        query_id = str(artifact.get("query_id") or "")
        if query_id in skipped_by_id:
            scores: dict[str, float] = {}
            tags = bad_case_tags(artifact, scores)
            tags.append("ragas_skipped")
            failure = skipped_by_id[query_id]
        else:
            scores = normalize_metric_row(raw_scores[score_index])
            score_index += 1
            tags = bad_case_tags(artifact, scores)
            for metric, threshold in thresholds.items():
                value = scores.get(metric)
                if value is not None and value < threshold and metric not in tags:
                    pass
            failure = ""
        for tag in tags:
            bad_counts[tag] += 1
        row = {
            "query_id": query_id,
            "question": artifact.get("question", ""),
            "question_type": artifact.get("metadata", {}).get("question_type", ""),
            "status": artifact.get("metadata", {}).get("status", ""),
            "bad_case_tags": ",".join(tags),
            "failure": failure,
            **scores,
        }
        detailed.append(row)
        if tags:
            low_scores.append(row)
            _write_bad_case(run_dir, artifact, scores, tags)

    csv_fields = [
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
    with (run_dir / "ragas_detailed.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(detailed)
    with (run_dir / "ragas_low_scores.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(low_scores)

    by_type: dict[str, Any] = {}
    for question_type in sorted({str(row.get("question_type") or "") for row in detailed}):
        type_rows = [row for row in detailed if row.get("question_type") == question_type]
        by_type[question_type] = aggregate_numeric_metrics(type_rows, METRIC_NAMES)
    summary = {
        "meta": {
            "artifacts": str(artifacts_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "judge_model": judge_model,
            "metric_names": list(METRIC_NAMES),
            "total": len(artifacts),
            "evaluated": len(raw_scores),
            "failed": len(skipped),
        },
        "aggregates": aggregate_numeric_metrics(detailed, METRIC_NAMES),
        "by_type": by_type,
        "bad_case_counts": dict(bad_counts),
        "failures": skipped,
    }
    (run_dir / "ragas_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Ragas over previously collected Prism answer artifacts")
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--thresholds", default=None)
    args = parser.parse_args(argv)

    summary = run_ragas_report(
        Path(args.artifacts),
        Path(args.thresholds) if args.thresholds else None,
        args.judge_model,
    )
    print(json.dumps(summary["meta"], ensure_ascii=False, indent=2))
    print(f"Summary: {Path(args.artifacts).parent / 'ragas_summary.json'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest engine/tests/test_run_ragas_on_artifacts.py -v
```

Expected: PASS with mocked evaluator.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add engine/eval/run_ragas_on_artifacts.py engine/tests/test_run_ragas_on_artifacts.py
git commit -m "feat: add offline ragas answer evaluator"
```

## Task 4: Thresholds and Evaluation Dependencies

**Files:**
- Create: `evaluation/ragas_thresholds.json`
- Create: `requirements-eval.txt`

- [ ] **Step 1: Add thresholds file**

Create `evaluation/ragas_thresholds.json`:

```json
{
  "faithfulness": 0.8,
  "response_relevancy": 0.75,
  "context_precision": 0.65,
  "context_recall": 0.65
}
```

- [ ] **Step 2: Add evaluation dependency file**

Create `requirements-eval.txt`:

```txt
-r requirements.txt
ragas
datasets
pandas
```

- [ ] **Step 3: Validate JSON and dependency file presence**

Run:

```powershell
python -m json.tool evaluation/ragas_thresholds.json
Test-Path requirements-eval.txt
```

Expected: JSON pretty-prints and `True` is printed for the dependency file.

- [ ] **Step 4: Commit Task 4**

Run:

```powershell
git add evaluation/ragas_thresholds.json requirements-eval.txt
git commit -m "chore: add ragas eval configuration"
```

## Task 5: Full Verification and Smoke Commands

**Files:**
- No source files unless verification exposes a defect.

- [ ] **Step 1: Run focused unit tests**

Run:

```powershell
pytest engine/tests/test_answer_artifacts.py engine/tests/test_run_ragas_on_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 2: Run existing answer eval tests to catch regressions**

Run:

```powershell
pytest engine/tests/test_run_answer_eval.py engine/tests/test_evaluation_runner.py -v
```

Expected: PASS.

- [ ] **Step 3: Run import smoke for CLIs**

Run:

```powershell
python -m engine.eval.collect_answer_artifacts --help
python -m engine.eval.run_ragas_on_artifacts --help
```

Expected: Both commands print argparse help and exit with code 0.

- [ ] **Step 4: Optional live smoke test when Engine and a KB are available**

Run with real values:

```powershell
python -m engine.eval.collect_answer_artifacts `
  --dataset evaluation/datasets/formal_docs_v1_first20.json `
  --tenant-id default-tenant `
  --kb-uid <real_kb_uid> `
  --engine-url http://localhost:<engine_port> `
  --dry-run
```

Expected: A new directory appears under `evaluation/runs/answer/` containing `answer_artifacts.jsonl` and `answer_summary.json`.

Then, in an environment with `requirements-eval.txt` installed and LLM credentials configured:

```powershell
python -m engine.eval.run_ragas_on_artifacts `
  --artifacts evaluation/runs/answer/<timestamp>/answer_artifacts.jsonl `
  --judge-model gpt-4o-mini `
  --thresholds evaluation/ragas_thresholds.json
```

Expected: The same directory contains `ragas_detailed.csv`, `ragas_summary.json`, `ragas_low_scores.csv`, and a `bad_cases/` directory when bad cases are tagged.

- [ ] **Step 5: Commit any verification fixes**

If verification required fixes, commit only those fixes:

```powershell
git add <fixed_files>
git commit -m "fix: stabilize ragas eval pipeline"
```

If no fixes were needed, do not create an empty commit.

## Self-Review

- Spec coverage: The plan covers artifact collection, offline Ragas evaluation, gold chunk reference construction, context extraction, file outputs, advisory thresholds, bad cases, tests, and smoke commands.
- Scope: No frontend, database persistence, CI gating, or replacement of existing eval scripts is included.
- Type consistency: The shared artifact schema uses `query_id`, `question`, `answer`, `sources`, `retrieved_contexts`, `reference`, and `metadata` consistently across tests and implementation snippets.
- Placeholder scan: Command examples use `<real_kb_uid>`, `<engine_port>`, and `<timestamp>` only where actual runtime values must be supplied by the executor.
