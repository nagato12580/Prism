from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from .a2a import AgentCard, Artifact, Message, Task
from .evidence_pool import EvidencePool
from .judge import JudgeAgent
from .schemas import DeepSearchConfig, JudgeVerdict
from .searcher import SearcherAgent


class DeepSearchResult:
    def __init__(
        self,
        *,
        status: str,
        summary: str,
        iterations: int,
        judge: JudgeVerdict,
        evidence: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        debug: dict[str, Any],
    ) -> None:
        self.status = status
        self.summary = summary
        self.iterations = iterations
        self.judge = judge
        self.evidence = evidence
        self.sources = sources
        self.debug = debug

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "retrieval_path": "scope_first_deep_search",
            "iterations": self.iterations,
            "judge": self.judge.model_dump(),
            "evidence": self.evidence,
            "sources": self.sources,
            "debug": self.debug,
        }


class DeepSearchOrchestrator:
    def __init__(self, session_factory: Callable[[], Any], config: DeepSearchConfig | None = None) -> None:
        self.config = config or DeepSearchConfig()
        self.searcher = SearcherAgent(session_factory)
        self.judge = JudgeAgent()

    def run(self, query: str) -> DeepSearchResult:
        task = Task(task_id=str(uuid.uuid4()), goal=query, depth=self.config.depth)
        cards = [
            AgentCard(name="SearcherAgent", role="searcher", capabilities=["scope", "evidence", "expand"]),
            AgentCard(name="JudgeAgent", role="judge", capabilities=["evaluate", "direct"]),
        ]
        messages: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []

        pool = EvidencePool()
        scope = self.searcher.find_scope(query, limit=self.config.scope_limit)
        messages.append(
            Message(
                sender="orchestrator",
                recipient="searcher",
                task_id=task.task_id,
                content={"query": query, "action": "find_scope"},
            ).to_dict()
        )
        artifacts.append(
            Artifact(
                artifact_id=str(uuid.uuid4()),
                task_id=task.task_id,
                kind="scope",
                payload=scope.model_dump(),
            ).to_dict()
        )

        pool.add_many(self.searcher.initial_evidence(scope, limit=self.config.evidence_limit))
        verdict = self.judge.evaluate(query, pool.snapshot(limit=self.config.evidence_limit), iteration=1)
        iterations = 1

        for iteration in range(2, self.config.max_iterations + 1):
            if verdict.status == "complete" or not verdict.directives:
                break
            iterations = iteration
            for directive in verdict.directives:
                records = self.searcher.follow_directive(directive, scope, limit=self.config.evidence_limit)
                pool.add_many(records)
                messages.append(
                    Message(
                        sender="judge",
                        recipient="searcher",
                        task_id=task.task_id,
                        content={"directive": directive.model_dump(), "returned": len(records)},
                        message_type="directive",
                    ).to_dict()
                )
            verdict = self.judge.evaluate(query, pool.snapshot(limit=self.config.evidence_limit), iteration=iteration)

        snapshot = pool.snapshot(limit=self.config.evidence_limit)
        evidence = [record.model_dump() for record in snapshot.records]
        sources = _dedupe_sources([record.source_payload() for record in snapshot.records])
        status = "success" if snapshot.records and verdict.status == "complete" else ("partial" if snapshot.records else "insufficient")
        summary = (
            f"Deep search collected {len(snapshot.records)} evidence records from {len(sources)} sources; judge status is {verdict.status}."
            if snapshot.records
            else "Deep search found no governed evidence for the query."
        )
        return DeepSearchResult(
            status=status,
            summary=summary,
            iterations=iterations,
            judge=verdict,
            evidence=evidence,
            sources=sources,
            debug={
                "task": task.to_dict(),
                "agent_cards": [card.to_dict() for card in cards],
                "messages": messages,
                "artifacts": artifacts,
            },
        )


def config_for_depth(depth: str, limit: int) -> DeepSearchConfig:
    if depth == "quick":
        return DeepSearchConfig(depth="quick", max_iterations=2, evidence_limit=limit, scope_limit=max(4, limit))
    if depth == "deep":
        return DeepSearchConfig(depth="deep", max_iterations=5, evidence_limit=max(limit, 16), scope_limit=max(limit, 12))
    return DeepSearchConfig(depth="standard", max_iterations=3, evidence_limit=limit, scope_limit=max(limit, 8))


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for source in sources:
        key = (str(source.get("source_kind") or ""), str(source.get("source_id") or source.get("chunk_id") or ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result

