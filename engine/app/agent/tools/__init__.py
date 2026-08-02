from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool

from engine.app.agent.tools.base import (
    BUILTIN_REGISTRY,
    ToolContext,
    ToolSpec,
    build_enabled_tools,
    registered_tool_names,
    register_tool,
)

import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
# import engine.app.agent.tools.entity_graph_search  # noqa: F401   # P3: demoted, logic reused internally
import engine.app.agent.tools.assets  # noqa: F401
# import engine.app.agent.tools.governed_knowledge   # noqa: F401   # P3: demoted
import engine.app.agent.tools.deep_knowledge_search  # noqa: F401
# import engine.app.agent.tools.knowledge_governance  # noqa: F401   # P3 unified retrieval + P5 insights supersede CKP-topic / PKU-evidence / material / raw-document tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.knowledge_base  # noqa: F401  # P4 authorized six-tool set (registered, default-enabled in Task 4)
import engine.app.agent.tools.page_index  # noqa: F401
import engine.app.agent.tools.memory  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401

# ---------------------------------------------------------------------------
# Tool group definitions for intent-based dynamic tool injection
# ---------------------------------------------------------------------------

TOOL_GROUPS: dict[str, dict] = {
    "record": {
        "label": "记录工具",
        "description": "捕获想法、收藏内容、管理个人知识资产",
        "tools": [
            "capture_thought",
            "asset_search",
            "asset_overview",
            "asset_related",
        ],
    },
    "memory": {
        "label": "记忆工具",
        "description": "查询用户偏好、目标、长期记忆和个人背景",
        "tools": ["memory_search"],
    },
    "knowledge": {
        "label": "知识库工具",
        "description": "检索知识库、查询文档、读取上传资料",
        "tools": [
            "list_kbs",
            "query_kb",
            "search_file",
            "find_kb_document",
            "open_kb_document",
            "get_mindmap",
            "knowledge_search",
            "deep_knowledge_search",
        ],
    },
}

# Tools always available regardless of intent classification.
COMMON_TOOLS: tuple[str, ...] = ("clarify_user", "datetime")


def build_tools_by_groups(
    ctx: "ToolContext",
    groups: list[str],
    *,
    deep_search_enabled: bool = False,
) -> "list[StructuredTool]":
    """Build tools only from selected *groups* plus common tools.

    Each group name must be a key in :data:`TOOL_GROUPS`.  Tools whose key is
    in ``COMMON_TOOLS`` are always included.  When *deep_search_enabled* is
    false the ``deep_knowledge_search`` tool is skipped even when the
    ``knowledge`` group is active.
    """
    selected_keys: set[str] = set(COMMON_TOOLS)
    for group in groups:
        group_def = TOOL_GROUPS.get(group)
        if group_def is not None:
            selected_keys.update(group_def["tools"])

    tools: "list[StructuredTool]" = []
    for key in selected_keys:
        spec = BUILTIN_REGISTRY.get(key)
        if spec is None:
            continue
        if key == "deep_knowledge_search" and not deep_search_enabled:
            continue
        tools.append(spec.builder(ctx))
    return tools


def tool_group_names(groups: list[str]) -> list[str]:
    """Return human-readable group labels for the given group keys."""
    return [
        TOOL_GROUPS[g]["label"]
        for g in groups
        if g in TOOL_GROUPS
    ]


__all__ = [
    "BUILTIN_REGISTRY",
    "COMMON_TOOLS",
    "TOOL_GROUPS",
    "ToolContext",
    "ToolSpec",
    "build_enabled_tools",
    "build_tools_by_groups",
    "registered_tool_names",
    "register_tool",
    "tool_group_names",
]
