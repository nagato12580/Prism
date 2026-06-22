from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "knowledge_search"


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question or search query for Prism knowledge.")


def _citation_key(source: Any) -> tuple[str, str]:
    if isinstance(source, dict) and source.get("chunk_id") is not None:
        return ("chunk_id", str(source["chunk_id"]))
    return (
        "json",
        json.dumps(source, ensure_ascii=False, sort_keys=True, default=str),
    )


def _append_unique_citations(citations: list[Any], sources: list[Any]) -> None:
    seen = {_citation_key(citation) for citation in citations}
    for source in sources:
        key = _citation_key(source)
        if key not in seen:
            citations.append(source)
            seen.add(key)


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
        # 如果 sources 为空（insufficient 场景），用 evidence 补充
        if not sources:
            sources = list(getattr(result, "evidence", []))
        _append_unique_citations(ctx.citations, sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(sources),
            "iterations": getattr(result, "iterations", 0),
        }
        summary = getattr(result, "summary", "")
        if not summary:
            count = len(sources)
            if count > 0:
                summary = f"检索到 {count} 条相关内容，证据不足，正在追问"
            else:
                summary = f"完成 {getattr(result, 'iterations', 0)} 轮检索，未找到匹配内容"
        payload: dict[str, Any] = {
            "status": getattr(result, "status", "insufficient"),
            "summary": summary,
            "missing": getattr(result, "missing", []),
            "clarify": getattr(result, "clarify", None),
            "sources": sources,
            "evidence": result.evidence,
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
        default_enabled=False,
    )
)
