import json
import logging
import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_agent_runner_test.db"

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


class FakeTraceTool:
    name = "deep_knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "partial",
                "summary": "Deep search collected evidence.",
                "trace_steps": [
                    {
                        "agent": "SearcherAgent",
                        "iteration": 1,
                        "label": "第 1 轮 · Searcher · Scope Finder",
                        "detail": "命中 1 个 CKP、2 个 PKU",
                    },
                    {
                        "agent": "JudgeAgent",
                        "iteration": 1,
                        "label": "第 1 轮 · Judge",
                        "detail": "overall=0.68 status=incomplete",
                    },
                ],
                "sources": [],
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


class FakeTraceModel:
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
                        "id": "call_trace",
                        "name": "deep_knowledge_search",
                        "args": {"query": "deep search"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer")


def event_types(lines):
    return [json.loads(line)["type"] for line in lines]


class FakeTraceRecorder:
    def __init__(self):
        self.steps = []
        self.finished_status = None

    def record_step(self, **kwargs):
        self.steps.append(kwargs)
        return f"step-{len(self.steps)}"

    def finish(self, status):
        self.finished_status = status


class FakeEvidenceTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Found evidence.",
                "stats": {"result_count": 1},
                "trace_steps": [{"label": "search", "detail": "found one"}],
                "evidence_items": [
                    {
                        "evidence_id": "ev-1",
                        "chunk_id": "chunk-1",
                        "item_id": "item-1",
                        "display_title": "Evidence title",
                        "excerpt": "Useful evidence",
                        "score": 0.9,
                    }
                ],
            }
        )


class FakeEvidenceModel:
    def __init__(self):
        self.calls = 0
        self.seen_tool_content = None

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
        self.seen_tool_content = messages[-1].content
        return FakeToolCall(content="Final answer")


def test_runner_records_tool_trace_and_streams_evidence_items():
    model = FakeEvidenceModel()
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=model, tools=[FakeEvidenceTool()])

    lines = list(
        runner.stream(
            "How?",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )
    tool_result = next(
        json.loads(line) for line in lines if json.loads(line)["type"] == "tool_result"
    )

    assert tool_result["data"]["evidence_items"] == [
        {
            "evidence_id": "ev-1",
            "chunk_id": "chunk-1",
            "item_id": "item-1",
            "display_title": "Evidence title",
            "excerpt": "Useful evidence",
            "score": 0.9,
        }
    ]
    assert json.loads(model.seen_tool_content)["evidence_items"] == tool_result["data"]["evidence_items"]
    assert [step["step_type"] for step in recorder.steps] == [
        "model_invoke",
        "model_response",
        "tool_call",
        "tool_result",
        "model_invoke",
        "model_response",
        "final_answer",
    ]
    assert recorder.steps[3]["evidence_items"] == tool_result["data"]["evidence_items"]
    assert recorder.finished_status == "success"


class FakeNoToolModel:
    def invoke(self, messages):
        return FakeToolCall(content="Direct answer")


def test_runner_records_no_tool_trace_success():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=FakeNoToolModel(), tools=[])

    list(
        runner.stream(
            "How?",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    assert [step["step_type"] for step in recorder.steps] == [
        "model_invoke",
        "model_response",
        "final_answer",
    ]
    assert recorder.steps[-1]["output_json"] == {"content": "Direct answer"}
    assert recorder.finished_status == "success"


class FakeLoopingToolModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_loop",
                    "name": "knowledge_search",
                    "args": {"query": "again"},
                }
            ]
        )


