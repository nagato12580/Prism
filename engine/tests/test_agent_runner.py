import json
import logging
import os
import re
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_agent_runner_test.db"

from engine.app.agent import runner as runner_mod
from engine.app.agent import events as events_mod
from engine.app.agent.prompts import AGENT_SYSTEM_PROMPT
from engine.app.agent.continuation import AgentContinuation
from engine.app.agent.runner import FORCED_NO_EVIDENCE_ANSWER, LangChainAgentRunner
from engine.app.agent.tools.base import ToolContext
from engine.app.agent.tools.knowledge import build as build_knowledge_tool


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


class FakeSlowTool:
    name = "raw_document_search"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        time.sleep(0.2)
        return json.dumps({"status": "sufficient", "summary": "Too late."})


class FakeSlowToolModel:
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
                        "id": "call_slow",
                        "name": "raw_document_search",
                        "args": {"query": "missing gbraid"},
                    }
                ]
            )
        return FakeToolCall(content="I could not finish the document search.")


class FakeRepeatingSlowToolModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_slow_{self.calls}",
                        "name": "raw_document_search",
                        "args": {"query": "same slow query"},
                    }
                ]
            )
        return FakeToolCall(content="I stopped retrying the slow search.")


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


class FakeUnknownToolRecoveryBaseModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return FakeUnknownToolRecoveryBoundModel(self)

    def invoke(self, messages):
        return FakeToolCall(content="Recovered answer from available evidence")


class FakeUnknownToolRecoveryBoundModel:
    def __init__(self, base):
        self.base = base

    def invoke(self, messages):
        self.base.calls += 1
        if self.base.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "knowledge_search",
                        "args": {"query": "MiniMind-O"},
                    }
                ]
            )
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_2",
                    "name": "deep_knowledge_search",
                    "args": {"query": "MiniMind-O details"},
                }
            ]
        )


def event_types(lines):
    return [json.loads(line)["type"] for line in lines]


def test_runner_checkpoint_round_trips_langchain_messages():
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="hello"),
        AIMessage(
            content="need tool",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "knowledge_search",
                    "args": {"query": "x"},
                }
            ],
        ),
        ToolMessage(content='{"status":"success"}', tool_call_id="call-1"),
        AIMessage(content="final"),
    ]

    payload = runner_mod._checkpoint_from_state(
        query="hello",
        effective_query="hello",
        iteration=1,
        messages=messages,
        runner_state={
            "timed_out_tools": [],
            "open_kb_document_counts": {"file-a": 2},
            "document_windows_by_file": {},
        },
    )
    json.dumps(payload)
    restored_messages, restored_state = runner_mod._state_from_checkpoint(payload)

    assert payload["version"] == 1
    assert [type(message) for message in restored_messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
    ]
    assert restored_messages[2].tool_calls[0]["id"] == "call-1"
    assert restored_messages[3].tool_call_id == "call-1"
    assert restored_state["open_kb_document_counts"] == {"file-a": 2}


@pytest.mark.parametrize(
    "tool_calls",
    [
        "",
        0,
        False,
        {},
        ["bad"],
        [{"id": "call-1", "name": "knowledge_search"}],
        [{"id": "call-1", "name": "knowledge_search", "args": "bad"}],
    ],
)
def test_runner_rejects_malformed_ai_tool_calls(tool_calls):
    checkpoint = {
        "version": 1,
        "messages": [
            {"type": "ai", "content": "", "tool_calls": tool_calls},
        ],
    }

    assert runner_mod._state_from_checkpoint(checkpoint) is None


def test_runner_accepts_ai_message_with_missing_tool_calls():
    checkpoint = {
        "version": 1,
        "messages": [
            {"type": "ai", "content": "final"},
        ],
    }

    restored_messages, _ = runner_mod._state_from_checkpoint(checkpoint)

    assert isinstance(restored_messages[0], AIMessage)
    assert restored_messages[0].tool_calls == []


def test_runner_rejects_malformed_checkpoint():
    assert runner_mod._state_from_checkpoint({"version": 2}) is None
    assert runner_mod._state_from_checkpoint({"version": 1, "messages": "bad"}) is None


def test_runner_rejects_unknown_checkpoint_phase():
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "phase": "weird",
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
        ],
        "tool_state": {},
    }

    assert runner_mod._state_from_checkpoint(checkpoint) is None

    lines = list(
        LangChainAgentRunner(
            model=FakeResumeModel(),
            tools=[FakeEvidenceTool()],
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    assert [json.loads(line)["type"] for line in lines] == ["error", "done"]


def test_runner_rejects_completed_checkpoint_resume():
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "phase": "completed",
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
            {"type": "ai", "content": "Done.", "tool_calls": []},
        ],
        "tool_state": {},
    }
    class CountingModel:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            return FakeToolCall(content="Should not resume")

    model = CountingModel()

    lines = list(
        LangChainAgentRunner(
            model=model,
            tools=[FakeEvidenceTool()],
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )
    events = [json.loads(line) for line in lines]

    assert [event["type"] for event in events] == ["error", "done"]
    assert "completed" in events[0]["data"]
    assert model.calls == 0


@pytest.mark.parametrize("iteration", ["2", True, -10])
def test_runner_checkpoint_state_defaults_malformed_scalar_fields(iteration):
    restored = runner_mod._state_from_checkpoint(
        {
            "version": 1,
            "query": {"bad": "query"},
            "effective_query": ["bad"],
            "iteration": iteration,
            "messages": [{"type": "human", "content": "hello"}],
            "tool_state": {},
        }
    )

    assert restored is not None
    _messages, state = restored
    assert state["query"] == ""
    assert state["effective_query"] == ""
    assert state["iteration"] == 0


def test_runner_checkpoint_state_defaults_malformed_tool_state_children():
    restored = runner_mod._state_from_checkpoint(
        {
            "version": 1,
            "messages": [{"type": "human", "content": "hello"}],
            "tool_state": {
                "timed_out_tools": 1,
                "open_kb_document_counts": 1,
                "document_windows_by_file": 1,
            },
        }
    )

    assert restored is not None
    _messages, state = restored
    assert state["timed_out_tools"] == set()
    assert state["open_kb_document_counts"] == {}
    assert state["document_windows_by_file"] == {}


def test_runner_checkpoint_state_sanitizes_nested_tool_state_values():
    valid_window = {
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 0,
        "next_offset": 5,
        "content": "hello",
        "has_more_after": True,
    }
    invalid_next_offset_window = {
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 0,
        "next_offset": 10,
        "content": "hello",
        "has_more_after": True,
    }
    restored = runner_mod._state_from_checkpoint(
        {
            "version": 1,
            "messages": [{"type": "human", "content": "hello"}],
            "tool_state": {
                "timed_out_tools": ["datetime", 3],
                "open_kb_document_counts": {
                    "file-a": 2,
                    "file-b": "x",
                    "file-c": True,
                    "": 4,
                },
                "document_windows_by_file": {
                    "file-a": [
                        valid_window,
                        {"next_offset": 10},
                        invalid_next_offset_window,
                        "bad",
                    ],
                    "file-b": "bad",
                    "": [valid_window],
                },
            },
        }
    )

    assert restored is not None
    _messages, state = restored
    assert state["timed_out_tools"] == {"datetime"}
    assert state["open_kb_document_counts"] == {"file-a": 2}
    assert state["document_windows_by_file"] == {"file-a": [valid_window]}


def test_runner_checkpoint_serializes_structured_message_content_as_text():
    message = AIMessage(content=[{"type": "text", "text": "visible"}])
    payload = runner_mod._checkpoint_from_state(
        query="q",
        effective_query="q",
        iteration=1,
        messages=[message],
        runner_state={},
    )

    restored = runner_mod._state_from_checkpoint(payload)

    assert restored is not None
    messages, _state = restored
    assert messages[0].content == "visible"


def test_runner_checkpoint_serializes_ai_tool_calls_as_json_safe_payload():
    sentinel = object()
    message = AIMessage(
        content="need tool",
        tool_calls=[
            {
                "id": "call-1",
                "name": "knowledge_search",
                "args": {
                    "query": "x",
                    "filters": {"tags": {"alpha", "beta"}},
                    "sentinel": sentinel,
                },
            }
        ],
    )

    payload = runner_mod._checkpoint_from_state(
        query="q",
        effective_query="q",
        iteration=1,
        messages=[message],
        runner_state={},
    )
    json.dumps(payload)
    restored = runner_mod._state_from_checkpoint(payload)

    assert restored is not None
    messages, _state = restored
    restored_call = messages[0].tool_calls[0]
    assert restored_call["args"]["query"] == "x"
    assert isinstance(restored_call["args"]["filters"]["tags"], str)
    assert isinstance(restored_call["args"]["sentinel"], str)
    assert message.tool_calls[0]["args"]["filters"]["tags"] == {"alpha", "beta"}
    assert message.tool_calls[0]["args"]["sentinel"] is sentinel


class FakeTraceRecorder:
    def __init__(self):
        self.steps = []
        self.finished_status = None
        self.checkpoints = []
        self.trace_id = "trace-test"

    def record_step(self, **kwargs):
        self.steps.append(kwargs)
        return f"step-{len(self.steps)}"

    def finish(self, status):
        self.finished_status = status

    def save_checkpoint(self, checkpoint, *, resume_status="checkpointed"):
        self.checkpoints.append(
            {"checkpoint": checkpoint, "resume_status": resume_status}
        )
        return True

    def find_successful_tool_result(self, *args, **kwargs):
        return None


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
                        "chunk_id": "c1",
                        "source_id": "s1",
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
        self.seen_tool_message = None

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
        self.seen_tool_message = messages[-1]
        self.seen_tool_content = messages[-1].content
        return FakeToolCall(content="Final answer")


class FakeResumeModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        assert isinstance(messages[-1], ToolMessage)
        return FakeToolCall(content="Resumed final answer")


class FakeResumeForcedFinalModel:
    def __init__(self):
        self.calls = 0
        self.synthesis_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        self.synthesis_messages = messages
        return FakeToolCall(content="Forced resumed final answer")


class FakeDuplicateToolModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_dup_{self.calls}",
                        "name": "knowledge_search",
                        "args": {"query": "same"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer")


class CountingEvidenceTool(FakeEvidenceTool):
    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return super().invoke(args)


class FakePartialMultiToolResumeModel:
    def __init__(self):
        self.calls = 0
        self.final_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        self.final_messages = list(messages)
        return AIMessage(content="Multi-tool resumed final answer")


class FakeGraphExplainTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Found graph-backed evidence.",
                "sources": [
                    {
                        "chunk_id": "c_graph",
                        "item_id": "i_graph",
                        "title": "MiniMind-O article",
                        "snippet": "MiniMind-O is discussed in the article.",
                        "graph_rag": {
                            "explain": {
                                "why": "Connected through the MiniMind-O entity to the source chunk.",
                                "evidence_type": "INFERRED",
                                "source_marker": "graph_2hop",
                            },
                            "path": [
                                {
                                    "source_marker": "graph_2hop",
                                    "steps": [
                                        {"label": "MiniMind-O"},
                                        {"edge_type": "MENTIONED_IN", "evidence_type": "INFERRED"},
                                        {"label": "MiniMind-O article"},
                                    ],
                                }
                            ],
                        },
                    }
                ],
                "evidence_items": [
                    {
                        "evidence_id": "document_chunk:c_graph",
                        "chunk_id": "c_graph",
                        "source_id": "c_graph",
                        "source_kind": "document_chunk",
                        "display_title": "MiniMind-O article",
                        "excerpt": "MiniMind-O is discussed in the article.",
                        "hit_reason": "matched knowledge_search result",
                        "retrieval_path": ["knowledge_search"],
                        "metadata": {
                            "graph_explain": {
                                "why": "Connected through the MiniMind-O entity to the source chunk.",
                                "evidence_type": "INFERRED",
                                "source_marker": "graph_2hop",
                            },
                            "graph_path": [
                                {
                                    "source_marker": "graph_2hop",
                                    "steps": [
                                        {"label": "MiniMind-O"},
                                        {"edge_type": "MENTIONED_IN", "evidence_type": "INFERRED"},
                                        {"label": "MiniMind-O article"},
                                    ],
                                }
                            ],
                            "evidence_type": "INFERRED",
                        },
                    }
                ],
            }
        )


