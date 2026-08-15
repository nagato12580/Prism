"""Collect Prism chat answer artifacts for offline answer-quality evaluation."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
FetchChunkText = Callable[[str], str | None]


class CachedChunkTextLookup:
    """Cache chunk text lookups for a single artifact collection run."""

    def __init__(
        self,
        fetch_chunk_text: FetchChunkText,
        *,
        close: Callable[[], None] | None = None,
    ) -> None:
        self._fetch_chunk_text = fetch_chunk_text
        self._close = close
        self._cache: dict[str, str | None] = {}

    def __call__(self, chunk_id: str) -> str | None:
        if chunk_id not in self._cache:
            self._cache[chunk_id] = self._fetch_chunk_text(chunk_id)
        return self._cache[chunk_id]

    def close(self) -> None:
        if self._close is not None:
            self._close()


def build_artifact(
    q: dict[str, Any],
    events: dict[str, Any],
    *,
    ttfb_ms: int,
    total_latency_ms: int,
    lookup_chunk_text: ChunkTextLookup | None = None,
    query_id_override: str | None = None,
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
        query_id=str(query_id_override or q.get("id") or q.get("query_id") or ""),
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


def create_scoped_chunk_text_lookup(
    tenant_id: str,
    kb_uid: str,
    active_index_generation: str | None = None,
) -> CachedChunkTextLookup:
    """Create a tenant/kb scoped, cached chunk text lookup for one collector run."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeTopic

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    session = sessionmaker(bind=engine)()
    resolved_generation = active_index_generation or _load_active_index_generation_in_session(
        session,
        KnowledgeTopic,
        tenant_id=tenant_id,
        kb_uid=kb_uid,
    )

    def fetch_chunk_text(chunk_id: str) -> str | None:
        return _lookup_chunk_text_in_session(
            session,
            KnowledgeChunk,
            chunk_id,
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            active_index_generation=resolved_generation,
        )

    def close() -> None:
        session.close()
        engine.dispose()

    return CachedChunkTextLookup(fetch_chunk_text, close=close)


def _lookup_chunk_text_in_session(
    session: Any,
    chunk_model: Any,
    chunk_id: str,
    *,
    tenant_id: str,
    kb_uid: str,
    active_index_generation: str | None = None,
) -> str | None:
    """Find a chunk by row id or public chunk_uid within the authorized scope."""
    if not chunk_id:
        return None

    for field_name in ("id", "chunk_uid"):
        if not hasattr(chunk_model, field_name):
            continue

        query = session.query(chunk_model).filter(getattr(chunk_model, field_name) == chunk_id)
        query = _apply_chunk_scope(query, chunk_model, tenant_id=tenant_id, kb_uid=kb_uid)
        query = _apply_active_generation(query, chunk_model, active_index_generation)
        query = _prefer_current_chunk_rows(query, chunk_model)
        chunk = query.first()
        if chunk is not None:
            text = getattr(chunk, "chunk_text", None)
            return str(text) if text is not None else None
    return None


def _apply_chunk_scope(
    query: Any,
    chunk_model: Any,
    *,
    tenant_id: str,
    kb_uid: str,
) -> Any:
    if tenant_id and hasattr(chunk_model, "tenant_id"):
        query = query.filter(chunk_model.tenant_id == tenant_id)
    if kb_uid and hasattr(chunk_model, "kb_uid"):
        query = query.filter(chunk_model.kb_uid == kb_uid)
    return query


def _apply_active_generation(
    query: Any,
    chunk_model: Any,
    active_index_generation: str | None,
) -> Any:
    if active_index_generation and hasattr(chunk_model, "generation"):
        query = query.filter(chunk_model.generation == active_index_generation)
    return query


def _prefer_current_chunk_rows(query: Any, chunk_model: Any) -> Any:
    from sqlalchemy import case

    order_clauses = []
    if hasattr(chunk_model, "is_active"):
        order_clauses.append(case((chunk_model.is_active.is_(True), 1), else_=0).desc())
    if hasattr(chunk_model, "status"):
        order_clauses.append(case((chunk_model.status == "active", 1), else_=0).desc())
    if hasattr(chunk_model, "created_at"):
        order_clauses.append(chunk_model.created_at.desc())
    if hasattr(chunk_model, "id"):
        order_clauses.append(chunk_model.id.desc())
    if order_clauses:
        query = query.order_by(*order_clauses)
    return query


def _load_active_index_generation_in_session(
    session: Any,
    topic_model: Any,
    *,
    tenant_id: str,
    kb_uid: str,
) -> str | None:
    if not hasattr(topic_model, "active_index_generation"):
        return None

    query = session.query(topic_model)
    if tenant_id and hasattr(topic_model, "tenant_id"):
        query = query.filter(topic_model.tenant_id == tenant_id)
    if kb_uid and hasattr(topic_model, "kb_uid"):
        query = query.filter(topic_model.kb_uid == kb_uid)
    topic = query.first()
    if topic is None:
        return None
    generation = getattr(topic, "active_index_generation", None)
    return str(generation) if generation else None


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
    chunk_lookup = create_scoped_chunk_text_lookup(args.tenant_id, args.kb_uid)

    def scope_token() -> str:
        if token_cache["token"] is None or time.time() - float(token_cache["last"]) > 500:
            token_cache["token"] = _sign_scope(args.tenant_id, args.kb_uid)
            token_cache["last"] = time.time()
        return str(token_cache["token"])

    try:
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
                        lookup_chunk_text=chunk_lookup,
                        query_id_override=query_id,
                    ).to_dict()
                )
    finally:
        chunk_lookup.close()

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
