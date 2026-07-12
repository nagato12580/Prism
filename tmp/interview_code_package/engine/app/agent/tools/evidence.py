from __future__ import annotations

import json
from typing import Any


MAX_EXCERPT_CHARS = 1600


def normalize_evidence_items(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in payload.get("sources") or []:
        if isinstance(source, dict):
            candidates.append(source)
    for source in payload.get("evidence") or []:
        if isinstance(source, dict):
            candidates.append(source)
    for material in payload.get("materials") or []:
        if not isinstance(material, dict):
            continue
        for source in material.get("raw_evidence") or []:
            if isinstance(source, dict):
                candidates.append(source)
        source = material.get("source")
        if isinstance(source, dict):
            candidates.append(source)

    normalized: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for source in candidates:
        item = _source_to_evidence(tool_name, source)
        if item is None:
            continue
        key = item["evidence_id"]
        if key in seen:
            normalized[seen[key]] = _merge_evidence_item(normalized[seen[key]], item)
            continue
        seen[key] = len(normalized)
        normalized.append(item)
    return normalized


def _source_to_evidence(tool_name: str, source: dict[str, Any]) -> dict[str, Any] | None:
    source_kind = str(source.get("source_kind") or source.get("ref_type") or "")
    chunk_id = _string_or_empty(source.get("chunk_id"))
    source_id = _string_or_empty(source.get("source_id") or source.get("ref_id") or chunk_id)
    item_id = _string_or_empty(source.get("item_id") or source.get("display_id"))
    if not source_kind and chunk_id:
        source_kind = "document_chunk"
    if not source_id and not chunk_id and not item_id:
        return None

    evidence_key = source_id or chunk_id or item_id
    evidence_kind = source_kind or "source"
    excerpt = _bounded_excerpt(
        source.get("snippet")
        or source.get("text")
        or source.get("evidence_span")
        or source.get("summary")
        or source.get("content")
        or ""
    )
    if not excerpt:
        return None
    graph_rag = source.get("graph_rag") if isinstance(source.get("graph_rag"), dict) else {}
    graph_explain = graph_rag.get("explain") if isinstance(graph_rag.get("explain"), dict) else source.get("graph_explain")
    metadata = {
        key: _json_safe_value(value)
        for key, value in {
            "chunk_type": source.get("chunk_type"),
            "chunk_index": source.get("chunk_index"),
            "display_type": source.get("display_type"),
            "display_id": source.get("display_id"),
            "graph_path": source.get("graph_path") or graph_rag.get("path"),
            "graph_explain": graph_explain,
            "evidence_type": source.get("evidence_type")
            or (graph_explain.get("evidence_type") if isinstance(graph_explain, dict) else None),
        }.items()
        if value is not None
    }
    return {
        "evidence_id": f"{evidence_kind}:{evidence_key}",
        "source_kind": evidence_kind,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "parent_chunk_id": _string_or_empty(source.get("parent_chunk_id") or source.get("parent_id")),
        "item_id": item_id,
        "display_title": _string_or_empty(source.get("display_title") or source.get("doc_name") or source.get("title")),
        "excerpt": excerpt,
        "hit_reason": _string_or_empty(source.get("hit_reason")) or f"matched {tool_name} result",
        "score": _number_or_none(_first_present(source, "score", "raw_score")),
        "retrieval_path": [tool_name],
        "metadata": metadata,
    }


def _string_or_empty(value: Any) -> str:
    return str(value) if value is not None else ""


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _merge_evidence_item(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        if key == "metadata":
            merged[key] = _merge_metadata(
                current.get("metadata") if isinstance(current.get("metadata"), dict) else {},
                value if isinstance(value, dict) else {},
            )
            continue
        if key == "retrieval_path":
            merged[key] = _merge_retrieval_path(current.get("retrieval_path"), value)
            continue
        merged[key] = _prefer_more_complete(current.get(key), value)
    return merged


def _merge_metadata(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        if key == "graph_explain":
            existing = merged.get(key) if isinstance(merged.get(key), dict) else {}
            candidate = value if isinstance(value, dict) else {}
            merged[key] = {
                **existing,
                **candidate,
            }
            continue
        merged[key] = _prefer_more_complete(merged.get(key), value)
    return merged


def _merge_retrieval_path(current: Any, incoming: Any) -> list[str]:
    merged: list[str] = []
    for path in (current, incoming):
        if not isinstance(path, list):
            continue
        for entry in path:
            if isinstance(entry, str) and entry not in merged:
                merged.append(entry)
    return merged


def _prefer_more_complete(current: Any, incoming: Any) -> Any:
    if _completeness_score(incoming) >= _completeness_score(current):
        return incoming
    return current


def _completeness_score(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.strip())
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, dict):
        score = len(value)
        if "steps" in value and isinstance(value.get("steps"), list):
            score += _completeness_score(value.get("steps"))
        return score
    if isinstance(value, list):
        score = len(value)
        for item in value:
            score += _completeness_score(item)
        return score
    return len(str(value))


def _bounded_excerpt(value: Any) -> str:
    text = str(value or "")
    return text[:MAX_EXCERPT_CHARS]
