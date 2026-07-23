from pydantic import ValidationError
import pytest


def test_tool_envelope_serializes_success_and_error():
    from engine.app.agent.tools.contracts import ToolEnvelope, ToolProblem

    ok = ToolEnvelope.ok({"items": []}, trace_id="trace-1")
    assert ok.model_dump()["status"] == "ok"
    error = ToolEnvelope.from_error(
        ToolProblem(code="KB_NOT_ALLOWED", message="denied", retryable=False),
        "trace-2",
    )
    assert error.error.code == "KB_NOT_ALLOWED"
    assert error.data is None


def test_no_hits_and_degraded_have_explicit_status_and_warnings():
    from engine.app.agent.tools.contracts import ToolEnvelope, ToolWarning

    no_hits = ToolEnvelope.no_hits({"items": []}, trace_id="trace-1")
    degraded = ToolEnvelope.degraded(
        {"items": [{"id": "one"}]},
        [ToolWarning(code="GRAPH_UNAVAILABLE", message="graph unavailable")],
        trace_id="trace-2",
    )

    assert no_hits.status == "no_hits"
    assert degraded.status == "degraded"
    assert degraded.warnings[0].code == "GRAPH_UNAVAILABLE"


def test_error_envelope_requires_problem_and_forbids_unknown_fields():
    from engine.app.agent.tools.contracts import ToolEnvelope

    with pytest.raises(ValidationError):
        ToolEnvelope(status="error", trace_id="trace-1")
    with pytest.raises(ValidationError):
        ToolEnvelope(status="ok", data={}, trace_id="trace-1", secret="leak")


def test_generic_envelope_preserves_error_field_and_all_constructors():
    from engine.app.agent.tools.contracts import ToolEnvelope, ToolProblem, ToolWarning

    Envelope = ToolEnvelope[dict[str, list[str]]]
    assert Envelope.ok({"items": []}, "t1").error is None
    assert Envelope.no_hits({"items": []}, "t2").status == "no_hits"
    assert Envelope.degraded(
        {"items": ["one"]},
        [ToolWarning(code="PARTIAL", message="partial")],
        "t3",
    ).status == "degraded"
    failed = Envelope.from_error(ToolProblem(code="FAILED", message="failed"), "t4")
    assert failed.error.code == "FAILED"
    assert "error" in Envelope.model_json_schema()["properties"]


def test_envelope_cannot_be_mutated_into_an_invalid_state():
    from engine.app.agent.tools.contracts import ToolEnvelope

    envelope = ToolEnvelope.ok({"items": []}, "trace-1")
    with pytest.raises(ValidationError):
        envelope.status = "error"

    assert envelope.status == "ok"
    assert envelope.error is None
