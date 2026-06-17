import json
import logging

from engine.app.chat import answer


class FakeRunner:
    def stream(self, query, history):
        yield json.dumps({"type": "agent_status", "data": {"label": query}}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


def test_answer_stream_delegates_to_agent_runner(monkeypatch):
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())

    lines = list(answer.answer_stream("hello", [{"role": "user", "content": "old"}]))

    assert json.loads(lines[0]) == {"type": "agent_status", "data": {"label": "hello"}}
    assert json.loads(lines[1]) == {"type": "done"}


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
