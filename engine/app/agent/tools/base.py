from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import StructuredTool


ToolBuilder = Callable[["ToolContext"], StructuredTool]


@dataclass(slots=True)
class ToolContext:
    # Legacy fields (kept for compatibility with existing callers/tests).
    rag_runner: Any | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    stats_holder: dict[str, Any] = field(default_factory=dict)
    clarify_holder: dict[str, Any] | None = None
    # Authorized knowledge-run scope (Tasks 3-6). Production construction is
    # authoritative in Tasks 4/6; until then tests/legacy callers may omit these.
    db: Any | None = None
    trace_id: str | None = None
    run_id: str | None = None
    knowledge_scope: Any | None = None
    retrieval_service: Any | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    key: str
    name: str
    description: str
    builder: ToolBuilder
    default_enabled: bool = True


BUILTIN_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    BUILTIN_REGISTRY[spec.key] = spec


def registered_tool_names() -> list[str]:
    """Names of all registered tools, in registration order."""
    return [spec.name for spec in BUILTIN_REGISTRY.values()]


def build_enabled_tools(
    ctx: ToolContext, overrides: dict[str, bool] | None = None
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []
    for key, spec in BUILTIN_REGISTRY.items():
        enabled = overrides.get(key, spec.default_enabled) if overrides else spec.default_enabled
        if enabled:
            tools.append(spec.builder(ctx))
    return tools
