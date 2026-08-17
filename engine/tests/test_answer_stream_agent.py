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


def test_classify_intent_sends_recent_history_to_llm(monkeypatch):
    captured = {}
    history = [
        {"role": "user", "content": "我喜欢简洁的回答"},
        {"role": "assistant", "content": "我会保持简洁"},
        {"role": "tool", "content": "ignored"},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": None},
    ]

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return '{"groups": [], "kb_specs": [], "reasoning": "普通聊天"}'

    monkeypatch.setattr(answer, "chat", fake_chat)

    answer.classify_intent("根据刚才的偏好推荐", history)

    assert json.loads(captured["messages"][1]["content"]) == {
        "query": "根据刚才的偏好推荐",
        "recent_history": [
            {"role": "user", "content": "我喜欢简洁的回答"},
            {"role": "assistant", "content": "我会保持简洁"},
        ],
    }


def test_intent_classifier_prompt_guides_contextual_followups():
    assert "这些 / 它 / 它们 / 继续 / 刚才那个 / 这篇 / 上述 / 前面" in answer._INTENT_CLASSIFY_PROMPT
    assert "知识库文档、论文、上传资料、引用、表格或章节" in answer._INTENT_CLASSIFY_PROMPT
    assert "出处 / 分别 / 展开 / 继续 / 对比" in answer._INTENT_CLASSIFY_PROMPT
    assert "我的论文 / 我的项目 / 我的设定" in answer._INTENT_CLASSIFY_PROMPT


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


def test_answer_stream_uses_existing_trace_checkpoint_on_resume(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
        ],
        "tool_state": {},
    }
    calls = []

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            calls.append(("load", trace_id))
            return checkpoint

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            calls.append(("resume", loaded_checkpoint, trace_recorder))
            yield json.dumps({"type": "token", "data": "resumed"}) + "\n"
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history: {"groups": [], "kb_specs": [], "reasoning": ""},
    )

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert calls[0] == ("load", "trace-resume")
    assert calls[1][0] == "resume"
    assert json.loads(lines[0])["data"] == "resumed"


def test_answer_stream_resume_infers_tool_groups_from_checkpoint(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
            {
                "type": "ai",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-knowledge",
                        "name": "knowledge_search",
                        "args": {"query": "How?"},
                    }
                ],
            },
        ],
        "tool_state": {},
    }
    captured = {}

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRunner()

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", build)

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["done"]
    assert "knowledge" in captured["tool_groups"]
    assert captured["tool_groups"] != []


def test_answer_stream_resume_enables_deep_search_from_checkpoint(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "How?"},
            {
                "type": "ai",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-deep-knowledge",
                        "name": "deep_knowledge_search",
                        "args": {"query": "How?"},
                    }
                ],
            },
        ],
        "tool_state": {},
    }
    captured = {}

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    def build(**kwargs):
        captured.update(kwargs)
        return FakeRunner()

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", build)

    lines = list(
        answer.answer_stream(
            "continue",
            [],
            resume_trace_id="trace-deep",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["done"]
    assert "knowledge" in captured["tool_groups"]
    assert captured["deep_search_enabled"] is True


def test_answer_stream_resume_attaches_existing_trace_recorder(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [{"type": "human", "content": "How?"}],
        "tool_state": {},
    }
    bound_recorder = object()
    captured = {}

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

        @classmethod
        def for_existing_trace(cls, trace_id, **kwargs):
            captured["attached_trace_id"] = trace_id
            return bound_recorder

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            captured["trace_recorder"] = trace_recorder
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["done"]
    assert captured["attached_trace_id"] == "trace-resume"
    assert captured["trace_recorder"] is bound_recorder


def test_answer_stream_resume_attach_none_emits_error_done(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [{"type": "human", "content": "How?"}],
        "tool_state": {},
    }

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

        @classmethod
        def for_existing_trace(cls, trace_id, **kwargs):
            return None

    def fail_build_agent_runner(**kwargs):
        raise AssertionError("runner should not be built")

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", fail_build_agent_runner)

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )
    events = [json.loads(line) for line in lines]

    assert [event["type"] for event in events] == ["error", "done"]
    assert "trace ownership validation failed" in events[0]["data"]


def test_answer_stream_resume_attach_exception_emits_error_done(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [{"type": "human", "content": "How?"}],
        "tool_state": {},
    }

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

        @classmethod
        def for_existing_trace(cls, trace_id, **kwargs):
            raise RuntimeError("attach failed")

    def fail_build_agent_runner(**kwargs):
        raise AssertionError("runner should not be built")

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", fail_build_agent_runner)

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )
    events = [json.loads(line) for line in lines]

    assert [event["type"] for event in events] == ["error", "done"]
    assert "trace ownership validation failed" in events[0]["data"]


