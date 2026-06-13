import json
from typing import Any


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
    return ndjson_event("tool_result", data)


def clarify_event(question: str, options: list[dict[str, str]]) -> str:
    return ndjson_event("clarify", {"question": question, "options": options})


def sources_event(sources: list[dict[str, Any]]) -> str:
    return ndjson_event("sources", sources)


def token_event(text: str) -> str:
    return ndjson_event("token", text)


def error_event(message: str) -> str:
    return ndjson_event("error", message)


def done_event() -> str:
    return ndjson_event("done")
