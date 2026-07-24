"""Task 6: NDJSON v2 event contract.

Every v2 event carries monotonic ``seq``, ``trace_id``, ``run_id`` and
``event_version=2``. Sources carry canonical Evidence + retrieval health.
Errors use code/message/retryable and never include stack/provider payloads.
"""

from engine.app.agent.events import EventSequencer, error_event, sources_event


def test_sources_event_v2_carries_seq_trace_run_evidence_and_health():
    event = sources_event(
        seq=4,
        trace_id="t1",
        run_id="r1",
        evidence=[{"evidence_id": "K1", "excerpt": "grounded"}],
        retrieval_health={"dense": "ok"},
    )

    assert event["type"] == "sources"
    assert event["seq"] == 4
    assert event["event_version"] == 2
    assert event["trace_id"] == "t1"
    assert event["run_id"] == "r1"
    assert event["evidence"][0]["evidence_id"] == "K1"
    assert event["retrieval_health"]["dense"] == "ok"


def test_sources_event_legacy_string_shape_still_works():
    # Legacy callers (sources_event(list)) must keep returning an NDJSON line.
    line = sources_event([{"chunk_id": "c1"}])

    assert isinstance(line, str)
    assert line.endswith("\n")
    assert '"type": "sources"' in line


def test_error_event_v2_uses_code_message_retryable_without_internals():
    event = error_event(
        seq=2,
        trace_id="t1",
        run_id="r1",
        code="RETRIEVAL_UNAVAILABLE",
        message="retrieval is down",
        retryable=True,
    )

    assert event["event_version"] == 2
    assert event["data"]["code"] == "RETRIEVAL_UNAVAILABLE"
    assert event["data"]["message"] == "retrieval is down"
    assert event["data"]["retryable"] is True
    lowered = str(event).lower()
    assert "stack" not in lowered
    assert "traceback" not in lowered
    assert "api_key" not in lowered
    assert "authorization" not in lowered


def test_event_sequencer_is_monotonic_and_stamps_metadata():
    sequencer = EventSequencer(trace_id="t1", run_id="r1")

    first = sequencer.event("agent_status", {"label": "thinking"})
    second = sequencer.event("token", "hello")

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert first["trace_id"] == "t1"
    assert second["run_id"] == "r1"
    assert first["event_version"] == 2
    assert first["type"] == "agent_status"
    assert second["data"] == "hello"


def test_sequencer_sources_and_error_helpers_match_contract():
    sequencer = EventSequencer(trace_id="t1", run_id="r1")

    sources = sequencer.sources(
        evidence=[{"evidence_id": "K1"}], retrieval_health={"dense": "ok"}
    )
    err = sequencer.error(code="X", message="boom", retryable=False)

    assert sources["seq"] == 1
    assert sources["evidence"][0]["evidence_id"] == "K1"
    assert err["seq"] == 2
    assert err["data"]["code"] == "X"
