import json

from engine.app.agent.runner import LangChainAgentRunner


class FakeToolCall:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Found evidence.",
                "sources": [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
            }
        )


class FakeModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "knowledge_search",
                        "args": {"query": "phase 2"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer")


def event_types(lines):
    return [json.loads(line)["type"] for line in lines]


def test_runner_emits_tool_sources_tokens_and_done():
    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])

    lines = list(runner.stream("How?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Final answer"


class FakeClarifyTool:
    name = "clarify_user"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "clarify",
                "question": "Which scope?",
                "options": [{"label": "Knowledge", "value": "scope:knowledge"}],
            }
        )


class FakeClarifyModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "clarify_user",
                    "args": {
                        "question": "Which scope?",
                        "options": [{"label": "Knowledge", "value": "scope:knowledge"}],
                    },
                }
            ]
        )


def test_runner_emits_clarify_and_stops():
    runner = LangChainAgentRunner(model=FakeClarifyModel(), tools=[FakeClarifyTool()])

    lines = list(runner.stream("Summarize it", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "clarify",
        "done",
    ]
