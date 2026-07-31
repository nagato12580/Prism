# prism/backend/app/services/graph_facts.py
"""Transaction-owned writer for scoped graph facts.

Settles extracted ``EntityCandidate`` objects into scoped MySQL facts
(Entity/Alias/Mention/Relation) and appends the corresponding Outbox events in
the *same* transaction. Extraction is idempotent per
``(tenant, kb, chunk, content_hash, extractor_config_hash)``: a repeated settle
of the same content/config returns the existing revision and emits no new
events.

This service only ``flush()``es; it never ``commit()``s or ``rollback()``s —
the caller owns the transaction so fact changes and Outbox events commit (or
roll back) atomically.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from backend.app.models.graph_outbox import GraphExtractionRevision
from backend.app.models import (
    EntityAlias,
    EntityMention,
    EntityRelation,
    KnowledgeEntity,
)
from backend.app.services.entity_extraction import EntityCandidate
from backend.app.services.graph_outbox import GraphOutboxService

_ENTITY_TEXT_MAX = 512


def _bounded_text(value: str, *, limit: int = _ENTITY_TEXT_MAX) -> str:
    return (value or "")[:limit]


def _bounded_aliases(values: list[str], *, limit: int = _ENTITY_TEXT_MAX) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        bounded = _bounded_text(value, limit=limit)
        if not bounded or bounded in seen:
            continue
        seen.add(bounded)
        deduped.append(bounded)
    return deduped


@dataclass(frozen=True)
class GraphFactScope:
    tenant_id: str
    kb_uid: str
    file_uid: str
    item_id: str
    chunk_uid: str
    graph_generation: str


@dataclass(frozen=True)
class SettleResult:
    revision_id: str
    event_count: int


class GraphFactWriter:
    def __init__(self, db) -> None:
        self.db = db
        self.outbox = GraphOutboxService(db)

    # -- extraction identity ---------------------------------------------- #

    def extraction_key(
        self, scope: GraphFactScope, content_hash: str, extractor_config_hash: str
    ) -> str:
        raw = "|".join(
            (scope.tenant_id, scope.kb_uid, scope.chunk_uid, content_hash, extractor_config_hash)
        )
        return sha256(raw.encode("utf-8")).hexdigest()

    def _entity_user_id(self, scope: GraphFactScope) -> str:
        raw = "|".join(
            (
                scope.tenant_id,
                scope.kb_uid,
                scope.graph_generation,
                "scoped-entity",
            )
        )
        return str(uuid5(NAMESPACE_URL, raw))

    def _get_or_create_revision(
        self,
        scope: GraphFactScope,
        content_hash: str,
        extractor_config_hash: str,
        model_version: str = "",
        prompt_version: str = "",
    ) -> tuple[GraphExtractionRevision, bool]:
        existing = (
            self.db.query(GraphExtractionRevision)
            .filter(
                GraphExtractionRevision.tenant_id == scope.tenant_id,
                GraphExtractionRevision.kb_uid == scope.kb_uid,
                GraphExtractionRevision.chunk_uid == scope.chunk_uid,
                GraphExtractionRevision.content_hash == content_hash,
                GraphExtractionRevision.extractor_config_hash == extractor_config_hash,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing, False
        revision = GraphExtractionRevision(
            tenant_id=scope.tenant_id,
            kb_uid=scope.kb_uid,
            file_uid=scope.file_uid,
            item_id=scope.item_id,
            chunk_uid=scope.chunk_uid,
            graph_generation=scope.graph_generation,
            content_hash=content_hash,
            extractor_config_hash=extractor_config_hash,
            status="running",
            model_version=model_version,
            prompt_version=prompt_version,
        )
        self.db.add(revision)
        self.db.flush()
        return revision, True

    # -- settlement ------------------------------------------------------- #

    def settle(
        self,
        scope: GraphFactScope,
        candidates: list[EntityCandidate],
        content_hash: str,
        extractor_config_hash: str,
        model_version: str = "",
        prompt_version: str = "",
    ) -> SettleResult:
        """Persist scoped facts + Outbox events idempotently.

        Returns a ``SettleResult`` with the revision id and the number of
        Outbox events appended this call. A repeated call for an already
        succeeded revision appends zero events.
        """
        revision, created = self._get_or_create_revision(
            scope, content_hash, extractor_config_hash, model_version, prompt_version
        )
        if revision.status == "succeeded":
            return SettleResult(revision_id=revision.revision_id, event_count=0)

        events_before = self._count_outbox()
        settled = self._upsert_scoped_facts(scope, revision.revision_id, candidates)
        for fact_kind, fact_id, event_type, payload in settled:
            self.outbox.append_fact_change(
                tenant_id=scope.tenant_id,
                kb_uid=scope.kb_uid,
                graph_generation=scope.graph_generation,
                aggregate_type=fact_kind,
                aggregate_id=fact_id,
                event_type=event_type,
                payload=payload,
            )
        events_after = self._count_outbox()
        revision.status = "succeeded"
        self.db.flush()
        return SettleResult(revision_id=revision.revision_id, event_count=events_after - events_before)

    # -- scoped upserts --------------------------------------------------- #

    def _upsert_scoped_facts(
        self,
        scope: GraphFactScope,
        revision_id: str,
        candidates: list[EntityCandidate],
    ) -> list[tuple[str, str, str, dict[str, Any]]]:
        changes: list[tuple[str, str, str, dict[str, Any]]] = []
        settled_by_surface: dict[tuple[str, str], KnowledgeEntity] = {}

        for candidate in candidates:
            if candidate.kind != "entity":
                continue
            entity = self._upsert_entity(scope, candidate)
            self._upsert_aliases(scope, entity, candidate)
            mention = self._upsert_mention(scope, entity, candidate, revision_id)
            settled_by_surface[(candidate.entity_type, candidate.surface_text)] = entity
            changes.append(
                (
                    "entity",
                    entity.id,
                    "entity.upserted",
                    self._entity_payload(scope, entity, mention),
                )
            )
            changes.append(
                (
                    "mention",
                    mention.id,
                    "mention.upserted",
                    self._mention_payload(scope, mention, candidate),
                )
            )

        for candidate in candidates:
            if candidate.kind != "relation":
                continue
            subject = self._resolve_entity(scope, settled_by_surface, candidate.subject_surface)
            obj = self._resolve_entity(
                scope, settled_by_surface, candidate.object_surface, candidate.object_entity_type
            )
            if subject and obj:
                relation = self._upsert_relation(scope, subject, obj, candidate, revision_id)
                changes.append(
                    (
                        "relation",
                        relation.id,
                        "relation.upserted",
                        self._relation_payload(scope, relation, candidate),
                    )
                )

        self.db.flush()
        return changes

    def _upsert_entity(self, scope: GraphFactScope, candidate: EntityCandidate) -> KnowledgeEntity:
        canonical_name = _bounded_text(candidate.surface_text)
        normalized_key = _bounded_text(candidate.normalized_key)
        aliases = _bounded_aliases(list(candidate.aliases))
        entity = (
            self.db.query(KnowledgeEntity)
            .filter(
                KnowledgeEntity.tenant_id == scope.tenant_id,
                KnowledgeEntity.kb_uid == scope.kb_uid,
                KnowledgeEntity.graph_generation == scope.graph_generation,
                KnowledgeEntity.entity_type == candidate.entity_type,
                KnowledgeEntity.normalized_key == normalized_key,
            )
            .one_or_none()
        )
        if entity is None:
            entity = KnowledgeEntity(
                tenant_id=scope.tenant_id,
                kb_uid=scope.kb_uid,
                graph_generation=scope.graph_generation,
                user_id=self._entity_user_id(scope),
                entity_type=candidate.entity_type,
                canonical_name=canonical_name,
                normalized_key=normalized_key,
                aliases=aliases,
                confidence=candidate.confidence,
                status="active",
            )
            self.db.add(entity)
            self.db.flush()
        else:
            entity.canonical_name = canonical_name
            entity.aliases = _bounded_aliases(list(entity.aliases or []) + aliases)
            entity.confidence = max(entity.confidence or 0.0, candidate.confidence)
        return entity

    def _upsert_aliases(self, scope: GraphFactScope, entity: KnowledgeEntity, candidate: EntityCandidate) -> None:
        for alias_key in _bounded_aliases(list(candidate.aliases)):
            existing = (
                self.db.query(EntityAlias)
                .filter(
                    EntityAlias.entity_id == entity.id,
                    EntityAlias.normalized_key == alias_key,
                )
                .one_or_none()
            )
            if existing is not None:
                continue
            self.db.add(
                EntityAlias(
                    entity_id=entity.id,
                    tenant_id=scope.tenant_id,
                    kb_uid=scope.kb_uid,
                    graph_generation=scope.graph_generation,
                    alias=alias_key,
                    normalized_key=alias_key,
                    confidence=candidate.confidence,
                    extraction_method=candidate.extraction_method,
                )
            )

    def _upsert_mention(
        self, scope: GraphFactScope, entity: KnowledgeEntity, candidate: EntityCandidate, revision_id: str
    ) -> EntityMention:
        mention = (
            self.db.query(EntityMention)
            .filter(
                EntityMention.tenant_id == scope.tenant_id,
                EntityMention.kb_uid == scope.kb_uid,
                EntityMention.graph_generation == scope.graph_generation,
                EntityMention.entity_id == entity.id,
                EntityMention.source_kind == "document_chunk",
                EntityMention.source_id == scope.chunk_uid,
            )
            .one_or_none()
        )
        if mention is None:
            surface_text = _bounded_text(candidate.surface_text)
            normalized_key = _bounded_text(candidate.normalized_key)
            mention = EntityMention(
                entity_id=entity.id,
                tenant_id=scope.tenant_id,
                kb_uid=scope.kb_uid,
                graph_generation=scope.graph_generation,
                file_uid=scope.file_uid,
                chunk_uid=scope.chunk_uid,
                revision_id=revision_id,
                active="true",
                source_kind="document_chunk",
                source_id=scope.chunk_uid,
                item_id=scope.item_id,
                chunk_id=scope.chunk_uid,
                surface_text=surface_text,
                normalized_key=normalized_key,
                evidence_span=candidate.evidence_span,
                confidence=candidate.confidence,
                extraction_method=candidate.extraction_method,
            )
            self.db.add(mention)
            self.db.flush()
        return mention

    def _upsert_relation(
        self,
        scope: GraphFactScope,
        subject: KnowledgeEntity,
        obj: KnowledgeEntity,
        candidate: EntityCandidate,
        revision_id: str,
    ) -> EntityRelation:
        relation = (
            self.db.query(EntityRelation)
            .filter(
                EntityRelation.tenant_id == scope.tenant_id,
                EntityRelation.kb_uid == scope.kb_uid,
                EntityRelation.graph_generation == scope.graph_generation,
                EntityRelation.subject_entity_id == subject.id,
                EntityRelation.predicate == candidate.predicate,
                EntityRelation.object_entity_id == obj.id,
                EntityRelation.source_kind == "document_chunk",
                EntityRelation.source_id == scope.chunk_uid,
            )
            .one_or_none()
        )
        if relation is None:
            relation = EntityRelation(
                subject_entity_id=subject.id,
                tenant_id=scope.tenant_id,
                kb_uid=scope.kb_uid,
                graph_generation=scope.graph_generation,
                file_uid=scope.file_uid,
                revision_id=revision_id,
                active="true",
                predicate=candidate.predicate,
                object_entity_id=obj.id,
                source_kind="document_chunk",
                source_id=scope.chunk_uid,
                evidence_span=candidate.evidence_span,
                confidence=candidate.confidence,
                extraction_method=candidate.extraction_method,
            )
            self.db.add(relation)
            self.db.flush()
        return relation

    def _resolve_entity(
        self,
        scope: GraphFactScope,
        settled_by_surface: dict[tuple[str, str], KnowledgeEntity],
        surface: str,
        entity_type: str = "",
    ) -> KnowledgeEntity | None:
        if not surface:
            return None
        direct = settled_by_surface.get((entity_type, surface)) or settled_by_surface.get(("", surface))
        if direct is not None:
            return direct
        query = self.db.query(KnowledgeEntity).filter(
            KnowledgeEntity.tenant_id == scope.tenant_id,
            KnowledgeEntity.kb_uid == scope.kb_uid,
            KnowledgeEntity.graph_generation == scope.graph_generation,
            KnowledgeEntity.canonical_name == surface,
            KnowledgeEntity.status == "active",
        )
        if entity_type:
            query = query.filter(KnowledgeEntity.entity_type == entity_type)
        return query.first()

    # -- payloads (public, de-tenantized for projection) ------------------ #

    def _entity_payload(self, scope: GraphFactScope, entity: KnowledgeEntity, mention: EntityMention) -> dict[str, Any]:
        return {
            "entity_id": entity.id,
            "entity_type": entity.entity_type,
            "normalized_key": entity.normalized_key,
            "canonical_name": entity.canonical_name,
            "aliases": list(entity.aliases or []),
            "mention_id": mention.id,
            "file_uid": scope.file_uid,
            "chunk_uid": scope.chunk_uid,
            "confidence": entity.confidence,
        }

    def _mention_payload(self, scope: GraphFactScope, mention: EntityMention, candidate: EntityCandidate) -> dict[str, Any]:
        return {
            "mention_id": mention.id,
            "entity_id": mention.entity_id,
            "file_uid": scope.file_uid,
            "chunk_uid": scope.chunk_uid,
            "surface_text": candidate.surface_text,
            "normalized_key": candidate.normalized_key,
            "evidence_span": (candidate.evidence_span or "")[:500],
            "confidence": candidate.confidence,
        }

    def _relation_payload(self, scope: GraphFactScope, relation: EntityRelation, candidate: EntityCandidate) -> dict[str, Any]:
        return {
            "relation_id": relation.id,
            "subject_entity_id": relation.subject_entity_id,
            "object_entity_id": relation.object_entity_id,
            "predicate": relation.predicate,
            "file_uid": scope.file_uid,
            "chunk_uid": scope.chunk_uid,
            "evidence_span": (candidate.evidence_span or "")[:500],
            "confidence": candidate.confidence,
        }

    def _count_outbox(self) -> int:
        from backend.app.models.graph_outbox import GraphOutboxEvent

        return self.db.query(GraphOutboxEvent).count()