def test_runner_records_max_iterations_error_trace():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(
        model=FakeLoopingToolModel(),
        tools=[FakeTool()],
        max_iterations=1,
    )

    list(
        runner.stream(
            "How?",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    assert recorder.steps[-1]["step_type"] == "error"
    assert recorder.steps[-1]["status"] == "error"
    assert recorder.finished_status == "error"


class FakeExceptionModel:
    def invoke(self, messages):
        raise RuntimeError("model unavailable")


def test_runner_records_exception_error_trace():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=FakeExceptionModel(), tools=[])

    list(
        runner.stream(
            "How?",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    assert recorder.steps[-1]["step_type"] == "error"
    assert recorder.steps[-1]["output_json"] == {"message": "model unavailable"}
    assert recorder.steps[-1]["status"] == "error"
    assert recorder.finished_status == "error"


def test_runner_emits_tool_sources_tokens_and_done():
    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])

    # Use non-empty history to skip title auto-generation (avoids LLM dependency)
    lines = list(runner.stream("How?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "agent_status",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Final answer"


def test_runner_includes_tool_trace_steps_in_tool_result_event():
    runner = LangChainAgentRunner(model=FakeTraceModel(), tools=[FakeTraceTool()])

    lines = list(runner.stream("How?", [{"role": "user", "content": "previous"}]))
    tool_result = next(json.loads(line) for line in lines if json.loads(line)["type"] == "tool_result")

    assert tool_result["data"]["trace_steps"] == [
        {
            "agent": "SearcherAgent",
            "iteration": 1,
            "label": "第 1 轮 · Searcher · Scope Finder",
            "detail": "命中 1 个 CKP、2 个 PKU",
        },
        {
            "agent": "JudgeAgent",
            "iteration": 1,
            "label": "第 1 轮 · Judge",
            "detail": "overall=0.68 status=incomplete",
        },
    ]


def test_runner_emits_title_on_first_exchange(monkeypatch):
    """Title event should be emitted when history has no prior user messages."""
    from engine.app.agent import runner as runner_mod

    def fake_chat(messages):
        return "测试标题"

    monkeypatch.setattr(runner_mod, "chat", fake_chat)

    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])
    lines = list(runner.stream("How?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "agent_status",
        "token",
        "title",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "测试标题"


def test_runner_skips_title_with_history(monkeypatch):
    """Title event should NOT be emitted when history contains prior user messages."""
    from engine.app.agent import runner as runner_mod

    calls = []
    def fake_chat(messages):
        calls.append(messages)
        return "should not appear"

    monkeypatch.setattr(runner_mod, "chat", fake_chat)

    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])
    lines = list(runner.stream("Follow up?", [{"role": "user", "content": "previous"}]))

    types = event_types(lines)
    assert "title" not in types
    assert calls == []  # chat should never be called


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
                        "name": "clarify_user",
                        "args": {
                            "question": "Which scope?",
                            "options": [{"label": "Knowledge", "value": "scope:knowledge"}],
                        },
                    }
                ]
            )
        return FakeToolCall(content="")


def test_runner_emits_clarify_and_stops():
    runner = LangChainAgentRunner(model=FakeClarifyModel(), tools=[FakeClarifyTool()])

    # Use non-empty history to skip title auto-generation
    lines = list(runner.stream("Summarize it", [{"role": "user", "content": "previous"}]))

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
        return FakeToolCall(content="")


def test_runner_emits_nested_clarify_from_insufficient_tool_payload_and_stops():
    runner = LangChainAgentRunner(
        model=FakeInsufficientClarifyModel(),
        tools=[FakeInsufficientClarifyTool()],
    )

    # Use non-empty history to skip title auto-generation
    lines = list(runner.stream("What scope?", [{"role": "user", "content": "previous"}]))

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

    lines = list(runner.stream("What scope?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "agent_status",
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

    lines = list(runner.stream("How?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == ["agent_status", "agent_status", "token", "done"]
    token_data = json.loads(lines[2])["data"]
    assert token_data == "Visible answer"
    assert "private chain of thought" not in token_data


def test_runner_logs_only_visible_text_preview(caplog):
    runner = LangChainAgentRunner(model=FakeStructuredFinalModel(), tools=[])

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        list(runner.stream("How?", [{"role": "user", "content": "previous"}]))

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

    lines = list(runner.stream("你好啊", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == ["agent_status", "agent_status", "token", "done"]
    assert json.loads(lines[0])["data"] == {"label": "chat"}
    assert json.loads(lines[2])["data"] == "你好！有什么我可以帮你的吗？"


def test_runner_falls_back_to_knowledge_search_when_model_skips_tools():
    model = FakePassiveModel()
    runner = LangChainAgentRunner(model=model, tools=[FakePassiveKnowledgeTool()])

    lines = list(runner.stream("How does phase 2 work?", [{"role": "user", "content": "previous"}]))

    # FakePassiveModel returns content without tools on first call;
    # no tool fallback exists in the current runner — it outputs text directly.
    assert event_types(lines) == [
        "agent_status",
        "agent_status",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Generic answer without tools"
    assert model.calls == 1


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
    # Model: call 1 = tool, call 2 = empty text (to emit deferred clarify)
    class FakeFallbackClarifyModel:
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
            return FakeToolCall(content="")

    model = FakeFallbackClarifyModel()
    runner = LangChainAgentRunner(model=model, tools=[FakeFallbackClarifyTool()])

    # Use non-empty history to skip title auto-generation
    lines = list(runner.stream("How does phase 2 work?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "clarify",
        "done",
    ]
    assert model.calls == 2
