from __future__ import annotations

from .schemas import EvidencePoolSnapshot, JudgeVerdict, SearchDirective


SOURCE_BACKED_KINDS = {"document_chunk", "personal_asset_unit", "personal_asset_item"}


def plan_fallback_directives(
    *,
    question: str,
    verdict: JudgeVerdict,
    snapshot: EvidencePoolSnapshot,
    required_source_evidence: int,
) -> list[SearchDirective]:
    source_count = source_backed_evidence_count(snapshot)
    if source_count < required_source_evidence:
        return [
            SearchDirective(
                strategy="source_backtrack",
                query=question,
                reason="need source-backed evidence before judging completeness",
            )
        ]

    weakest_dimension = _weakest_dimension(verdict)
    if weakest_dimension == "grounding_score":
        return [
            SearchDirective(
                strategy="scoped_chunk_search",
                query=question,
                reason="grounding score is low; search scoped source chunks for direct support",
            )
        ]
    if weakest_dimension == "coverage_score":
        return [
            SearchDirective(
                strategy="pku_requery",
                query=question,
                reason="coverage score is low; re-query PKUs for missing aspects",
            )
        ]
    if weakest_dimension == "source_diversity_score":
        return [
            SearchDirective(
                strategy="pku_graph_expansion",
                query=question,
                reason="source diversity is low; expand through related PKUs",
            )
        ]
    if weakest_dimension == "conflict_score":
        return [
            SearchDirective(
                strategy="ckp_rescope",
                query=question,
                reason="conflict score is low; re-scope CKPs for contradictions",
            )
        ]
    if weakest_dimension == "structure_score":
        return [
            SearchDirective(
                strategy="pku_graph_expansion",
                query=question,
                reason="structure score is low; expand graph relations",
            )
        ]

    return [
        SearchDirective(
            strategy="global_fallback",
            query=question,
            reason="evidence is still below completion threshold; broaden search scope",
        )
    ]


def source_backed_evidence_count(snapshot: EvidencePoolSnapshot) -> int:
    return sum(
        1
        for record in snapshot.records
        if record.source_id and record.source_kind in SOURCE_BACKED_KINDS
    )


def _weakest_dimension(verdict: JudgeVerdict) -> str:
    scores = {
        "coverage_score": verdict.coverage_score,
        "grounding_score": verdict.grounding_score,
        "source_diversity_score": verdict.source_diversity_score,
        "conflict_score": verdict.conflict_score,
        "structure_score": verdict.structure_score,
    }
    return min(scores, key=scores.get)
