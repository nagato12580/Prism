import json

from engine.app.agent.events import (
    agent_status_event,
    done_event,
    error_event,
    sources_event,
    token_event,
    tool_call_event,
    tool_result_event,
    clarify_event,
)


def parse(line: str) -> dict:
    assert line.endswith("\n")
    return json.loads(line)


def test_event_helpers_emit_ndjson_lines():
    assert parse(agent_status_event("analyzing")) == {
        "type": "agent_status",
        "data": {"label": "analyzing"},
    }
    assert parse(token_event("hello")) == {"type": "token", "data": "hello"}
    assert parse(done_event()) == {"type": "done"}
    assert parse(error_event("boom")) == {"type": "error", "data": "boom"}


def test_tool_and_clarify_events_have_stable_shape():
    assert parse(tool_call_event("knowledge_search", "phase 2")) == {
        "type": "tool_call",
        "data": {"tool": "knowledge_search", "query": "phase 2"},
    }

    tool_result = parse(
        tool_result_event(
            tool="knowledge_search",
            status="success",
            summary="3 hits",
            query="phase 2",
            stats={"hit_count": 3},
            latency_ms=24,
        )
    )
    assert tool_result["type"] == "tool_result"
    assert tool_result["data"]["tool"] == "knowledge_search"
    assert tool_result["data"]["status"] == "success"
    assert tool_result["data"]["stats"] == {"hit_count": 3}
    assert tool_result["data"]["latency_ms"] == 24

    clarify = parse(
        clarify_event(
            "Which scope?",
            [
                {"label": "Current knowledge base", "value": "scope:knowledge"},
                {"label": "Allow web", "value": "scope:web"},
            ],
        )
    )
    assert clarify == {
        "type": "clarify",
        "data": {
            "question": "Which scope?",
            "options": [
                {"label": "Current knowledge base", "value": "scope:knowledge"},
                {"label": "Allow web", "value": "scope:web"},
            ],
        },
    }


def test_sources_event_preserves_existing_shape():
    sources = [{"chunk_id": "c1", "item_id": "i1", "score": 0.91}]
    assert parse(sources_event(sources)) == {"type": "sources", "data": sources}
