import json
import logging
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_answer_import.db")

from engine.app.chat import answer


def test_knowledge_retrieval_service_passes_explicit_top_k_override(monkeypatch):
    class Topic:
        active_index_generation = "index-1"
        active_graph_generation = None

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return Topic()

    class DB:
        def query(self, model):
            return Query()

    captured = {}

    def fake_execute(request, scope):
        captured["request"] = request
        return type("Response", (), {"model_dump": lambda self: {"status": "no_hits"}})()

    monkeypatch.setattr(answer, "execute_retrieval", fake_execute)

    answer._KnowledgeRetrievalService(DB()).query(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        query="all papers",
        top_k=37,
    )

    assert captured["request"].config.top_k == 37


def test_knowledge_retrieval_service_deep_mode_uses_depth_controls(monkeypatch):
    class Topic:
        active_index_generation = "index-1"
        active_graph_generation = "graph-1"

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return Topic()

    class DB:
        def query(self, model):
            return Query()

    captured = {}

    class FakeAgenticResult:
        status = "sufficient"
        evidence = [{
            "file_uid": "file-a",
            "chunk_id": "chunk-a",
            "text": "grounded text",
            "channels": {"graph": {"raw_score": 1.0, "raw_rank": 1}},
        }]
        iterations = 5

    class FakeRunner:
        def __init__(self, **kwargs):
            captured["config"] = kwargs["config"]

        def run(self, query):
            captured["query"] = query
            return FakeAgenticResult()

    monkeypatch.setattr(answer, "AgenticRagRunner", FakeRunner)
    monkeypatch.setattr(answer, "make_unified_search", lambda **_kwargs: lambda *_args, **_kw: [])
    monkeypatch.setattr(answer, "_load_chunks", lambda *_args, **_kwargs: {})

    result = answer._KnowledgeRetrievalService(DB()).query(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        query="all papers",
        mode="deep",
        top_k=12,
        depth="deep",
        max_iterations=10,
    )

    assert result["status"] == "ok"
    assert result["retrieval_health"]["agentic"]["iterations"] == 5
    config = captured["config"]
    assert (config.mode, config.top_k, config.graph_hops, config.max_iterations) == (
        "deep",
        12,
        3,
        5,
    )


def test_load_chunks_resolves_public_chunk_uid_not_internal_id(monkeypatch):
    class Chunk:
        id = "internal-row-id"; chunk_uid = "public-chunk-uid"; parent_id = None
        item_id = "item-1"; chunk_text = "public text"
    class Query:
        def __init__(self, model): self.model = model
        def filter(self, *args): return self
        def all(self):
            name = getattr(self.model, "__name__", "")
            if name == "KnowledgeChunk": return [Chunk()]
            return []
    class DB:
        def query(self, model, *rest): return Query(model)
        def close(self): pass
    monkeypatch.setattr(answer, "_Session", lambda: DB())
    result = answer._load_chunks(["public-chunk-uid"])
    assert result["public-chunk-uid"]["text"] == "public text"
    assert "internal-row-id" not in result


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
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

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
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

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


def test_answer_stream_injects_resources_for_authorized_knowledge_scope(monkeypatch):
    class Scope:
        allowed_kb_uids = ("kb-a",)

    class DB:
        closed = False

        def close(self):
            self.closed = True

    db = DB()
    captured = {}

    monkeypatch.setattr(answer, "_Session", lambda: db)
    monkeypatch.setattr(
        answer,
        "build_agent_runner",
        lambda **kwargs: captured.update(kwargs) or FakeRunner(),
    )

    list(answer.answer_stream("hello", [], knowledge_scope=Scope()))

    assert captured["knowledge_scope"].allowed_kb_uids == ("kb-a",)
    assert captured["db_session"] is db
    assert captured["retrieval_service"] is not None
    assert db.closed is True


def test_answer_stream_forwards_explicit_rag_controls(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        answer,
        "build_agent_runner",
        lambda **kwargs: captured.update(kwargs) or FakeRunner(),
    )
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    list(
        answer.answer_stream(
            "hello",
            [],
            deep_search_enabled=True,
            deep_search_top_k=17,
            graph_hops=3,
            rag_max_iterations=4,
        )
    )

    assert captured["deep_search_top_k"] == 17
    assert captured["graph_hops"] == 3
    assert captured["rag_max_iterations"] == 4


def test_answer_stream_continues_when_trace_start_returns_none(monkeypatch):
    FakeTraceRecorder.instances = []
    runner = CapturingRunner()
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: runner)
    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeTraceRecorder)
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

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
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    lines = list(answer.answer_stream("hello", []))

    assert [json.loads(line)["type"] for line in lines] == ["agent_status", "done"]
    assert runner.trace_recorder is None


def test_answer_stream_returns_needs_kb_selection_for_knowledge_intent_without_scope(monkeypatch):
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {
            "groups": ["knowledge"],
            "kb_specs": [],
            "reasoning": "用户要求总结上传资料，需要知识库。",
        },
    )

    def fail_build_agent_runner(**kwargs):
        raise AssertionError("runner should not be built when KB selection is required")

    monkeypatch.setattr(answer, "build_agent_runner", fail_build_agent_runner)

    events = list(answer.answer_stream("总结上传资料的核心观点", history=[]))

    assert len(events) == 1
    assert '"type": "needs_kb_selection"' in events[0]
    assert "总结上传资料的核心观点" in events[0]


def test_answer_stream_does_not_request_kb_selection_for_non_knowledge_intent(monkeypatch):
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    class FakeRunner:
        def stream(self, query, history, trace_recorder=None):
            yield '{"type":"delta","data":"你好"}\n'

    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer.AgentTraceRecorder, "start", lambda self: None)

    events = list(answer.answer_stream("你好", history=[]))

    assert not any("needs_kb_selection" in event for event in events)


