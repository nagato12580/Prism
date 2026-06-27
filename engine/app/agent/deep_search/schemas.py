from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DepthMode = Literal["quick", "standard", "deep"]


class DeepSearchConfig(BaseModel):
    depth: DepthMode = "standard"
    max_iterations: int = 3
    evidence_limit: int = 12
    scope_limit: int = 8


class ScopeResult(BaseModel):
    query: str
    seed_ckp_ids: list[str] = Field(default_factory=list)
    seed_pku_ids: list[str] = Field(default_factory=list)
    candidate_item_ids: list[str] = Field(default_factory=list)
    candidate_topic_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class EvidenceRecord(BaseModel):
    evidence_id: str
    strategy: str
    source_kind: str = ""
    source_id: str = ""
    pku_id: str | None = None
    ckp_id: str | None = None
    item_id: str | None = None
    topic_id: str | None = None
    title: str = ""
    statement: str = ""
    snippet: str = ""
    relation_type: str = "same_as"
    retrieval_score: float = 0.0
    relation_confidence: float = 0.0
    knowledge_confidence: float = 0.0
    source_quality: float = 0.0
    coverage_bonus: float = 0.0
    scope_distance: int = 0
    final_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def dedupe_key(self) -> tuple[str, str, str, str]:
        return (
            self.source_kind,
            self.source_id,
            self.pku_id or "",
            self.ckp_id or "",
        )

    def source_payload(self) -> dict[str, Any]:
        payload = {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "item_id": self.item_id or "",
            "display_type": self.source_kind,
            "display_id": self.source_id,
            "display_title": self.title,
            "display_label": self.source_kind or "source",
            "snippet": self.snippet or self.statement,
            "score": self.final_score,
            "raw_score": self.retrieval_score,
        }
        if self.source_kind == "document_chunk":
            payload["chunk_id"] = self.source_id
        return payload


class EvidencePoolSnapshot(BaseModel):
    total_count: int
    records: list[EvidenceRecord]
    grouped_by_ckp: dict[str, list[EvidenceRecord]] = Field(default_factory=dict)
    grouped_by_source: dict[str, list[EvidenceRecord]] = Field(default_factory=dict)


class SearchDirective(BaseModel):
    strategy: str
    query: str = ""
    reason: str = ""
    limit: int = 8
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgeVerdict(BaseModel):
    status: Literal["complete", "incomplete"] = "incomplete"
    coverage_score: float = 0.0
    grounding_score: float = 0.0
    source_diversity_score: float = 0.0
    conflict_score: float = 0.0
    structure_score: float = 0.0
    overall_score: float = 0.0
    missing: list[str] = Field(default_factory=list)
    directives: list[SearchDirective] = Field(default_factory=list)
