from __future__ import annotations

import json
import re
from typing import Any

from ...config import settings
from ...llm.client import chat
from .directive_planner import plan_fallback_directives, source_backed_evidence_count
from .schemas import EvidencePoolSnapshot, JudgeVerdict, SearchDirective


class JudgeAgent:
    def evaluate(self, question: str, snapshot: EvidencePoolSnapshot, iteration: int) -> JudgeVerdict:
        fallback = self._deterministic_evaluate(question, snapshot, iteration)
        if not settings.DEEP_SEARCH_JUDGE_MODEL:
            return fallback

        try:
            content = chat(
                _build_judge_messages(question, snapshot, iteration),
                model=settings.DEEP_SEARCH_JUDGE_MODEL,
                api_base=settings.DEEP_SEARCH_JUDGE_API_BASE or None,
                api_key=settings.DEEP_SEARCH_JUDGE_API_KEY or None,
            )
            return _apply_completion_gates(_parse_judge_verdict(content), question, snapshot, iteration)
        except Exception:
            return fallback

    def _deterministic_evaluate(self, question: str, snapshot: EvidencePoolSnapshot, iteration: int) -> JudgeVerdict:
        records = snapshot.records
        source_count = len({(record.source_kind, record.source_id) for record in records if record.source_id})
        ckp_count = len({record.ckp_id for record in records if record.ckp_id})
        has_raw_source = any(record.source_kind in {"document_chunk", "personal_asset_unit", "personal_asset_item"} for record in records)
        has_direct = any(record.strategy == "source_backtrack" for record in records)
        has_related_only = bool(records) and all(record.relation_type == "related_to" for record in records)
        asks_conflict = _contains_any(question, ["conflict", "contradict", "矛盾", "冲突", "不同"])
        asks_structure = _contains_any(question, ["relation", "structure", "graph", "关系", "结构", "图谱"])
        has_conflict = any(record.relation_type == "contradicts" for record in records)
        has_structure = any(record.relation_type not in {"same_as", "supports", "defines"} for record in records)

        coverage_score = min(len(records) / 4.0, 1.0)
        grounding_score = 1.0 if has_raw_source else 0.0
        source_diversity_score = min(source_count / 2.0, 1.0)
        conflict_score = 1.0 if not asks_conflict or has_conflict else 0.25
        structure_score = 1.0 if not asks_structure or has_structure or ckp_count > 1 else 0.45
        overall = round(
            coverage_score * 0.30
            + grounding_score * 0.30
            + source_diversity_score * 0.15
            + conflict_score * 0.10
            + structure_score * 0.15,
            4,
        )

        missing: list[str] = []
        directives: list[SearchDirective] = []
        if not has_raw_source:
            missing.append("No raw source-backed evidence has been found.")
            directives.append(SearchDirective(strategy="source_backtrack", query=question, reason="need raw sources"))
        if not has_direct or has_related_only:
            missing.append("Direct PKU evidence is not strong enough.")
            directives.append(SearchDirective(strategy="pku_requery", query=question, reason="need direct PKU evidence"))
        if source_count < 2 and iteration <= 2:
            directives.append(SearchDirective(strategy="pku_graph_expansion", query=question, reason="increase evidence diversity"))
        if asks_conflict and not has_conflict:
            missing.append("Conflict evidence has not been checked.")
            directives.append(SearchDirective(strategy="ckp_rescope", query=question, reason="look for contradictions"))
        if asks_structure and not has_structure and iteration <= 2:
            directives.append(SearchDirective(strategy="pku_graph_expansion", query=question, reason="look for graph structure"))

        complete = (
            overall >= settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE
            and has_raw_source
            and not has_related_only
            and (not asks_conflict or has_conflict or len(records) >= 3)
        )
        return _apply_completion_gates(JudgeVerdict(
            status="complete" if complete else "incomplete",
            coverage_score=round(coverage_score, 4),
            grounding_score=round(grounding_score, 4),
            source_diversity_score=round(source_diversity_score, 4),
            conflict_score=round(conflict_score, 4),
            structure_score=round(structure_score, 4),
            overall_score=overall,
            missing=missing,
            directives=_dedupe_directives(directives),
        ), question, snapshot, iteration)