def test_answer_stream_keeps_legacy_topic_fallback_for_knowledge_intent(monkeypatch):
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": ["knowledge"], "kb_specs": [], "reasoning": "知识库问题"},
    )

    class FakeRunner:
        def stream(self, query, history, trace_recorder=None):
            yield '{"type":"delta","data":"ok"}\n'

    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer.AgentTraceRecorder, "start", lambda self: None)
    monkeypatch.setattr(answer, "_resolve_scope_for_topic", lambda topic_id: None)

    events = list(answer.answer_stream("总结资料", history=[], topic_id="legacy-topic"))

    assert not any("needs_kb_selection" in event for event in events)


def test_build_agent_runner_enables_deep_search_tool_when_requested(monkeypatch):
    class FakeModel:
        pass

    captured = {}

    def fake_build_enabled_tools(ctx, overrides=None):
        captured["overrides"] = overrides
        return []

    monkeypatch.setattr(answer, "_resolve_search_scope", lambda topic_id, source_types=None: None)
    monkeypatch.setattr(answer, "build_enabled_tools", fake_build_enabled_tools)
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())

    runner = answer.build_agent_runner(deep_search_enabled=True, deep_search_depth="deep")

    assert captured["overrides"]["deep_knowledge_search"] is True
    assert runner.system_prompt.endswith("deep_knowledge_search。")


def test_build_agent_runner_does_not_advertise_deep_search_when_disabled(monkeypatch):
    class FakeModel:
        pass

    monkeypatch.setattr(answer, "_resolve_search_scope", lambda topic_id, source_types=None: None)
    monkeypatch.setattr(answer, "build_enabled_tools", lambda ctx, overrides=None: [])
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())

    runner = answer.build_agent_runner(deep_search_enabled=False)

    assert "deep_knowledge_search" not in runner.system_prompt


def test_build_agent_runner_places_chat_controls_on_rag_runner(monkeypatch):
    captured = {}

    def fake_rag_runner(**kwargs):
        captured["config"] = kwargs["config"]
        return object()

    monkeypatch.setattr(answer, "_resolve_search_scope", lambda *args: None)
    monkeypatch.setattr(answer, "AgenticRagRunner", fake_rag_runner)
    monkeypatch.setattr(answer, "build_enabled_tools", lambda ctx, overrides=None: [])
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: object())

    answer.build_agent_runner(
        deep_search_enabled=True,
        deep_search_top_k=19,
        graph_hops=3,
        rag_max_iterations=4,
    )

    config = captured["config"]
    assert (config.mode, config.top_k, config.graph_hops, config.max_iterations) == (
        "deep",
        19,
        3,
        4,
    )


def test_build_agent_runner_adds_memory_search_to_authorized_knowledge_scope(monkeypatch):
    from engine.app.security.knowledge_scope import AuthorizedKnowledgeScope

    class FakeModel:
        pass

    class FakeTool:
        def __init__(self, name):
            self.name = name

    monkeypatch.setattr(answer, "_resolve_search_scope", lambda *args: None)
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())
    monkeypatch.setattr(
        answer,
        "build_knowledge_tools",
        lambda ctx: {"query_kb": FakeTool("query_kb")},
    )
    monkeypatch.setitem(
        answer.BUILTIN_REGISTRY,
        "clarify_user",
        type("Spec", (), {"builder": staticmethod(lambda ctx: FakeTool("clarify_user"))})(),
    )
    monkeypatch.setitem(
        answer.BUILTIN_REGISTRY,
        "datetime",
        type("Spec", (), {"builder": staticmethod(lambda ctx: FakeTool("datetime"))})(),
    )
    monkeypatch.setitem(
        answer.BUILTIN_REGISTRY,
        "memory_search",
        type("Spec", (), {"builder": staticmethod(lambda ctx: FakeTool("memory_search"))})(),
    )

    runner = answer.build_agent_runner(
        knowledge_scope=AuthorizedKnowledgeScope(
            actor_id="alice",
            tenant_id="tenant-a",
            allowed_kb_uids=("kb-a",),
            run_id="run-1",
            expires_at=9999999999,
        )
    )

    assert [tool.name for tool in runner.tools] == [
        "query_kb",
        "clarify_user",
        "datetime",
        "memory_search",
    ]


def test_build_agent_runner_applies_iteration_limit_to_authorized_knowledge_scope(monkeypatch):
    from engine.app.security.knowledge_scope import AuthorizedKnowledgeScope

    class FakeModel:
        pass

    monkeypatch.setattr(answer, "_resolve_search_scope", lambda *args: None)
    monkeypatch.setattr(answer, "create_chat_model", lambda settings: FakeModel())
    monkeypatch.setattr(answer, "build_knowledge_tools", lambda ctx: {})

    runner = answer.build_agent_runner(
        rag_max_iterations=9,
        knowledge_scope=AuthorizedKnowledgeScope(
            actor_id="alice",
            tenant_id="tenant-a",
            allowed_kb_uids=("kb-a",),
            run_id="run-1",
            expires_at=9999999999,
        ),
    )

    assert runner.max_iterations == 9


def test_answer_stream_logs_request_lifecycle(monkeypatch, caplog):
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

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
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    lines = list(answer.answer_stream("hello", []))

    assert json.loads(lines[0]) == {"type": "error", "data": "no model"}


def test_answer_stream_logs_runner_build_error(monkeypatch, caplog):
    def fail(**kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(answer, "build_agent_runner", fail)
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

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
