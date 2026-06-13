from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "web_search"


class WebSearchInput(BaseModel):
    query: str = Field(..., description="Web query to search for.")


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        return "Web search is not configured for this Prism phase."

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Search the web when external lookup is configured.",
        args_schema=WebSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Search the web when external lookup is configured.",
        builder=build,
        default_enabled=False,
    )
)
