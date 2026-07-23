"""Cross-encoder rerank client with graceful degradation.

Calls a rerank HTTP API (Jina/Cohere/bge style). On ANY failure (disabled,
missing config, timeout, non-200, parse error) it returns the input order
unchanged so retrieval never breaks.
"""
import json
import logging
import math
import numbers
import urllib.request

from ..config import settings
from .execution_control import RetrievalExecutionAborted, RetrievalExecutionControl

logger = logging.getLogger("uvicorn.error")


def _post_rerank(query: str, docs: list[str], top_n: int, timeout: float | None = None) -> list[dict]:
    """POST to the configured rerank endpoint; return [{"index": int, ...}].

    Raises on any problem so the caller can degrade.
    """
    if not (settings.RERANK_API_BASE and settings.RERANK_API_KEY and settings.RERANK_MODEL):
        raise RuntimeError("rerank not configured")
    url = settings.RERANK_API_BASE.rstrip("/") + "/rerank"
    body = json.dumps({"model": settings.RERANK_MODEL, "query": query, "documents": docs, "top_n": top_n}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {settings.RERANK_API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout or settings.RERANK_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or data.get("data") or []
    return [
        {"index": r.get("index", r.get("document_index")), "relevance_score": r.get("relevance_score", r.get("score"))}
        for r in results if isinstance(r, dict)
    ]


def _warn_unavailable(warnings: list[dict] | None, exc: Exception) -> None:
    logger.warning("[rerank] RERANK_UNAVAILABLE (using input order) err=%s", exc)
    if warnings is not None:
        warnings.append({"code": "RERANK_UNAVAILABLE", "message": str(exc), "retryable": True})


def _validated_order(order: list[dict], candidate_count: int, top_n: int) -> list[tuple[int, float | None]]:
    expected_count = min(candidate_count, top_n)
    if len(order) != expected_count:
        raise ValueError(f"rerank returned {len(order)} results; expected {expected_count}")
    validated: list[tuple[int, float | None]] = []
    seen: set[int] = set()
    for entry in order:
        idx = entry.get("index")
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < candidate_count or idx in seen:
            raise ValueError("rerank returned an invalid or duplicate index")
        seen.add(idx)
        score = entry.get("relevance_score")
        if score is None:
            raise ValueError("rerank result is missing a relevance score")
        if not isinstance(score, numbers.Real) or isinstance(score, bool) or not math.isfinite(float(score)):
            raise ValueError("rerank returned a non-numeric relevance score")
        validated.append((idx, float(score)))
    return validated


def rerank(
    query: str,
    candidates: list[dict],
    top_n: int,
    enabled: bool | None = None,
    *,
    warnings: list[dict] | None = None,
    control: RetrievalExecutionControl | None = None,
) -> list[dict]:
    """Rerank candidates by relevance to query. Never raises.

    Each candidate may carry a "text" used as the rerank document. Returns the
    reordered list (top_n), each tagged source_marker='rerank' on success.
    """
    if enabled is None:
        enabled = settings.RERANK_ENABLED
    if not enabled or not candidates:
        return candidates[:top_n]
    docs = [c.get("text") for c in candidates]
    if any(not isinstance(doc, str) or not doc.strip() for doc in docs):
        _warn_unavailable(warnings, ValueError("rerank candidates must contain non-empty text"))
        return candidates[:top_n]
    try:
        if control: control.checkpoint()
        if control:
            order = _post_rerank(query, docs, top_n, control.remaining_timeout(30))
        else:
            order = _post_rerank(query, docs, top_n)
        if control: control.checkpoint()
        validated = _validated_order(order, len(candidates), top_n)
    except RetrievalExecutionAborted:
        raise
    except Exception as exc:
        _warn_unavailable(warnings, exc)
        return candidates[:top_n]
    out: list[dict] = []
    for idx, score in validated:
        item = dict(candidates[idx]); item["source_marker"] = "rerank"
        if score is not None:
            item["rerank_score"] = score
        out.append(item)
    return out[:top_n]
