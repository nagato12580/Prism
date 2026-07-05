from dataclasses import dataclass

from sqlalchemy import or_

from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    EntityAlias,
    EntityMention,
    EntityRelation,
    KnowledgeEntity,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalAssetUnit,
    PersonalKnowledgeUnit,
)


@dataclass
class GraphProjectionResult:
    ckp_count: int = 0
    pku_count: int = 0
    entity_count: int = 0
    alias_count: int = 0
    source_count: int = 0
    relation_count: int = 0
    pku_entity_mention_count: int = 0


PARENT_TARGET_RELATIONS = {"parent", "part_of", "subtopic_of"}
PARENT_SOURCE_RELATIONS = {"child", "has_child", "includes", "hierarchy"}
ENTITY_RELATION_TYPES = {
    "authored": "AUTHORED",
    "affiliated_with": "AFFILIATED_WITH",
    "educated_at": "EDUCATED_AT",
    "has_email": "HAS_EMAIL",
    "co_author": "CO_AUTHOR",
}


def project_ckp_graph(db, graph, user_id: str = "default-user", *, ckp_ids: set[str] | None = None, pku_ids: set[str] | None = None) -> GraphProjectionResult:
    result = GraphProjectionResult()

    ckp_query = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.user_id == user_id,
            CanonicalKnowledgePoint.status != "deprecated",
        )
    )
    if ckp_ids is not None:
        ckp_query = ckp_query.filter(CanonicalKnowledgePoint.id.in_(ckp_ids))
    ckps = ckp_query.all()
    active_ckp_ids = {ckp.id for ckp in ckps}
    for ckp in ckps:
        graph.upsert_ckp(
            {
                "id": ckp.id,
                "user_id": ckp.user_id,
                "title": ckp.title,
                "ckp_type": ckp.canonical_type,
                "status": ckp.status,
                "confidence": ckp.confidence,
            }
        )
        result.ckp_count += 1

    pku_query = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == user_id,
            PersonalKnowledgeUnit.status != "deprecated",
        )
    )
    if pku_ids is not None:
        pku_query = pku_query.filter(PersonalKnowledgeUnit.id.in_(pku_ids))
    pkus = pku_query.all()
    active_pku_ids = {pku.id for pku in pkus}
    seen_source_ids = set()
    for pku in pkus:
        graph.upsert_pku(
            {
                "id": pku.id,
                "user_id": pku.user_id,
                "unit_type": pku.unit_type,
                "statement_hash": pku.normalized_statement_hash,
                "confidence": pku.confidence,
                "status": pku.status,
            }
        )
        result.pku_count += 1

        source_node = _source_node_for_pku(db, pku, user_id)
        if source_node["id"] not in seen_source_ids:
            graph.upsert_source(source_node)
            seen_source_ids.add(source_node["id"])
            result.source_count += 1
        graph.relate(
            "PKU",
            pku.id,
            "EVIDENCED_BY",
            "Source",
            source_node["id"],
            {"source_kind": pku.source_kind, "source_id": pku.source_id},
        )
        result.relation_count += 1

    ckp_rel_query = db.query(CanonicalRelation).filter(CanonicalRelation.user_id == user_id)
    if ckp_ids is not None:
        ckp_rel_query = ckp_rel_query.filter(
            or_(
                CanonicalRelation.source_canonical_id.in_(ckp_ids),
                CanonicalRelation.target_canonical_id.in_(ckp_ids),
            )
        )
    ckp_relations = ckp_rel_query.all()
    for relation in ckp_relations:
        if ckp_ids is None and (
            relation.source_canonical_id not in active_ckp_ids
            or relation.target_canonical_id not in active_ckp_ids
        ):
            continue

        props = _relation_props(relation, ["relation_type", "confidence", "reason"])
        if relation.relation_type in PARENT_TARGET_RELATIONS:
            graph.relate(
                "CKP",
                relation.target_canonical_id,
                "HAS_CHILD",
                "CKP",
                relation.source_canonical_id,
                props,
            )
        elif relation.relation_type in PARENT_SOURCE_RELATIONS:
            graph.relate(
                "CKP",
                relation.source_canonical_id,
                "HAS_CHILD",
                "CKP",
                relation.target_canonical_id,
                props,
            )
        else:
            graph.relate(
                "CKP",
                relation.source_canonical_id,
                "RELATED_TO",
                "CKP",
                relation.target_canonical_id,
                props,
            )
        result.relation_count += 1

    link_query = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.user_id == user_id)
    if ckp_ids is not None or pku_ids is not None:
        link_filters = []
        if ckp_ids is not None:
            link_filters.append(PKUCanonicalLink.canonical_id.in_(ckp_ids))
        if pku_ids is not None:
            link_filters.append(PKUCanonicalLink.pku_id.in_(pku_ids))
        if len(link_filters) > 1:
            link_query = link_query.filter(or_(*link_filters))
        else:
            link_query = link_query.filter(link_filters[0])
    links = link_query.all()
    for link in links:
        if ckp_ids is None and (link.canonical_id not in active_ckp_ids or link.pku_id not in active_pku_ids):
            continue
        graph.relate(
            "CKP",
            link.canonical_id,
            "SUPPORTED_BY",
            "PKU",
            link.pku_id,
            _relation_props(link, ["relation_type", "role", "confidence", "reason"]),
        )
        result.relation_count += 1

    pku_rel_query = db.query(PKURelation).filter(PKURelation.user_id == user_id)
    if pku_ids is not None:
        pku_rel_query = pku_rel_query.filter(
            or_(
                PKURelation.source_pku_id.in_(pku_ids),
                PKURelation.target_pku_id.in_(pku_ids),
            )
        )
    pku_relations = pku_rel_query.all()
    for relation in pku_relations:
        if pku_ids is None and (
            relation.source_pku_id not in active_pku_ids
            or relation.target_pku_id not in active_pku_ids
        ):
            continue
        graph.relate(
            "PKU",
            relation.source_pku_id,
            "RELATED_TO",
            "PKU",
            relation.target_pku_id,
            _relation_props(
                relation,
                ["relation_type", "confidence", "reason", "source_kind", "source_id"],
            ),
        )
        result.relation_count += 1

    return result