def _build_judge_messages(question: str, snapshot: EvidencePoolSnapshot, iteration: int) -> list[dict[str, str]]:
    evidence = [_evidence_summary(record) for record in snapshot.records[:20]]
    payload = {
        "question": question,
        "iteration": iteration,
        "total_evidence_count": snapshot.total_count,
        "evidence": evidence,
        "allowed_directive_strategies": [
            "source_backtrack",
            "pku_requery",
            "pku_graph_expansion",
            "ckp_rescope",
            "scoped_chunk_search",
            "global_fallback",
        ],
        "required_json_schema": {
            "status": "complete|incomplete",
            "coverage_score": "float 0..1",
            "grounding_score": "float 0..1",
            "source_diversity_score": "float 0..1",
            "conflict_score": "float 0..1",
            "structure_score": "float 0..1",
            "overall_score": "float 0..1",
            "missing": ["short unmet requirement"],
            "directives": [{"strategy": "strategy name", "query": "query text", "reason": "why", "limit": 8}],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are the Deep Knowledge Search judge. Decide whether the retrieved evidence is "
                "sufficient to answer the user question. Return JSON only. Do not include markdown, "
                "analysis, chain-of-thought, or extra text."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False),
        },
    ]


def _evidence_summary(record: Any) -> dict[str, Any]:
    return {
        "evidence_id": record.evidence_id,
        "strategy": record.strategy,
        "source_kind": record.source_kind,
        "source_id": record.source_id,
        "pku_id": record.pku_id,
        "ckp_id": record.ckp_id,
        "item_id": record.item_id,
        "topic_id": record.topic_id,
        "title": record.title,
        "statement": record.statement,
        "snippet": record.snippet,
        "relation_type": record.relation_type,
        "final_score": record.final_score,
    }


def _parse_judge_verdict(content: str) -> JudgeVerdict:
    data = json.loads(_extract_json_object(content))
    verdict = JudgeVerdict(**data)
    verdict.directives = _dedupe_directives(verdict.directives)
    return verdict


def _apply_completion_gates(
    verdict: JudgeVerdict,
    question: str,
    snapshot: EvidencePoolSnapshot,
    iteration: int,
) -> JudgeVerdict:
    missing = list(verdict.missing)
    directives = list(verdict.directives)
    required_overall = settings.DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE
    required_source_evidence = settings.DEEP_SEARCH_JUDGE_MIN_SOURCE_EVIDENCE
    source_evidence_count = _source_backed_evidence_count(snapshot)

    if verdict.overall_score < required_overall:
        missing.append(
            f"Judge overall score {verdict.overall_score:.2f} is below required threshold {required_overall:.2f}."
        )
    if source_evidence_count < required_source_evidence:
        missing.append(
            f"Source-backed evidence count {source_evidence_count} is below required minimum {required_source_evidence}."
        )

    if missing:
        verdict.status = "incomplete"
        if not directives:
            directives.extend(
                plan_fallback_directives(
                    question=question,
                    verdict=verdict,
                    snapshot=snapshot,
                    required_source_evidence=required_source_evidence,
                )
            )

    verdict.missing = _dedupe_strings(missing)
    verdict.directives = _dedupe_directives(directives)
    return verdict


def _source_backed_evidence_count(snapshot: EvidencePoolSnapshot) -> int:
    return source_backed_evidence_count(snapshot)


def _extract_json_object(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def _contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _dedupe_directives(directives: list[SearchDirective]) -> list[SearchDirective]:
    seen: set[str] = set()
    result: list[SearchDirective] = []
    for directive in directives:
        if directive.strategy in seen:
            continue
        seen.add(directive.strategy)
        result.append(directive)
    return result


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
