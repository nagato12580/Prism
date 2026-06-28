from __future__ import annotations

import json
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from engine.app.agent.deep_search.orchestrator import DeepSearchOrchestrator, config_for_depth
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.governed_knowledge import _append_unique_citations
from engine.app.config import settings


KEY = "deep_knowledge_search"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class DeepKnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question to answer from governed personal knowledge.")
    depth: Literal["quick", "standard", "deep"] = Field("standard", description="Maximum deep-search depth.")
    limit: int = Field(12, ge=3, le=30, description="Maximum evidence records to return.")


def _build_deep_knowledge_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, depth: str = "standard", limit: int = 12) -> str:
        config = config_for_depth(depth, limit)
        orchestrator = DeepSearchOrchestrator(_Session, config=config)
        result = orchestrator.run(query)
        payload = result.to_payload()
        _append_unique_citations(ctx.citations, payload["sources"])
        trace_steps = payload.get("trace_steps") or []
        ctx.stats_holder[KEY] = {
            "status": payload["status"],
            "iterations": payload["iterations"],
            "evidence_count": len(payload["evidence"]),
            "source_count": len(payload["sources"]),
            "judge_overall_score": payload["judge"]["overall_score"],
            "trace_step_count": len(trace_steps),
            "deep_trace_steps": trace_steps,
            "depth": config.depth,
        }
        payload["stats"] = ctx.stats_holder[KEY]
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Deep governed knowledge search. Use when deep search is enabled and the user asks a knowledge-base "
            "question that needs CKP/PKU scope discovery, source-backed evidence, multi-step follow-up search, "
            "or completeness checking."
        ),
        args_schema=DeepKnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Scope-first governed knowledge deep search with judge-directed evidence expansion.",
        builder=_build_deep_knowledge_search,
        default_enabled=False,
    )
)