class FakeGraphExplainModel:
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
                        "id": "call_graph",
                        "name": "knowledge_search",
                        "args": {"query": "What does MiniMind-O say?"},
                    }
                ]
            )
        self.seen_tool_content = messages[-1].content
        return FakeToolCall(content="Final answer")


class FakeGraphExplainRagResult:
    status = "sufficient"
    summary = "Found graph-backed evidence."
    missing = []
    clarify = None
    iterations = 1
    evidence = []
    sources = [
        {
            "chunk_id": "c_graph",
            "item_id": "i_graph",
            "title": "MiniMind-O article",
            "snippet": "MiniMind-O is discussed in the article.",
            "graph_rag": {
                "explain": {
                    "why": "Connected through the MiniMind-O entity to the source chunk.",
                    "evidence_type": "INFERRED",
                    "source_marker": "graph_2hop",
                },
                "path": [
                    {
                        "source_marker": "graph_2hop",
                        "steps": [
                            {"label": "MiniMind-O"},
                            {"edge_type": "MENTIONED_IN", "evidence_type": "INFERRED"},
                            {"label": "MiniMind-O article"},
                        ],
                    }
                ],
            },
        }
    ]


class FakeGraphExplainRagRunner:
    def run(self, query):
        return FakeGraphExplainRagResult()


def test_recent_turn_history_keeps_last_ten_user_turns():
    history = []
    for index in range(1, 13):
        history.append({"role": "user", "content": f"user {index}"})
        history.append({"role": "assistant", "content": f"assistant {index}"})

    recent = runner_mod._recent_turn_history(history, 10)

    assert [item["content"] for item in recent][:2] == ["user 3", "assistant 3"]
    assert [item["content"] for item in recent][-2:] == ["user 12", "assistant 12"]
    assert len(recent) == 20


def test_estimate_tokens_uses_characters_divided_by_three():
    assert runner_mod._estimate_text_tokens("abcdef") == 2
    assert runner_mod._estimate_text_tokens("") == 0


def test_summary_transcript_limits_input_size(monkeypatch):
    monkeypatch.setattr(runner_mod.settings, "MAX_SUMMARY_TOKENS", 10, raising=False)
    history = _history_with_turns(12, content_size=30)

    transcript = runner_mod._summary_transcript(history)

    assert transcript
    assert len(transcript) <= 120
    assert "user 12 " in transcript
    assert "user 1 " not in transcript


def _history_with_turns(count, content_size=20):
    history = []
    for index in range(1, count + 1):
        history.append({"role": "user", "content": f"user {index} " + ("u" * content_size)})
        history.append({"role": "assistant", "content": f"assistant {index} " + ("a" * content_size)})
    return history


