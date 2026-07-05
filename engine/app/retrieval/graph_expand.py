"""Graph expansion for unified GraphRAG retrieval.

Given a query, match seed Entities (by alias/normalized_key), then walk the
Neo4j graph to collect neighboring Source chunks as extra retrieval candidates.
fast mode = 1 hop; deep mode = 2 hops + same-community members + god neighbors
+ surprising-edge endpoints.
"""
import logging

from backend.app.models import EntityAlias, KnowledgeEntity
from backend.app.services.entity_resolution import normalize_entity_key

logger = logging.getLogger("uvicorn.error")


def match_seed_entities(db, query: str, limit: int = 10) -> list[str]:
    """Return up to `limit` entity ids whose alias/name matches query terms."""
    try:
        import jieba
        terms = [t for t in jieba.cut(query) if t.strip()]
    except Exception:
        terms = [t for t in query.split() if t.strip()]
    keys = {normalize_entity_key(t) for t in terms if t}

    ids: set[str] = set()

    # 1) exact token match via alias table
    if keys:
        alias_rows = (
            db.query(EntityAlias.entity_id.label("eid"))
            .filter(EntityAlias.normalized_key.in_(keys))
            .distinct()
            .limit(limit)
            .all()
        )
        ids |= {r.eid for r in alias_rows}

    # 2) exact token match via entity name
    if keys and len(ids) < limit:
        name_rows = (
            db.query(KnowledgeEntity.id)
            .filter(KnowledgeEntity.normalized_key.in_(keys))
            .limit(limit - len(ids))
            .all()
        )
        ids |= {r.id for r in name_rows}

    # 3) substring match: entity canonical name appears in query
    if len(ids) < limit:
        all_entities = (
            db.query(KnowledgeEntity.id, KnowledgeEntity.canonical_name)
            .filter(KnowledgeEntity.status == "active")
            .all()
        )
        for eid, name in all_entities:
            if name and name in query:
                ids.add(eid)
                if len(ids) >= limit:
                    break

    return list(ids)[:limit]


def _entity_community(graph, entity_id: str) -> int | None:
    try:
        return graph.entity_community(entity_id)
    except Exception:
        return None


def expand_candidates(
    db,
    graph,
    seed_entity_ids: list[str],
    mode: str,
    hops: int,
    max_candidates: int,
    neighbors_per_node: int = 8,
    community_members: int = 10,
    god_neighbors: int = 10,
) -> list[dict]:
    """Walk the graph from seeds; return [{chunk_id, item_id, source_marker}].

    Source nodes have id "document_chunk:<chunk_id>"; we strip the prefix.
    """
    candidates: list[dict] = []
    seen_chunks: set[str] = set()

    def _add_source(node_id: str, marker: str):
        if not node_id or not node_id.startswith("document_chunk:"):
            return
        chunk_id = node_id.split("document_chunk:", 1)[1]
        if chunk_id in seen_chunks:
            return
        seen_chunks.add(chunk_id)
        candidates.append({"chunk_id": chunk_id, "item_id": None, "source_marker": marker})

    def _walk(entity_id: str, marker: str, hop_limit: int):
        try:
            for n in graph.neighbors(entity_id, hops=hop_limit, limit=neighbors_per_node):
                if (n.get("kind") == "Source"):
                    _add_source(n["id"], marker)
        except Exception as exc:
            logger.warning("[graph_expand] neighbors_failed entity=%s err=%s", entity_id, exc)

    hop_marker = "graph_1hop" if mode == "fast" else "graph_2hop"

    for eid in seed_entity_ids:
        _walk(eid, hop_marker, hops)
        if mode != "deep":
            continue
        # deep-only expansions
        cid = _entity_community(graph, eid)
        if cid is not None:
            try:
                for m in graph.community_members(cid, limit=community_members):
                    _walk(m["id"], "community", hops)
            except Exception as exc:
                logger.warning("[graph_expand] community_failed err=%s", exc)
        try:
            for g in graph.god_neighbors(eid, limit=god_neighbors):
                _walk(g, "god", hops)
        except Exception as exc:
            logger.warning("[graph_expand] god_failed err=%s", exc)
        try:
            for s in graph.surprising_endpoints(eid):
                _walk(s, "surprising", hops)
        except Exception as exc:
            logger.warning("[graph_expand] surprising_failed err=%s", exc)

    return candidates[:max_candidates]
