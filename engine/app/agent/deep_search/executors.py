from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeFile

from .schemas import EvidenceRecord, ScopeResult


SessionFactory = Callable[[], Any]


def _terms(query: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
        if len(term) > 1
    ]


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {val}" for key, val in value.items())
    return str(value)


def _contains_score(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for term in terms if term in lowered)
    return hits / len(terms)


def _source_quality(source_kind: str) -> float:
    if source_kind == "document_chunk":
        return 1.0
    if source_kind == "personal_asset_unit":
        return 0.85
    if source_kind:
        return 0.7
    return 0.0


class ScopeFinderExecutor:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def run(self, query: str, limit: int = 8) -> ScopeResult:
        terms = _terms(query)
        db = self._session_factory()
        try:
            ckps = (
                db.query(CanonicalKnowledgePoint)
                .filter(
                    CanonicalKnowledgePoint.user_id == "default-user",
                    CanonicalKnowledgePoint.status != "deprecated",
                )
                .limit(max(limit * 8, 40))
                .all()
            )
            ckp_scores = []
            for ckp in ckps:
                text = " ".join(
                    [
                        ckp.title or "",
                        ckp.canonical_statement or "",
                        ckp.summary or "",
                        _json_text(ckp.keywords),
                        _json_text(ckp.concepts),
                        _json_text(ckp.entities),
                    ]
                )
                score = _contains_score(text, terms)
                if score > 0:
                    ckp_scores.append((ckp, score))
            ckp_scores.sort(key=lambda item: (item[1], item[0].confidence or 0.0), reverse=True)
            seed_ckp_ids = [str(ckp.id) for ckp, _score in ckp_scores[:limit]]

            pkus = (
                db.query(PersonalKnowledgeUnit)
                .filter(
                    PersonalKnowledgeUnit.user_id == "default-user",
                    PersonalKnowledgeUnit.status == "active",
                )
                .limit(max(limit * 12, 60))
                .all()
            )
            pku_scores = []
            for pku in pkus:
                text = " ".join(
                    [
                        pku.statement or "",
                        pku.evidence_span or "",
                        _json_text(pku.keywords),
                        _json_text(pku.concepts),
                        _json_text(pku.entities),
                    ]
                )
                score = _contains_score(text, terms)
                if score > 0:
                    pku_scores.append((pku, score))
            pku_scores.sort(key=lambda item: (item[1], item[0].confidence or 0.0), reverse=True)
            seed_pku_ids = [str(pku.id) for pku, _score in pku_scores[:limit]]

            candidate_item_ids, candidate_topic_ids = _candidate_source_ids(db, seed_pku_ids)
            return ScopeResult(
                query=query,
                seed_ckp_ids=seed_ckp_ids,
                seed_pku_ids=seed_pku_ids,
                candidate_item_ids=candidate_item_ids,
                candidate_topic_ids=candidate_topic_ids,
                reasons=[f"terms={','.join(terms)}"] if terms else [],
            )
        finally:
            db.close()


class SourceBacktrackExecutor:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def run(self, scope: ScopeResult, limit: int = 20) -> list[EvidenceRecord]:
        db = self._session_factory()
        try:
            query = db.query(PKUCanonicalLink).join(PersonalKnowledgeUnit)
            if scope.seed_pku_ids or scope.seed_ckp_ids:
                filters = []
                if scope.seed_pku_ids:
                    filters.append(PKUCanonicalLink.pku_id.in_(scope.seed_pku_ids))
                if scope.seed_ckp_ids:
                    filters.append(PKUCanonicalLink.canonical_id.in_(scope.seed_ckp_ids))
                query = query.filter(*filters)
            links = query.limit(limit).all()
            return [_record_from_link(link, "source_backtrack", 0, 0.75) for link in links if link.pku]
        finally:
            db.close()


