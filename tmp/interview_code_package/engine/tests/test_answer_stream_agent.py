import json
import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_answer_import.db")

from engine.app.chat import answer


class FakeRunner:
    def stream(self, query, history, trace_recorder=None):
        yield json.dumps({"type": "agent_status", "data": {"label": query}}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


class CapturingRunner:
    def __init__(self):
        self.trace_recorder = "unset"

    def stream(self, query, history, trace_recorder=None):
        self.trace_recorder = trace_recorder
        yield json.dumps({"type": "agent_status", "data": {"label": query}}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


class FakeTraceRecorder:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeTraceRecorder.instances.append(self)

    def start(self):
        return None


def test_answer_stream_delegates_to_agent_runner(monkeypatch):
    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRunner()

    monkeypatch.setattr(answer, "build_agent_runner", build)

    lines = list(answer.answer_stream("hello", [{"role": "user", "content": "old"}]))

    parsed = [json.loads(line) for line in lines]
    if parsed[0]["type"] == "trace":
        parsed = parsed[1:]

    assert parsed[0] == {"type": "agent_status", "data": {"label": "hello"}}
    assert parsed[1] == {"type": "done"}
    assert captured["deep_search_enabled"] is False
    assert captured["deep_search_depth"] == "standard"


def test_answer_stream_forwards_deep_search_options(monkeypatch):
    captured = {}

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRunner()

    monkeypatch.setattr(answer, "build_agent_runner", build)

    list(
        answer.answer_stream(
            "hello",
            [],
            deep_search_enabled=True,
            deep_search_depth="deep",
        )
    )

    assert captured["deep_search_enabled"] is True
    assert captured["deep_search_depth"] == "deep"


def test_answer_stream_continues_when_trace_start_returns_none(monkeypatch):
    FakeTraceRecorder.instances = []
    runner = CapturingRunner()
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: runner)
    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeTraceRecorder)

    lines = list(
        answer.answer_stream(
            "hello",
            [],
            session_id="session-1",
            user_message_id="message-1",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["agent_status", "done"]
    assert runner.trace_recorder is None
    assert FakeTraceRecorder.instances[0].kwargs["session_id"] == "session-1"
    assert FakeTraceRecorder.instances[0].kwargs["user_message_id"] == "message-1"


def test_answer_stream_continues_when_trace_start_raises(monkeypatch):
    class RaisingTraceRecorder(FakeTraceRecorder):
        def start(self):
            raise RuntimeError("trace unavailable")

    runner = CapturingRunner()
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: runner)
    monkeypatch.setattr(answer, "AgentTraceRecorder", RaisingTraceRecorder)

    lines = list(answer.answer_stream("hello", []))

    assert [json.loads(line)["type"] for line in lines] == ["agent_status", "done"]
    assert runner.trace_recorder is None


def test_build_agent_runner_enables_deep_search_tool_when_requested(monkeypatch):
    class FakeModel:
        pass

    captured = {}

    def fake_build_enabled_tools(ctx, overrides=None):
        captured["overrides"] = overrides
        return []

    monkeypatch.setattr(answer, "_resolve_allowed_item_ids", lambda topic_id: None)
    monkeypatch.setattr(answer, "build_enabled_tools", fake_build_enabled_tools)
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())

    runner = answer.build_agent_runner(deep_search_enabled=True, deep_search_depth="deep")

    assert captured["overrides"]["deep_knowledge_search"] is True
    assert runner.system_prompt.endswith("deep_knowledge_search。")


def test_build_agent_runner_does_not_advertise_deep_search_when_disabled(monkeypatch):
    class FakeModel:
        pass

    monkeypatch.setattr(answer, "_resolve_allowed_item_ids", lambda topic_id: None)
    monkeypatch.setattr(answer, "build_enabled_tools", lambda ctx, overrides=None: [])
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())

    runner = answer.build_agent_runner(deep_search_enabled=False)

    assert "deep_knowledge_search" not in runner.system_prompt


def test_answer_stream_logs_request_lifecycle(monkeypatch, caplog):
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        list(answer.answer_stream("hello", [{"role": "user", "content": "old"}]))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "[chat] request_start" in message
        and 'query="hello"' in message
        and "history_messages=1" in message
        for message in messages
    )
    assert any("[chat] runner_ready" in message for message in messages)
    assert any("[chat] stream_complete" in message for message in messages)


def test_answer_stream_emits_error_when_runner_build_fails(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(answer, "build_agent_runner", fail)

    lines = list(answer.answer_stream("hello", []))

    assert json.loads(lines[0]) == {"type": "error", "data": "no model"}


def test_answer_stream_logs_runner_build_error(monkeypatch, caplog):
    def fail(**kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(answer, "build_agent_runner", fail)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        list(answer.answer_stream("hello", []))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "[chat] request_error" in message and 'error="no model"' in message
        for message in messages
    )


def test_judge_rag_treats_sufficient_without_answer_basis_as_malformed(
    monkeypatch,
):
    monkeypatch.setattr(answer, "chat", lambda messages: '{"status":"sufficient"}')

    result = answer._judge_rag("q", "q", [], [])

    assert result.status == "insufficient"
    assert result.missing == [
        "The evidence judge returned malformed sufficient JSON."
    ]


def test_judge_rag_treats_invalid_json_as_insufficient(monkeypatch):
    monkeypatch.setattr(answer, "chat", lambda messages: "not json")

    result = answer._judge_rag("q", "q", [], [])

    assert result.status == "insufficient"
    assert "The evidence judge returned invalid JSON." in result.missing


def test_judge_rag_accepts_valid_sufficient_output(monkeypatch):
    monkeypatch.setattr(
        answer,
        "chat",
        lambda messages: json.dumps(
            {
                "status": "sufficient",
                "answer_basis": "The retrieved notes answer the question.",
                "useful_chunk_ids": ["chunk-1"],
            }
        ),
    )

    result = answer._judge_rag("q", "q", [], [])

    assert result.status == "sufficient"
    assert result.answer_basis == "The retrieved notes answer the question."
    assert result.useful_chunk_ids == ["chunk-1"]


def test_judge_rag_includes_graph_explanations_in_judge_payload(monkeypatch):
    captured = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return json.dumps(
            {
                "status": "sufficient",
                "answer_basis": "The inferred graph evidence is enough to answer.",
                "useful_chunk_ids": ["chunk-1"],
            }
        )

    monkeypatch.setattr(answer, "chat", fake_chat)

    result = answer._judge_rag(
        "What does MiniMind-O say?",
        "MiniMind-O",
        [
            {
                "chunk_id": "chunk-1",
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
        [],
    )

    judge_payload = json.loads(captured["messages"][1]["content"])
    assert judge_payload["graph_explanations"] == [
        "Graph inference: Connected through the MiniMind-O entity to the source chunk. Path: MiniMind-O -> MENTIONED_IN -> MiniMind-O article.",
    ]
    assert result.status == "sufficient"
