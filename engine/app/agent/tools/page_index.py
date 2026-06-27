from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.config import settings
from engine.app.retrieval.page_index import PageIndexService


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class PageIndexDocumentInput(BaseModel):
    doc_id: str = Field(..., description="Knowledge item ID for the document.")


class PageIndexPageContentInput(BaseModel):
    doc_id: str = Field(..., description="Knowledge item ID for the document.")
    pages: str = Field(
        ...,
        description="Tight page range, such as '5-7', '3,8', or '12'.",
    )


def _service() -> PageIndexService:
    return PageIndexService(_Session)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _build_get_document(ctx: ToolContext) -> StructuredTool:
    def run(doc_id: str) -> str:
        payload = _service().get_document(doc_id)
        ctx.stats_holder["page_index_get_document"] = {
            "status": payload.get("status"),
            "page_count": payload.get("page_count", 0),
            "chunk_count": payload.get("chunk_count", 0),
        }
        return _json(payload)

    return StructuredTool.from_function(
        func=run,
        name="page_index_get_document",
        description="Get PageIndex-like metadata for a Prism document: status, name, page count, and chunk count.",
        args_schema=PageIndexDocumentInput,
    )


def _build_get_document_structure(ctx: ToolContext) -> StructuredTool:
    def run(doc_id: str) -> str:
        payload = _service().get_document_structure(doc_id)
        ctx.stats_holder["page_index_get_document_structure"] = {
            "status": payload.get("status"),
            "page_count": payload.get("page_count", 0),
            "section_count": len(payload.get("sections", [])),
        }
        return _json(payload)

    return StructuredTool.from_function(
        func=run,
        name="page_index_get_document_structure",
        description="Get a PageIndex-like document structure tree with sections, page ranges, and child chunk previews.",
        args_schema=PageIndexDocumentInput,
    )


def _build_get_page_content(ctx: ToolContext) -> StructuredTool:
    def run(doc_id: str, pages: str) -> str:
        payload = _service().get_page_content(doc_id, pages)
        page_payloads = payload.get("pages_content", [])
        for page in page_payloads:
            ctx.citations.append(
                {
                    "source": "page_index",
                    "doc_id": doc_id,
                    "page": page.get("page"),
                    "chunk_ids": page.get("chunk_ids", []),
                }
            )
        ctx.stats_holder["page_index_get_page_content"] = {
            "status": payload.get("status"),
            "page_count": len(page_payloads),
            "chunk_count": sum(len(page.get("chunk_ids", [])) for page in page_payloads),
        }
        return _json(payload)

    return StructuredTool.from_function(
        func=run,
        name="page_index_get_page_content",
        description=(
            "Retrieve exact page text from a Prism document. Use after reading document metadata "
            "and structure; request tight page ranges instead of the whole document."
        ),
        args_schema=PageIndexPageContentInput,
    )


register_tool(
    ToolSpec(
        key="page_index_get_document",
        name="page_index_get_document",
        description="Get PageIndex-like document metadata.",
        builder=_build_get_document,
        default_enabled=False,
    )
)

register_tool(
    ToolSpec(
        key="page_index_get_document_structure",
        name="page_index_get_document_structure",
        description="Get PageIndex-like document structure tree.",
        builder=_build_get_document_structure,
        default_enabled=False,
    )
)

register_tool(
    ToolSpec(
        key="page_index_get_page_content",
        name="page_index_get_page_content",
        description="Get PageIndex-like page content for tight page ranges.",
        builder=_build_get_page_content,
        default_enabled=False,
    )
)
