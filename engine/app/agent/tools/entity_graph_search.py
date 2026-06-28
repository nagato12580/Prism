from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "entity_graph_search"


class EntityGraphSearchInput(BaseModel):
    query: str
    limit: int = Field(8, ge=1, le=20)


class EntityGraphSearchService:
    def search_entity_context(self, query: str, limit: int = 8) -> dict[str, Any]:
        return {
            "status": "insufficient",
            "summary": "Entity graph search is not configured yet.",
            "entities": [],
            "sources": [],
            "paths": [],
        }


def build(ctx: ToolContext, graph_search: Any | None = None) -> StructuredTool:
    service = graph_search if graph_search is not None else EntityGraphSearchService()

    def run(query: str, limit: int = 8) -> str:
        payload = service.search_entity_context(query, limit=limit)
        sources = list(payload.get("sources", []))
        ctx.citations.extend(sources)
        ctx.stats_holder[KEY] = {
            "entity_count": len(payload.get("entities", [])),
            "source_count": len(sources),
            "path_count": len(payload.get("paths", [])),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Search the entity graph for people, organizations, papers, aliases, "
            "and source-backed paths. Use before declaring a named entity absent."
        ),
        args_schema=EntityGraphSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description=(
            "Search the entity graph for people, organizations, papers, aliases, "
            "and source-backed paths. Use before declaring a named entity absent."
        ),
        builder=build,
        default_enabled=True,
    )
)
