"""Cross-encoder rerank client with graceful degradation.

Calls a rerank HTTP API (Jina/Cohere/bge style). On ANY failure (disabled,
missing config, timeout, non-200, parse error) it returns the input order
unchanged so retrieval never breaks.
"""
import json
import logging
import urllib.request

from ..config import settings

logger = logging.getLogger("uvicorn.error")


def _post_rerank(query: str, docs: list[str], top_n: int) -> list[dict]:
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
    with urllib.request.urlopen(req, timeout=settings.RERANK_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or data.get("data") or []
    return [{"index": r.get("index", r.get("document_index"))} for r in results if isinstance(r, dict)]


def rerank(query: str, candidates: list[dict], top_n: int, enabled: bool | None = None) -> list[dict]:
    """Rerank candidates by relevance to query. Never raises.

    Each candidate may carry a "text" used as the rerank document. Returns the
    reordered list (top_n), each tagged source_marker='rerank' on success.
    """
    if enabled is None:
        enabled = settings.RERANK_ENABLED
    if not enabled or not candidates:
        return candidates[:top_n]
    docs = [c.get("text") or c.get("chunk_id") or "" for c in candidates]
    try:
        order = _post_rerank(query, docs, top_n)
    except Exception as exc:
        logger.warning("[rerank] degraded (using input order) err=%s", exc)
        return candidates[:top_n]
    out: list[dict] = []
    for entry in order:
        idx = entry.get("index")
        if isinstance(idx, int) and 0 <= idx < len(candidates):
            item = dict(candidates[idx]); item["source_marker"] = "rerank"
            out.append(item)
    if not out:  # parsing yielded nothing usable -> degrade
        return candidates[:top_n]
    return out[:top_n]