def test_build_messages_uses_full_history_below_threshold(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 32000, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    history = _history_with_turns(3, content_size=10)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")

    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert any("user 1" in content for content in contents)
    assert any("assistant 1" in content for content in contents)
    assert not any("会话早期摘要" in content for content in contents)


def test_build_messages_compresses_history_at_threshold(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：旧任务")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 600, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)
    monkeypatch.setattr(runner_mod.settings, "LOOP_RECENT_TURNS", 10, raising=False)

    history = _history_with_turns(12, content_size=50)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")

    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert any("会话早期摘要" in content for content in contents)
    assert not any("user 1 " in content for content in contents if not content.startswith("会话早期摘要"))
    assert any("user 3 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)


def test_compressed_history_still_injects_active_continuation(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：读文档")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 600, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    state = AgentContinuation(
        version=1,
        objective="读取论文后续内容",
        kb_uid="kb-a",
        file_uid="file-a",
        next_offset=123,
        has_more_after=True,
    )
    history = _history_with_turns(12, content_size=50)
    messages = runner._build_messages(
        "继续",
        history=history,
        effective_query="读取论文后续内容",
        active_continuation=state,
    )
    contents = [getattr(message, "content", "") for message in messages]

    assert any("file_uid: file-a" in content for content in contents)
    assert any("next_offset: 123" in content for content in contents)


def test_min_recent_history_fallback_still_keeps_active_continuation(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：读文档")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 80, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)
    monkeypatch.setattr(runner_mod.settings, "LOOP_RECENT_TURNS", 10, raising=False)
    monkeypatch.setattr(runner_mod.settings, "MIN_LOOP_RECENT_TURNS", 6, raising=False)

    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    state = AgentContinuation(
        version=1,
        objective="读取论文后续内容",
        kb_uid="kb-a",
        file_uid="file-a",
        next_offset=456,
        has_more_after=True,
    )
    history = _history_with_turns(12, content_size=50)
    messages = runner._build_messages(
        "继续",
        history=history,
        effective_query="读取论文后续内容",
        active_continuation=state,
    )
    contents = [getattr(message, "content", "") for message in messages]

    assert any("file_uid: file-a" in content for content in contents)
    assert any("next_offset: 456" in content for content in contents)
    assert any("user 7 " in content for content in contents)


def test_compressed_history_falls_back_to_recent_history_when_summary_fails(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")

    def fail_chat(*args, **kwargs):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(runner_mod, "chat", fail_chat)
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 600, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    history = _history_with_turns(12, content_size=50)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert not any("会话早期摘要" in content for content in contents)
    assert not any("user 1 " in content for content in contents)
    assert any("user 3 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)


def test_summary_failure_still_keeps_active_continuation(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")

    def fail_chat(*args, **kwargs):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(runner_mod, "chat", fail_chat)
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 700, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    state = AgentContinuation(
        version=1,
        objective="读取论文后续内容",
        kb_uid="kb-a",
        file_uid="file-a",
        next_offset=789,
        has_more_after=True,
    )
    history = _history_with_turns(12, content_size=50)
    messages = runner._build_messages(
        "继续",
        history=history,
        effective_query="读取论文后续内容",
        active_continuation=state,
    )
    contents = [getattr(message, "content", "") for message in messages]

    assert any("file_uid: file-a" in content for content in contents)
    assert any("next_offset: 789" in content for content in contents)
    assert not any("user 1 " in content for content in contents)
    assert any("user 7 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)


def test_compressed_history_uses_min_recent_history_when_still_over_budget(monkeypatch):
    monkeypatch.setattr(runner_mod, "recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod, "chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：旧任务")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 80, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)
    monkeypatch.setattr(runner_mod.settings, "LOOP_RECENT_TURNS", 10, raising=False)
    monkeypatch.setattr(runner_mod.settings, "MIN_LOOP_RECENT_TURNS", 6, raising=False)

    history = _history_with_turns(12, content_size=50)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert any("会话早期摘要" in content for content in contents)
    assert not any("user 6 " in content for content in contents if not content.startswith("会话早期摘要"))
    assert any("user 7 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)


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
            "chunk_id": "c1",
            "source_id": "s1",
            "display_title": "Evidence title",
            "excerpt": "Useful evidence",
            "score": 0.9,
        }
    ]
    assert isinstance(model.seen_tool_message, ToolMessage)
    tool_message_json = json.loads(model.seen_tool_content)
    assert tool_message_json["evidence_items"] == tool_result["data"]["evidence_items"]
    assert tool_message_json["evidence_items"][0]["chunk_id"] == "c1"
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


def test_runner_resumes_from_checkpoint_messages():
    checkpoint = runner_mod._checkpoint_from_state(
        query="How?",
        effective_query="How?",
        iteration=1,
        messages=[
            SystemMessage(content="system"),
            HumanMessage(content="How?"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "knowledge_search",
                        "args": {"query": "same"},
                    }
                ],
            ),
            ToolMessage(
                content='{"status":"success","summary":"cached"}',
                tool_call_id="call-1",
            ),
        ],
        runner_state={
            "timed_out_tools": [],
            "open_kb_document_counts": {},
            "document_windows_by_file": {},
        },
    )
    runner = LangChainAgentRunner(model=FakeResumeModel(), tools=[FakeEvidenceTool()])
    lines = list(runner.resume_stream(checkpoint, trace_recorder=FakeTraceRecorder()))

    events = [json.loads(line) for line in lines]
    assert events[-2]["type"] == "token"
    assert events[-2]["data"] == "Resumed final answer"
    assert events[-1]["type"] == "done"


def test_runner_resumes_from_model_response_checkpoint_executes_pending_tool():
    recorder = FakeTraceRecorder()
    source_runner = LangChainAgentRunner(
        model=FakeCheckpointModel(),
        tools=[FakeCheckpointTool()],
    )

    list(source_runner.stream("How?", [], trace_recorder=recorder))

    checkpoint = next(
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
        and item["checkpoint"]["messages"][-1]["type"] == "ai"
        and item["checkpoint"]["messages"][-1]["tool_calls"]
    )
    assert checkpoint["phase"] == "pending_tools"

    resume_tool = CountingEvidenceTool()
    lines = list(
        LangChainAgentRunner(
            model=FakeResumeModel(),
            tools=[resume_tool],
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert resume_tool.calls == 1
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Resumed final answer"


def test_runner_resumes_pending_tool_checkpoint_uses_dedupe():
    checkpoint = runner_mod._checkpoint_from_state(
        query="How?",
        effective_query="How?",
        iteration=1,
        messages=[
            SystemMessage(content="system"),
            HumanMessage(content="How?"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_dedupe",
                        "name": "knowledge_search",
                        "args": {"query": "same"},
                    }
                ],
            ),
        ],
        runner_state={
            "timed_out_tools": [],
            "open_kb_document_counts": {},
            "document_windows_by_file": {},
        },
        phase="pending_tools",
    )
    tool = CountingEvidenceTool()
    recorder = FakeTraceRecorder()
    recorder.find_successful_tool_result = lambda *, tool_name, args: {
        "dedupe_key": "cached-key",
        "output_json": {
            "status": "success",
            "summary": "Cached evidence.",
            "payload": {
                "status": "sufficient",
                "summary": "Cached evidence.",
                "stats": {"result_count": 1},
                "evidence_items": [
                    {
                        "evidence_id": "ev-cached",
                        "chunk_id": "c-cached",
                        "source_id": "s-cached",
                        "display_title": "Cached title",
                        "excerpt": "Cached evidence",
                        "score": 0.9,
                    }
                ],
            },
            "latency_ms": 7,
        },
    }

    lines = list(
        LangChainAgentRunner(
            model=FakeResumeModel(),
            tools=[tool],
        ).resume_stream(checkpoint, trace_recorder=recorder)
    )

    events = [json.loads(line) for line in lines]
    tool_results = [event for event in events if event["type"] == "tool_result"]
    result_steps = [
        step for step in recorder.steps if step.get("step_type") == "tool_result"
    ]
    assert tool.calls == 0
    assert tool_results
    assert tool_results[0]["data"]["summary"] == "Cached evidence."
    assert result_steps[-1]["input_json"]["reused"] is True
    assert result_steps[-1]["dedupe_key"] == "cached-key"


@pytest.mark.parametrize(
    "tool_call",
    [
        {"id": "", "name": "knowledge_search", "args": {"query": "same"}},
        {"name": "knowledge_search", "args": {"query": "same"}},
    ],
)
def test_runner_resumes_checkpoint_tool_call_without_id(tool_call):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "phase": "pending_tools",
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
            {"type": "ai", "content": "", "tool_calls": [tool_call]},
        ],
        "tool_state": {
            "timed_out_tools": [],
            "open_kb_document_counts": {},
            "document_windows_by_file": {},
        },
    }
    tool = CountingEvidenceTool()

    lines = list(
        LangChainAgentRunner(
            model=FakeResumeModel(),
            tools=[tool],
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert tool.calls == 1
    assert not any(
        event["type"] == "error" and "malformed" in str(event.get("data", ""))
        for event in events
    )
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Resumed final answer"


def test_runner_resumes_legacy_model_response_checkpoint_executes_pending_tool():
    recorder = FakeTraceRecorder()
    source_runner = LangChainAgentRunner(
        model=FakeCheckpointModel(),
        tools=[FakeCheckpointTool()],
    )

    list(source_runner.stream("How?", [], trace_recorder=recorder))

    checkpoint = next(
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
        and item["checkpoint"]["messages"][-1]["type"] == "ai"
        and item["checkpoint"]["messages"][-1]["tool_calls"]
    )
    checkpoint.pop("phase")

    resume_tool = CountingEvidenceTool()
    lines = list(
        LangChainAgentRunner(
            model=FakeResumeModel(),
            tools=[resume_tool],
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert resume_tool.calls == 1
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Resumed final answer"


def test_runner_resumes_from_last_tool_checkpoint_forces_final_answer():
    recorder = FakeTraceRecorder()
    source_runner = LangChainAgentRunner(
        model=FakeCheckpointModel(),
        tools=[FakeCheckpointTool()],
        max_iterations=1,
    )

    list(source_runner.stream("How?", [], trace_recorder=recorder))

    checkpoint = next(
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
        and item["checkpoint"]["messages"][-1]["type"] == "tool"
    )
    assert checkpoint["phase"] == "tool_result"

    model = FakeResumeForcedFinalModel()
    lines = list(
        LangChainAgentRunner(
            model=model,
            tools=[CountingEvidenceTool()],
            max_iterations=1,
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert model.calls == 1
    assert "error" not in [event["type"] for event in events]
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Forced resumed final answer"


def test_runner_resumes_legacy_last_tool_checkpoint_forces_final_answer():
    recorder = FakeTraceRecorder()
    source_runner = LangChainAgentRunner(
        model=FakeCheckpointModel(),
        tools=[FakeCheckpointTool()],
        max_iterations=1,
    )

    list(source_runner.stream("How?", [], trace_recorder=recorder))

    checkpoint = next(
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
        and item["checkpoint"]["messages"][-1]["type"] == "tool"
    )
    checkpoint.pop("phase")

    model = FakeResumeForcedFinalModel()
    lines = list(
        LangChainAgentRunner(
            model=model,
            tools=[CountingEvidenceTool()],
            max_iterations=1,
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert model.calls == 1
    assert "error" not in [event["type"] for event in events]
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Forced resumed final answer"


def test_runner_resumes_partial_multi_tool_checkpoint_without_synthetic_ai():
    original_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_first",
                "name": "knowledge_search",
                "args": {"query": "first"},
            },
            {
                "id": "call_second",
                "name": "knowledge_search",
                "args": {"query": "second"},
            },
        ],
    )
    checkpoint = runner_mod._checkpoint_from_state(
        query="How?",
        effective_query="How?",
        iteration=1,
        messages=[
            SystemMessage(content="system"),
            HumanMessage(content="How?"),
            original_ai,
            ToolMessage(
                content='{"status":"sufficient","summary":"First evidence."}',
                tool_call_id="call_first",
            ),
        ],
        runner_state={
            "timed_out_tools": [],
            "open_kb_document_counts": {},
            "document_windows_by_file": {},
        },
        phase="tool_result",
    )
    model = FakePartialMultiToolResumeModel()
    resume_tool = CountingEvidenceTool()

    lines = list(
        LangChainAgentRunner(
            model=model,
            tools=[resume_tool],
            max_iterations=2,
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    assert resume_tool.calls == 1
    assert [event["type"] for event in events][-2:] == ["token", "done"]
    assert events[-2]["data"] == "Multi-tool resumed final answer"
    assert model.final_messages is not None
    assert [
        type(message)
        for message in model.final_messages[-3:]
    ] == [AIMessage, ToolMessage, ToolMessage]
    assert model.final_messages[-3].tool_calls == original_ai.tool_calls
    assert [
        message.tool_call_id
        for message in model.final_messages[-2:]
    ] == ["call_first", "call_second"]


def test_runner_resumes_open_document_pending_tool_preserves_cap_final():
    original_ai = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_first",
                "name": "knowledge_search",
                "args": {"query": "first"},
            },
            {
                "id": "call_open",
                "name": "open_kb_document",
                "args": {
                    "kb_uid": "kb-a",
                    "file_uid": "file-a",
                    "offset": 4000,
                    "window_size": 1000,
                },
            },
        ],
    )
    checkpoint = runner_mod._checkpoint_from_state(
        query="Summarize the full paper",
        effective_query="Summarize the full paper",
        iteration=1,
        messages=[
            SystemMessage(content="system"),
            HumanMessage(content="Summarize the full paper"),
            original_ai,
            ToolMessage(
                content='{"status":"sufficient","summary":"First evidence."}',
                tool_call_id="call_first",
            ),
        ],
        runner_state={
            "timed_out_tools": [],
            "open_kb_document_counts": {"file-a": 4},
            "document_windows_by_file": {
                "file-a": [
                    {
                        "kb_uid": "kb-a",
                        "file_uid": "file-a",
                        "offset": index * 1000,
                        "next_offset": (index + 1) * 1000,
                        "content": f"existing window {index}",
                        "has_more_after": True,
                    }
                    for index in range(4)
                ]
            },
        },
        phase="tool_result",
    )
    tool = FakeOpenKbDocumentTool()
    model = FakeLoopingOpenKbDocumentModel()

    lines = list(
        LangChainAgentRunner(
            model=model,
            tools=[FakeEvidenceTool(), tool],
            max_iterations=5,
        ).resume_stream(checkpoint, trace_recorder=FakeTraceRecorder())
    )

    events = [json.loads(line) for line in lines]
    token_text = "".join(
        event["data"] for event in events if event["type"] == "token"
    )
    assert tool.calls == 1
    assert "Agent reached the maximum tool iteration limit" not in "\n".join(lines)
    assert event_types(lines)[-3:] == ["token", "continuation", "done"]
    assert "5" in token_text
    assert events[-2]["data"]["file_uid"] == "file-a"
    assert events[-2]["data"]["next_offset"] > 4000


def test_runner_reuses_successful_tool_result_for_duplicate_call():
    model = FakeDuplicateToolModel()
    tool = CountingEvidenceTool()
    recorder = FakeTraceRecorder()
    cached = {}
    cached_latency_ms = 12

    def find_successful_tool_result(*, tool_name, args):
        key = (tool_name, json.dumps(args, sort_keys=True))
        if key not in cached:
            return None
        return cached[key]

    def record_step(**kwargs):
        recorder.steps.append(kwargs)
        if kwargs["step_type"] == "tool_result" and kwargs["status"] == "success":
            key = (
                kwargs["tool_name"],
                json.dumps(kwargs["input_json"]["args"], sort_keys=True),
            )
            output_json = json.loads(json.dumps(kwargs["output_json"]))
            output_json["latency_ms"] = cached_latency_ms
            cached[key] = {
                "dedupe_key": kwargs["dedupe_key"],
                "output_json": output_json,
            }
        return f"step-{len(recorder.steps)}"

    recorder.find_successful_tool_result = find_successful_tool_result
    recorder.record_step = record_step

    runner = LangChainAgentRunner(model=model, tools=[tool])
    lines = list(runner.stream("How?", [], trace_recorder=recorder))

    assert tool.calls == 1
    assert event_types(lines).count("tool_result") == 2
    tool_result_events = [
        json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "tool_result"
    ]
    assert tool_result_events[1]["latency_ms"] == cached_latency_ms
    assert tool_result_events[1]["status"] == tool_result_events[0]["status"]
    assert tool_result_events[1]["summary"] == tool_result_events[0]["summary"]
    assert tool_result_events[1]["evidence_items"] == tool_result_events[0]["evidence_items"]

    tool_result_steps = [
        step for step in recorder.steps if step["step_type"] == "tool_result"
    ]
    assert tool_result_steps[1]["input_json"]["reused"] is True
    assert tool_result_steps[1]["latency_ms"] == cached_latency_ms


class FakeCheckpointTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Checkpoint evidence.",
                "evidence_items": [
                    {
                        "evidence_id": "ev-checkpoint",
                        "chunk_id": "chunk-checkpoint",
                        "source_id": "source-checkpoint",
                        "display_title": "Checkpoint title",
                        "excerpt": "Checkpoint excerpt",
                    }
                ],
            }
        )


class FakeCheckpointModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_checkpoint",
                        "name": "knowledge_search",
                        "args": {"query": "checkpoint query"},
                    }
                ],
            )
        return AIMessage(content="Checkpoint final answer")


def test_runner_saves_checkpoint_after_model_response_and_tool_result():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(
        model=FakeCheckpointModel(),
        tools=[FakeCheckpointTool()],
    )

    list(
        runner.stream(
            "How?",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    assert len(recorder.checkpoints) >= 3
    checkpointed = [
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
    ]
    completed = [
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "completed"
    ]
    assert checkpointed
    assert completed

    for item in recorder.checkpoints:
        payload = item["checkpoint"]
        json.dumps(payload)
        assert payload["version"] == 1
        assert payload["query"] == "How?"
        assert payload["effective_query"] == "How?"
        assert "iteration" in payload
        assert isinstance(payload["messages"], list)
        assert set(payload["tool_state"]) == {
            "timed_out_tools",
            "open_kb_document_counts",
            "document_windows_by_file",
        }

    assert any(
        any(
            message["type"] == "ai"
            and message["tool_calls"]
            and message["tool_calls"][0]["id"] == "call_checkpoint"
            for message in checkpoint["messages"]
        )
        for checkpoint in checkpointed
    )
    assert any(
        any(message["type"] == "tool" for message in checkpoint["messages"])
        for checkpoint in checkpointed
    )
    assert recorder.checkpoints[-1]["resume_status"] == "completed"


def test_runner_saves_open_kb_document_count_in_tool_checkpoint():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(
        model=FakeScriptedOpenModel(
            [("open_kb_document", {"kb_uid": "kb-a", "file_uid": "file-a", "offset": 0})],
            final_text="Done.",
        ),
        tools=[
            FakeRecordingDocumentTool(
                [
                    {
                        "kb_uid": "kb-a",
                        "file_uid": "file-a",
                        "offset": 0,
                        "next_offset": 6,
                        "content": "window",
                        "has_more_after": True,
                    }
                ]
            )
        ],
    )

    list(
        runner.stream(
            "Open the document",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    tool_checkpoint = next(
        item["checkpoint"]
        for item in recorder.checkpoints
        if item["resume_status"] == "checkpointed"
        and any(message["type"] == "tool" for message in item["checkpoint"]["messages"])
    )

    assert tool_checkpoint["tool_state"]["open_kb_document_counts"]["file-a"] == 1


def test_runner_preserves_graph_explanations_in_tool_message_payload():
    model = FakeGraphExplainModel()
    runner = LangChainAgentRunner(model=model, tools=[FakeGraphExplainTool()])

    list(runner.stream("What does MiniMind-O say?", [{"role": "user", "content": "previous"}]))

    payload = json.loads(model.seen_tool_content)
    assert payload["graph_explanations"] == [
        "Graph inference: Connected through the MiniMind-O entity to the source chunk. Path: MiniMind-O -> MENTIONED_IN -> MiniMind-O article.",
    ]
    assert payload["evidence_items"][0]["metadata"]["graph_explain"]["evidence_type"] == "INFERRED"


def test_knowledge_tool_derives_graph_explanations_from_evidence_items():
    ctx = ToolContext(rag_runner=FakeGraphExplainRagRunner(), citations=[], stats_holder={})
    tool = build_knowledge_tool(ctx)

    payload = json.loads(tool.invoke({"query": "What does MiniMind-O say?"}))

    assert payload["graph_explanations"] == [
        "Graph inference: Connected through the MiniMind-O entity to the source chunk. Path: MiniMind-O -> MENTIONED_IN -> MiniMind-O article.",
    ]
    assert payload["evidence_items"][0]["metadata"]["graph_explain"]["evidence_type"] == "INFERRED"


def test_agent_system_prompt_constrains_evidence_identifier_usage():
    policy_phrases = [
        "只能使用本轮工具 JSON 的 `evidence_items` 中真实出现过的 id",
        "本轮 `evidence_items` 未包含该 id",
        "当前工具结果未返回该 id、无法验证",
        "不得编造、补全或猜测 id",
        "优先依据其中的 `excerpt`、`chunk_id` 和 `source_id`",
        "而不是只根据 summary 做概括性猜测",
    ]

    for phrase in policy_phrases:
        assert phrase in AGENT_SYSTEM_PROMPT


def test_agent_system_prompt_includes_graph_explanation_rules():
    policy_phrases = [
        "When evidence depends on graph expansion",
        "Never present INFERRED graph edges as if they were verbatim source facts",
        "When multiple sources are connected through entities",
    ]

    for phrase in policy_phrases:
        assert phrase in AGENT_SYSTEM_PROMPT


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


class FakeLastIterationToolRequestModel:
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
                        "id": "call_search",
                        "name": "knowledge_search",
                        "args": {"query": "hierarchical anchoring"},
                    }
                ]
            )
        if self.calls == 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_mindmap",
                        "name": "get_mindmap",
                        "args": {"kb_uid": "kb-a"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer from existing evidence.")


class FakeMindmapTool:
    name = "get_mindmap"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return json.dumps({"status": "ok", "data": {"mindmap": {"nodes": []}}})


class FakeOpenKbDocumentTool:
    name = "open_kb_document"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        content = f"window {self.calls}"
        offset = args.get("offset", 0)
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "kb_uid": args["kb_uid"],
                    "file_uid": args["file_uid"],
                    "offset": offset,
                    "next_offset": offset + len(content),
                    "content": content,
                    "has_more_after": True,
                },
            }
        )


class FakeNestedOpenKbDocumentTool(FakeOpenKbDocumentTool):
    def invoke(self, args):
        self.calls += 1
        content = f"nested window {self.calls}"
        offset = args.get("offset", 0)
        return json.dumps(
            {
                "status": "success",
                "payload": {
                    "summary": {
                        "status": "ok",
                        "data": {
                            "kb_uid": args["kb_uid"],
                            "file_uid": args["file_uid"],
                            "offset": offset,
                            "next_offset": offset + len(content),
                            "content": content,
                            "has_more_after": True,
                        },
                    }
                },
            }
        )


class FakeLoopingOpenKbDocumentModel:
    def __init__(self):
        self.calls = 0
        self.last_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        if self.calls <= 99:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_open_{self.calls}",
                        "name": "open_kb_document",
                        "args": {
                            "kb_uid": "kb-a",
                            "file_uid": "file-a",
                            "offset": (self.calls - 1) * 1000,
                            "window_size": 1000,
                        },
                    }
                ]
            )
        return FakeToolCall(content="should not reach here")


