from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.evidence import normalize_evidence_items
from engine.app.agent.tools.knowledge import _append_unique_citations


KEY = "deep_knowledge_search"


class DeepKnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question to answer from Prism's unified knowledge graph.")
    depth: Literal["quick", "standard", "deep"] = Field("standard", description="Requested deep-search depth.")
    limit: int = Field(12, ge=3, le=30, description="Maximum evidence records to return.")


def _judge_payload_from_result(status: str, sources: list[dict[str, Any]], missing: list[str]) -> dict[str, Any]:
    sufficient = status == "sufficient"
    source_count = len(sources)
    return {
        "status": "complete" if sufficient else "incomplete",
        "overall_score": 1.0 if sufficient else (0.5 if source_count else 0.0),
        "grounding_score": 1.0 if source_count else 0.0,
        "coverage_score": 1.0 if sufficient else (0.4 if source_count else 0.0),
        "missing": missing,
        "directives": [],
    }


def _trace_steps_from_result(depth: str, status: str, iterations: int, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "agent": "UnifiedRetrieval",
            "iteration": 1,
            "label": "Deep Unified Retrieval",
            "detail": f"mode=deep depth={depth} collected {len(sources)} grounded sources.",
        },
        {
            "agent": "JudgeAgent",
            "iteration": max(1, iterations),
            "label": f"Judge iteration {max(1, iterations)}",
            "detail": f"status={status} sources={len(sources)}",
        },
    ]


def _build_not_configured_payload() -> dict[str, Any]:
    judge = _judge_payload_from_result("insufficient", [], ["No RAG runner is available."])
    return {
        "status": "insufficient",
        "summary": "Deep knowledge search is not configured.",
        "retrieval_path": "unified_graphrag_deep_search",
        "iterations": 0,
        "judge": judge,
        "missing": judge["missing"],
        "clarify": None,
        "sources": [],
        "evidence": [],
        "trace_steps": _trace_steps_from_result("standard", "insufficient", 0, []),
    }


def _build_deep_knowledge_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, depth: str = "standard", limit: int = 12) -> str:
        if ctx.rag_runner is None:
            payload = _build_not_configured_payload()
            payload["evidence_items"] = []
            ctx.stats_holder[KEY] = {
                "status": payload["status"],
                "iterations": payload["iterations"],
                "evidence_count": 0,
                "source_count": 0,
                "judge_overall_score": payload["judge"]["overall_score"],
                "trace_step_count": len(payload["trace_steps"]),
                "deep_trace_steps": payload["trace_steps"],
                "depth": depth,
            }
            payload["stats"] = ctx.stats_holder[KEY]
            return json.dumps(payload, ensure_ascii=False)

        result = ctx.rag_runner.run(query)
        sources = list(getattr(result, "sources", []))
        if not sources:
            sources = list(getattr(result, "evidence", []))

        _append_unique_citations(ctx.citations, sources)

        missing = list(getattr(result, "missing", []))
        judge = _judge_payload_from_result(getattr(result, "status", "insufficient"), sources, missing)
        trace_steps = _trace_steps_from_result(depth, getattr(result, "status", "insufficient"), getattr(result, "iterations", 0), sources)
        payload: dict[str, Any] = {
            "status": getattr(result, "status", "insufficient"),
            "summary": getattr(result, "summary", "") or (
                f"Deep unified retrieval found {len(sources)} grounded sources."
                if sources
                else "Deep unified retrieval found no grounded evidence."
            ),
            "retrieval_path": "unified_graphrag_deep_search",
            "iterations": getattr(result, "iterations", 0),
            "judge": judge,
            "missing": missing,
            "clarify": getattr(result, "clarify", None),
            "sources": sources,
            "evidence": list(getattr(result, "evidence", [])),
            "trace_steps": trace_steps,
        }
        ctx.stats_holder[KEY] = {
            "status": payload["status"],
            "iterations": payload["iterations"],
            "evidence_count": len(payload["evidence"]),
            "source_count": len(payload["sources"]),
            "judge_overall_score": payload["judge"]["overall_score"],
            "trace_step_count": len(trace_steps),
            "deep_trace_steps": trace_steps,
            "depth": depth,
        }
        payload["stats"] = ctx.stats_holder[KEY]
        payload["evidence_items"] = normalize_evidence_items(KEY, payload)
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Deep unified knowledge search. Use when deep search is enabled and the user asks a knowledge-base "
            "question that needs multi-round retrieval, graph expansion, cross-source evidence, or completeness checking."
        ),
        args_schema=DeepKnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Deep unified GraphRAG retrieval with multi-round evidence gathering.",
        builder=_build_deep_knowledge_search,
        default_enabled=False,
    )
)