def project_entity_graph(db, graph, user_id: str = "default-user", *, entity_ids: set[str] | None = None) -> GraphProjectionResult:
    result = GraphProjectionResult()

    entity_query = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.status != "deprecated",
        )
    )
    if entity_ids is not None:
        entity_query = entity_query.filter(KnowledgeEntity.id.in_(entity_ids))
    entities = entity_query.all()
    active_entity_ids = {entity.id for entity in entities}
    for entity in entities:
        graph.upsert_entity(
            {
                "id": entity.id,
                "user_id": entity.user_id,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "normalized_key": entity.normalized_key,
                "status": entity.status,
                "confidence": entity.confidence,
            }
        )
        result.entity_count += 1

    aliases = db.query(EntityAlias).filter(EntityAlias.entity_id.in_(active_entity_ids)).all()
    for alias in aliases:
        graph.upsert_alias(
            {
                "id": alias.id,
                "key": alias.normalized_key,
                "surface_text": alias.alias,
                "entity_id": alias.entity_id,
            }
        )
        result.alias_count += 1
        result.relation_count += 1

    seen_source_ids = set()
    mentions = db.query(EntityMention).filter(EntityMention.entity_id.in_(active_entity_ids)).all()
    for mention in mentions:
        source_node = _source_node_for_mention(db, mention, user_id)
        if source_node["id"] not in seen_source_ids:
            graph.upsert_source(source_node)
            seen_source_ids.add(source_node["id"])
            result.source_count += 1
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_node["id"],
            _relation_props(
                mention,
                [
                    "confidence",
                    "evidence_span",
                    "extraction_method",
                    "source_kind",
                    "source_id",
                ],
            ),
        )
        result.relation_count += 1

    entity_rel_query = db.query(EntityRelation)
    if entity_ids is not None:
        entity_rel_query = entity_rel_query.filter(
            or_(
                EntityRelation.subject_entity_id.in_(entity_ids),
                EntityRelation.object_entity_id.in_(entity_ids),
            )
        )
    else:
        entity_rel_query = entity_rel_query.filter(EntityRelation.subject_entity_id.in_(active_entity_ids))
    relations = entity_rel_query.all()
    for relation in relations:
        if entity_ids is None and (not relation.object_entity_id or relation.object_entity_id not in active_entity_ids):
            continue
        graph.relate(
            "Entity",
            relation.subject_entity_id,
            ENTITY_RELATION_TYPES.get(relation.predicate, "RELATED_TO"),
            "Entity",
            relation.object_entity_id,
            _relation_props(
                relation,
                [
                    "predicate",
                    "confidence",
                    "evidence_span",
                    "extraction_method",
                    "source_kind",
                    "source_id",
                ],
            ),
        )
        result.relation_count += 1

    return result