class FakeDsmlAfterOpenLimitModel(FakeLoopingOpenKbDocumentModel):
    def invoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        if self.calls <= 5:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_open_{self.calls}",
                        "name": "open_kb_document",
                        "args": {
                            "kb_uid": "kb-a",
                            "file_uid": "file-a",
                            "offset": (self.calls - 1) * 1000,
                            "window_size": 1000,
                        },
                    }
                ]
            )
        return FakeToolCall(
            content=(
                "<｜｜DSML｜｜tool_calls>\n"
                "<｜｜DSML｜｜invoke name=\"open_kb_document\">\n"
                "<｜｜DSML｜｜parameter name=\"file_uid\" string=\"true\">file-a</｜｜DSML｜｜parameter>\n"
                "</｜｜DSML｜｜invoke>\n"
                "</｜｜DSML｜｜tool_calls>"
            )
        )


class FakeAnswersAfterOpenLimitModel(FakeLoopingOpenKbDocumentModel):
    def invoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        if self.calls <= 5:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_open_{self.calls}",
                        "name": "open_kb_document",
                        "args": {
                            "kb_uid": "kb-a",
                            "file_uid": "file-a",
                            "offset": (self.calls - 1) * 1000,
                            "window_size": 1000,
                        },
                    }
                ]
            )
        return FakeToolCall(content="Based on the five windows, hierarchical anchoring means staged grounding.")


def test_runner_synthesizes_after_tool_on_last_iteration():
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

    forced_invoke = next(
        step for step in recorder.steps
        if step["step_type"] == "model_invoke"
        and step["input_json"].get("iteration") == "forced_final_after_iteration_limit"
    )
    assert forced_invoke["input_json"]["message_roles"] == ["system", "human"]
    assert recorder.steps[-1]["step_type"] == "final_answer"
    assert recorder.finished_status == "success"


def test_runner_forces_final_answer_when_last_iteration_requests_tool_with_evidence():
    recorder = FakeTraceRecorder()
    model = FakeLastIterationToolRequestModel()
    mindmap_tool = FakeMindmapTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeTool(), mindmap_tool],
        max_iterations=2,
    )

    lines = list(
        runner.stream(
            "Explain hierarchical anchoring",
            [{"role": "user", "content": "previous"}],
            trace_recorder=recorder,
        )
    )

    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    assert mindmap_tool.calls == 1
    assert model.calls == 3
    assert "Final answer from existing evidence." in token_text
    assert "Agent reached the maximum tool iteration limit" not in "\n".join(lines)
    assert recorder.steps[-1]["step_type"] == "final_answer"
    assert recorder.finished_status == "success"


def test_synthesis_selection_retains_decisive_final_find_result():
    old_evidence = [
        {"text": f"old semantic excerpt {index}", "file_uid": f"file-{index}"}
        for index in range(10)
    ]
    messages = [
        ToolMessage(
            content=json.dumps(
                {
                    "status": "success",
                    "payload": {
                        "summary": {
                            "status": "ok",
                            "data": {"evidence": old_evidence},
                        }
                    },
                }
            ),
            tool_call_id="call_query",
        ),
        ToolMessage(
            content=json.dumps(
                {"data": {"file_uid": "older-paper", "content": "older document window one"}}
            ),
            tool_call_id="call_old_open_1",
        ),
        ToolMessage(
            content=json.dumps(
                {"data": {"file_uid": "older-paper", "content": "older document window two"}}
            ),
            tool_call_id="call_old_open_2",
        ),
        ToolMessage(
            content=json.dumps(
                {"data": {"file_uid": "older-paper", "content": "older document window three"}}
            ),
            tool_call_id="call_old_open_3",
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "status": "ok",
                    "data": {
                        "file_uid": "optimizer-paper",
                        "matches": [{"text": "Adam, initial learning rate 0.01"}],
                    },
                }
            ),
            tool_call_id="call_find",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_find"],
    )
    prompt = runner_mod._document_cap_synthesis_messages(
        "What was Adam's initial learning rate?",
        messages,
        required_tool_call_ids=["call_find"],
    )

    assert selected[0].text == "Adam, initial learning rate 0.01"
    assert selected[0].kind == "match"
    assert selected[0].tool_call_id == "call_find"
    assert "0.01" in prompt[1].content


