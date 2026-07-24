import os
import subprocess
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///./_agent_trace_recorder_import.db")

from backend.app.database import Base
from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
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
        cwd=os.getcwd(),
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

