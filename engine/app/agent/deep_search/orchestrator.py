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
        trace_steps: list[dict[str, Any]],
        debug: dict[str, Any],
    ) -> None:
        self.status = status
        self.summary = summary
        self.iterations = iterations
        self.judge = judge
        self.evidence = evidence
        self.sources = sources
        self.trace_steps = trace_steps
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
            "trace_steps": self.trace_steps,
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
        trace_steps: list[dict[str, Any]] = []

        pool = EvidencePool()
        scope = self.searcher.find_scope(query, limit=self.config.scope_limit)
        trace_steps.append(
            _trace_step(
                agent="SearcherAgent",
                iteration=1,
                label="第 1 轮 · Searcher · Scope Finder",
                detail=(
                    f"命中 {len(scope.seed_ckp_ids)} 个 CKP、{len(scope.seed_pku_ids)} 个 PKU、"
                    f"{len(scope.candidate_item_ids)} 个候选 source"
                ),
            )
        )
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

        initial_records = self.searcher.initial_evidence(scope, limit=self.config.evidence_limit)
        pool.add_many(initial_records)
        trace_steps.append(
            _trace_step(
                agent="SearcherAgent",
                iteration=1,
                label="第 1 轮 · Searcher · Source Backtrack",
                detail=f"收集 {len(initial_records)} 条 source-backed evidence",
            )
        )
        verdict = self.judge.evaluate(query, pool.snapshot(limit=self.config.evidence_limit), iteration=1)
        trace_steps.append(_judge_trace_step(verdict, iteration=1))
        iterations = 1

        for iteration in range(2, self.config.max_iterations + 1):
            if verdict.status == "complete" or not verdict.directives:
                break
            iterations = iteration
            for directive in verdict.directives:
                records = self.searcher.follow_directive(directive, scope, limit=self.config.evidence_limit)
                pool.add_many(records)
                trace_steps.append(
                    _trace_step(
                        agent="SearcherAgent",
                        iteration=iteration,
                        label=f"第 {iteration} 轮 · Searcher · {_strategy_label(directive.strategy)}",
                        detail=f"{directive.reason or directive.strategy}，新增 {len(records)} 条 evidence",
                    )
                )
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
            trace_steps.append(_judge_trace_step(verdict, iteration=iteration))

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
            trace_steps=trace_steps,
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


def _trace_step(agent: str, iteration: int, label: str, detail: str) -> dict[str, Any]:
    return {
        "agent": agent,
        "iteration": iteration,
        "label": label,
        "detail": detail,
    }


def _judge_trace_step(verdict: JudgeVerdict, iteration: int) -> dict[str, Any]:
    directives = ", ".join(directive.strategy for directive in verdict.directives) or "none"
    return _trace_step(
        agent="JudgeAgent",
        iteration=iteration,
        label=f"第 {iteration} 轮 · Judge",
        detail=(
            f"overall={verdict.overall_score:.2f} grounding={verdict.grounding_score:.2f} "
            f"coverage={verdict.coverage_score:.2f} status={verdict.status}; 下一步: {directives}"
        ),
    )


def _strategy_label(strategy: str) -> str:
    labels = {
        "source_backtrack": "Source Backtrack",
        "pku_requery": "PKU Re-query",
        "pku_graph_expansion": "PKU Graph Expansion",
        "ckp_rescope": "CKP Re-scope",
        "scoped_chunk_search": "Scoped Chunk Search",
        "global_fallback": "Global Fallback",
    }
    return labels.get(strategy, strategy)