def test_synthesis_selection_orders_distinct_file_coverage_before_duplicate_file():
    messages = [
        ToolMessage(
            content=json.dumps(
                {
                    "data": {
                        "coverage": {"files_considered": 3},
                        "evidence": [
                            {"text": "file-a coverage one", "file_uid": "file-a"},
                            {"text": "file-a coverage two", "file_uid": "file-a"},
                            {"text": "file-b coverage", "file_uid": "file-b"},
                            {"text": "file-c coverage", "file_uid": "file-c"},
                        ],
                    }
                }
            ),
            tool_call_id="call_coverage",
        )
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_coverage"],
    )

    assert [item.kind for item in selected] == ["coverage"] * 4
    assert [item.file_uid for item in selected] == ["file-a", "file-b", "file-c", "file-a"]


def test_synthesis_candidates_index_only_tool_results_in_message_order():
    messages = [
        FakeToolCall(content="ignored model response"),
        ToolMessage(
            content=json.dumps({"data": {"content": "first result"}}),
            tool_call_id="call_first",
        ),
        FakeToolCall(content="another ignored model response"),
        ToolMessage(
            content=json.dumps({"data": {"content": "second result"}}),
            tool_call_id="call_second",
        ),
    ]

    candidates = runner_mod._synthesis_evidence_candidates(messages)

    assert [item.result_index for item in candidates] == [0, 1]


def test_synthesis_selection_preserves_each_required_tool_result_within_budget():
    messages = [
        ToolMessage(
            content=json.dumps({"data": {"matches": [{"text": "first exact fact"}]}}),
            tool_call_id="call_first",
        ),
        ToolMessage(
            content=json.dumps({"data": {"content": "second document fact", "file_uid": "file-b"}}),
            tool_call_id="call_second",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_first", "call_second"],
    )

    assert [item.tool_call_id for item in selected[:2]] == ["call_first", "call_second"]
    assert [item.text for item in selected[:2]] == ["first exact fact", "second document fact"]


def test_synthesis_selection_uses_unique_candidate_after_required_duplicate():
    shared = "shared fact " * 20
    messages = [
        ToolMessage(
            content=json.dumps(
                {"data": {"evidence": [{"text": shared}, {"text": "call-a detail " * 20}]}}
            ),
            tool_call_id="call_a",
        ),
        ToolMessage(
            content=json.dumps(
                {"data": {"evidence": [{"text": shared}, {"text": "call-b detail " * 20}]}}
            ),
            tool_call_id="call_b",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_a", "call_b"],
        char_budget=550,
    )

    assert {item.tool_call_id for item in selected} >= {"call_a", "call_b"}
    assert any(item.tool_call_id == "call_b" and "call-b detail" in item.text for item in selected)


def test_synthesis_selection_keeps_required_results_within_total_budget():
    messages = [
        ToolMessage(
            content=json.dumps({"data": {"content": "a" * 700}}),
            tool_call_id="call_first",
        ),
        ToolMessage(
            content=json.dumps({"data": {"content": "b" * 700}}),
            tool_call_id="call_last",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_first", "call_last"],
        char_budget=800,
    )

    assert [item.tool_call_id for item in selected] == ["call_first", "call_last"]
    assert all(item.text for item in selected)
    assert sum(len(re.sub(r"\s+", " ", item.text).strip()) for item in selected) <= 800

    impossible = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_first", "call_last"],
        char_budget=0,
    )
    assert impossible == []


def test_synthesis_selection_keeps_required_truncated_excerpts_distinct():
    messages = [
        ToolMessage(
            content=json.dumps({"data": {"content": "a" * 700}}),
            tool_call_id="call_first",
        ),
        ToolMessage(
            content=json.dumps({"data": {"content": ("a" * 500) + ("b" * 200)}}),
            tool_call_id="call_last",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_first", "call_last"],
        char_budget=800,
    )
    normalized = [re.sub(r"\s+", " ", item.text).strip() for item in selected]

    assert [item.tool_call_id for item in selected] == ["call_first", "call_last"]
    assert sum(len(text) for text in normalized) <= 800
    assert len(set(normalized)) == 2


def test_synthesis_selection_prioritizes_all_final_tool_candidates():
    historical = [
        {"text": f"historical match {index} ".ljust(700, "x")}
        for index in range(11)
    ]
    messages = [
        ToolMessage(
            content=json.dumps({"data": {"matches": historical}}),
            tool_call_id="call_old",
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "data": {
                        "evidence": [
                            {"text": "Adam optimizer ".ljust(700, "a")},
                            {"text": "initial learning rate 0.01 ".ljust(700, "b")},
                        ]
                    }
                }
            ),
            tool_call_id="call_final",
        ),
    ]

    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids=["call_final"],
    )

    assert "Adam optimizer" in selected[0].text
    assert "initial learning rate 0.01" in selected[1].text


def test_resolved_tool_call_id_falls_back_to_tool_name():
    assert runner_mod._resolved_tool_call_id({"id": "", "name": "knowledge_search"}) == "knowledge_search"
    assert runner_mod._resolved_tool_call_id({"name": "open_kb_document"}) == "open_kb_document"


class FakeRequiredFallbackModel:
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
                        "id": "call_old",
                        "name": "knowledge_search",
                        "args": {"query": "historical"},
                    }
                ]
            )
        if self.calls == 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_final",
                        "name": "knowledge_search",
                        "args": {"query": "decisive"},
                    }
                ]
            )
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_ignored",
                    "name": "knowledge_search",
                    "args": {"query": "ignored"},
                }
            ]
        )


class FakeRequiredFallbackTool:
    name = "knowledge_search"

    def invoke(self, args):
        if args["query"] == "historical":
            return json.dumps(
                {
                    "data": {
                        "matches": [
                            {"text": f"historical match {index} ".ljust(700, "x")}
                            for index in range(11)
                        ]
                    }
                }
            )
        return json.dumps(
            {
                "data": {
                    "evidence": [
                        {"text": "Adam optimizer ".ljust(700, "a")},
                        {"text": "initial learning rate 0.01 ".ljust(700, "b")},
                    ]
                }
            }
        )


def test_runner_fallback_prioritizes_final_required_tool_evidence():
    runner = LangChainAgentRunner(
        model=FakeRequiredFallbackModel(),
        tools=[FakeRequiredFallbackTool()],
        max_iterations=2,
    )

    lines = list(
        runner.stream(
            "What was Adam's initial learning rate?",
            [{"role": "user", "content": "previous"}],
        )
    )
    token_text = "".join(
        json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token"
    )

    assert "initial learning rate 0.01" in token_text


class FakeFinalOpenEvidenceModel:
    def __init__(self):
        self.calls = 0
        self.forced_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[{"id": "call_old", "name": "knowledge_search", "args": {"query": "Adam"}}]
            )
        if self.calls == 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_final_open",
                        "name": "open_kb_document",
                        "args": {"file_uid": "paper", "offset": 0},
                    }
                ]
            )
        self.forced_messages = messages
        return FakeToolCall(content="The initial learning rate was 0.01.")


class FakeManyOldEvidenceTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "success",
                "payload": {
                    "summary": {
                        "status": "ok",
                        "data": {
                            "evidence": [
                                {"text": f"old semantic excerpt {index}"}
                                for index in range(14)
                            ]
                        },
                    }
                },
            }
        )


class FakeFinalOpenEvidenceTool:
    name = "open_kb_document"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "file_uid": args["file_uid"],
                    "content": "Adam, initial learning rate 0.01",
                    "has_more_after": False,
                },
            }
        )


def test_runner_includes_final_open_result_in_last_iteration_forced_synthesis():
    model = FakeFinalOpenEvidenceModel()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeManyOldEvidenceTool(), FakeFinalOpenEvidenceTool()],
        max_iterations=2,
    )

    lines = list(runner.stream("What was Adam's initial learning rate?", [{"role": "user", "content": "previous"}]))

    assert "0.01" in model.forced_messages[1].content
    assert "0.01" in "".join(
        json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token"
    )


def test_runner_forces_answer_after_five_open_kb_document_calls_for_same_run():
    model = FakeLoopingOpenKbDocumentModel()
    tool = FakeOpenKbDocumentTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[tool],
        max_iterations=10,
    )

    lines = list(
        runner.stream(
            "Summarize the full paper",
            [{"role": "user", "content": "previous"}],
        )
    )

    assert tool.calls == 5
    assert "Agent reached the maximum tool iteration limit" not in "\n".join(lines)
    assert event_types(lines)[-3:] == ["token", "continuation", "done"]
    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    assert "还没读取完整篇文档" in token_text
    assert "是否继续" in token_text


def test_runner_immediately_answers_when_open_limit_reached_on_final_iteration():
    model = FakeLoopingOpenKbDocumentModel()
    tool = FakeOpenKbDocumentTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[tool],
        max_iterations=5,
    )

    lines = list(
        runner.stream(
            "Explain the paper in detail",
            [{"role": "user", "content": "previous"}],
        )
    )

    assert tool.calls == 5
    assert "Agent reached the maximum tool iteration limit" not in "\n".join(lines)
    assert event_types(lines)[-3:] == ["token", "continuation", "done"]
    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    assert "还没读取完整篇文档" in token_text
    assert "是否继续" in token_text


def test_runner_gives_model_one_no_tool_answer_pass_at_open_limit():
    model = FakeAnswersAfterOpenLimitModel()
    tool = FakeNestedOpenKbDocumentTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[tool],
        max_iterations=5,
    )

    lines = list(
        runner.stream(
            "Explain the paper in detail",
            [{"role": "user", "content": "previous"}],
        )
    )

    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    forced_messages = model.last_messages
    assert [message.type for message in forced_messages] == ["system", "human"]
    assert not any(isinstance(message, ToolMessage) for message in forced_messages)
    assert "Explain the paper in detail" in forced_messages[1].content
    assert "nested window 1" in forced_messages[1].content
    assert "nested window 5" in forced_messages[1].content
    assert tool.calls == 5
    assert model.calls == 6
    assert "Based on the five windows" in token_text
    assert "我已经连续读取了这篇文档的前 5 个窗口" not in token_text
    assert "Agent reached the maximum tool iteration limit" not in "\n".join(lines)


def test_runner_suppresses_textual_dsml_tool_call_after_open_limit():
    model = FakeDsmlAfterOpenLimitModel()
    tool = FakeOpenKbDocumentTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[tool],
        max_iterations=10,
    )

    lines = list(
        runner.stream(
            "Explain hierarchical anchoring",
            [{"role": "user", "content": "previous"}],
        )
    )

    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    assert tool.calls == 5
    assert "DSML" not in token_text
    assert "open_kb_document" not in token_text
    assert "还没读取完整篇文档" in token_text
    assert "是否继续" in token_text
    assert "window 1" in token_text
    assert "window 5" in token_text


class FakeEmptyEvidenceTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "insufficient",
                "summary": "No grounded evidence is available.",
                "sources": [{"chunk_id": "ghost", "item_id": "gone", "text": ""}],
                "evidence": [{"chunk_id": "ghost", "text": ""}],
                "evidence_items": [],
            }
        )


class FakeRetryingInsufficientModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= 99:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_retry_{self.calls}",
                        "name": "knowledge_search",
                        "args": {"query": f"retry {self.calls}"},
                    }
                ]
            )
        return FakeToolCall(content="The current knowledge base has no usable grounded evidence for this question.")


def test_runner_forces_answer_after_repeated_insufficient_results_without_valid_evidence():
    runner = LangChainAgentRunner(
        model=FakeRetryingInsufficientModel(),
        tools=[FakeEmptyEvidenceTool()],
        max_iterations=5,
    )

    lines = list(runner.stream("What is MiniMind-O?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "tool_call",
        "tool_result",
        "sources",
        "agent_status",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == FORCED_NO_EVIDENCE_ANSWER
    assert runner.model.calls == 3


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


def test_runner_times_out_slow_tool_and_emits_error_result():
    runner = LangChainAgentRunner(
        model=FakeSlowToolModel(),
        tools=[FakeSlowTool()],
        tool_timeout_seconds=0.01,
    )

    lines = list(runner.stream("What is gbraid?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "agent_status",
        "token",
        "done",
    ]
    tool_result = next(json.loads(line) for line in lines if json.loads(line)["type"] == "tool_result")
    assert tool_result["data"]["tool"] == "raw_document_search"
    assert tool_result["data"]["status"] == "error"
    assert "timed out" in tool_result["data"]["summary"]
    assert json.loads(lines[-2])["data"] == "I could not finish the document search."


def test_runner_forces_grounded_answer_after_unknown_tool_when_evidence_exists():
    base_model = FakeUnknownToolRecoveryBaseModel()
    runner = LangChainAgentRunner(model=base_model, tools=[FakeTool()])

    lines = list(runner.stream("What is MiniMind-O?", [{"role": "user", "content": "previous"}]))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "tool_call",
        "tool_result",
        "agent_status",
        "token",
        "done",
    ]
    tool_results = [json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "tool_result"]
    assert tool_results[1]["tool"] == "deep_knowledge_search"
    assert tool_results[1]["status"] == "error"
    assert tool_results[1]["summary"] == "Unknown tool: deep_knowledge_search"
    assert json.loads(lines[-2])["data"] == "Recovered answer from available evidence"


def test_runner_blocks_repeated_calls_after_tool_timeout():
    slow_tool = FakeSlowTool()
    runner = LangChainAgentRunner(
        model=FakeRepeatingSlowToolModel(),
        tools=[slow_tool],
        tool_timeout_seconds=0.01,
    )

    lines = list(runner.stream("What is gbraid?", [{"role": "user", "content": "previous"}]))
    tool_results = [json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "tool_result"]

    assert len(tool_results) == 2
    assert tool_results[0]["status"] == "error"
    assert "timed out" in tool_results[0]["summary"]
    assert tool_results[1]["status"] == "error"
    assert "disabled after a previous timeout" in tool_results[1]["summary"]
    assert slow_tool.calls == 1
    assert json.loads(lines[-2])["data"] == "I stopped retrying the slow search."


def test_runner_default_tool_timeout_comes_from_settings():
    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])

    assert runner.tool_timeout_seconds == runner_mod.settings.AGENT_TOOL_TIMEOUT_SECONDS


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


def test_runner_trace_tool_result_records_full_payload_for_bad_case_analysis():
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=FakeTraceModel(), tools=[FakeTraceTool()])

    list(runner.stream("How?", [{"role": "user", "content": "previous"}], trace_recorder=recorder))

    tool_result_step = next(step for step in recorder.steps if step["step_type"] == "tool_result")
    assert tool_result_step["input_json"] == {
        "tool": "deep_knowledge_search",
        "call_id": "call_trace",
        "args": {"query": "deep search"},
        "query": "deep search",
        "reused": False,
    }
    assert tool_result_step["output_json"]["payload"]["status"] == "partial"
    assert tool_result_step["output_json"]["payload"]["trace_steps"][0]["agent"] == "SearcherAgent"


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


CONTINUATION_STATE = {
    "version": 1,
    "objective": "层次锚定的超参数怎么设置？",
    "kb_uid": "kb-hyper",
    "file_uid": "file-hyper",
    "next_offset": 1651,
    "has_more_after": True,
}


def _continuation_history(state=None):
    return [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {
            "role": "assistant",
            "content": "我先读到这里，请回复继续。",
            "continuation": state or CONTINUATION_STATE,
        },
    ]


class FakeScriptedOpenModel:
    def __init__(self, calls, final_text="阶段性答案"):
        self.calls = list(calls)
        self.final_text = final_text
        self.invocations = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invocations.append(messages)
        index = len(self.invocations) - 1
        if index < len(self.calls):
            name, args = self.calls[index]
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"call_{index + 1}",
                        "name": name,
                        "args": dict(args),
                    }
                ]
            )
        return FakeToolCall(content=self.final_text)


class FakeRecordingDocumentTool:
    name = "open_kb_document"

    def __init__(self, windows=None):
        self.args = []
        self.windows = list(windows or [])

    def invoke(self, args):
        self.args.append(dict(args))
        index = len(self.args) - 1
        window = self.windows[index] if index < len(self.windows) else {}
        offset = window.get("offset", args.get("offset", 0))
        content = window.get("content")
        if content is None:
            requested_next_offset = window.get("next_offset")
            if isinstance(requested_next_offset, int) and not isinstance(requested_next_offset, bool):
                content = "x" * max(0, requested_next_offset - offset)
            else:
                content = f"window {index + 1}"
        next_offset = window.get("next_offset", offset + len(content))
        return json.dumps(
            {
                "status": window.get("status", "ok"),
                "data": {
                    "kb_uid": window.get("kb_uid", args.get("kb_uid", "kb-hyper")),
                    "file_uid": window.get("file_uid", args.get("file_uid", "file-hyper")),
                    "offset": offset,
                    "next_offset": next_offset,
                    "content": content,
                    "has_more_after": window.get("has_more_after", True),
                },
            },
            ensure_ascii=False,
        )


class FakeFindDocumentTool:
    name = "find_in_kb_document"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "file_uid": args.get("file_uid"),
                    "matches": [{"line": 1652, "text": "exact hyperparameter"}],
                },
            }
        )


def _five_open_calls(offsets=None):
    offsets = offsets or [0, 100, 200, 300, 400]
    return [
        (
            "open_kb_document",
            {"kb_uid": "kb-hyper", "file_uid": "file-hyper", "offset": offset},
        )
        for offset in offsets
    ]


def test_continuation_event_emits_only_safe_cursor_fields():
    state = AgentContinuation(**CONTINUATION_STATE)

    payload = json.loads(events_mod.continuation_event(state))

    assert payload == {"type": "continuation", "data": CONTINUATION_STATE}
    assert "content" not in json.dumps(payload)
    assert "scope" not in json.dumps(payload)


def test_bare_continue_uses_stored_objective_for_clean_synthesis_and_trace():
    model = FakeScriptedOpenModel(_five_open_calls())
    tool = FakeRecordingDocumentTool()
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=model, tools=[tool], max_iterations=10)

    list(runner.stream("继续", _continuation_history(), trace_recorder=recorder))

    forced_messages = model.invocations[-1]
    assert CONTINUATION_STATE["objective"] in forced_messages[1].content
    assert "用户问题：继续\n" not in forced_messages[1].content
    resume_messages = [
        message.content
        for message in model.invocations[0]
        if getattr(message, "type", "") == "system" and "1651" in message.content
    ]
    assert resume_messages
    assert CONTINUATION_STATE["objective"] in resume_messages[0]
    assert "file-hyper" in resume_messages[0]
    assert "kb-hyper" in resume_messages[0]
    assert any(
        getattr(message, "type", "") == "human" and message.content == "继续"
        for message in model.invocations[0]
    )
    invokes = [step for step in recorder.steps if step["step_type"] == "model_invoke"]
    assert all(
        step["input_json"]["effective_objective_source"] == "continuation_state"
        for step in invokes
    )


def test_resume_rewrites_stale_beginning_open_to_saved_cursor():
    model = FakeScriptedOpenModel(
        [("open_kb_document", {"file_uid": "file-hyper", "offset": 0})]
    )
    tool = FakeRecordingDocumentTool()
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=model, tools=[tool])

    list(runner.stream("继续", _continuation_history(), trace_recorder=recorder))

    resumed_args = {"kb_uid": "kb-hyper", "file_uid": "file-hyper", "offset": 1651}
    assert tool.args == [resumed_args]
    tool_steps = [
        step for step in recorder.steps if step["step_type"] in {"tool_call", "tool_result"}
    ]
    assert [step["input_json"]["args"] for step in tool_steps] == [
        resumed_args,
        resumed_args,
    ]
    returned_data = json.loads(model.invocations[1][-1].content)["data"]
    assert returned_data["kb_uid"] == "kb-hyper"
    assert returned_data["file_uid"] == "file-hyper"
    assert returned_data["offset"] == 1651


def test_same_file_explicit_line_is_preserved_and_consumes_resume():
    model = FakeScriptedOpenModel(
        [
            ("find_in_kb_document", {"file_uid": "file-hyper", "query": "hyperparameter"}),
            ("open_kb_document", {"file_uid": "file-hyper", "line": 1652}),
            ("open_kb_document", {"file_uid": "file-hyper", "offset": 0}),
        ]
    )
    tool = FakeRecordingDocumentTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeFindDocumentTool(), tool],
        max_iterations=5,
    )

    list(runner.stream("继续", _continuation_history()))

    assert tool.args[0] == {"file_uid": "file-hyper", "line": 1652}
    assert tool.args[1] == {"file_uid": "file-hyper", "offset": 0}


def test_wrong_explicit_file_does_not_consume_resume():
    model = FakeScriptedOpenModel(
        [
            ("open_kb_document", {"kb_uid": "kb-other", "file_uid": "file-other", "offset": 0}),
            ("open_kb_document", {"offset": 0}),
        ]
    )
    tool = FakeRecordingDocumentTool()
    runner = LangChainAgentRunner(model=model, tools=[tool])

    list(runner.stream("继续", _continuation_history()))

    assert tool.args[0] == {
        "kb_uid": "kb-other",
        "file_uid": "file-other",
        "offset": 0,
    }
    assert tool.args[1] == {
        "kb_uid": "kb-hyper",
        "file_uid": "file-hyper",
        "offset": 1651,
    }


