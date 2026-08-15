import os
import json
import subprocess
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///./_agent_trace_recorder_import.db")

from backend.app.database import Base
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
from engine.app.agent import trace as trace_module
from engine.app.agent.trace import AgentTraceRecorder


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_agent_trace_recorder_persists_run_step_evidence_and_finish(session_factory):
    recorder = AgentTraceRecorder(
        session_id="session-1",
        user_message_id="message-1",
        user_query="What evidence supports this?",
        model="test-model",
        session_factory=session_factory,
    )

    trace_id = recorder.start()
    step_id = recorder.record_step(
        step_type="tool_result",
        tool_name="knowledge_search",
        tool_call_id="call-1",
        input_json={"query": "evidence"},
        output_json={"result_count": 1},
        latency_ms=42,
        evidence_items=[
            {
                "evidence_id": "ev-1",
                "source_kind": "knowledge",
                "source_id": "source-1",
                "chunk_id": "chunk-1",
                "parent_chunk_id": "parent-1",
                "item_id": "item-1",
                "display_title": "Evidence Title",
                "excerpt": "Useful excerpt",
                "hit_reason": "Matched the query",
                "score": 0.87,
                "retrieval_path": ["root", "chunk-1"],
                "metadata": {"rank": 1},
            }
        ],
    )
    recorder.finish("success")

    db = session_factory()
    try:
        trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).one()
        step = db.query(AgentTraceStep).filter(AgentTraceStep.id == step_id).one()
        evidence = db.query(AgentTraceEvidence).filter(AgentTraceEvidence.trace_step_id == step_id).one()

        assert trace.session_id == "session-1"
        assert trace.user_message_id == "message-1"
        assert trace.user_query == "What evidence supports this?"
        assert trace.model == "test-model"
        assert trace.status == "success"
        assert trace.ended_at is not None

        assert step.trace_id == trace_id
        assert step.step_index == 0
        assert step.step_type == "tool_result"
        assert step.tool_name == "knowledge_search"
        assert step.tool_call_id == "call-1"
        assert step.input_json == {"query": "evidence"}
        assert step.output_json == {"result_count": 1}
        assert step.status == "success"
        assert step.latency_ms == 42
        assert step.ended_at is not None

        assert evidence.evidence_id == "ev-1"
        assert evidence.source_kind == "knowledge"
        assert evidence.source_id == "source-1"
        assert evidence.chunk_id == "chunk-1"
        assert evidence.parent_chunk_id == "parent-1"
        assert evidence.item_id == "item-1"
        assert evidence.display_title == "Evidence Title"
        assert evidence.excerpt == "Useful excerpt"
        assert evidence.hit_reason == "Matched the query"
        assert evidence.score == 0.87
        assert evidence.retrieval_path_json == ["root", "chunk-1"]
        assert evidence.metadata_json == {"rank": 1}
    finally:
        db.close()


def test_agent_trace_recorder_saves_and_loads_checkpoint(session_factory):
    recorder = AgentTraceRecorder(
        session_id="session-checkpoint",
        user_message_id="message-checkpoint",
        user_query="resume me",
        model="test-model",
        session_factory=session_factory,
    )
    trace_id = recorder.start()

    checkpoint = {
        "version": 1,
        "query": "resume me",
        "iteration": 2,
        "messages": [{"type": "human", "content": "resume me"}],
        "tool_state": {"timed_out_tools": []},
    }
    assert recorder.save_checkpoint(checkpoint, resume_status="checkpointed") is True

    loaded = AgentTraceRecorder.load_checkpoint(
        trace_id,
        session_factory=session_factory,
    )
    assert loaded == checkpoint

    db = session_factory()
    try:
        trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).one()
        assert trace.resume_status == "checkpointed"
        assert trace.last_event_seq == 1
    finally:
        db.close()


