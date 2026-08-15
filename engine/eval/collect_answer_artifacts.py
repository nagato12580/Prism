"""Collect Prism chat answer artifacts for offline answer-quality evaluation."""
from __future__ import annotations

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
    ChunkTextLookup,
    build_reference_from_gold,
    extract_retrieved_contexts,
    parse_ndjson_events,
    write_jsonl,
)

RESULTS_DIR = _project_root / "evaluation" / "runs" / "answer"
SCOPE_TTL_SECONDS = 600


def build_artifact(
    q: dict[str, Any],
    events: dict[str, Any],
    *,
    ttfb_ms: int,
    total_latency_ms: int,
    lookup_chunk_text: ChunkTextLookup | None = None,
) -> AnswerArtifact:
    """Map one dataset row plus parsed stream events into an answer artifact."""
    sources = [source for source in events.get("sources") or [] if isinstance(source, dict)]
    contexts, missing_context_count = extract_retrieved_contexts(
        sources,
        lookup_chunk_text=lookup_chunk_text,
    )
    metadata = {
        "question_type": q.get("question_type", ""),
        "paper_title": _paper_title(q),
        "ttfb_ms": ttfb_ms,
        "total_latency_ms": total_latency_ms,
        "tool_calls": int(events.get("tool_calls") or 0),
        "token_count": int(events.get("token_count") or 0),
        "status": events.get("status", "unknown"),
        "missing_context_count": missing_context_count,
    }
    if events.get("error"):
        metadata["error"] = events["error"]

    return AnswerArtifact(
        query_id=str(q.get("id") or q.get("query_id") or ""),
        question=str(q.get("question") or q.get("query") or ""),
        answer=str(events.get("answer") or ""),
        sources=sources,
        retrieved_contexts=contexts,
        reference=build_reference_from_gold(q, lookup_chunk_text=lookup_chunk_text),
        metadata=metadata,
    )


def summarize_artifacts(
    dataset_path: str,
    artifacts: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact run summary for collected answer artifacts."""
    status_counts = Counter(
        str(artifact.get("metadata", {}).get("status") or "unknown")
        for artifact in artifacts
    )
    missing_context_count = sum(
        int(artifact.get("metadata", {}).get("missing_context_count") or 0)
        for artifact in artifacts
    )

    return {
        "meta": {
            "dataset": dataset_path,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_artifacts": len(artifacts),
            "failed": len(failures),
        },
        "status_counts": dict(status_counts),
        "missing_context_count": missing_context_count,
        "failures": failures,
    }


def _paper_title(q: dict[str, Any]) -> str:
    paper_titles = q.get("paper_titles")
    if isinstance(paper_titles, list) and paper_titles:
        return str(paper_titles[0])
    return str(q.get("item_title") or q.get("paper_title") or "")


def _lookup_chunk_text(chunk_id: str) -> str | None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.models.knowledge_item import KnowledgeChunk

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    session = sessionmaker(bind=engine)()
    try:
        chunk = session.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
        if chunk is None:
            chunk = (
                session.query(KnowledgeChunk)
                .filter(KnowledgeChunk.chunk_uid == chunk_id)
                .first()
            )
        return str(chunk.chunk_text) if chunk is not None else None
    finally:
        session.close()


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


def _load_queries(dataset_path: Path) -> list[dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if isinstance(dataset, list):
        queries = dataset
    elif isinstance(dataset, dict):
        queries = dataset.get("queries") or dataset.get("cases") or []
    else:
        queries = []
    return [query for query in queries if isinstance(query, dict)]


def _collect_one(
    client: httpx.Client,
    *,
    engine_url: str,
    question: str,
    scope_token: str,
    deep_search: bool,
) -> tuple[dict[str, Any], int, int]:
    start = time.perf_counter()
    lines: list[str] = []
    ttfb_ms = 0

    with client.stream(
        "POST",
        f"{engine_url.rstrip('/')}/api/v1/chat/answer",
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
        for line in response.iter_lines():
            if ttfb_ms == 0:
                ttfb_ms = round((time.perf_counter() - start) * 1000)
            lines.append(line + "\n")

    total_latency_ms = round((time.perf_counter() - start) * 1000)
    return parse_ndjson_events(lines), ttfb_ms, total_latency_ms


def _error_events(error: str) -> dict[str, Any]:
    return {
        "answer": "",
        "sources": [],
        "token_count": 0,
        "tool_calls": 0,
        "status": "error",
        "error": error,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Collect Prism answer artifacts for offline Ragas evaluation",
    )
    parser.add_argument("--dataset", required=True, help="Path to golden dataset JSON")
    parser.add_argument("--tenant-id", default="default-tenant")
    parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--engine-url", default=f"http://localhost:{settings.ENGINE_PORT}")
    parser.add_argument("--dry-run", action="store_true", help="Collect only first 3 cases")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    queries = _load_queries(dataset_path)
    if args.dry_run:
        queries = queries[:3]

    run_dir = RESULTS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    artifacts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    token_cache: dict[str, Any] = {"token": None, "last": 0.0}

    def scope_token() -> str:
        if token_cache["token"] is None or time.time() - float(token_cache["last"]) > 500:
            token_cache["token"] = _sign_scope(args.tenant_id, args.kb_uid)
            token_cache["last"] = time.time()
        return str(token_cache["token"])

    with httpx.Client(timeout=300.0) as client:
        for index, query in enumerate(queries, start=1):
            question = str(query.get("question") or query.get("query") or "")
            query_id = str(query.get("id") or query.get("query_id") or index)
            print(f"[{index}/{len(queries)}] {query_id} {question[:80]}", flush=True)

            try:
                events, ttfb_ms, total_latency_ms = _collect_one(
                    client,
                    engine_url=args.engine_url,
                    question=question,
                    scope_token=scope_token(),
                    deep_search=_is_deep_search_case(query),
                )
            except Exception as exc:
                failures.append(
                    {"query_id": query_id, "question": question, "error": str(exc)}
                )
                events = _error_events(str(exc))
                ttfb_ms = 0
                total_latency_ms = 0

            artifacts.append(
                build_artifact(
                    query,
                    events,
                    ttfb_ms=ttfb_ms,
                    total_latency_ms=total_latency_ms,
                    lookup_chunk_text=_lookup_chunk_text,
                ).to_dict()
            )

    artifact_path = run_dir / "answer_artifacts.jsonl"
    summary_path = run_dir / "answer_summary.json"
    write_jsonl(artifact_path, artifacts)
    summary_path.write_text(
        json.dumps(
            summarize_artifacts(str(dataset_path), artifacts, failures),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Artifacts: {artifact_path}")
    print(f"Summary: {summary_path}")


def _is_deep_search_case(query: dict[str, Any]) -> bool:
    return (
        query.get("question_type") == "cross_paper"
        or query.get("depth") == "deep"
        or query.get("deep_search_enabled") is True
    )


if __name__ == "__main__":
    main()