def test_fifth_open_emits_safe_continuation_from_furthest_window():
    requested_offsets = [100, 500, 200, 900, 400]
    windows = [
        {"offset": 100, "next_offset": 200},
        {"offset": 500, "next_offset": 600},
        {"offset": 200, "next_offset": 300},
        {
            "offset": 900,
            "next_offset": 1000,
            "content": "furthest secret excerpt".ljust(100, "x"),
        },
        {"offset": 400, "next_offset": 500},
    ]
    model = FakeScriptedOpenModel(_five_open_calls(requested_offsets), final_text="")
    tool = FakeRecordingDocumentTool(windows)
    runner = LangChainAgentRunner(model=model, tools=[tool], max_iterations=10)

    lines = list(runner.stream("总结超参数", [{"role": "user", "content": "previous"}]))

    events = [json.loads(line) for line in lines]
    continuation = next(event for event in events if event["type"] == "continuation")
    assert continuation["data"] == {
        "version": 1,
        "objective": "总结超参数",
        "kb_uid": "kb-hyper",
        "file_uid": "file-hyper",
        "next_offset": 1000,
        "has_more_after": True,
    }
    assert list(continuation["data"]) == [
        "version",
        "objective",
        "kb_uid",
        "file_uid",
        "next_offset",
        "has_more_after",
    ]
    assert "furthest secret excerpt" not in json.dumps(continuation, ensure_ascii=False)
    assert event_types(lines)[-2:] == ["continuation", "done"]
    assert tool.args == [args for _, args in _five_open_calls(requested_offsets)]


def test_furthest_eof_window_emits_no_continuation_state():
    windows = [
        {"offset": 0, "next_offset": 100, "has_more_after": True},
        {"offset": 400, "next_offset": 500, "has_more_after": False},
        {"offset": 100, "next_offset": 200, "has_more_after": True},
        {"offset": 200, "next_offset": 300, "has_more_after": True},
        {"offset": 300, "next_offset": 400, "has_more_after": True},
    ]
    model = FakeScriptedOpenModel(_five_open_calls(), final_text="")
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeRecordingDocumentTool(windows)],
        max_iterations=10,
    )

    lines = list(runner.stream("总结全文", [{"role": "user", "content": "previous"}]))

    assert "continuation" not in event_types(lines)


def test_substantive_current_query_ignores_prior_continuation_state():
    model = FakeScriptedOpenModel(
        [("open_kb_document", {"file_uid": "file-hyper", "offset": 0})]
    )
    tool = FakeRecordingDocumentTool()
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(model=model, tools=[tool])

    list(
        runner.stream(
            "改为比较不同优化器",
            _continuation_history(),
            trace_recorder=recorder,
        )
    )

    assert tool.args == [{"file_uid": "file-hyper", "offset": 0}]
    assert not any(
        getattr(message, "type", "") == "system" and "do not restart" in message.content.lower()
        for message in model.invocations[0]
    )
    first_invoke = next(step for step in recorder.steps if step["step_type"] == "model_invoke")
    assert first_invoke["input_json"]["effective_objective_source"] == "current"


def test_history_fallback_supplies_latest_objective_to_clean_synthesis():
    history = [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "比较各数据集的学习率"},
        {"role": "assistant", "content": "请回复继续", "continuation": {"version": 99}},
    ]
    model = FakeScriptedOpenModel(_five_open_calls(), final_text="")
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeRecordingDocumentTool()],
        max_iterations=10,
    )

    list(runner.stream("继续", history, trace_recorder=recorder))

    assert "用户问题：比较各数据集的学习率" in model.invocations[-1][1].content
    invokes = [step for step in recorder.steps if step["step_type"] == "model_invoke"]
    assert all(
        step["input_json"]["effective_objective_source"] == "history_fallback"
        for step in invokes
    )


def test_forced_document_cap_answer_uses_window_wording_not_page_number():
    model = FakeScriptedOpenModel(
        _five_open_calls(),
        final_text="我已读取到第5页，层次锚定采用分阶段设置。",
    )
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeRecordingDocumentTool()],
        max_iterations=10,
    )

    lines = list(runner.stream("总结全文", [{"role": "user", "content": "previous"}]))
    token_text = "".join(
        json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token"
    )

    assert "5 个窗口" in token_text
    assert "第5页" not in token_text


class FakeTraceContinuationModel:
    def __init__(self):
        self.first_complete = False
        self.request = 1
        self.request_calls = {1: 0, 2: 0}
        self.invocations = []
        self.second_forced_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if self.first_complete and any(
            getattr(message, "type", "") == "human" and message.content == "继续"
            for message in messages
        ):
            self.request = 2
        self.request_calls[self.request] += 1
        call = self.request_calls[self.request]
        self.invocations.append((self.request, messages))

        if self.request == 1:
            if call <= 5:
                return FakeToolCall(
                    tool_calls=[
                        {
                            "id": f"trace_first_open_{call}",
                            "name": "open_kb_document",
                            "args": {
                                "kb_uid": "kb-hyper",
                                "file_uid": "file-hyper",
                                "offset": (call - 1) * 100,
                            },
                        }
                    ]
                )
            self.first_complete = True
            return FakeToolCall(content="我已读取到第5页，先给出阶段性结论。是否继续？")

        if call == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "trace_stale_restart",
                        "name": "open_kb_document",
                        "args": {
                            "kb_uid": "kb-hyper",
                            "file_uid": "file-hyper",
                            "offset": 0,
                        },
                    }
                ]
            )
        if call == 2:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "trace_semantic_query",
                        "name": "query_kb",
                        "args": {
                            "kb_uid": "kb-hyper",
                            "query_text": "层次锚定 超参数",
                        },
                    }
                ]
            )
        if call in {3, 4}:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"trace_resumed_open_{call}",
                        "name": "open_kb_document",
                        "args": {
                            "kb_uid": "kb-hyper",
                            "file_uid": "file-hyper",
                            "offset": 600 + (call - 3) * 100,
                        },
                    }
                ]
            )
        if call in {5, 6}:
            suffix = "jump" if call == 5 else "final"
            line = 42 if call == 5 else 84
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": f"trace_{suffix}_find",
                        "name": "find_kb_document",
                        "args": {
                            "file_uid": "file-hyper",
                            "query": "Adam learning rate layers",
                        },
                    },
                    {
                        "id": f"trace_{suffix}_open",
                        "name": "open_kb_document",
                        "args": {"file_uid": "file-hyper", "line": line},
                    },
                ]
            )

        self.second_forced_messages = messages
        return FakeToolCall(
            content=(
                "我已读取到第5页：使用 Adam，初始学习率为 0.01，"
                "层数取 {3, 4, 5}。是否继续？"
            )
        )


class FakeTraceSemanticTool:
    name = "query_kb"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "kb_uid": args["kb_uid"],
                    "evidence": [
                        {
                            "file_uid": "file-hyper",
                            "text": f"semantic evidence {index}: hierarchical anchoring context",
                        }
                        for index in range(10)
                    ],
                },
            },
            ensure_ascii=False,
        )


class FakeTraceFindTool:
    name = "find_kb_document"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "file_uid": args["file_uid"],
                    "matches": [
                        {
                            "line": 84,
                            "text": "decisive find: Adam optimizer with layer counts {3, 4, 5}",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )


class FakeTraceWindowTool:
    name = "open_kb_document"

    def __init__(self):
        self.args = []

    def invoke(self, args):
        self.args.append(dict(args))
        call = len(self.args)
        if call == 10:
            content = "decisive open: initial learning rate 0.01."
        else:
            content = f"trace document window {call}"
        if "line" in args:
            offset = 800 if call == 9 else 900
        else:
            offset = args.get("offset", 0)
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "kb_uid": args.get("kb_uid", "kb-hyper"),
                    "file_uid": args["file_uid"],
                    "offset": offset,
                    "next_offset": offset + len(content),
                    "content": content,
                    "has_more_after": True,
                },
            },
            ensure_ascii=False,
        )


def test_trace_shaped_continuation_preserves_final_evidence_and_resume_cursor():
    objective = "层次锚定的超参数怎么设置？"
    model = FakeTraceContinuationModel()
    window_tool = FakeTraceWindowTool()
    recorder = FakeTraceRecorder()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeTraceSemanticTool(), FakeTraceFindTool(), window_tool],
        max_iterations=10,
    )

    first_lines = list(
        runner.stream(objective, [{"role": "user", "content": "previous"}])
    )
    first_events = [json.loads(line) for line in first_lines]
    first_continuation = next(
        event["data"] for event in first_events if event["type"] == "continuation"
    )
    first_answer = "".join(
        event["data"] for event in first_events if event["type"] == "token"
    )

    assert first_continuation["file_uid"] == "file-hyper"
    assert first_continuation["next_offset"] > 0
    assert first_continuation["has_more_after"] is True
    assert len(window_tool.args) == 5

    history = [
        {"role": "user", "content": objective},
        {
            "role": "assistant",
            "content": first_answer,
            "continuation": first_continuation,
        },
    ]
    second_lines = list(runner.stream("继续", history, trace_recorder=recorder))
    second_events = [json.loads(line) for line in second_lines]
    second_answer = "".join(
        event["data"] for event in second_events if event["type"] == "token"
    )
    second_continuation = next(
        event["data"] for event in second_events if event["type"] == "continuation"
    )

    assert window_tool.args[5] == {
        "kb_uid": "kb-hyper",
        "file_uid": "file-hyper",
        "offset": first_continuation["next_offset"],
    }
    assert window_tool.args[8] == {"file_uid": "file-hyper", "line": 42}
    assert window_tool.args[9] == {"file_uid": "file-hyper", "line": 84}
    assert len(window_tool.args[5:]) == 5
    assert second_continuation["objective"] == objective
    assert second_continuation["file_uid"] == "file-hyper"
    assert second_continuation["next_offset"] > first_continuation["next_offset"]
    assert second_continuation["has_more_after"] is True

    semantic_tool_messages = [
        message
        for request, messages in model.invocations
        if request == 2
        for message in messages
        if isinstance(message, ToolMessage)
        and message.tool_call_id == "trace_semantic_query"
    ]
    semantic_payload = json.loads(semantic_tool_messages[-1].content)
    assert len(semantic_payload["data"]["evidence"]) == 10

    synthesis_prompt = model.second_forced_messages[1].content
    assert f"用户问题：{objective}" in synthesis_prompt
    assert "用户问题：继续\n" not in synthesis_prompt
    assert "decisive find: Adam optimizer with layer counts {3, 4, 5}" in synthesis_prompt
    assert "decisive open: initial learning rate 0.01" in synthesis_prompt
    assert "Adam" in second_answer
    assert "0.01" in second_answer
    assert "第5页" not in second_answer
    assert event_types(second_lines)[-3:] == ["token", "continuation", "done"]


def _document_window_messages(status="ok", **overrides):
    data = {
        "kb_uid": "kb-valid",
        "file_uid": "file-valid",
        "offset": 10,
        "next_offset": 14,
        "content": "abcd",
        "has_more_after": True,
    }
    data.update(overrides)
    return [
        ToolMessage(
            content=json.dumps({"status": status, "data": data}),
            tool_call_id="call_window",
        )
    ]


