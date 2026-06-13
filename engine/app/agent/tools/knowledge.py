from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "knowledge_search"


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question or search query for Prism knowledge.")


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        if ctx.rag_runner is None:
            ctx.stats_holder[KEY] = {"hit_count": 0, "iterations": 0}
            return json.dumps(
                {
                    "status": "insufficient",
                    "summary": "Knowledge search is not configured.",
                    "missing": ["No RAG runner is available."],
                    "clarify": None,
                    "sources": [],
                    "evidence": [],
                },
                ensure_ascii=False,
            )

        result = ctx.rag_runner.run(query)
        sources = list(getattr(result, "sources", []))
        ctx.citations.extend(sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(sources),
            "iterations": getattr(result, "iterations", 0),
        }
        payload: dict[str, Any] = {
            "status": getattr(result, "status", "insufficient"),
            "summary": getattr(result, "summary", ""),
            "missing": getattr(result, "missing", []),
            "clarify": getattr(result, "clarify", None),
            "sources": sources,
            "evidence": getattr(result, "evidence", []),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Search Prism's indexed knowledge and return grounded evidence.",
        args_schema=KnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Search Prism's indexed knowledge and return grounded evidence.",
        builder=build,
        default_enabled=True,
    )
)
