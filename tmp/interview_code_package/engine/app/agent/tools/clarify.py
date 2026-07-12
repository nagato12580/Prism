from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


KEY = "clarify_user"


class ClarifyInput(BaseModel):
    question: str = Field(..., description="Clarifying question to ask the user.")
    options: list[dict[str, str]] = Field(
        default_factory=list, description="Suggested answer options."
    )


def build(ctx: ToolContext) -> StructuredTool:
    def run(question: str, options: list[dict[str, str]]) -> str:
        trimmed_options = options[:3]
        payload = {
            "status": "clarify",
            "question": question,
            "options": trimmed_options,
        }
        if ctx.clarify_holder is not None:
            ctx.clarify_holder.clear()
            ctx.clarify_holder.update(
                {"question": question, "options": trimmed_options}
            )
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Ask the user for a specific clarification before answering.",
        args_schema=ClarifyInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Ask the user for a specific clarification before answering.",
        builder=build,
        default_enabled=True,
    )
)
