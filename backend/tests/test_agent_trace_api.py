import os

import pytest
from fastapi.testclient import TestClient

from backend.app.database import get_db
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep


@pytest.fixture()
def client(db_session, monkeypatch):
    prev_skip_engine = os.environ.get("SKIP_ENGINE")
    os.environ["SKIP_ENGINE"] = "1"
    try:
        from backend.app import main

        monkeypatch.setattr(main, "auto_migrate", lambda Base, engine: None)
        app = main.create_app()

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as test_client:
            yield test_client
        app.dependency_overrides.clear()
    finally:
        if prev_skip_engine is None:
            os.environ.pop("SKIP_ENGINE", None)
        else:
            os.environ["SKIP_ENGINE"] = prev_skip_engine


def _seed_trace(db_session):
    trace = AgentTrace(
        session_id="session-1",
        user_message_id="user-1",
        user_query="query",
        status="success",
        model="test-model",
    )
    db_session.add(trace)
    db_session.flush()

    step = AgentTraceStep(
        trace_id=trace.id,
        step_index=1,
        step_type="tool_result",
        tool_name="raw_document_search",
        tool_call_id="call_1",
        input_json={"query": "query"},
        output_json={"status": "success", "summary": "found"},
        status="success",
        latency_ms=10,
    )
    db_session.add(step)
    db_session.flush()

    db_session.add(
        AgentTraceEvidence(
            trace_step_id=step.id,
            evidence_id="document_chunk:chunk-1",
            source_kind="document_chunk",
            source_id="chunk-1",
            chunk_id="chunk-1",
            item_id="item-1",
            display_title="Doc",
            excerpt="excerpt",
            hit_reason="matched",
            score=1.0,
            retrieval_path_json=["raw_document_search"],
            metadata_json={"chunk_index": 1},
        )
    )
    db_session.commit()
    return trace.id


def test_bind_trace_message(client, db_session):
    trace_id = _seed_trace(db_session)

    resp = client.post(
        f"/api/v1/traces/{trace_id}/bind-message",
        json={"session_id": "session-1", "assistant_message_id": "assistant-1"},
    )

    assert resp.status_code == 200
    assert resp.json()["assistant_message_id"] == "assistant-1"
    db_session.expire_all()
    trace = db_session.query(AgentTrace).filter_by(id=trace_id).one()
    assert trace.assistant_message_id == "assistant-1"


def test_export_trace(client, db_session):
    trace_id = _seed_trace(db_session)

    resp = client.get(f"/api/v1/traces/{trace_id}/export")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["trace_id"] == trace_id
    assert payload["steps"][0]["tool_name"] == "raw_document_search"
    assert payload["steps"][0]["evidence_items"][0]["chunk_id"] == "chunk-1"