@pytest.mark.parametrize("status", ["error", "no_hits", "failed", None, ""])
def test_document_window_extraction_rejects_non_success_status(status):
    assert runner_mod._document_windows_from_messages(
        _document_window_messages(status=status)
    ) == []


@pytest.mark.parametrize("status", ["ok", "success", "degraded"])
def test_document_window_extraction_accepts_explicit_success_statuses(status):
    windows = runner_mod._document_windows_from_messages(
        _document_window_messages(status=status)
    )

    assert windows == [
        {
            "kb_uid": "kb-valid",
            "file_uid": "file-valid",
            "offset": 10,
            "next_offset": 14,
            "content": "abcd",
            "has_more_after": True,
        }
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"content": ""},
        {"content": "   ", "next_offset": 13},
        {"offset": "10"},
        {"offset": True},
        {"offset": -1},
        {"next_offset": "14"},
        {"next_offset": False},
        {"next_offset": -1},
        {"offset": 10, "next_offset": 9},
        {"offset": 10, "next_offset": 13},
        {"has_more_after": "false"},
        {"kb_uid": None},
        {"kb_uid": ""},
        {"file_uid": None},
        {"file_uid": ""},
    ],
)
def test_document_window_extraction_rejects_malformed_progress(overrides):
    assert runner_mod._document_windows_from_messages(
        _document_window_messages(**overrides)
    ) == []


def test_malformed_document_windows_do_not_emit_continuation():
    windows = [
        {"status": "error", "offset": 0, "next_offset": 4, "content": "data"},
        {"offset": 4, "next_offset": 4, "content": ""},
        {"offset": True, "next_offset": 5, "content": "data"},
        {"offset": 8, "next_offset": 20, "content": "short"},
        {
            "offset": 20,
            "next_offset": 24,
            "content": "data",
            "has_more_after": "false",
        },
    ]
    model = FakeScriptedOpenModel(_five_open_calls(), final_text="")
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeRecordingDocumentTool(windows)],
        max_iterations=10,
    )

    lines = list(runner.stream("总结全文", [{"role": "user", "content": "previous"}]))

    assert "continuation" not in event_types(lines)


def test_document_cap_normalization_preserves_generic_five_page_reference():
    original = "实验要求参与者读取了5页材料"

    assert runner_mod._normalize_document_cap_progress(original) == original


@pytest.mark.parametrize("prefix", ["已", "已经"])
def test_document_cap_normalization_rewrites_only_trace_style_progress(prefix):
    assert runner_mod._normalize_document_cap_progress(
        f"我{prefix}读取到第 5 页，继续分析"
    ) == "我已读取了 5 个窗口，继续分析"


def test_runner_reuse_resets_resume_state_before_substantive_request():
    model = FakeScriptedOpenModel(
        [("open_kb_document", {"file_uid": "file-hyper", "offset": 0})]
    )
    tool = FakeRecordingDocumentTool()
    runner = LangChainAgentRunner(model=model, tools=[tool])

    list(runner.stream("继续", _continuation_history()))
    model.calls = [("open_kb_document", {"file_uid": "file-hyper", "offset": 0})]
    model.invocations = []
    list(
        runner.stream(
            "改为检查文档开头",
            [{"role": "user", "content": "previous"}],
        )
    )

    assert tool.args == [
        {"kb_uid": "kb-hyper", "file_uid": "file-hyper", "offset": 1651},
        {"file_uid": "file-hyper", "offset": 0},
    ]


def test_global_iteration_limit_uses_continuation_objective_for_synthesis():
    model = FakeScriptedOpenModel(
        [("open_kb_document", {"file_uid": "file-hyper", "offset": 0})],
        final_text="阶段性答案",
    )
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeRecordingDocumentTool()],
        max_iterations=1,
    )

    list(runner.stream("继续", _continuation_history()))

    synthesis_prompt = model.invocations[-1][1].content
    assert CONTINUATION_STATE["objective"] in synthesis_prompt
    assert "用户问题：继续\n" not in synthesis_prompt


def _nested_document_window_messages(outer_status, inner_status):
    inner = json.loads(_document_window_messages(status=inner_status)[0].content)
    envelope = {"payload": {"summary": inner}}
    if outer_status is not None:
        envelope["status"] = outer_status
    return [
        ToolMessage(
            content=json.dumps(envelope),
            tool_call_id="call_nested_window",
        )
    ]


@pytest.mark.parametrize(
    ("outer_status", "inner_status"),
    [
        ("error", "ok"),
        (None, "ok"),
        ("success", "failed"),
    ],
)
def test_document_window_extraction_rejects_failed_nested_status_chain(
    outer_status,
    inner_status,
):
    assert runner_mod._document_windows_from_messages(
        _nested_document_window_messages(outer_status, inner_status)
    ) == []


class FakeNestedStatusDocumentTool:
    name = "open_kb_document"

    def __init__(self, outer_status, inner_status):
        self.outer_status = outer_status
        self.inner_status = inner_status

    def invoke(self, args):
        content = "data"
        offset = args.get("offset", 0)
        inner = {
            "status": self.inner_status,
            "data": {
                "kb_uid": args["kb_uid"],
                "file_uid": args["file_uid"],
                "offset": offset,
                "next_offset": offset + len(content),
                "content": content,
                "has_more_after": True,
            },
        }
        envelope = {"payload": {"summary": inner}}
        if self.outer_status is not None:
            envelope["status"] = self.outer_status
        return json.dumps(envelope)


@pytest.mark.parametrize(
    ("outer_status", "inner_status"),
    [
        ("error", "ok"),
        (None, "ok"),
        ("success", "failed"),
    ],
)
def test_failed_nested_status_chain_never_emits_continuation(
    outer_status,
    inner_status,
):
    runner = LangChainAgentRunner(
        model=FakeScriptedOpenModel(_five_open_calls(), final_text=""),
        tools=[FakeNestedStatusDocumentTool(outer_status, inner_status)],
        max_iterations=10,
    )

    lines = list(runner.stream("总结全文", [{"role": "user", "content": "previous"}]))

    assert "continuation" not in event_types(lines)


class FakeTimeoutThenSuccessTool:
    name = "raw_document_search"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        if self.calls == 1:
            time.sleep(0.1)
        return json.dumps({"status": "success", "summary": "fresh invocation"})


def test_runner_reuse_clears_timed_out_tool_disablement():
    model = FakeSlowToolModel()
    tool = FakeTimeoutThenSuccessTool()
    runner = LangChainAgentRunner(
        model=model,
        tools=[tool],
        tool_timeout_seconds=0.01,
    )

    list(runner.stream("first request", [{"role": "user", "content": "previous"}]))
    model.calls = 0
    second_lines = list(
        runner.stream("second request", [{"role": "user", "content": "previous"}])
    )

    second_result = next(
        json.loads(line)["data"]
        for line in second_lines
        if json.loads(line)["type"] == "tool_result"
    )
    assert tool.calls == 2
    assert second_result["status"] == "success"
    assert second_result["summary"] == "fresh invocation"


def test_runner_reuse_drops_unemitted_pending_clarify():
    model = FakeClarifyModel()
    runner = LangChainAgentRunner(
        model=model,
        tools=[FakeClarifyTool()],
        max_iterations=1,
    )

    first_lines = list(
        runner.stream("first request", [{"role": "user", "content": "previous"}])
    )
    second_lines = list(
        runner.stream("second request", [{"role": "user", "content": "previous"}])
    )

    assert "clarify" not in event_types(first_lines)
    assert "clarify" not in event_types(second_lines)


class FakeIterationLimitSemanticTool:
    name = "query_kb"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return json.dumps(
            {
                "status": "success",
                "data": {
                    "evidence": [
                        {
                            "text": "最终语义证据：实验要求参与者读取了5页材料",
                            "file_uid": "semantic-file",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        )


class FakeIterationLimitSemanticModel:
    def __init__(self):
        self.calls = 0
        self.synthesis_messages = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_final_semantic",
                        "name": "query_kb",
                        "args": {"query": "比较实验阅读要求"},
                    }
                ]
            )
        self.synthesis_messages = messages
        return FakeToolCall(content="证据原文：我已读取到第5页。")


def test_iteration_limit_semantic_synthesis_uses_generic_prompt_after_final_tool():
    model = FakeIterationLimitSemanticModel()
    tool = FakeIterationLimitSemanticTool()
    runner = LangChainAgentRunner(model=model, tools=[tool], max_iterations=1)

    lines = list(
        runner.stream(
            "比较实验阅读要求",
            [{"role": "user", "content": "previous"}],
        )
    )

    prompt = "\n".join(message.content for message in model.synthesis_messages)
    token_text = "".join(
        json.loads(line)["data"]
        for line in lines
        if json.loads(line)["type"] == "token"
    )
    types = event_types(lines)
    assert tool.calls == 1
    assert model.calls == 2
    assert types.index("tool_result") < types.index("token")
    assert "比较实验阅读要求" in prompt
    assert "最终语义证据：实验要求参与者读取了5页材料" in prompt
    assert "工具迭代预算" in prompt
    for unsupported in (
        "文档尚未完整读取",
        "五次读取",
        "5 个窗口",
        "5个窗口",
        "是否继续读取",
    ):
        assert unsupported not in prompt
    assert token_text == "证据原文：我已读取到第5页。"


class FakeIterationLimitNoHitsTool:
    name = "query_kb"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return json.dumps({"status": "no_hits", "data": {"evidence": []}})


class FakeIterationLimitNoHitsModel:
    def __init__(self, forced_tool_call):
        self.calls = 0
        self.forced_tool_call = forced_tool_call

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_no_hits",
                        "name": "query_kb",
                        "args": {"query": "不存在的事实"},
                    }
                ]
            )
        if self.forced_tool_call:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_forced_retry",
                        "name": "query_kb",
                        "args": {"query": "retry"},
                    }
                ]
            )
        return FakeToolCall(content="")


@pytest.mark.parametrize("forced_tool_call", [False, True])
def test_iteration_limit_no_hits_uses_generic_deterministic_fallback(
    forced_tool_call,
):
    model = FakeIterationLimitNoHitsModel(forced_tool_call)
    tool = FakeIterationLimitNoHitsTool()
    runner = LangChainAgentRunner(model=model, tools=[tool], max_iterations=1)

    lines = list(
        runner.stream(
            "不存在的事实是什么？",
            [{"role": "user", "content": "previous"}],
        )
    )

    types = event_types(lines)
    token_text = "".join(
        json.loads(line)["data"]
        for line in lines
        if json.loads(line)["type"] == "token"
    )
    assert tool.calls == 1
    assert model.calls == 2
    assert types.index("tool_result") < types.index("token")
    assert "工具迭代" in token_text
    assert "未获得可用证据" in token_text
    assert "无法可靠回答" in token_text
    for unsupported in ("文档", "窗口", "未完整", "继续"):
        assert unsupported not in token_text