def test_agent_trace_recorder_attaches_existing_trace(session_factory):
    recorder = AgentTraceRecorder(
        session_id="session-attach",
        user_message_id="message-attach",
        user_query="resume existing trace",
        model="test-model",
        session_factory=session_factory,
    )
    trace_id = recorder.start()
    dedupe_key = AgentTraceRecorder.tool_dedupe_key(
        trace_id=trace_id,
        tool_name="knowledge_search",
        args={"query": "same"},
    )
    recorder.record_step(step_type="model_response", output_json={"content": "thinking"})
    recorder.record_step(
        step_type="tool_result",
        tool_name="knowledge_search",
        tool_call_id="call-existing",
        dedupe_key=dedupe_key,
        input_json={"args": {"query": "same"}},
        output_json={"status": "success", "payload": {"summary": "cached"}},
        status="success",
    )

    attached = AgentTraceRecorder.for_existing_trace(
        trace_id,
        session_factory=session_factory,
    )

    assert attached is not None
    assert attached.trace_id == trace_id
    assert attached.session_id == "session-attach"
    assert attached.user_message_id == "message-attach"
    assert attached.user_query == "resume existing trace"
    assert attached.model == "test-model"
    assert attached.record_step(step_type="model_response", output_json={"content": "resumed"})
    assert attached.find_successful_tool_result(
        tool_name="knowledge_search",
        args={"query": "same"},
    ) == {
        "dedupe_key": dedupe_key,
        "output_json": {"status": "success", "payload": {"summary": "cached"}},
    }
    assert attached.save_checkpoint(
        {
            "version": 1,
            "query": "resume existing trace",
            "iteration": 3,
            "messages": [{"type": "human", "content": "resume existing trace"}],
            "tool_state": {},
        }
    ) is True

    db = session_factory()
    try:
        step_indexes = [
            step.step_index
            for step in db.query(AgentTraceStep)
            .filter(AgentTraceStep.trace_id == trace_id)
            .order_by(AgentTraceStep.step_index)
            .all()
        ]
        trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).one()
        assert step_indexes == [0, 1, 2]
        assert trace.last_event_seq == 1
    finally:
        db.close()


def test_agent_trace_recorder_reuses_successful_tool_result_by_dedupe_key(session_factory):
    recorder = AgentTraceRecorder(
        session_id="session-dedupe",
        user_message_id="message-dedupe",
        user_query="dedupe",
        model="test-model",
        session_factory=session_factory,
    )
    trace_id = recorder.start()
    dedupe_key = AgentTraceRecorder.tool_dedupe_key(
        trace_id=trace_id,
        tool_name="knowledge_search",
        args={"query": "same", "top_k": 3},
    )
    recorder.record_step(
        step_type="tool_result",
        tool_name="knowledge_search",
        tool_call_id="call-1",
        dedupe_key=dedupe_key,
        input_json={"args": {"query": "same", "top_k": 3}},
        output_json={"payload": {"status": "success", "summary": "cached"}, "status": "success", "latency_ms": 12},
        status="success",
        latency_ms=12,
    )

    reused = recorder.find_successful_tool_result(
        tool_name="knowledge_search",
        args={"top_k": 3, "query": "same"},
    )

    assert reused == {
        "dedupe_key": dedupe_key,
        "output_json": {"payload": {"status": "success", "summary": "cached"}, "status": "success", "latency_ms": 12},
    }


def test_tool_dedupe_key_distinguishes_sensitive_values_without_exposing_them():
    first = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"query": "same", "api_key": "secret-one"},
    )
    second = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"query": "same", "api_key": "secret-two"},
    )
    repeat = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"api_key": "secret-one", "query": "same"},
    )
    identity_helper = getattr(trace_module, "_dedupe_json_identity", None)

    assert first != second
    assert first == repeat
    assert identity_helper is not None
    identity = identity_helper({"api_key": "secret-one"})
    assert "secret-one" not in repr(identity)


def test_dedupe_identity_hashes_nested_sensitive_values():
    identity = trace_module._dedupe_json_identity({"api_key": {"value": "secret-one", "scopes": ["read"]}})
    dumped = json.dumps(identity, sort_keys=True)
    assert "secret-one" not in dumped
    assert "read" not in dumped
    assert "__sensitive_sha256__" in dumped

    first = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"api_key": {"value": "secret-one"}},
    )
    second = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"api_key": {"value": "secret-two"}},
    )
    repeat = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="external_tool",
        args={"api_key": {"value": "secret-one"}},
    )
    assert first != second
    assert first == repeat


def test_dedupe_identity_hashes_sensitive_nested_mapping_keys():
    identity = trace_module._dedupe_json_identity({"api_key": {"secret-key": "secret-value"}})
    dumped = json.dumps(identity, sort_keys=True)
    assert "secret-key" not in dumped
    assert "secret-value" not in dumped
    assert "__sensitive_sha256__" in dumped


