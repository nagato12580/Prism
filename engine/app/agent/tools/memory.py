from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from backend.app.models.memory import MemoryEntry
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.config import settings


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class MemorySearchInput(BaseModel):
    query: str = Field(..., description="Query for user long-term memory, preferences, goals, constraints, or profile.")
    limit: int = Field(10, ge=1, le=30, description="Maximum number of memories to return.")


def _memory_to_source(memory: MemoryEntry, score: float) -> dict[str, Any]:
    return {
        "memory_id": memory.id,
        "ref_type": "memory",
        "ref_id": memory.id,
        "title": memory.title,
        "content": memory.content,
        "memory_type": memory.memory_type,
        "category": memory.category,
        "tags": memory.tags or [],
        "importance": memory.importance,
        "score": score,
    }


def _build_memory_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 10) -> str:
        db = _Session()
        try:
            q_norm = (query or "").strip()
            stmt = db.query(MemoryEntry).filter(MemoryEntry.user_id == "default-user")
            if q_norm:
                like = f"%{q_norm}%"
                stmt = stmt.filter(
                    or_(
                        MemoryEntry.title.like(like),
                        MemoryEntry.content.like(like),
                        MemoryEntry.category.like(like),
                        MemoryEntry.memory_type.like(like),
                    )
                )
            memories = stmt.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit).all()
            sources = [_memory_to_source(memory, 1.0) for memory in memories]
            ctx.citations.extend(sources)
            ctx.stats_holder["memory_search"] = {"hit_count": len(sources)}
            return json.dumps(
                {
                    "status": "success" if sources else "insufficient",
                    "summary": f"找到 {len(sources)} 条长期记忆。" if sources else "未找到匹配的长期记忆。",
                    "sources": sources,
                    "memories": sources,
                },
                ensure_ascii=False,
            )
        finally:
            db.close()

    return StructuredTool.from_function(
        func=run,
        name="memory_search",
        description=(
            "Search confirmed long-term memory and user profile context, including preferences, goals, "
            "constraints, current projects, and stable personal context. Use when understanding the user's "
            "own preferences or remembered context is necessary."
        ),
        args_schema=MemorySearchInput,
    )


register_tool(
    ToolSpec(
        key="memory_search",
        name="memory_search",
        description="Search long-term memory and user profile context.",
        builder=_build_memory_search,
        default_enabled=True,
    )
)
