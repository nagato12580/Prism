"""Six authorized, read-only knowledge tools.

These are the model-visible knowledge toolset for Prism agents. Every tool:

- Is read-only (no writes, no filesystem mutation).
- Carries no ``actor_id`` / ``tenant_id`` in its input schema. The verified
  ``AuthorizedKnowledgeScope`` on :class:`ToolContext` is the only authority.
- Returns one :class:`ToolEnvelope` so the model always sees the same shape.
- Whitelists public DTO fields; internal ORM columns (``storage_uri``,
  ``file_path``, ``relative_path``, legacy aliases) are never exposed.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import asc
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeFile, KnowledgeTopic

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.contracts import ToolEnvelope, ToolProblem, ToolWarning


# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class KnowledgeToolError(Exception):
    """Typed, model-visible tool failure. Mapped to ``ToolEnvelope.from_error``."""

    code: str = "KNOWLEDGE_TOOL_ERROR"
    retryable: bool = False

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)
        self.message = message or self.code


class KnowledgeToolDenied(KnowledgeToolError):
    code = "KB_NOT_ALLOWED"
    retryable = False

    def __init__(self, kb_uid: str) -> None:
        super().__init__(f"knowledge base '{kb_uid}' is outside the authorized run scope")
        self.kb_uid = kb_uid


class KnowledgeToolNotFound(KnowledgeToolError):
    code = "KB_NOT_FOUND"
    retryable = False


class KnowledgeToolInvalidRequest(KnowledgeToolError):
    code = "INVALID_REQUEST"
    retryable = False


# --------------------------------------------------------------------------- #
# Public DTOs (frozen, extra-forbid; never expose internal paths)
# --------------------------------------------------------------------------- #


class _StrictDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KbSummary(_StrictDTO):
    kb_uid: str
    name: str
    description: str | None = None
    status: str


class ListKbsData(_StrictDTO):
    items: list[KbSummary] = Field(default_factory=list)


class EvidenceItem(_StrictDTO):
    """Public, de-tenantized evidence projected from canonical Evidence.

    ``tenant_id`` and internal/provider/storage fields are intentionally absent.
    """

    kb_uid: str
    file_uid: str
    chunk_uid: str
    item_id: str | None = None
    display_title: str | None = None
    excerpt: str
    score: float | None = None
    retrieval_channels: tuple[str, ...] = ()
    evidence_type: str | None = None
    index_generation: str | None = None
    evidence_id: str | None = None


class QueryKbData(_StrictDTO):
    evidence: list[EvidenceItem] = Field(default_factory=list)
    retrieval_health: dict[str, Any] = Field(default_factory=dict)


class FileSummary(_StrictDTO):
    file_uid: str
    kb_uid: str
    title: str | None = None
    original_filename: str | None = None
    media_type: str | None = None
    mime_type: str | None = None
    parse_status: str
    page_count: int | None = None


class SearchFileData(_StrictDTO):
    items: list[FileSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class MatchSpan(_StrictDTO):
    line: int
    start: int
    end: int


class FindMatch(_StrictDTO):
    line: int
    snippet: str
    match: MatchSpan | None = None


class FindDocumentData(_StrictDTO):
    file_uid: str
    kb_uid: str
    matched: bool
    matches: list[FindMatch] = Field(default_factory=list)
    truncated: bool = False


class OpenDocumentData(_StrictDTO):
    file_uid: str
    kb_uid: str
    offset: int
    window_size: int
    content: str
    has_more_before: bool
    has_more_after: bool


class MindmapData(_StrictDTO):
    kb_uid: str
    mindmap: dict[str, Any] | None = None
    version: int | None = None
    status: str | None = None


# --------------------------------------------------------------------------- #
# Input schemas
# --------------------------------------------------------------------------- #


class QueryKbInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str = Field(min_length=1, max_length=128)
    query_text: str = Field(min_length=1, max_length=4000)
    mode: Literal["standard", "deep"] = "standard"
    file_filter: tuple[str, ...] = Field(default=(), max_length=100)


class SearchFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str | None = Field(default=None, min_length=1, max_length=128)
    query: str | None = Field(default=None, min_length=1, max_length=4000)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(default=50, ge=1, le=300)
    media_types: tuple[str, ...] = Field(default=(), max_length=64)


class FindDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str = Field(min_length=1, max_length=128)
    file_uid: str = Field(min_length=1, max_length=128)
    patterns: list[str] = Field(min_length=1, max_length=20)
    use_regex: bool = False
    case_sensitive: bool = False
    max_windows: int = Field(default=5, ge=1, le=20)
    window_size: int = Field(default=80, ge=1, le=200)


class OpenDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str = Field(min_length=1, max_length=128)
    file_uid: str = Field(min_length=1, max_length=128)
    line: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    window_size: int = Field(default=500, ge=1, le=2000)

    @model_validator(mode="after")
    def _exactly_one_position(self):
        if self.line is not None and self.offset is not None:
            raise ValueError("specify either 'line' or 'offset', not both")
        return self


class ListKbsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetMindmapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str = Field(min_length=1, max_length=128)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


_CURSOR_VERSION = 1
_MAX_PATTERN_LEN = 256
_MAX_PATTERN_COUNT = 32


def _trace(ctx: ToolContext) -> str:
    return ctx.trace_id or "unknown"


def _require_scope(ctx: ToolContext):
    scope = ctx.knowledge_scope
    if scope is None:
        raise KnowledgeToolError("authorized knowledge scope is not configured")
    return scope


def _require_allowed_kb(ctx: ToolContext, kb_uid: str):
    scope = _require_scope(ctx)
    if kb_uid not in scope.allowed_kb_uids:
        raise KnowledgeToolDenied(kb_uid)
    return scope


def _require_db(ctx: ToolContext) -> Session:
    if ctx.db is None:
        raise KnowledgeToolError("database session is not configured")
    return ctx.db


def _require_retrieval(ctx: ToolContext):
    if ctx.retrieval_service is None:
        raise KnowledgeToolError("retrieval service is not configured")
    return ctx.retrieval_service


def _encode_cursor(after: str) -> str:
    payload = json.dumps({"v": _CURSOR_VERSION, "after": after}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_")
        data = json.loads(raw)
        after = data["after"]
        if not isinstance(after, str) or not after:
            raise ValueError
    except (ValueError, binascii.Error, KeyError) as exc:
        raise KnowledgeToolInvalidRequest("invalid search cursor") from exc
    return after


def _decode_cursor(cursor: str) -> str:
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        data = json.loads(raw)
        after = data["after"]
        if not isinstance(after, str) or not after:
            raise ValueError
    except (ValueError, binascii.Error, KeyError) as exc:
        raise KnowledgeToolInvalidRequest("invalid search cursor") from exc
    return after


def _topic_query(db: Session, tenant_id: str, kb_uids: list[str]):
    return (
        db.query(KnowledgeTopic)
        .filter(
            KnowledgeTopic.tenant_id == tenant_id,
            KnowledgeTopic.kb_uid.in_(kb_uids),
            KnowledgeTopic.deleted_at.is_(None),
        )
    )


def _file_summary(file: KnowledgeFile) -> FileSummary:
    return FileSummary(
        file_uid=file.file_uid,
        kb_uid=file.kb_uid,
        title=file.title,
        original_filename=file.original_filename,
        media_type=file.media_type,
        mime_type=file.mime_type,
        parse_status=file.parse_status,
        page_count=file.page_count,
    )


def _evidence_item_from_raw(raw: dict[str, Any]) -> EvidenceItem:
    """Project a canonical Evidence dict into the public, de-tenantized DTO."""
    excerpt = str(
        raw.get("excerpt")
        or raw.get("snippet")
        or raw.get("text")
        or ""
    )
    channels = raw.get("retrieval_channels") or raw.get("channels")
    if isinstance(channels, (list, tuple)):
        channels = tuple(str(c) for c in channels)
    else:
        channels = ()
    return EvidenceItem(
        kb_uid=str(raw.get("kb_uid") or ""),
        file_uid=str(raw.get("file_uid") or ""),
        chunk_uid=str(raw.get("chunk_uid") or raw.get("chunk_id") or ""),
        item_id=raw.get("item_id") if raw.get("item_id") else None,
        display_title=raw.get("display_title") if raw.get("display_title") else None,
        excerpt=excerpt,
        score=raw.get("score") if raw.get("score") is not None else None,
        retrieval_channels=channels,
        evidence_type=raw.get("evidence_type") if raw.get("evidence_type") else None,
        index_generation=raw.get("index_generation") if raw.get("index_generation") else None,
        evidence_id=raw.get("evidence_id") if raw.get("evidence_id") else None,
    )


def _compile_patterns(
    patterns: list[str], use_regex: bool, case_sensitive: bool
) -> re.Pattern[str]:
    if len(patterns) > _MAX_PATTERN_COUNT:
        raise KnowledgeToolInvalidRequest(
            f"too many patterns (max {_MAX_PATTERN_COUNT})"
        )
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled_terms: list[str] = []
    for pattern in patterns:
        if not pattern:
            raise KnowledgeToolInvalidRequest("pattern must not be empty")
        if len(pattern) > _MAX_PATTERN_LEN:
            raise KnowledgeToolInvalidRequest(
                f"pattern exceeds {_MAX_PATTERN_LEN} characters"
            )
        if use_regex:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise KnowledgeToolInvalidRequest(f"invalid regex pattern: {exc.msg}") from exc
            compiled_terms.append(pattern)
        else:
            compiled_terms.append(re.escape(pattern))
    body = "|".join(compiled_terms)
    try:
        return re.compile(body, flags)
    except re.error as exc:  # pragma: no cover - defensive, patterns are escaped/validated
        raise KnowledgeToolInvalidRequest(f"invalid search pattern: {exc.msg}") from exc


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _build_list_kbs(ctx: ToolContext) -> StructuredTool:
    def run() -> dict[str, Any]:
        try:
            scope = _require_scope(ctx)
            db = _require_db(ctx)
            rows = (
                _topic_query(db, scope.tenant_id, list(scope.allowed_kb_uids))
                .order_by(asc(KnowledgeTopic.kb_uid))
                .all()
            )
            items = [
                KbSummary(
                    kb_uid=row.kb_uid,
                    name=row.name,
                    description=row.description,
                    status=row.status,
                )
                for row in rows
            ]
            return ToolEnvelope.ok(ListKbsData(items=items), _trace(ctx)).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="list_kbs",
        description=(
            "List the knowledge bases available in the authorized run scope. "
            "Returns only kb_uid, name, description, and status."
        ),
        args_schema=ListKbsInput,
    )


def _build_query_kb(ctx: ToolContext) -> StructuredTool:
    def run(
        kb_uid: str,
        query_text: str,
        mode: Literal["standard", "deep"] = "standard",
        file_filter: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        try:
            scope = _require_allowed_kb(ctx, kb_uid)
            retrieval = _require_retrieval(ctx)
            response = retrieval.query(
                tenant_id=scope.tenant_id,
                kb_uid=kb_uid,
                query=query_text,
                mode="deep" if mode == "deep" else "fast",
                file_uids=tuple(file_filter),
            )
            status = str(response.get("status") or "ok")
            raw_evidence = list(response.get("evidence") or [])
            warnings = [
                ToolWarning(code=str(w.get("code", "WARNING")), message=str(w.get("message", "")))
                for w in (response.get("warnings") or [])
                if isinstance(w, dict)
            ]
            evidence = [_evidence_item_from_raw(item) for item in raw_evidence if isinstance(item, dict)]
            data = QueryKbData(
                evidence=evidence,
                retrieval_health=dict(response.get("retrieval_health") or {}),
            )
            if status == "unavailable":
                return ToolEnvelope.from_error(
                    ToolProblem(code="RETRIEVAL_UNAVAILABLE", message="retrieval is unavailable", retryable=True),
                    _trace(ctx),
                ).model_dump()
            if status == "no_hits":
                return ToolEnvelope.no_hits(data, _trace(ctx)).model_dump()
            if warnings or status == "degraded":
                return ToolEnvelope.degraded(data, warnings, _trace(ctx)).model_dump()
            return ToolEnvelope.ok(data, _trace(ctx)).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="query_kb",
        description=(
            "Query a knowledge base in the authorized run scope for grounded evidence. "
            "Use 'standard' for fast retrieval and 'deep' for multi-round graph-aware retrieval. "
            "Cite the returned evidence_id values in the answer."
        ),
        args_schema=QueryKbInput,
    )


def _build_search_file(ctx: ToolContext) -> StructuredTool:
    def run(
        kb_uid: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        media_types: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        try:
            scope = _require_scope(ctx)
            db = _require_db(ctx)
            allowed = list(scope.allowed_kb_uids)
            target_kbs = [kb_uid] if kb_uid else allowed
            # Enforce scope even for an explicit kb_uid.
            for kb in target_kbs:
                if kb not in allowed:
                    raise KnowledgeToolDenied(kb)
            after = _decode_cursor(cursor) if cursor else None
            q = (
                db.query(KnowledgeFile)
                .filter(
                    KnowledgeFile.tenant_id == scope.tenant_id,
                    KnowledgeFile.kb_uid.in_(target_kbs),
                    KnowledgeFile.deleted_at.is_(None),
                )
            )
            if media_types:
                q = q.filter(KnowledgeFile.media_type.in_(list(media_types)))
            if query:
                q = q.filter(KnowledgeFile.title.ilike(f"%{query}%"))
            if after:
                q = q.filter(KnowledgeFile.file_uid > after)
            q = q.order_by(asc(KnowledgeFile.file_uid)).limit(limit + 1)
            rows = q.all()
            page = rows[:limit]
            next_cursor = _encode_cursor(page[-1].file_uid) if len(rows) > limit else None
            items = [_file_summary(f) for f in page]
            return ToolEnvelope.ok(
                SearchFileData(items=items, next_cursor=next_cursor), _trace(ctx)
            ).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="search_file",
        description=(
            "Search file metadata (titles) across the authorized knowledge bases. "
            "Non-semantic, cursor-paginated; use find_kb_document for in-file content matches."
        ),
        args_schema=SearchFileInput,
    )


def _build_find_kb_document(ctx: ToolContext) -> StructuredTool:
    def run(
        kb_uid: str,
        file_uid: str,
        patterns: list[str],
        use_regex: bool = False,
        case_sensitive: bool = False,
        max_windows: int = 5,
        window_size: int = 80,
    ) -> dict[str, Any]:
        try:
            scope = _require_allowed_kb(ctx, kb_uid)
            db = _require_db(ctx)
            file = (
                db.query(KnowledgeFile)
                .filter(
                    KnowledgeFile.file_uid == file_uid,
                    KnowledgeFile.kb_uid == kb_uid,
                    KnowledgeFile.tenant_id == scope.tenant_id,
                    KnowledgeFile.deleted_at.is_(None),
                )
                .first()
            )
            if file is None:
                raise KnowledgeToolNotFound("document not found in the authorized scope")
            content = file.content_text or ""
            regex = _compile_patterns(patterns, use_regex, case_sensitive)
            matches: list[FindMatch] = []
            truncated = False
            for m in regex.finditer(content):
                if len(matches) >= max_windows:
                    truncated = True
                    break
                line = content.count("\n", 0, m.start()) + 1
                half = max(0, (window_size - (m.end() - m.start())) // 2)
                start = max(0, m.start() - half)
                end = min(len(content), start + window_size)
                start = max(0, end - window_size)
                snippet = content[start:end].replace("\n", " ")
                matches.append(
                    FindMatch(
                        line=line,
                        snippet=snippet,
                        match=MatchSpan(line=line, start=m.start() - start, end=m.end() - start),
                    )
                )
            data = FindDocumentData(
                file_uid=file.file_uid,
                kb_uid=file.kb_uid,
                matched=bool(matches),
                matches=matches,
                truncated=truncated,
            )
            return ToolEnvelope.ok(data, _trace(ctx)).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="find_kb_document",
        description=(
            "Find exact keyword or regex matches inside a document's parsed text. "
            "Non-semantic and bounded; returns line-anchored snippets, never storage paths."
        ),
        args_schema=FindDocumentInput,
    )


def _build_open_kb_document(ctx: ToolContext) -> StructuredTool:
    def run(
        kb_uid: str,
        file_uid: str,
        line: int | None = None,
        offset: int | None = None,
        window_size: int = 500,
    ) -> dict[str, Any]:
        try:
            scope = _require_allowed_kb(ctx, kb_uid)
            db = _require_db(ctx)
            file = (
                db.query(KnowledgeFile)
                .filter(
                    KnowledgeFile.file_uid == file_uid,
                    KnowledgeFile.kb_uid == kb_uid,
                    KnowledgeFile.tenant_id == scope.tenant_id,
                    KnowledgeFile.deleted_at.is_(None),
                )
                .first()
            )
            if file is None:
                raise KnowledgeToolNotFound("document not found in the authorized scope")
            content = file.content_text or ""
            length = len(content)
            if line is not None:
                line_index = line - 1
                pos = 0
                for _ in range(line_index):
                    nl = content.find("\n", pos)
                    if nl == -1:
                        pos = length
                        break
                    pos = nl + 1
                start = pos
            else:
                start = offset or 0
            start = max(0, min(start, length))
            end = min(length, start + window_size)
            window = content[start:end]
            data = OpenDocumentData(
                file_uid=file.file_uid,
                kb_uid=file.kb_uid,
                offset=start,
                window_size=window_size,
                content=window,
                has_more_before=start > 0,
                has_more_after=end < length,
            )
            return ToolEnvelope.ok(data, _trace(ctx)).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="open_kb_document",
        description=(
            "Open a bounded text window of a document's parsed content by offset or line. "
            "Use small windows and page forward; never returns storage or internal paths."
        ),
        args_schema=OpenDocumentInput,
    )


def _build_get_mindmap(ctx: ToolContext) -> StructuredTool:
    def run(kb_uid: str) -> dict[str, Any]:
        try:
            scope = _require_allowed_kb(ctx, kb_uid)
            db = _require_db(ctx)
            topic = (
                _topic_query(db, scope.tenant_id, [kb_uid])
                .first()
            )
            if topic is None:
                raise KnowledgeToolNotFound("knowledge base not found in the authorized scope")
            mindmap = topic.mindmap if isinstance(topic.mindmap, dict) else None
            version = topic.mindmap_version if isinstance(topic.mindmap_version, int) else None
            status = (
                str(mindmap.get("status"))
                if isinstance(mindmap, dict) and mindmap.get("status")
                else None
            )
            data = MindmapData(
                kb_uid=topic.kb_uid,
                mindmap=mindmap,
                version=version,
                status=status,
            )
            return ToolEnvelope.ok(data, _trace(ctx)).model_dump()
        except KnowledgeToolError as exc:
            return ToolEnvelope.from_error(
                ToolProblem(code=exc.code, message=exc.message, retryable=exc.retryable),
                _trace(ctx),
            ).model_dump()

    return StructuredTool.from_function(
        func=run,
        name="get_mindmap",
        description=(
            "Get the mind-map structure for an authorized knowledge base. "
            "Use it to understand the overall structure before querying."
        ),
        args_schema=GetMindmapInput,
    )


def build_tools(ctx: ToolContext) -> dict[str, StructuredTool]:
    """Build the six authorized knowledge tools bound to ``ctx``."""
    return {spec.name: spec.builder(ctx) for spec in KNOWLEDGE_TOOL_SPECS}


# --------------------------------------------------------------------------- #
# Registration (internal specs - not auto-visible via the legacy registry)
# --------------------------------------------------------------------------- #


LIST_KBS_SPEC = ToolSpec(
    key="list_kbs",
    name="list_kbs",
    description="List authorized knowledge bases (safe fields only).",
    builder=_build_list_kbs,
    # Not auto-visible via build_enabled_tools until Task 4 binds the Skill/run.
    default_enabled=False,
)
QUERY_KB_SPEC = ToolSpec(
    key="query_kb",
    name="query_kb",
    description="Query an authorized knowledge base for grounded evidence.",
    builder=_build_query_kb,
    default_enabled=False,
)
SEARCH_FILE_SPEC = ToolSpec(
    key="search_file",
    name="search_file",
    description="Search file metadata (titles) across authorized knowledge bases.",
    builder=_build_search_file,
    default_enabled=False,
)
FIND_KB_DOCUMENT_SPEC = ToolSpec(
    key="find_kb_document",
    name="find_kb_document",
    description="Find exact keyword/regex matches inside a document's text.",
    builder=_build_find_kb_document,
    default_enabled=False,
)
OPEN_KB_DOCUMENT_SPEC = ToolSpec(
    key="open_kb_document",
    name="open_kb_document",
    description="Open a bounded text window of a document.",
    builder=_build_open_kb_document,
    default_enabled=False,
)
GET_MINDMAP_SPEC = ToolSpec(
    key="get_mindmap",
    name="get_mindmap",
    description="Get the mind-map structure for an authorized knowledge base.",
    builder=_build_get_mindmap,
    default_enabled=False,
)


def _register_knowledge_tools() -> None:
    for spec in KNOWLEDGE_TOOL_SPECS:
        register_tool(spec)


KNOWLEDGE_TOOL_SPECS = (
    LIST_KBS_SPEC,
    QUERY_KB_SPEC,
    SEARCH_FILE_SPEC,
    FIND_KB_DOCUMENT_SPEC,
    OPEN_KB_DOCUMENT_SPEC,
    GET_MINDMAP_SPEC,
)

# Stable, ordered names of the six authorized knowledge tools. The Knowledge
# Skill and ``registered_tool_names()`` stay in sync with this constant.
KNOWLEDGE_TOOL_NAMES = tuple(spec.name for spec in KNOWLEDGE_TOOL_SPECS)


_register_knowledge_tools()
