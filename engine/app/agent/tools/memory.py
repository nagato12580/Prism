from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from backend.app.models.memory import MemoryEntry, MemorySource, MemoryStatement, MemoryStatus
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.config import settings


_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


class MemorySearchInput(BaseModel):
    query: str = Field(..., description="Query for user long-term memory, preferences, goals, constraints, or profile.")
    limit: int = Field(10, ge=1, le=30, description="Maximum number of memories to return.")


def _entry_to_source(memory: MemoryEntry, score: float) -> dict[str, Any]:
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
        "source": "asset",
        "score": score,
    }


def _statement_to_source(statement: MemoryStatement, score: float) -> dict[str, Any]:
    return {
        "memory_id": statement.id,
        "ref_type": "memory",
        "ref_id": statement.id,
        "title": statement.content[:80] if statement.content else "",
        "content": statement.content,
        "memory_type": statement.statement_type,
        "category": statement.temporal_type,
        "tags": [],
        "importance": statement.importance,
        "source": "conversation",
        "score": score,
    }


def _build_memory_search(ctx: ToolContext) -> StructuredTool:
    def run(query: str, limit: int = 10) -> str:
        db = _Session()
        try:
            q_norm = (query or "").strip()
            sources: list[dict[str, Any]] = []

            # 1. MemoryEntry（资产沉淀记忆）
            entry_stmt = db.query(MemoryEntry).filter(MemoryEntry.user_id == "default-user")
            if q_norm:
                like = f"%{q_norm}%"
                entry_stmt = entry_stmt.filter(
                    or_(
                        MemoryEntry.title.like(like),
                        MemoryEntry.content.like(like),
                        MemoryEntry.category.like(like),
                        MemoryEntry.memory_type.like(like),
                    )
                )
            entries = entry_stmt.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit).all()
            sources.extend(_entry_to_source(memory, 1.0) for memory in entries)

            # 2. MemoryStatement（对话提取确认后的记忆陈述）
            statement_stmt = (
                db.query(MemoryStatement)
                .filter(
                    MemoryStatement.user_id == "default-user",
                    MemoryStatement.status == MemoryStatus.CONFIRMED,
                )
            )
            if q_norm:
                like = f"%{q_norm}%"
                statement_stmt = statement_stmt.filter(
                    or_(
                        MemoryStatement.content.like(like),
                        MemoryStatement.statement_type.like(like),
                        MemoryStatement.temporal_type.like(like),
                    )
                )
            statements = statement_stmt.order_by(MemoryStatement.importance.desc(), MemoryStatement.updated_at.desc()).limit(limit).all()
            sources.extend(_statement_to_source(statement, 1.0) for statement in statements)

            # 合并去重（按 ref_id）并按重要度排序，截断 limit
            seen: set[str] = set()
            merged: list[dict[str, Any]] = []
            for src in sources:
                rid = src["ref_id"]
                if rid in seen:
                    continue
                seen.add(rid)
                merged.append(src)
            merged.sort(key=lambda s: s.get("importance", 0.0), reverse=True)
            merged = merged[:limit]

            ctx.citations.extend(merged)
            ctx.stats_holder["memory_search"] = {"hit_count": len(merged)}
            return json.dumps(
                {
                    "status": "success" if merged else "insufficient",
                    "summary": f"找到 {len(merged)} 条长期记忆。" if merged else "未找到匹配的长期记忆。",
                    "sources": merged,
                    "memories": merged,
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
            "constraints, current projects, and stable personal context. Covers both asset-settled memories "
            "and conversation-extracted confirmed statements. Use when understanding the user's "
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
