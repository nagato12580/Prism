from __future__ import annotations

from .schemas import EvidencePoolSnapshot, EvidenceRecord


_STRATEGY_PENALTIES = {
    "source_backtrack": 0.0,
    "pku_requery": 0.03,
    "scoped_chunk_search": 0.04,
    "pku_graph_expansion": 0.08,
    "ckp_rescope": 0.10,
    "global_fallback": 0.18,
}

_RELATION_PENALTIES = {
    "same_as": 0.0,
    "defines": 0.0,
    "supports": 0.0,
    "contains": 0.01,
    "part_of": 0.01,
    "related_to": 0.08,
}


class EvidencePool:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str], EvidenceRecord] = {}

    def add_many(self, records: list[EvidenceRecord]) -> None:
        for record in records:
            scored = self._score_record(record)
            key = scored.dedupe_key()
            current = self._records.get(key)
            if current is None or scored.final_score > current.final_score:
                self._records[key] = scored

    def snapshot(self, limit: int | None = None) -> EvidencePoolSnapshot:
        records = sorted(
            self._records.values(),
            key=lambda item: (item.final_score, item.retrieval_score, item.evidence_id),
            reverse=True,
        )
        if limit is not None:
            records = records[:limit]

        grouped_by_ckp: dict[str, list[EvidenceRecord]] = {}
        grouped_by_source: dict[str, list[EvidenceRecord]] = {}
        for record in records:
            if record.ckp_id:
                grouped_by_ckp.setdefault(record.ckp_id, []).append(record)
            if record.source_id:
                grouped_by_source.setdefault(record.source_id, []).append(record)

        return EvidencePoolSnapshot(
            total_count=len(self._records),
            records=records,
            grouped_by_ckp=grouped_by_ckp,
            grouped_by_source=grouped_by_source,
        )

    def _score_record(self, record: EvidenceRecord) -> EvidenceRecord:
        base_score = (
            _clamp(record.retrieval_score) * 0.35
            + _clamp(record.relation_confidence) * 0.25
            + _clamp(record.knowledge_confidence) * 0.20
            + _clamp(record.source_quality) * 0.15
            + _clamp(record.coverage_bonus) * 0.05
        )
        distance_penalty = min(max(record.scope_distance, 0) * 0.03, 0.18)
        strategy_penalty = _STRATEGY_PENALTIES.get(record.strategy, 0.06)
        relation_penalty = _RELATION_PENALTIES.get(record.relation_type, 0.04)
        if record.relation_type == "contradicts":
            relation_penalty = 0.0
        final_score = max(base_score - distance_penalty - strategy_penalty - relation_penalty, 0.0)
        return record.model_copy(update={"final_score": round(final_score, 4)})


def _clamp(value: float) -> float:
    return max(0.0, min(float(value or 0.0), 1.0))