class PkuGraphExpansionExecutor:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def run(self, seed_pku_ids: list[str], limit: int = 12) -> list[EvidenceRecord]:
        if not seed_pku_ids:
            return []
        db = self._session_factory()
        try:
            relations = (
                db.query(PKURelation)
                .filter(
                    (PKURelation.source_pku_id.in_(seed_pku_ids))
                    | (PKURelation.target_pku_id.in_(seed_pku_ids))
                )
                .limit(limit)
                .all()
            )
            target_ids: list[str] = []
            relation_by_target: dict[str, PKURelation] = {}
            for relation in relations:
                candidate = relation.target_pku_id if relation.source_pku_id in seed_pku_ids else relation.source_pku_id
                if candidate in seed_pku_ids:
                    continue
                target_ids.append(str(candidate))
                relation_by_target[str(candidate)] = relation

            if not target_ids:
                return []
            links = (
                db.query(PKUCanonicalLink)
                .filter(PKUCanonicalLink.pku_id.in_(target_ids))
                .limit(limit)
                .all()
            )
            records = []
            for link in links:
                relation = relation_by_target.get(str(link.pku_id))
                relation_type = relation.relation_type if relation else link.relation_type
                confidence = relation.confidence if relation else link.confidence
                records.append(
                    _record_from_link(
                        link,
                        "pku_graph_expansion",
                        1,
                        0.55,
                        relation_type=relation_type,
                        relation_confidence=float(confidence or 0.0),
                    )
                )
            return records
        finally:
            db.close()


class PkuRequeryExecutor:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def run(self, query: str, seed_ckp_ids: list[str], limit: int = 12) -> list[EvidenceRecord]:
        if not seed_ckp_ids:
            return []
        terms = _terms(query)
        db = self._session_factory()
        try:
            links = (
                db.query(PKUCanonicalLink)
                .join(PersonalKnowledgeUnit)
                .filter(PKUCanonicalLink.canonical_id.in_(seed_ckp_ids))
                .limit(max(limit * 4, 24))
                .all()
            )
            scored = []
            for link in links:
                pku = link.pku
                if not pku or pku.status != "active":
                    continue
                text = " ".join([pku.statement or "", pku.evidence_span or "", _json_text(pku.keywords), _json_text(pku.concepts)])
                score = _contains_score(text, terms)
                if score > 0:
                    scored.append((link, score))
            scored.sort(key=lambda item: (item[1], item[0].confidence or 0.0), reverse=True)
            return [
                _record_from_link(link, "pku_requery", 0, score)
                for link, score in scored[:limit]
            ]
        finally:
            db.close()


def _candidate_source_ids(db: Any, pku_ids: list[str]) -> tuple[list[str], list[str]]:
    if not pku_ids:
        return [], []
    pkus = db.query(PersonalKnowledgeUnit).filter(PersonalKnowledgeUnit.id.in_(pku_ids)).all()
    chunk_ids = [str(pku.source_id) for pku in pkus if pku.source_kind == "document_chunk" and pku.source_id]
    if not chunk_ids:
        return [], []
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
    item_ids = sorted({str(chunk.item_id) for chunk in chunks if chunk.item_id})
    files = db.query(KnowledgeFile).filter(KnowledgeFile.item_id.in_(item_ids)).all() if item_ids else []
    topic_ids = sorted({str(file.topic_id) for file in files if file.topic_id})
    return item_ids, topic_ids


def _record_from_link(
    link: PKUCanonicalLink,
    strategy: str,
    scope_distance: int,
    retrieval_score: float,
    *,
    relation_type: str | None = None,
    relation_confidence: float | None = None,
) -> EvidenceRecord:
    pku = link.pku
    ckp = link.canonical
    return EvidenceRecord(
        evidence_id=f"{strategy}:{link.id}",
        strategy=strategy,
        source_kind=str(pku.source_kind or ""),
        source_id=str(pku.source_id or ""),
        pku_id=str(pku.id),
        ckp_id=str(link.canonical_id),
        title=ckp.title if ckp else "",
        statement=str(pku.statement or ""),
        snippet=str(pku.evidence_span or pku.statement or ""),
        relation_type=relation_type or link.relation_type or "same_as",
        retrieval_score=float(retrieval_score or 0.0),
        relation_confidence=float(relation_confidence if relation_confidence is not None else (link.confidence or 0.0)),
        knowledge_confidence=float(pku.confidence or 0.0),
        source_quality=_source_quality(str(pku.source_kind or "")),
        coverage_bonus=0.1 if pku.evidence_span else 0.0,
        scope_distance=scope_distance,
    )
