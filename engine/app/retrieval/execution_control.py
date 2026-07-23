"""Cooperative cancellation and hard I/O budgets for retrieval."""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic


class RetrievalExecutionAborted(RuntimeError):
    pass


class RetrievalDeadlineExceeded(RetrievalExecutionAborted):
    pass


class RetrievalCancelled(RetrievalExecutionAborted):
    pass


@dataclass
class RetrievalExecutionControl:
    deadline: float
    cancel_callback: Callable[[], bool] | None = None
    heartbeat_callback: Callable[[], None] | None = None
    heartbeat_interval_seconds: float = 5.0
    _last_heartbeat: float = field(default_factory=monotonic)

    @classmethod
    def with_timeout(cls, timeout_seconds: float, **kwargs):
        return cls(deadline=monotonic() + timeout_seconds, **kwargs)

    def checkpoint(self) -> None:
        now = monotonic()
        if now >= self.deadline:
            raise RetrievalDeadlineExceeded("retrieval deadline exceeded")
        if self.cancel_callback is not None and self.cancel_callback():
            raise RetrievalCancelled("retrieval canceled")
        if self.heartbeat_callback is not None and now - self._last_heartbeat >= self.heartbeat_interval_seconds:
            self.heartbeat_callback()
            self._last_heartbeat = monotonic()
        if monotonic() >= self.deadline:
            raise RetrievalDeadlineExceeded("retrieval deadline exceeded")

    def remaining_timeout(self, cap_seconds: float = 30.0) -> float:
        self.checkpoint()
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise RetrievalDeadlineExceeded("retrieval deadline exceeded")
        return max(0.001, min(float(cap_seconds), remaining))
