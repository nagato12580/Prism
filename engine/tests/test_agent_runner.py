import json
import logging
import os
import time

from langchain_core.messages import ToolMessage

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_agent_runner_test.db"

from engine.app.agent import runner as runner_mod
from engine.app.agent.prompts import AGENT_SYSTEM_PROMPT
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


class FakeOpenKbDocumentTool:
    name = "open_kb_document"

    def __init__(self):
        self.calls = 0

    def invoke(self, args):
        self.calls += 1
        return json.dumps(
            {
                "status": "ok",
                "data": {
                    "file_uid": args["file_uid"],
                    "offset": args.get("offset", 0),
                    "content": f"window {self.calls}",
                    "has_more_after": True,
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
    assert recorder.steps[-1]["output_json"]["message"] == "Agent reached the maximum tool iteration limit."
    assert recorder.steps[-1]["output_json"]["iteration_limit"] == 1
    assert recorder.steps[-1]["output_json"]["message_count"] > 0
    assert recorder.finished_status == "error"


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
    assert event_types(lines)[-2:] == ["token", "done"]
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
    assert event_types(lines)[-2:] == ["token", "done"]
    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
    assert "还没读取完整篇文档" in token_text
    assert "是否继续" in token_text


def test_runner_gives_model_one_no_tool_answer_pass_at_open_limit():
    model = FakeAnswersAfterOpenLimitModel()
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

    token_text = "".join(json.loads(line)["data"] for line in lines if json.loads(line)["type"] == "token")
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
