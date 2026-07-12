from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import StructuredTool


ToolBuilder = Callable[["ToolContext"], StructuredTool]


@dataclass(slots=True)
class ToolContext:
    rag_runner: Any | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    stats_holder: dict[str, Any] = field(default_factory=dict)
    clarify_holder: dict[str, Any] | None = None


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


def build_enabled_tools(
    ctx: ToolContext, overrides: dict[str, bool] | None = None
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []
    for key, spec in BUILTIN_REGISTRY.items():
        enabled = overrides.get(key, spec.default_enabled) if overrides else spec.default_enabled
        if enabled:
            tools.append(spec.builder(ctx))
    return tools
