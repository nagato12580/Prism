from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


_BARE_CONTINUATION = re.compile(
    r"^\s*(继续|继续读|继续读取|接着读|往下读)[。.!！?？]?\s*$"
)


@dataclass(frozen=True)
class AgentContinuation:
    version: int
    objective: str
    kb_uid: str
    file_uid: str
    next_offset: int
    has_more_after: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_bare_continuation(query: str) -> bool:
    return bool(_BARE_CONTINUATION.fullmatch(query or ""))


def _parse_state(value: Any) -> AgentContinuation | None:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("version"), int)
        or isinstance(value.get("version"), bool)
        or value["version"] != 1
    ):
        return None

    objective = value.get("objective")
    kb_uid = value.get("kb_uid")
    file_uid = value.get("file_uid")
    next_offset = value.get("next_offset")
    has_more_after = value.get("has_more_after")
    if not all(
        isinstance(item, str) and item.strip() for item in (objective, kb_uid, file_uid)
    ):
        return None
    if len(kb_uid.strip()) > 128 or len(file_uid.strip()) > 128:
        return None
    if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset < 0:
        return None
    if not isinstance(has_more_after, bool) or not has_more_after:
        return None

    return AgentContinuation(
        version=1,
        objective=objective.strip()[:8000],
        kb_uid=kb_uid.strip(),
        file_uid=file_uid.strip(),
        next_offset=next_offset,
        has_more_after=True,
    )


def continuation_from_history(history: list[dict[str, Any]]) -> AgentContinuation | None:
    if not history:
        return None

    latest = history[-1]
    if not isinstance(latest, dict) or latest.get("role") != "assistant":
        return None
    return _parse_state(latest.get("continuation"))


def resolve_effective_objective(
    query: str,
    history: list[dict[str, Any]],
    continuation: AgentContinuation | None,
) -> str:
    if not is_bare_continuation(query):
        return query
    if continuation is not None:
        return continuation.objective

    for item in reversed(history):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        content = content.strip()
        if content and not is_bare_continuation(content):
            return content[:8000]
    return query
