"""Versioned knowledge enrichment built only from public, bounded inputs."""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from collections import defaultdict, deque
from copy import deepcopy
from hashlib import sha256
from math import isfinite
from pathlib import PurePosixPath
from typing import Any, Iterable

from sqlalchemy import func, or_

from backend.app.models import (
    EvaluationDataset,
    EvaluationDatasetItem,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeTopic,
)
from backend.app.models.entity import EntityMention, EntityRelation
from backend.app.utils.time import local_now


MAX_REPRESENTATIVE_CHUNKS = 24
MAX_REPRESENTATIVE_CHARS = 12_000
MAX_SUMMARY_CHARS = 800
MAX_FILES = 500
MAX_QUESTIONS = 50
MAX_QUESTION_CHARS = 500
MAX_MINDMAP_NODES = 2_000
MAX_EXPORT_ENTRIES = 1_200
MAX_EXPORT_ENTRY_BYTES = 5 * 1024 * 1024
MAX_EXPORT_BYTES = 50 * 1024 * 1024

_SAFE_CONFIG_KEYS = {
    "embedding": frozenset({"model", "dimension", "dimensions", "normalize", "version"}),
    "parser": frozenset({"preset", "preset_id", "ocr", "language", "version"}),
    "chunk": frozenset({"preset", "preset_id", "chunk_size", "overlap", "version"}),
    "retrieval": frozenset({"mode", "top_k", "graph_hops", "rrf_k", "rerank_top_k", "dense_weight", "bm25_weight", "graph_weight"}),
    "graph": frozenset({"mode", "graph_hops", "max_hops", "enabled", "version"}),
}


def _json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("enrichment response must be a JSON object")
    return value