def test_answer_stream_resume_requires_session_owner(monkeypatch):
    calls = []

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            calls.append(("load", trace_id, kwargs))
            raise AssertionError("load_checkpoint should not be called")

    def fail_build_agent_runner(**kwargs):
        raise AssertionError("runner should not be built")

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", fail_build_agent_runner)

    lines = list(answer.answer_stream("continue", [], resume_trace_id="trace-only"))
    events = [json.loads(line) for line in lines]

    assert [event["type"] for event in events] == ["error", "done"]
    assert "resume requires session/user message identifiers" in events[0]["data"]
    assert calls == []


def test_answer_stream_resume_loads_trace_with_session_owner(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [{"type": "human", "content": "How?"}],
        "tool_state": {},
    }
    bound_recorder = object()
    calls = []

    class FakeRecorder:
        next_checkpoint = checkpoint

        @classmethod
        def load_checkpoint(cls, trace_id, *, session_id=None, user_message_id=None):
            calls.append(("load", trace_id, session_id, user_message_id))
            return cls.next_checkpoint

        @classmethod
        def for_existing_trace(cls, trace_id, *, session_id=None, user_message_id=None):
            calls.append(("attach", trace_id, session_id, user_message_id))
            return bound_recorder

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            calls.append(("resume", loaded_checkpoint, trace_recorder))
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace",
            session_id="session-a",
            user_message_id="user-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["done"]
    assert calls[0] == ("load", "trace", "session-a", "user-a")
    assert calls[1] == ("attach", "trace", "session-a", "user-a")
    assert calls[2] == ("resume", checkpoint, bound_recorder)

    calls.clear()
    FakeRecorder.next_checkpoint = None
    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace",
            session_id="session-a",
            user_message_id="user-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["error", "done"]
    assert calls == [("load", "trace", "session-a", "user-a")]


def test_answer_stream_resume_bypasses_kb_selection_preflight(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "总结资料",
        "effective_query": "总结资料",
        "iteration": 1,
        "messages": [
            {"type": "system", "content": "system"},
            {"type": "human", "content": "总结资料"},
        ],
        "tool_state": {},
    }
    calls = []

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            calls.append(("load", trace_id))
            return checkpoint

    class FakeRunner:
        def resume_stream(self, loaded_checkpoint, trace_recorder=None):
            calls.append(("resume", loaded_checkpoint, trace_recorder))
            yield json.dumps({"type": "token", "data": "resumed from checkpoint"}) + "\n"
            yield json.dumps({"type": "done", "data": {}}) + "\n"

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {
            "groups": ["knowledge"],
            "kb_specs": [],
            "reasoning": "needs knowledge",
        },
    )

    lines = list(
        answer.answer_stream(
            "总结资料",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )
    events = [json.loads(line) for line in lines]

    assert calls[0] == ("load", "trace-resume")
    assert calls[1][0] == "resume"
    assert [event["type"] for event in events] == ["token", "done"]
    assert events[0]["data"] == "resumed from checkpoint"
    assert not any(event["type"] == "needs_kb_selection" for event in events)


def test_answer_stream_resume_missing_checkpoint_emits_done(monkeypatch):
    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return None

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history: {"groups": [], "kb_specs": [], "reasoning": ""},
    )

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-missing",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["error", "done"]