def test_dedupe_identity_hashes_sensitive_non_string_leaves():
    identity = trace_module._dedupe_json_identity({"access_token": {"expires": 123, "enabled": True}})
    sensitive_subtree = identity["access_token"]

    assert all(key.startswith("sensitive:") for key in sensitive_subtree)
    assert all(
        isinstance(value, dict) and set(value) == {"__sensitive_sha256__"}
        for value in sensitive_subtree.values()
    )
    assert 123 not in sensitive_subtree.values()
    assert True not in sensitive_subtree.values()


def test_dedupe_identity_hashes_sensitive_object_fallback():
    class SecretObject:
        def __repr__(self):
            return "secret-object-token"

    identity = trace_module._dedupe_json_identity({"api_key": SecretObject()})
    dumped = json.dumps(identity, sort_keys=True)
    assert "secret-object-token" not in dumped
    assert "__sensitive_sha256__" in dumped


def test_tool_dedupe_key_is_deterministic_for_sets():
    first = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="set_tool",
        args={"tags": {"beta", "alpha", "gamma"}},
    )
    second = AgentTraceRecorder.tool_dedupe_key(
        trace_id="trace-1",
        tool_name="set_tool",
        args={"tags": {"gamma", "beta", "alpha"}},
    )

    assert first == second


def test_agent_trace_recorder_disables_after_session_factory_failure():
    def failing_session_factory():
        raise RuntimeError("database unavailable")

    recorder = AgentTraceRecorder(
        session_id=None,
        user_message_id=None,
        user_query="Will this raise?",
        model="test-model",
        session_factory=failing_session_factory,
    )

    assert recorder.start() is None
    assert recorder.record_step(step_type="tool_result") is None
    recorder.finish("failed")


def test_agent_trace_recorder_coerces_non_json_safe_values_and_invalid_score(session_factory):
    marker = object()
    payload_uuid = uuid.uuid4()
    payload_date = date(2026, 6, 29)
    payload_datetime = datetime(2026, 6, 29, 12, 34, 56)

    recorder = AgentTraceRecorder(
        session_id="session-2",
        user_message_id="message-2",
        user_query="Can tracing survive odd payloads?",
        model="test-model",
        session_factory=session_factory,
    )

    trace_id = recorder.start()
    step_id = recorder.record_step(
        step_type="tool_result",
        input_json={
            "when": payload_datetime,
            "price": Decimal("12.5"),
            "uuid": payload_uuid,
            "tags": {"alpha", "beta"},
            "blob": b"hello",
            "obj": marker,
        },
        output_json=("tuple", payload_date),
        evidence_items=[
            {
                "evidence_id": "ev-2",
                "score": "not-a-float",
                "retrieval_path": ("root", payload_uuid),
                "metadata": {payload_uuid: {b"bytes", Decimal("2.5")}},
            }
        ],
    )

    db = session_factory()
    try:
        step = db.query(AgentTraceStep).filter(AgentTraceStep.id == step_id).one()
        evidence = db.query(AgentTraceEvidence).filter(AgentTraceEvidence.trace_step_id == step_id).one()

        assert trace_id is not None
        assert step.input_json["when"] == "2026-06-29T12:34:56"
        assert step.input_json["price"] == 12.5
        assert step.input_json["uuid"] == str(payload_uuid)
        assert sorted(step.input_json["tags"]) == ["alpha", "beta"]
        assert step.input_json["blob"] == "hello"
        assert step.input_json["obj"] == repr(marker)
        assert step.output_json == ["tuple", "2026-06-29"]
        assert evidence.score is None
        assert evidence.retrieval_path_json == ["root", str(payload_uuid)]
        assert sorted(evidence.metadata_json[str(payload_uuid)], key=str) == [2.5, "bytes"]
    finally:
        db.close()


def test_agent_trace_recorder_redacts_sensitive_json_keys(session_factory):
    recorder = AgentTraceRecorder(
        session_id="session-redact",
        user_message_id="message-redact",
        user_query="redact",
        model="test-model",
        session_factory=session_factory,
    )

    recorder.start()
    step_id = recorder.record_step(
        step_type="tool_result",
        input_json={
            "query": "safe",
            "api_key": "sk-secret",
            "nested": {"Authorization": "Bearer token", "password": "pw"},
        },
        output_json={"access_token": "token", "summary": "safe"},
    )

    db = session_factory()
    try:
        step = db.query(AgentTraceStep).filter(AgentTraceStep.id == step_id).one()

        assert step.input_json["query"] == "safe"
        assert step.input_json["api_key"] == "[REDACTED]"
        assert step.input_json["nested"]["Authorization"] == "[REDACTED]"
        assert step.input_json["nested"]["password"] == "[REDACTED]"
        assert step.output_json["access_token"] == "[REDACTED]"
        assert step.output_json["summary"] == "safe"
    finally:
        db.close()


