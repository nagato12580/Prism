import json
from typing import Any, Iterator


EVENT_VERSION = 2


def ndjson_event(event_type: str, data: Any = None) -> str:
    payload: dict[str, Any] = {"type": event_type}
    if data is not None:
        payload["data"] = data
    return json.dumps(payload, ensure_ascii=False) + "\n"


def agent_status_event(label: str) -> str:
    return ndjson_event("agent_status", {"label": label})


def tool_call_event(tool: str, query: str = "") -> str:
    return ndjson_event("tool_call", {"tool": tool, "query": query})


def tool_result_event(
    tool: str,
    status: str,
    summary: str,
    query: str = "",
    stats: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    trace_steps: list[dict[str, Any]] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
) -> str:
    data: dict[str, Any] = {
        "tool": tool,
        "status": status,
        "summary": summary,
        "query": query,
    }
    if stats is not None:
        data["stats"] = stats
    if latency_ms is not None:
        data["latency_ms"] = latency_ms
    if trace_steps:
        data["trace_steps"] = trace_steps
    if evidence_items:
        data["evidence_items"] = evidence_items
    return ndjson_event("tool_result", data)


def trace_event(trace_id: str) -> str:
    return ndjson_event("trace", {"trace_id": trace_id})


def clarify_event(question: str, options: list[dict[str, str]]) -> str:
    return ndjson_event("clarify", {"question": question, "options": options})


def sources_event(
    evidence: list[dict[str, Any]] | None = None,
    *,
    sources: list[dict[str, Any]] | None = None,
    seq: int | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    retrieval_health: dict[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> Any:
    """Sources event.

    v2 mode (``seq`` provided) returns a dict stamped with monotonic metadata
    and canonical Evidence + retrieval health. Legacy mode
    (``sources_event(sources_list)``) returns an NDJSON line for existing
    callers; the runner is migrated to v2 incrementally.
    """
    if seq is not None:
        return {
            "type": "sources",
            "seq": seq,
            "trace_id": trace_id,
            "run_id": run_id,
            "event_version": EVENT_VERSION,
            "evidence": list(evidence or []),
            "retrieval_health": dict(retrieval_health or {}),
            "warnings": list(warnings or []),
        }
    legacy_sources = sources if sources is not None else evidence
    return ndjson_event("sources", legacy_sources or [])


def token_event(text: str) -> str:
    return ndjson_event("token", text)


def error_event(
    message: str | None = None,
    *,
    seq: int | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    code: str = "ERROR",
    retryable: bool = False,
) -> Any:
    """Error event.

    v2 mode (``seq`` provided) returns a dict whose ``data`` carries only
    ``code`` / ``message`` / ``retryable`` — never stack traces, provider
    payloads, credentials, or authorization material. Legacy mode returns an
    NDJSON line for existing callers.
    """
    if seq is not None:
        return {
            "type": "error",
            "seq": seq,
            "trace_id": trace_id,
            "run_id": run_id,
            "event_version": EVENT_VERSION,
            "data": {
                "code": code,
                "message": message or "",
                "retryable": bool(retryable),
            },
        }
    return ndjson_event("error", message)


def title_event(title: str) -> str:
    return ndjson_event("title", title)


def done_event() -> str:
    return ndjson_event("done")


class EventSequencer:
    """Assigns monotonic ``seq`` and stamps v2 metadata on every event."""

    def __init__(self, *, trace_id: str | None, run_id: str | None) -> None:
        self.trace_id = trace_id
        self.run_id = run_id
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def event(self, event_type: str, data: Any = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": event_type,
            "seq": self.next_seq(),
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "event_version": EVENT_VERSION,
        }
        if data is not None:
            payload["data"] = data
        return payload

    def sources(
        self,
        *,
        evidence: list[dict[str, Any]] | None = None,
        retrieval_health: dict[str, Any] | None = None,
        warnings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "sources",
            "seq": self.next_seq(),
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "event_version": EVENT_VERSION,
            "evidence": list(evidence or []),
            "retrieval_health": dict(retrieval_health or {}),
            "warnings": list(warnings or []),
        }

    def error(
        self,
        *,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return {
            "type": "error",
            "seq": self.next_seq(),
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "event_version": EVENT_VERSION,
            "data": {"code": code, "message": message, "retryable": bool(retryable)},
        }

    def serialize(self, event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    def stream(self, events: Iterator[dict[str, Any]]) -> Iterator[str]:
        for event in events:
            yield self.serialize(event)
