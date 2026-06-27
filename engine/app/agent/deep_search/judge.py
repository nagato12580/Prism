from __future__ import annotations

from .schemas import EvidencePoolSnapshot, JudgeVerdict, SearchDirective


class JudgeAgent:
    def evaluate(self, question: str, snapshot: EvidencePoolSnapshot, iteration: int) -> JudgeVerdict:
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

        complete = overall >= 0.72 and has_raw_source and not has_related_only and (not asks_conflict or has_conflict or len(records) >= 3)
        return JudgeVerdict(
            status="complete" if complete else "incomplete",
            coverage_score=round(coverage_score, 4),
            grounding_score=round(grounding_score, 4),
            source_diversity_score=round(source_diversity_score, 4),
            conflict_score=round(conflict_score, 4),
            structure_score=round(structure_score, 4),
            overall_score=overall,
            missing=missing,
            directives=_dedupe_directives(directives),
        )


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

