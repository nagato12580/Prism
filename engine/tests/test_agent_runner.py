import json
import logging

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


def test_runner_logs_agent_progress(caplog):
    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        list(runner.stream("How does phase 2 work?", [{"role": "user", "content": "old"}]))

    messages = [record.getMessage() for record in caplog.records]
    assert any("[agent] start" in message for message in messages)
    assert any("history_messages=1" in message for message in messages)
    assert any("[agent] model_invoke iteration=1" in message for message in messages)
    assert any(
        "[agent] tool_call tool=knowledge_search" in message
        and 'query="phase 2"' in message
        for message in messages
    )
    assert any(
        "[agent] tool_result tool=knowledge_search status=success" in message
        and 'summary="Found evidence."' in message
        for message in messages
    )
    assert any(
        "[agent] output" in message and 'preview="Final answer"' in message
        for message in messages
    )
    assert any("[agent] done" in message for message in messages)


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


class FakeInsufficientClarifyTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "insufficient",
                "summary": "Knowledge base evidence is insufficient.",
                "clarify": {
                    "question": "Which scope should I use?",
                    "options": [
                        {
                            "label": "Current knowledge base",
                            "value": "scope:knowledge",
                        }
                    ],
                },
            }
        )


class FakeInsufficientClarifyModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "knowledge_search",
                    "args": {"query": "phase 2"},
                }
            ]
        )


def test_runner_emits_nested_clarify_from_insufficient_tool_payload_and_stops():
    runner = LangChainAgentRunner(
        model=FakeInsufficientClarifyModel(),
        tools=[FakeInsufficientClarifyTool()],
    )

    lines = list(runner.stream("What scope?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "clarify",
        "done",
    ]
    clarify_data = json.loads(lines[-2])["data"]
    assert clarify_data == {
        "question": "Which scope should I use?",
        "options": [{"label": "Current knowledge base", "value": "scope:knowledge"}],
    }
    assert not any(json.loads(line)["type"] == "token" for line in lines)


class FakeMalformedClarifyTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "insufficient",
                "summary": "Knowledge base evidence is insufficient.",
                "clarify": {"question": ["Which scope?"], "options": "knowledge"},
            }
        )


class FakeContinueAfterMalformedClarifyModel:
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


def test_runner_ignores_malformed_nested_clarify_and_continues():
    runner = LangChainAgentRunner(
        model=FakeContinueAfterMalformedClarifyModel(),
        tools=[FakeMalformedClarifyTool()],
    )

    lines = list(runner.stream("What scope?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Final answer"


class FakeStructuredFinalModel:
    def invoke(self, messages):
        return FakeToolCall(
            content=[
                {"type": "reasoning", "text": "private chain of thought"},
                {"type": "text", "text": "Visible answer"},
            ]
        )


def test_runner_streams_only_visible_text_from_structured_final_content():
    runner = LangChainAgentRunner(model=FakeStructuredFinalModel(), tools=[])

    lines = list(runner.stream("How?", []))

    assert event_types(lines) == ["agent_status", "token", "done"]
    token_data = json.loads(lines[1])["data"]
    assert token_data == "Visible answer"
    assert "private chain of thought" not in token_data


def test_runner_logs_only_visible_text_preview(caplog):
    runner = LangChainAgentRunner(model=FakeStructuredFinalModel(), tools=[])

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        list(runner.stream("How?", []))

    messages = [record.getMessage() for record in caplog.records]
    output_logs = [message for message in messages if "[agent] output" in message]
    assert output_logs
    assert any('preview="Visible answer"' in message for message in output_logs)
    assert all("private chain of thought" not in message for message in output_logs)


class FakeReasoningOnlyModel:
    def invoke(self, messages):
        return FakeToolCall(
            content=[
                {"type": "reasoning", "text": "private chain of thought"},
            ]
        )


def test_runner_skips_token_when_structured_final_content_has_no_visible_text():
    runner = LangChainAgentRunner(model=FakeReasoningOnlyModel(), tools=[])

    lines = list(runner.stream("How?", []))

    assert event_types(lines) == ["agent_status", "done"]


class FakePassiveKnowledgeTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Found evidence in the knowledge base.",
                "sources": [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
                "evidence": [{"chunk_id": "c1", "text": "Phase 2 uses agentic RAG."}],
            }
        )


class FakePassiveModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(content="Generic answer without tools")
        return FakeToolCall(content="Grounded answer from fallback")


class FakeCasualChatModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeToolCall(content="你好！有什么我可以帮你的吗？")


def test_runner_does_not_fallback_to_knowledge_search_for_casual_chat_answer():
    runner = LangChainAgentRunner(
        model=FakeCasualChatModel(),
        tools=[FakePassiveKnowledgeTool()],
    )

    lines = list(runner.stream("你好啊", []))

    assert event_types(lines) == ["agent_status", "token", "done"]
    assert json.loads(lines[0])["data"] == {"label": "chat"}
    assert json.loads(lines[1])["data"] == "你好！有什么我可以帮你的吗？"


def test_runner_falls_back_to_knowledge_search_when_model_skips_tools():
    model = FakePassiveModel()
    runner = LangChainAgentRunner(model=model, tools=[FakePassiveKnowledgeTool()])

    lines = list(runner.stream("How does phase 2 work?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Grounded answer from fallback"
    assert model.calls == 2


class FakeFallbackClarifyTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "insufficient",
                "summary": "",
                "clarify": {
                    "question": "Need more scope?",
                    "options": [{"label": "Current KB", "value": "scope:kb"}],
                },
                "sources": [],
                "evidence": [],
            }
        )


def test_runner_stops_after_fallback_clarify():
    model = FakePassiveModel()
    runner = LangChainAgentRunner(model=model, tools=[FakeFallbackClarifyTool()])

    lines = list(runner.stream("How does phase 2 work?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "clarify",
        "done",
    ]
    assert model.calls == 1