def test_answer_stream_resume_exception_emits_done(monkeypatch):
    checkpoint = {
        "version": 1,
        "query": "How?",
        "effective_query": "How?",
        "iteration": 1,
        "messages": [{"type": "human", "content": "How?"}],
        "tool_state": {},
    }

    class FakeRecorder:
        @classmethod
        def load_checkpoint(cls, trace_id, **kwargs):
            return checkpoint

    def build(**kwargs):
        raise RuntimeError("runner boom")

    monkeypatch.setattr(answer, "AgentTraceRecorder", FakeRecorder)
    monkeypatch.setattr(answer, "build_agent_runner", build)

    lines = list(
        answer.answer_stream(
            "How?",
            [],
            resume_trace_id="trace-resume",
            session_id="session-a",
            user_message_id="message-a",
        )
    )

    assert [json.loads(line)["type"] for line in lines] == ["error", "done"]


def test_answer_stream_classifies_with_recent_five_turns(monkeypatch):
    classified = {}
    history = [
        {"role": "user", "content": "user-1"},
        {"role": "assistant", "content": "assistant-1"},
        {"role": "user", "content": "user-2"},
        {"role": "assistant", "content": "assistant-2"},
        {"role": "user", "content": "user-3"},
        {"role": "assistant", "content": "assistant-3"},
        {"role": "user", "content": "user-4"},
        {"role": "assistant", "content": "assistant-4"},
        {"role": "user", "content": "user-5"},
        {"role": "assistant", "content": "assistant-5"},
        {"role": "user", "content": "user-6"},
        {"role": "assistant", "content": "assistant-6"},
    ]

    def classify(query, intent_history=None):
        classified["query"] = query
        classified["history"] = intent_history
        return {"groups": [], "kb_specs": [], "reasoning": "普通聊天"}

    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer, "classify_intent", classify)
    monkeypatch.setattr(answer.settings, "INTENT_RECENT_TURNS", 5)

    list(answer.answer_stream("hello", history))

    assert classified == {
        "query": "hello",
        "history": history[2:],
    }


def test_answer_stream_keeps_runner_full_history_when_intent_uses_recent_history(monkeypatch):
    captured = {}
    history = [
        {"role": "user", "content": "user-1"},
        {"role": "assistant", "content": "assistant-1"},
        {"role": "user", "content": "user-2"},
        {"role": "assistant", "content": "assistant-2"},
        {"role": "user", "content": "user-3"},
        {"role": "assistant", "content": "assistant-3"},
        {"role": "user", "content": "user-4"},
        {"role": "assistant", "content": "assistant-4"},
        {"role": "user", "content": "user-5"},
        {"role": "assistant", "content": "assistant-5"},
        {"role": "user", "content": "user-6"},
        {"role": "assistant", "content": "assistant-6"},
    ]

    class HistoryCapturingRunner:
        def stream(self, query, runner_history, trace_recorder=None):
            captured["history"] = runner_history
            yield json.dumps({"type": "done"}) + "\n"

    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: HistoryCapturingRunner())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, intent_history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    list(answer.answer_stream("hello", history))

    assert captured["history"] == history


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


def test_answer_stream_forces_knowledge_group_for_scoped_topic(monkeypatch):
    class Scope:
        allowed_kb_uids = ("kb-a",)

    class DB:
        def close(self):
            pass

    captured = {}

    monkeypatch.setattr(answer, "_Session", lambda: DB())
    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "generic"},
    )
    monkeypatch.setattr(
        answer,
        "build_agent_runner",
        lambda **kwargs: captured.update(kwargs) or FakeRunner(),
    )
    monkeypatch.setattr(answer.AgentTraceRecorder, "start", lambda self: None)

    list(answer.answer_stream("generic RAG question", [], topic_id="kb-a", knowledge_scope=Scope()))

    assert "knowledge" in captured["tool_groups"]
    assert captured["knowledge_scope"].allowed_kb_uids == ("kb-a",)


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