def project_pku_entity_mentions(db, graph, user_id: str = "default-user", *, pku_ids: set[str] | None = None, entity_ids: set[str] | None = None) -> GraphProjectionResult:
    """Bridge the entity subgraph and the CKP/PKU subgraph.

    Entity extraction and PKU extraction both consume the same source text
    (chunk / asset unit), so ``EntityMention.source_id`` and
    ``PersonalKnowledgeUnit.source_id`` share the same value when they
    originate from the same source.  This function joins them by
    ``(source_kind, source_id)`` and creates ``PKU -[:MENTIONS_ENTITY]-> Entity``
    edges, turning the previously implicit 3-hop ``Entity→Source←PKU←CKP``
    path into an explicit 1-hop ``Entity←MENTIONS_ENTITY←PKU←CKP`` path.

    Child-to-parent rollup: PKU extraction runs only on parent chunks, while
    entity extraction runs on both parent and child chunks.  To maximize the
    bridge coverage, entity mentions found on child chunks are rolled up to
    their parent chunk before matching against PKU ``source_id``.
    """
    result = GraphProjectionResult()

    pku_query = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == user_id,
            PersonalKnowledgeUnit.status != "deprecated",
        )
    )
    if pku_ids is not None:
        pku_query = pku_query.filter(PersonalKnowledgeUnit.id.in_(pku_ids))
    pkus = pku_query.all()
    if not pkus:
        return result

    mention_query = (
        db.query(EntityMention, KnowledgeEntity)
        .join(KnowledgeEntity, EntityMention.entity_id == KnowledgeEntity.id)
        .filter(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.status != "deprecated",
        )
    )
    if entity_ids is not None:
        mention_query = mention_query.filter(KnowledgeEntity.id.in_(entity_ids))
    mentions = mention_query.all()
    if not mentions:
        return result

    # Collect child chunk ids that need parent lookup
    child_source_ids = {
        mention.source_id
        for mention, _ in mentions
        if mention.source_kind == "document_chunk" and mention.source_id
    }
    parent_map: dict[str, str] = {}
    if child_source_ids:
        child_chunks = (
            db.query(KnowledgeChunk.id, KnowledgeChunk.parent_id)
            .filter(
                KnowledgeChunk.id.in_(child_source_ids),
                KnowledgeChunk.parent_id.isnot(None),
            )
            .all()
        )
        parent_map = {str(c.id): str(c.parent_id) for c in child_chunks if c.parent_id}

    entities_by_source: dict[tuple[str, str], set[str]] = {}
    for mention, entity in mentions:
        source_kind = mention.source_kind or ""
        source_id = mention.source_id or ""
        if not source_id:
            continue
        # Roll up child chunk mentions to their parent chunk
        if source_kind == "document_chunk" and source_id in parent_map:
            source_id = parent_map[source_id]
        key = (source_kind, source_id)
        entities_by_source.setdefault(key, set()).add(entity.id)

    for pku in pkus:
        key = (pku.source_kind or "", pku.source_id or "")
        entity_ids = entities_by_source.get(key)
        if not entity_ids:
            continue
        for entity_id in entity_ids:
            graph.relate(
                "PKU",
                pku.id,
                "MENTIONS_ENTITY",
                "Entity",
                entity_id,
                {
                    "source_kind": pku.source_kind,
                    "source_id": pku.source_id,
                },
            )
            result.pku_entity_mention_count += 1
            result.relation_count += 1

    return result


def _source_node_for_pku(db, pku: PersonalKnowledgeUnit, user_id: str) -> dict:
    item_id = pku.source_id
    title = pku.source_id

    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if chunk:
            item_id = chunk.item_id
            item = (
                db.query(KnowledgeItem)
                .filter(
                    KnowledgeItem.id == chunk.item_id,
                    KnowledgeItem.user_id == user_id,
                )
                .first()
            )
            if item and item.title:
                title = item.title

    return {
        "id": f"{pku.source_kind}:{pku.source_id}",
        "source_kind": pku.source_kind,
        "source_id": pku.source_id,
        "item_id": item_id,
        "title": title,
    }


def _source_node_for_mention(db, mention: EntityMention, user_id: str) -> dict:
    item_id = mention.item_id or mention.source_id
    title = mention.item_id or mention.source_id

    if mention.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == mention.source_id).first()
        if chunk:
            item_id = chunk.item_id
            item = (
                db.query(KnowledgeItem)
                .filter(
                    KnowledgeItem.id == chunk.item_id,
                    KnowledgeItem.user_id == user_id,
                )
                .first()
            )
            if item and item.title:
                title = item.title
    elif mention.source_kind == "personal_asset_unit":
        unit = (
            db.query(PersonalAssetUnit)
            .filter(
                PersonalAssetUnit.id == mention.source_id,
                PersonalAssetUnit.user_id == user_id,
            )
            .first()
        )
        if unit:
            item_id = unit.id
            if unit.title:
                title = unit.title

    return {
        "id": f"{mention.source_kind}:{mention.source_id}",
        "source_kind": mention.source_kind,
        "source_id": mention.source_id,
        "item_id": item_id,
        "title": title,
    }


def _relation_props(model, names):
    return {name: getattr(model, name) for name in names}
