from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "datetime"


class DateTimeInput(BaseModel):
    pass


def build(ctx: ToolContext) -> StructuredTool:
    def run() -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Return the current datetime in Asia/Shanghai as ISO 8601.",
        args_schema=DateTimeInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Return the current datetime in Asia/Shanghai as ISO 8601.",
        builder=build,
        default_enabled=True,
    )
)
