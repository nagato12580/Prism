from backend.app.models import AgentTrace, AgentTraceEvidence, AgentTraceStep
from backend.app.services.agent_trace import export_trace


def test_agent_trace_models_persist(db_session):
    trace = AgentTrace(
        session_id="session-1",
        user_message_id="user-1",
        user_query="What is this chunk?",
        status="running",
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
        input_json={"query": "chunk"},
        output_json={"status": "success", "summary": "found"},
        status="success",
        latency_ms=12,
    )
    db_session.add(step)
    db_session.flush()

    evidence = AgentTraceEvidence(
        trace_step_id=step.id,
        evidence_id="document_chunk:chunk-1",
        source_kind="document_chunk",
        source_id="chunk-1",
        chunk_id="chunk-1",
        parent_chunk_id="parent-1",
        item_id="item-1",
        display_title="Doc",
        excerpt="raw excerpt",
        hit_reason="matched raw document search result",
        score=0.9,
        retrieval_path_json=["raw_document_search"],
        metadata_json={
            "chunk_type": "child",
            "chunk_index": 3,
            "graph_path": [{"node_id": "e1", "node_type": "entity"}],
            "graph_explain": {"why": "expanded from seed", "evidence_type": "INFERRED"},
            "evidence_type": "INFERRED",
        },
    )
    db_session.add(evidence)
    db_session.commit()

    loaded = db_session.query(AgentTrace).filter_by(id=trace.id).one()
    assert loaded.steps[0].evidence_items[0].chunk_id == "chunk-1"
    assert loaded.steps[0].evidence_items[0].metadata_json["chunk_index"] == 3
    assert loaded.steps[0].evidence_items[0].metadata_json["graph_explain"]["evidence_type"] == "INFERRED"

    exported = export_trace(db_session, trace.id)
    metadata = exported["steps"][0]["evidence_items"][0]["metadata"]
    assert metadata["graph_path"][0]["node_id"] == "e1"
    assert metadata["graph_explain"]["why"] == "expanded from seed"
    assert metadata["evidence_type"] == "INFERRED"
