from contextlib import contextmanager
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.services.graph_client import GraphClient
from engine.app.config import settings
from engine.app.retrieval.contracts import SearchScope
from engine.app.retrieval.evidence import ChannelProblem, ChannelScore, Evidence, RetrievalResponse
from engine.app.retrieval.unified import unified_search


router = APIRouter(prefix="/internal/retrieval", tags=["internal-retrieval"])
logger = logging.getLogger("uvicorn.error")
MAX_FILTER_ITEMS = 100
MAX_FILE_UID_LENGTH = 128
MAX_SOURCE_TYPE_LENGTH = 64
FileUid = Annotated[str, StringConstraints(min_length=1, max_length=MAX_FILE_UID_LENGTH)]
SourceType = Annotated[str, StringConstraints(min_length=1, max_length=MAX_SOURCE_TYPE_LENGTH)]


class AuthorizedKnowledgeScope(SearchScope):
    """Scope materialized by the Backend after KnowledgeAccessPolicy succeeds."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_uids: tuple[FileUid, ...] = Field(default=(), max_length=MAX_FILTER_ITEMS)
    source_types: tuple[SourceType, ...] = Field(default=(), max_length=MAX_FILTER_ITEMS)


class RetrievalOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(default=10, ge=1, le=100)
    graph_hops: int | None = Field(default=None, ge=1, le=3)


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["fast", "deep"] = "fast"
    filters: PublicFilters = Field(default_factory=PublicFilters)
    config: RetrievalOverrides = Field(default_factory=RetrievalOverrides)


def _normalize(row: dict, scope: AuthorizedKnowledgeScope, warnings: list[ChannelProblem]) -> Evidence:
    metadata = dict(row.get("metadata") or {})
    graph_rag = metadata.get("graph_rag") or row.get("graph_rag") or {}
    graph_explain = graph_rag.get("explain") if isinstance(graph_rag, dict) else {}
    channels = dict(row.get("channels") or {})
    file_uid = row.get("file_uid") or metadata.get("file_uid")
    chunk_uid = row.get("chunk_uid") or row.get("chunk_id") or metadata.get("chunk_uid")
    if not isinstance(file_uid, str) or not file_uid.strip():
        raise ValueError("retrieval hit is missing file_uid provenance")
    if not isinstance(chunk_uid, str) or not chunk_uid.strip():
        raise ValueError("retrieval hit is missing chunk_uid provenance")
    degradation_flags = tuple(dict.fromkeys(
        [warning.code for warning in warnings]
        + [w.get("code", "") for w in row.get("warnings", []) if w.get("code")]
    ))
    return Evidence(
        tenant_id=scope.tenant_id,
        kb_uid=scope.kb_uid,
        file_uid=file_uid,
        item_id=row.get("item_id") or metadata.get("item_id"),
        chunk_uid=chunk_uid,
        parent_chunk_uid=metadata.get("parent_chunk_uid"),
        display_title=str(row.get("display_title") or row.get("title") or metadata.get("display_title") or metadata.get("title") or ""),
        original_filename=row.get("original_filename") or metadata.get("original_filename"),
        excerpt=str(row.get("excerpt") or row.get("snippet") or row.get("text") or metadata.get("excerpt") or metadata.get("snippet") or metadata.get("text") or ""),
        page_start=row.get("page_start", metadata.get("page_start", metadata.get("page_number"))),
        page_end=row.get("page_end", metadata.get("page_end", metadata.get("page_number"))),
        char_start=row.get("char_start", metadata.get("char_start")),
        char_end=row.get("char_end", metadata.get("char_end")),
        channel_scores={name: ChannelScore(**score) for name, score in channels.items()},
        rrf_score=float(row.get("rrf_score", row.get("score", 0.0))),
        rerank_score=row.get("rerank_score"),
        rerank_model=row.get("rerank_model"),
        retrieval_channels=tuple(channels),
        graph_path=tuple(graph_rag.get("path") or ()) if isinstance(graph_rag, dict) else (),
        graph_explanation=(graph_explain or {}).get("explanation") if isinstance(graph_explain, dict) else None,
        evidence_type=metadata.get("evidence_type", "chunk"),
        index_generation=scope.index_generation,
        degradation_flags=degradation_flags,
    )


def verify_authorized_scope() -> AuthorizedKnowledgeScope:
    """Fail closed until a trusted transport verifier is wired by security infrastructure."""
    raise HTTPException(status_code=503, detail="authorized scope verifier is not configured")


@contextmanager
def open_retrieval_resources():
    engine = None
    db = None
    graph_client = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    try:
        engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        db = sessionmaker(bind=engine)()
        graph_client = GraphClient()
        yield db, graph_client
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        for label, resource, method_name in (
            ("graph", graph_client, "close"),
            ("db", db, "close"),
            ("engine", engine, "dispose"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method_name)()
            except BaseException as exc:
                cleanup_errors.append(exc)
                logger.warning("[retrieval] %s cleanup failed err=%s", label, exc)
        if cleanup_errors and primary_error is None:
            raise cleanup_errors[0]


def execute_retrieval(
    request: RetrievalRequest, scope: AuthorizedKnowledgeScope
) -> RetrievalResponse:
    scope = scope.model_copy(update={
        "file_uids": request.filters.file_uids,
        "source_types": request.filters.source_types,
    })
    diagnostics: dict = {}
    try:
        with open_retrieval_resources() as (db, graph_client):
            results = unified_search(
                request.query,
                request.config.top_k,
                mode=request.mode,
                db=db,
                graph_client=graph_client,
                scope=scope,
                graph_hops=request.config.graph_hops,
                diagnostics=diagnostics,
            )
    except ValueError as exc:
        return RetrievalResponse(status="invalid_request", warnings=[
            ChannelProblem(code="INVALID_RETRIEVAL_REQUEST", message=str(exc), retryable=False)
        ])
    except Exception as exc:
        return RetrievalResponse(status="unavailable", warnings=[
            ChannelProblem(code="RETRIEVAL_UNAVAILABLE", message=str(exc), retryable=True)
        ])
    warnings = [ChannelProblem.model_validate(item) for item in diagnostics.get("warnings", [])]
    evidence = []
    malformed_count = 0
    for row in results:
        try:
            evidence.append(_normalize(row, scope, warnings))
        except (ValidationError, ValueError, TypeError):
            malformed_count += 1
    if malformed_count:
        warnings.append(ChannelProblem(
            code="MALFORMED_RETRIEVAL_HIT",
            message=f"Skipped {malformed_count} retrieval hit(s) without valid provenance",
            retryable=False,
        ))
    status = diagnostics.get("status") or ("ok" if evidence else "no_hits")
    if malformed_count and status not in {"unavailable", "invalid_request"}:
        status = "degraded"
    return RetrievalResponse(status=status, evidence=evidence, warnings=warnings)


@router.post("/query", response_model=RetrievalResponse)
def query_retrieval(
    request: RetrievalRequest,
    scope: AuthorizedKnowledgeScope = Depends(verify_authorized_scope),
):
    return execute_retrieval(request, scope)