def test_agent_trace_recorder_close_failure_does_not_raise(session_factory):
    class CloseFailingSession:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        def close(self):
            self._session.close()
            raise RuntimeError("close failed")

    def close_failing_session_factory():
        return CloseFailingSession(session_factory())

    recorder = AgentTraceRecorder(
        session_id="session-3",
        user_message_id="message-3",
        user_query="Will close break tracing?",
        model="test-model",
        session_factory=close_failing_session_factory,
    )

    assert recorder.start() is not None
    assert recorder.record_step(step_type="tool_result") is None
    recorder.finish("failed")


def test_agent_trace_recorder_step_refresh_failure_after_commit_still_allows_finish(session_factory):
    class RefreshFailingSession:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        def refresh(self, _value):
            raise RuntimeError("refresh failed")

    def refresh_failing_session_factory():
        return RefreshFailingSession(session_factory())

    recorder = AgentTraceRecorder(
        session_id="session-4",
        user_message_id="message-4",
        user_query="Will refresh failure break finish?",
        model="test-model",
        session_factory=refresh_failing_session_factory,
    )

    trace_id = recorder.start()
    step_id = recorder.record_step(step_type="tool_result")
    recorder.finish("success")

    db = session_factory()
    try:
        trace = db.query(AgentTrace).filter(AgentTrace.id == trace_id).one()
        step = db.query(AgentTraceStep).filter(AgentTraceStep.id == step_id).one()

        assert step.step_index == 0
        assert trace.status == "success"
        assert trace.ended_at is not None
    finally:
        db.close()


def test_agent_trace_recorder_commit_failure_disables_without_raising():
    class CommitFailingSession:
        def __init__(self):
            self.commit_called = False

        def add(self, _value):
            self._value = _value

        def flush(self):
            self._value.id = self._value.id or str(uuid.uuid4())

        def commit(self):
            self.commit_called = True
            raise RuntimeError("commit failed")

        def rollback(self):
            pass

        def close(self):
            pass

    sessions = []

    def commit_failing_session_factory():
        session = CommitFailingSession()
        sessions.append(session)
        return session

    recorder = AgentTraceRecorder(
        session_id=None,
        user_message_id=None,
        user_query="Will commit failure raise?",
        model="test-model",
        session_factory=commit_failing_session_factory,
    )

    assert recorder.start() is None
    assert sessions[0].commit_called
    assert recorder.record_step(step_type="tool_result") is None
    recorder.finish("failed")


def test_agent_trace_module_import_does_not_create_default_engine_when_database_url_missing():
    env = os.environ.copy()
    env["DATABASE_URL"] = ""

    result = subprocess.run(
        [sys.executable, "-c", "import engine.app.agent.trace"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_record_evidence_snapshot_persists_short_ids_and_invalid_citations(session_factory):
    from engine.app.agent.citations import CitationRegistry

    recorder = AgentTraceRecorder(
        session_id="session-2",
        user_message_id="message-2",
        user_query="cite please",
        model="test-model",
        session_factory=session_factory,
    )
    trace_id = recorder.start()

    registry = CitationRegistry()
    registry.register(
        {
            "kb_uid": "kb-a",
            "file_uid": "file-a",
            "chunk_uid": "chunk-b",
            "index_generation": "gen-1",
            "source_kind": "document_chunk",
            "excerpt": "grounded",
        }
    )
    snapshot = registry.snapshot()

    step_id = recorder.record_evidence_snapshot(
        evidence_items=snapshot, invalid_citations=("K9",)
    )
    recorder.finish("success")

    db = session_factory()
    try:
        step = db.query(AgentTraceStep).filter(AgentTraceStep.id == step_id).one()
        assert step.step_type == "evidence_snapshot"
        evidence = (
            db.query(AgentTraceEvidence)
            .filter(AgentTraceEvidence.trace_step_id == step_id)
            .one()
        )
        # Short id assigned by the run-local registry is persisted verbatim.
        assert evidence.evidence_id == "K1"
        assert evidence.excerpt == "grounded"
    finally:
        db.close()

