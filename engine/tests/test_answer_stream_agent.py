import json

from engine.app.chat import answer


class FakeRunner:
    def stream(self, query, history):
        yield json.dumps({"type": "agent_status", "data": {"label": query}}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


def test_answer_stream_delegates_to_agent_runner(monkeypatch):
    monkeypatch.setattr(answer, "build_agent_runner", lambda: FakeRunner())

    lines = list(answer.answer_stream("hello", [{"role": "user", "content": "old"}]))

    assert json.loads(lines[0]) == {"type": "agent_status", "data": {"label": "hello"}}
    assert json.loads(lines[1]) == {"type": "done"}


def test_answer_stream_emits_error_when_runner_build_fails(monkeypatch):
    def fail():
        raise RuntimeError("no model")

    monkeypatch.setattr(answer, "build_agent_runner", fail)

    lines = list(answer.answer_stream("hello", []))

    assert json.loads(lines[0]) == {"type": "error", "data": "no model"}
