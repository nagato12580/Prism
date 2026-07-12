from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem


SessionFactory = Callable[[], Any]


def _meta_value(meta: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(meta, dict):
        return None
    for key in keys:
        if key in meta and meta[key] not in (None, ""):
            return meta[key]
    return None


def _as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _page_range(meta: dict[str, Any] | None, fallback: int) -> tuple[int, int]:
    start = _as_int(_meta_value(meta, "page_start", "start_page", "page"), fallback)
    end = _as_int(_meta_value(meta, "page_end", "end_page", "page"), start)
    if end < start:
        end = start
    return start, end


def _format_pages(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def _parse_pages(pages: str) -> list[int]:
    selected: set[int] = set()
    for part in re.split(r"\s*,\s*", pages.strip()):
        if not part:
            continue
        if "-" in part:
            raw_start, raw_end = part.split("-", 1)
            start = _as_int(raw_start.strip(), 0)
            end = _as_int(raw_end.strip(), start)
            if start <= 0:
                continue
            if end < start:
                start, end = end, start
            selected.update(range(start, end + 1))
        else:
            page = _as_int(part, 0)
            if page > 0:
                selected.add(page)
    return sorted(selected)


class PageIndexService:
    """Builds a PageIndex-like view from Prism knowledge chunks."""

    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory

    def get_document(self, doc_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            item = db.query(KnowledgeItem).filter(KnowledgeItem.id == doc_id).first()
            if not item:
                return {
                    "status": "missing",
                    "doc_id": doc_id,
                    "name": "",
                    "page_count": 0,
                    "chunk_count": 0,
                }
            chunks = self._chunks_for_item(db, doc_id)
            page_count = self._page_count(chunks)
            return {
                "status": "ready",
                "doc_id": str(item.id),
                "name": item.title or "",
                "source_type": item.source_type or "",
                "page_count": page_count,
                "chunk_count": len(chunks),
                "parent_count": sum(1 for chunk in chunks if chunk.chunk_type == "parent"),
                "child_count": sum(1 for chunk in chunks if chunk.chunk_type == "child"),
            }
        finally:
            db.close()

    def get_document_structure(self, doc_id: str) -> dict[str, Any]:
        db = self._session_factory()
        try:
            item = db.query(KnowledgeItem).filter(KnowledgeItem.id == doc_id).first()
            chunks = self._chunks_for_item(db, doc_id)
            parents = [chunk for chunk in chunks if chunk.chunk_type == "parent"]
            children_by_parent: dict[str, list[KnowledgeChunk]] = defaultdict(list)
            for chunk in chunks:
                if chunk.chunk_type == "child" and chunk.parent_id:
                    children_by_parent[str(chunk.parent_id)].append(chunk)

            sections: list[dict[str, Any]] = []
            for index, parent in enumerate(parents, start=1):
                start, end = _page_range(parent.extra_meta, index)
                title = str(
                    _meta_value(parent.extra_meta, "heading", "title", "section")
                    or self._infer_heading(parent.chunk_text)
                    or f"Section {index}"
                )
                child_payload = []
                for child in sorted(children_by_parent.get(str(parent.id), []), key=lambda c: (c.chunk_index, c.id)):
                    c_start, c_end = _page_range(child.extra_meta, start)
                    child_payload.append(
                        {
                            "chunk_id": str(child.id),
                            "pages": _format_pages(c_start, c_end),
                            "chunk_index": child.chunk_index,
                            "preview": (child.chunk_text or "")[:240],
                        }
                    )
                sections.append(
                    {
                        "chunk_id": str(parent.id),
                        "title": title,
                        "pages": _format_pages(start, end),
                        "chunk_index": parent.chunk_index,
                        "children": child_payload,
                    }
                )

            return {
                "status": "ready" if item else "missing",
                "doc_id": doc_id,
                "name": item.title if item else "",
                "page_count": self._page_count(chunks),
                "sections": sections,
            }
        finally:
            db.close()

    def get_page_content(self, doc_id: str, pages: str) -> dict[str, Any]:
        requested_pages = _parse_pages(pages)
        db = self._session_factory()
        try:
            item = db.query(KnowledgeItem).filter(KnowledgeItem.id == doc_id).first()
            if not item:
                return {
                    "status": "missing",
                    "doc_id": doc_id,
                    "pages": pages,
                    "pages_content": [],
                }
            chunks = self._chunks_for_item(db, doc_id)
            page_payloads: list[dict[str, Any]] = []
            for page in requested_pages:
                page_chunks = []
                for fallback, chunk in enumerate(chunks, start=1):
                    if chunk.chunk_type != "child":
                        continue
                    start, end = _page_range(chunk.extra_meta, fallback)
                    if start <= page <= end:
                        page_chunks.append(chunk)
                page_payloads.append(
                    {
                        "page": page,
                        "text": "\n\n".join(chunk.chunk_text or "" for chunk in page_chunks),
                        "chunk_ids": [str(chunk.id) for chunk in page_chunks],
                    }
                )
            return {
                "status": "success",
                "doc_id": doc_id,
                "name": item.title or "",
                "pages": pages,
                "pages_content": page_payloads,
            }
        finally:
            db.close()

    def search_pages(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if term.strip()]
        db = self._session_factory()
        try:
            rows = (
                db.query(KnowledgeChunk, KnowledgeItem)
                .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.item_id)
                .filter(KnowledgeChunk.chunk_type == "child")
                .all()
            )
            scored: dict[tuple[str, int], dict[str, Any]] = {}
            for fallback, (chunk, item) in enumerate(rows, start=1):
                text = (chunk.chunk_text or "").lower()
                score = sum(text.count(term) for term in terms) if terms else 0
                if score <= 0:
                    continue
                start, end = _page_range(chunk.extra_meta, fallback)
                for page in range(start, end + 1):
                    key = (str(item.id), page)
                    payload = scored.setdefault(
                        key,
                        {
                            "chunk_id": str(chunk.id),
                            "item_id": str(item.id),
                            "doc_id": str(item.id),
                            "doc_name": item.title or "",
                            "page": page,
                            "score": 0.0,
                            "source": "page_index",
                            "chunk_ids": [],
                        },
                    )
                    payload["score"] += float(score)
                    payload["chunk_ids"].append(str(chunk.id))
            results = list(scored.values())
            results.sort(key=lambda item: (float(item["score"]), item["doc_name"]), reverse=True)
            return results[:top_k]
        finally:
            db.close()

    @staticmethod
    def _infer_heading(text: str | None) -> str:
        if not text:
            return ""
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:120]
        return ""

    @staticmethod
    def _page_count(chunks: list[KnowledgeChunk]) -> int:
        max_page = 0
        for fallback, chunk in enumerate(chunks, start=1):
            _start, end = _page_range(chunk.extra_meta, fallback)
            max_page = max(max_page, end)
        return max_page

    @staticmethod
    def _chunks_for_item(db: Any, item_id: str) -> list[KnowledgeChunk]:
        return (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.item_id == item_id)
            .order_by(KnowledgeChunk.chunk_type.desc(), KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.id.asc())
            .all()
        )