def call_llm(kind: str, payload: dict[str, Any], *, model: str | None = None, prompt_version: str | None = None) -> dict[str, Any]:
    """Call the configured model with a JSON-only, already bounded payload."""
    from engine.app.llm.client import chat

    if kind == "mindmap":
        instruction = "Return JSON object {nodes:[{id,title,file_uid?,relative_path?,children:[]}]}. Use only supplied public file_uid values."
    elif kind == "sample_questions":
        instruction = "Return JSON object {questions:[string]}. Questions must be answerable from the supplied summaries."
    else:
        raise ValueError("unsupported enrichment kind")
    raw = chat(
        [
            {"role": "system", "content": f"{instruction} Prompt version: {prompt_version or 'v1'}."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        model=model,
        timeout_seconds=90,
        max_retries=0,
    )
    return _json_object(raw)


def _safe_relative_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return ""
    raw_parts = text.split("/")
    if ".." in raw_parts:
        return ""
    parts = [part for part in raw_parts if part not in {"", "."}]
    return "/".join(parts)[:1024]


def _safe_name(value: Any, fallback: str) -> str:
    text = str(value or "").replace("\\", "/").split("/")[-1]
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-")
    return (text[:120] or fallback)


def safe_display_name(value: Any, fallback: str = "Untitled") -> str:
    text = str(value or "").replace("\\", "/").split("/")[-1]
    text = "".join(char for char in text if char >= " " and char not in {'"', "'"}).strip(" .")
    return text[:255] or fallback


def safe_relative_path(value: Any, *, fallback_basename: str = "") -> str:
    safe = _safe_relative_path(value)
    if safe:
        return safe
    return safe_display_name(value, fallback_basename) if value else fallback_basename


def _node_matches(node: dict[str, Any], file_uid: str) -> bool:
    return str(node.get("file_uid") or node.get("id") or "") == file_uid


def _remove_nodes(nodes: list[dict[str, Any]], deleted: set[str]) -> list[dict[str, Any]]:
    result = []
    for source in nodes:
        if not isinstance(source, dict) or any(_node_matches(source, uid) for uid in deleted):
            continue
        node = deepcopy(source)
        node["children"] = _remove_nodes(list(node.get("children") or []), deleted)
        result.append(node)
    return result


def _rename_nodes(nodes: list[dict[str, Any]], renamed: dict[str, dict[str, Any]]) -> None:
    for node in nodes:
        file_uid = str(node.get("file_uid") or node.get("id") or "")
        change = renamed.get(file_uid)
        if change:
            if change.get("title") is not None:
                node["title"] = str(change["title"])[:500]
            if "relative_path" in change:
                node["relative_path"] = _safe_relative_path(change.get("relative_path"))
        _rename_nodes(list(node.get("children") or []), renamed)


def apply_mindmap_diff(
    existing: dict[str, Any] | None,
    *,
    added: Iterable[Any],
    deleted: Iterable[str],
    renamed: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Apply delete/rename without a model; additions require generation."""
    current = deepcopy(existing) if isinstance(existing, dict) else {"status": "stale", "nodes": []}
    nodes = list(current.get("nodes") or [])
    deleted_set = {str(value) for value in deleted if value}
    nodes = _remove_nodes(nodes, deleted_set)
    rename_map = {
        str(row.get("file_uid")): row
        for row in renamed
        if isinstance(row, dict) and row.get("file_uid")
    }
    _rename_nodes(nodes, rename_map)
    current["nodes"] = nodes
    unplaced = []
    for raw in list(added):
        if not isinstance(raw, dict) or not raw.get("file_uid") or not raw.get("title") or raw.get("complex"):
            unplaced.append(str(raw.get("file_uid") if isinstance(raw, dict) else raw))
            continue
        node = {
            "id": str(raw.get("id") or raw["file_uid"])[:128],
            "file_uid": str(raw["file_uid"])[:64],
            "title": safe_display_name(raw["title"]),
            "children": [],
        }
        relative_path = _safe_relative_path(raw.get("relative_path"))
        if relative_path:
            node["relative_path"] = relative_path
        parent_id = raw.get("parent_id")
        if parent_id is None:
            nodes.append(node)
            continue
        def insert(rows):
            for candidate in rows:
                if str(candidate.get("id")) == str(parent_id):
                    candidate.setdefault("children", []).append(node)
                    return True
                if insert(candidate.get("children") or []):
                    return True
            return False
        if not insert(nodes):
            unplaced.append(str(raw["file_uid"]))
    if unplaced:
        current["status"] = "stale"
        current["stale_reason"] = "files_added"
        current["unplaced_file_uids"] = unplaced
    else:
        current.pop("unplaced_file_uids", None)
    return current


def _value(row: Any, *names: str, default=None):
    for name in names:
        if isinstance(row, dict) and name in row:
            return row[name]
        if hasattr(row, name):
            return getattr(row, name)
    return default


def _snapshot_input_revision(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    try:
        return max(0, int(value.get("input_revision") or 0))
    except (TypeError, ValueError):
        return 0


def select_representative_chunks(
    chunks: Iterable[Any],
    *,
    max_chunks: int = MAX_REPRESENTATIVE_CHUNKS,
    max_chars: int = MAX_REPRESENTATIVE_CHARS,
    per_chunk_chars: int = MAX_SUMMARY_CHARS,
) -> list[dict[str, Any]]:
    """Round-robin across file/heading strata under hard count/character caps."""
    max_chunks = max(0, min(int(max_chunks), MAX_REPRESENTATIVE_CHUNKS))
    max_chars = max(0, min(int(max_chars), MAX_REPRESENTATIVE_CHARS))
    per_chunk_chars = max(1, min(int(per_chunk_chars), MAX_SUMMARY_CHARS))
    strata: dict[tuple[str, tuple[str, ...]], deque[dict[str, Any]]] = defaultdict(deque)
    for row in chunks:
        file_uid = str(_value(row, "file_uid", default="") or "")
        chunk_uid = str(_value(row, "chunk_uid", "id", default="") or "")
        raw_path = _value(row, "title_path", default=[]) or []
        title_path = tuple(str(part)[:200] for part in raw_path[:8]) if isinstance(raw_path, (list, tuple)) else ()
        text = str(_value(row, "summary", "text", "chunk_text", default="") or "").strip()
        if not file_uid or not text:
            continue
        strata[(file_uid, title_path)].append({
            "chunk_uid": chunk_uid,
            "file_uid": file_uid,
            "title_path": list(title_path),
            "summary": text[:per_chunk_chars],
        })
    selected: list[dict[str, Any]] = []
    used = 0
    file_strata: dict[str, deque[tuple[str, tuple[str, ...]]]] = defaultdict(deque)
    for key in sorted(strata):
        file_strata[key[0]].append(key)
    files = sorted(file_strata)
    while files and len(selected) < max_chunks and used < max_chars:
        next_files = []
        for file_uid in files:
            if len(selected) >= max_chunks or used >= max_chars:
                break
            headings = file_strata[file_uid]
            if not headings:
                continue
            key = headings.popleft()
            queue = strata[key]
            if not queue:
                continue
            candidate = queue.popleft()
            remaining = max_chars - used
            if remaining <= 0:
                break
            candidate["summary"] = candidate["summary"][:remaining]
            if candidate["summary"]:
                selected.append(candidate)
                used += len(candidate["summary"])
            if queue:
                headings.append(key)
            if headings:
                next_files.append(file_uid)
        files = next_files
    return selected


def _sanitize_nodes(nodes: Iterable[Any], *, allowed_file_uids: set[str] | None = None) -> list[dict[str, Any]]:
    count = 0

    def clean(rows: Iterable[Any], depth: int) -> list[dict[str, Any]]:
        nonlocal count
        if depth > 16:
            return []
        result = []
        for raw in rows:
            if count >= MAX_MINDMAP_NODES or not isinstance(raw, dict):
                break
            file_uid = str(raw.get("file_uid") or "")[:64]
            if file_uid and allowed_file_uids is not None and file_uid not in allowed_file_uids:
                continue
            title = str(raw.get("title") or "Untitled")[:500]
            node_id = str(raw.get("id") or file_uid or sha256(f"{depth}:{title}:{count}".encode()).hexdigest()[:24])[:128]
            count += 1
            node = {"id": node_id, "title": title, "children": clean(raw.get("children") or [], depth + 1)}
            if file_uid:
                node["file_uid"] = file_uid
            relative_path = _safe_relative_path(raw.get("relative_path"))
            if relative_path:
                node["relative_path"] = relative_path
            result.append(node)
        return result

    return clean(nodes, 0)


def store_mindmap(
    db,
    topic: KnowledgeTopic,
    *,
    nodes: Iterable[Any],
    index_generation: str | None,
    graph_generation: str | None,
    model: str,
    prompt_version: str,
    status: str = "ready",
) -> dict[str, Any]:
    version = int(topic.mindmap_version or 0) + 1
    input_revision = _snapshot_input_revision(topic.mindmap)
    snapshot = {
        "status": status,
        "version": version,
        "input_revision": input_revision,
        "index_generation": index_generation,
        "graph_generation": graph_generation,
        "model": str(model)[:255],
        "prompt_version": str(prompt_version)[:128],
        "generated_at": local_now().isoformat(),
        "nodes": _sanitize_nodes(nodes),
    }
    topic.mindmap = snapshot
    topic.mindmap_version = version
    topic.mindmap_generated_at = local_now()
    db.flush()
    db.refresh(topic)
    return deepcopy(snapshot)


def store_sample_questions(
    db,
    topic: KnowledgeTopic,
    *,
    questions: Iterable[Any],
    index_generation: str | None,
    graph_generation: str | None,
    model: str,
    prompt_version: str,
    status: str = "ready",
) -> dict[str, Any]:
    clean_questions = []
    for value in questions:
        question = str(value).strip()[:MAX_QUESTION_CHARS]
        if question and question not in clean_questions:
            clean_questions.append(question)
        if len(clean_questions) >= MAX_QUESTIONS:
            break
    version = int(topic.sample_questions_version or 0) + 1
    input_revision = _snapshot_input_revision(topic.sample_questions)
    snapshot = {
        "status": status,
        "version": version,
        "input_revision": input_revision,
        "index_generation": index_generation,
        "graph_generation": graph_generation,
        "model": str(model)[:255],
        "prompt_version": str(prompt_version)[:128],
        "generated_at": local_now().isoformat(),
        "questions": clean_questions,
    }
    topic.sample_questions = snapshot
    topic.sample_questions_version = version
    db.flush()
    db.refresh(topic)
    return deepcopy(snapshot)


def mark_topic_enrichment_stale(
    topic: KnowledgeTopic,
    *,
    reason: str,
    deleted_file_uids: Iterable[str] = (),
    renamed: Iterable[dict[str, Any]] = (),
    increment_input_revision: bool = True,
) -> KnowledgeTopic:
    """Mutate one topic so callers can include staleness in their transaction."""
    questions = deepcopy(topic.sample_questions) if isinstance(topic.sample_questions, dict) else {
        "version": int(topic.sample_questions_version or 0),
        "questions": [],
    }
    question_revision = _snapshot_input_revision(questions)
    if increment_input_revision:
        question_revision += 1
    questions["status"] = "stale"
    questions["stale_reason"] = str(reason)[:128]
    questions["input_revision"] = question_revision
    questions.setdefault("questions", [])
    topic.sample_questions = questions
    deleted = list(deleted_file_uids)
    renamed_rows = list(renamed)
    mindmap = apply_mindmap_diff(topic.mindmap, added=[], deleted=deleted, renamed=renamed_rows)
    mindmap_revision = _snapshot_input_revision(mindmap)
    if increment_input_revision:
        mindmap_revision += 1
    mindmap["input_revision"] = mindmap_revision
    mindmap.setdefault("version", int(topic.mindmap_version or 0))
    if deleted or renamed_rows:
        topic.mindmap_version = int(topic.mindmap_version or mindmap.get("version") or 0) + 1
        mindmap["version"] = topic.mindmap_version
        mindmap["updated_without_model"] = True
    else:
        mindmap["status"] = "stale"
        mindmap["stale_reason"] = str(reason)[:128]
    topic.mindmap = mindmap
    return topic


def mark_enrichment_stale(
    db,
    kb_uid: str,
    *,
    reason: str,
    deleted_file_uids: Iterable[str] = (),
    renamed: Iterable[dict[str, Any]] = (),
    commit: bool = True,
) -> KnowledgeTopic | None:
    topic = (
        db.query(KnowledgeTopic)
        .filter_by(kb_uid=kb_uid, deleted_at=None)
        .populate_existing()
        .with_for_update()
        .one_or_none()
    )
    if topic is None:
        return None
    mark_topic_enrichment_stale(
        topic,
        reason=reason,
        deleted_file_uids=deleted_file_uids,
        renamed=renamed,
    )
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(topic)
    return topic


def activate_graph_generation(db, kb_uid: str, generation: str, *, expected_old: str | None):
    """The sole graph-activation boundary until the later production Graph plan lands."""
    topic = db.query(KnowledgeTopic).filter_by(
        kb_uid=kb_uid, active_graph_generation=expected_old, deleted_at=None,
    ).with_for_update().one_or_none()
    if topic is None:
        raise RuntimeError("active graph generation changed concurrently")
    topic.active_graph_generation = generation
    mark_topic_enrichment_stale(topic, reason="active_graph_generation_changed")
    db.commit()
    db.refresh(topic)
    return topic


def representative_chunks_for_topic(db, topic: KnowledgeTopic) -> list[dict[str, Any]]:
    query = db.query(KnowledgeChunk).filter_by(tenant_id=topic.tenant_id, kb_uid=topic.kb_uid)
    if topic.active_index_generation:
        current = query.filter(KnowledgeChunk.generation == topic.active_index_generation).all()
    else:
        current = []
    rows = current or query.order_by(KnowledgeChunk.file_uid, KnowledgeChunk.chunk_index, KnowledgeChunk.id).limit(2_000).all()
    return select_representative_chunks(rows)


def mindmap_input_for_topic(db, topic: KnowledgeTopic) -> dict[str, Any]:
    summaries = defaultdict(list)
    for row in representative_chunks_for_topic(db, topic):
        summaries[row["file_uid"]].append({"title_path": row["title_path"], "summary": row["summary"]})
    files = (
        db.query(KnowledgeFile)
        .filter_by(tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, deleted_at=None)
        .order_by(KnowledgeFile.relative_path, KnowledgeFile.file_uid)
        .limit(MAX_FILES)
        .all()
    )
    return {
        "knowledge_base": {"kb_uid": topic.kb_uid, "title": topic.name[:255]},
        "files": [
            {
                "file_uid": row.file_uid,
                "title": str(row.title or row.original_filename or "Untitled")[:255],
                "relative_path": _safe_relative_path(row.relative_path),
                "representative_summaries": summaries[row.file_uid][:4],
            }
            for row in files
        ],
    }


def generate_mindmap(db, topic: KnowledgeTopic, *, model: str, prompt_version: str, llm=call_llm) -> list[dict[str, Any]]:
    payload = mindmap_input_for_topic(db, topic)
    result = llm("mindmap", payload, model=model, prompt_version=prompt_version)
    allowed = {row["file_uid"] for row in payload["files"]}
    return _sanitize_nodes(result.get("nodes") or [], allowed_file_uids=allowed)


def generate_sample_questions(db, topic: KnowledgeTopic, *, model: str, prompt_version: str, llm=call_llm) -> list[str]:
    representatives = representative_chunks_for_topic(db, topic)
    files = (
        db.query(KnowledgeFile.file_uid, KnowledgeFile.title, KnowledgeFile.original_filename, KnowledgeFile.relative_path)
        .filter_by(tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, deleted_at=None)
        .order_by(KnowledgeFile.file_uid)
        .limit(MAX_FILES)
        .all()
    )
    payload = {
        "knowledge_base": {"kb_uid": topic.kb_uid, "title": topic.name[:255]},
        "files": [
            {"file_uid": row.file_uid, "title": str(row.title or row.original_filename or "Untitled")[:255], "relative_path": _safe_relative_path(row.relative_path)}
            for row in files
        ],
        "representative_chunks": representatives,
    }
    result = llm("sample_questions", payload, model=model, prompt_version=prompt_version)
    questions = []
    for raw in result.get("questions") or []:
        value = str(raw).strip()[:MAX_QUESTION_CHARS]
        if value and value not in questions:
            questions.append(value)
        if len(questions) >= MAX_QUESTIONS:
            break
    return questions


def _safe_config(value: Any, kind: str) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result = {}
    for key in sorted(_SAFE_CONFIG_KEYS[kind]):
        if key not in source:
            continue
        item = source.get(key)
        if item is None or isinstance(item, (str, bool, int)) or isinstance(item, float) and isfinite(item):
            result[key] = item
    return result


class _BudgetedZipEntry:
    def __init__(self, builder, handle):
        self.builder = builder
        self.handle = handle
        self.size = 0

    def write(self, content: str | bytes):
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(data) > self.builder.max_entry_bytes or self.size + len(data) > self.builder.max_entry_bytes:
            raise ValueError("knowledge export entry budget exceeded")
        if self.builder.total + len(data) > self.builder.max_total_bytes:
            raise ValueError("knowledge export budget exceeded")
        self.handle.write(data)
        self.size += len(data)
        self.builder.total += len(data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.handle.close()


class _ZipBuilder:
    def __init__(self, *, max_entries: int, max_entry_bytes: int, max_total_bytes: int, spool_max_size: int):
        self.spool = tempfile.SpooledTemporaryFile(max_size=spool_max_size, mode="w+b")
        self.archive = zipfile.ZipFile(self.spool, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6)
        self.names: set[str] = set()
        self.count = 0
        self.total = 0
        self.max_entries = max_entries
        self.max_entry_bytes = max_entry_bytes
        self.max_total_bytes = max_total_bytes

    def open(self, name: str):
        normalized = str(PurePosixPath(name))
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or normalized in self.names:
            raise ValueError("unsafe or duplicate ZIP entry")
        if self.count >= self.max_entries:
            raise ValueError("knowledge export entry count exceeded")
        info = zipfile.ZipInfo(normalized, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        handle = self.archive.open(info, "w")
        self.names.add(normalized)
        self.count += 1
        return _BudgetedZipEntry(self, handle)

    def add(self, name: str, content: str | bytes):
        with self.open(name) as entry:
            entry.write(content)

    def finish(self):
        self.archive.close()
        self.spool.seek(0, 2)
        if self.spool.tell() > self.max_total_bytes:
            self.spool.close()
            raise ValueError("knowledge export archive budget exceeded")
        self.spool.seek(0)
        return self.spool

    def abort(self):
        try:
            self.archive.close()
        finally:
            self.spool.close()


def _json_bytes(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_BLOCKED_EXPORT_KEYS = ("secret", "password", "api_key", "token", "provider", "storage", "file_path", "vector", "embedding")


def _safe_export_value(value: Any, *, field: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_export_value(item, field=str(key))
            for key, item in value.items()
            if not any(blocked in str(key).lower() for blocked in _BLOCKED_EXPORT_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_safe_export_value(item, field=field) for item in value]
    if isinstance(value, str) and field.lower() in {"name", "title", "original_filename", "filename"}:
        return safe_display_name(value)
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def _write_json_rows(entry, rows, mapper, *, limit: int):
    for index, row in enumerate(rows):
        if index >= limit:
            break
        encoded = _json_bytes(_safe_export_value(mapper(row))) + "\n"
        if len(encoded.encode("utf-8")) > entry.builder.max_entry_bytes:
            raise ValueError("knowledge export entry budget exceeded")
        entry.write(encoded)


def build_knowledge_export(
    db,
    topic: KnowledgeTopic,
    *,
    max_files: int = MAX_FILES,
    max_entries: int = MAX_EXPORT_ENTRIES,
    max_entry_bytes: int = MAX_EXPORT_ENTRY_BYTES,
    max_total_bytes: int = MAX_EXPORT_BYTES,
    spool_max_size: int = 2 * 1024 * 1024,
):
    max_files = max(1, min(int(max_files), MAX_FILES))
    max_entries = max(8, min(int(max_entries), MAX_EXPORT_ENTRIES))
    max_entry_bytes = max(1_024, min(int(max_entry_bytes), MAX_EXPORT_ENTRY_BYTES))
    max_total_bytes = max(8_192, min(int(max_total_bytes), MAX_EXPORT_BYTES))
    spool_max_size = max(1, min(int(spool_max_size), MAX_EXPORT_BYTES))
    builder = _ZipBuilder(
        max_entries=max_entries, max_entry_bytes=max_entry_bytes,
        max_total_bytes=max_total_bytes, spool_max_size=spool_max_size,
    )
    try:
        file_count = db.query(func.count(KnowledgeFile.id)).filter_by(
            tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, deleted_at=None,
        ).scalar() or 0
        builder.add("manifest.json", _json_bytes(_safe_export_value({
            "format": "prism-knowledge-export-v1",
            "knowledge_base": {"kb_uid": topic.kb_uid, "name": topic.name, "version": topic.version},
            "index_generation": topic.active_index_generation,
            "graph_generation": topic.active_graph_generation,
            "file_count": min(file_count, max_files),
        })))
        builder.add("config.json", _json_bytes(_safe_export_value({
            "embedding": _safe_config(topic.embedding_profile, "embedding"),
            "parser": _safe_config(topic.parser_config, "parser"),
            "chunk": _safe_config(topic.chunk_config, "chunk"),
            "retrieval": _safe_config(topic.retrieval_config, "retrieval"),
            "graph": _safe_config(topic.graph_config, "graph"),
        })))
        files = db.query(KnowledgeFile).filter_by(
            tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, deleted_at=None,
        ).order_by(KnowledgeFile.file_uid).limit(max_files).yield_per(100)
        item_ids: list[str] = []
        document_refs: list[tuple[int, str, str, str]] = []
        with builder.open("files.json") as entry:
            entry.write("[")
            for ordinal, row in enumerate(files):
                public = _safe_export_value({
                    "file_uid": row.file_uid,
                    "title": row.title or row.original_filename,
                    "relative_path": _safe_relative_path(row.relative_path),
                    "media_type": row.media_type,
                    "mime_type": row.mime_type,
                    "content_sha256": row.content_sha256,
                    "size_bytes": row.size_bytes,
                    "parsed_content_version": row.parsed_content_version,
                })
                entry.write(("," if ordinal else "") + _json_bytes(public))
                if row.item_id:
                    item_ids.append(row.item_id)
                    document_refs.append((ordinal, row.item_id, row.file_uid, row.original_filename or row.title or ""))
            entry.write("]")
        for ordinal, item_id, file_uid, display_name in document_refs:
            item = db.query(KnowledgeItem).filter_by(
                id=item_id, tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
            ).one_or_none()
            if item is not None:
                name = _safe_name(display_name, f"document-{ordinal + 1}.md")
                if not name.lower().endswith(".md"):
                    name += ".md"
                builder.add(
                    f"documents/{ordinal + 1:04d}-{name}-{file_uid[:8]}.md",
                    item.normalized_markdown or item.content or "",
                )

        datasets = db.query(EvaluationDataset).filter_by(
            tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
        ).order_by(EvaluationDataset.dataset_uid).limit(100).yield_per(25)
        for ordinal, dataset in enumerate(datasets):
            rows = db.query(EvaluationDatasetItem).filter_by(
                dataset_id=dataset.id, tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
            ).order_by(EvaluationDatasetItem.ordinal).limit(10_000).yield_per(100)
            with builder.open(f"evaluation/{ordinal + 1:04d}-{dataset.dataset_uid[:12]}.jsonl") as entry:
                _write_json_rows(entry, rows, lambda row: {
                    "query": row.query,
                    "gold_chunk_uids": list(row.gold_chunk_uids or []),
                    "gold_answer": row.gold_answer,
                }, limit=10_000)

        source_ids = set(item_ids)
        chunk_rows = db.query(KnowledgeChunk.id, KnowledgeChunk.chunk_uid).filter_by(
            tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
        ).limit(20_000).yield_per(500)
        for row_id, chunk_uid in chunk_rows:
            source_ids.add(row_id)
            source_ids.add(chunk_uid)
        entity_ids: set[str] = set()
        if source_ids:
            mentions = db.query(EntityMention.entity_id).filter(
                or_(EntityMention.item_id.in_(item_ids), EntityMention.source_id.in_(source_ids)),
            ).limit(20_000).yield_per(500)
            entity_ids.update(row[0] for row in mentions)
        entities = db.query(KnowledgeEntity).filter(
            KnowledgeEntity.id.in_(entity_ids),
        ).order_by(KnowledgeEntity.id).limit(20_000).yield_per(500) if entity_ids else ()
        with builder.open("graph/entities.jsonl") as entry:
            _write_json_rows(entry, entities, lambda row: {
                "entity_uid": row.id, "type": row.entity_type, "name": row.canonical_name,
                "description": row.description, "confidence": row.confidence, "status": row.status,
            }, limit=20_000)
        relations = db.query(EntityRelation).filter(
            EntityRelation.source_id.in_(source_ids),
        ).order_by(EntityRelation.id).limit(20_000).yield_per(500) if source_ids else ()
        with builder.open("graph/relations.jsonl") as entry:
            _write_json_rows(entry, relations, lambda row: {
                "relation_uid": row.id, "subject_entity_uid": row.subject_entity_id,
                "predicate": row.predicate, "object_entity_uid": row.object_entity_id,
                "object_literal": row.object_literal, "evidence": row.evidence_span,
                "confidence": row.confidence,
            }, limit=20_000)
        return builder.finish()
    except Exception:
        builder.abort()
        raise
