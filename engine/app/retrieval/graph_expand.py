"""Graph expansion for unified GraphRAG retrieval.

Given a query, match seed Entities (by alias/normalized_key), then walk the
Neo4j graph to collect neighboring Sources as extra retrieval candidates.
fast mode = 1 hop; deep mode = 2 hops + same-community members + god neighbors
+ surprising-edge endpoints.
"""
import logging

from backend.app.models import EntityAlias, KnowledgeEntity
from backend.app.services.entity_resolution import normalize_entity_key
from .contracts import Candidate, ChannelResult, SearchScope
from .execution_control import RetrievalExecutionAborted, RetrievalExecutionControl

logger = logging.getLogger("uvicorn.error")


def graph_search(
    query: str, scope: SearchScope, graph_client, top_k: int, hops: int,
    control: RetrievalExecutionControl | None = None,
) -> ChannelResult:
    """Retrieve graph-backed chunks using fully scoped Cypher at every stage."""
    if not scope.graph_generation:
        return ChannelResult.failed("graph", "GRAPH_GENERATION_REQUIRED", retryable=False)
    params = {
        "search_query": query, "tenant_id": scope.tenant_id, "kb_uid": scope.kb_uid,
        "generation": scope.graph_generation, "file_uids": list(scope.file_uids),
        "source_types": list(scope.source_types), "top_k": top_k, "hops": max(1, int(hops)),
    }
    seed_query = """
    // seed_entities
    MATCH (e:ScopedEntity {tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $generation})
    WHERE toLower(e.canonical_name) CONTAINS toLower($search_query)
       OR EXISTS { MATCH (a:ScopedAlias {tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $generation})-[:ALIAS_OF]->(e)
                   WHERE toLower(a.surface_text) CONTAINS toLower($search_query) }
    RETURN DISTINCT e.id AS entity_id LIMIT $top_k
    """
    path_query = f"""
    // source_paths
    MATCH p=(e:ScopedEntity {{tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $generation}})
      -[:RELATED_TO|MENTIONED_IN*1..{max(1, int(hops))}]-(s:ScopedSource {{tenant_id: $tenant_id, kb_uid: $kb_uid, graph_generation: $generation}})
    WHERE e.id IN $entity_ids
      AND (size($file_uids) = 0 OR s.file_uid IN $file_uids)
      AND (size($source_types) = 0 OR s.source_type IN $source_types)
    RETURN DISTINCT s.chunk_uid AS chunk_uid, s.item_id AS item_id, s.file_uid AS file_uid,
           s.source_type AS source_type, 1.0 / length(p) AS score,
           [n IN nodes(p) | n.id] AS path
    ORDER BY score DESC LIMIT $top_k
    """
    try:
        if control: control.checkpoint()
        timeout = control.remaining_timeout(30) if control else None
        seeds = graph_client._execute_read(seed_query, params, **({"timeout": timeout} if control else {}))
        if control: control.checkpoint()
        seed_ids = [row["entity_id"] for row in seeds if row.get("entity_id")]
        timeout = control.remaining_timeout(30) if control else None
        rows = graph_client._execute_read(path_query, {**params, "entity_ids": seed_ids}, **({"timeout": timeout} if control else {}))
        if control: control.checkpoint()
    except RetrievalExecutionAborted:
        raise
    except Exception:
        logger.exception("[graph_search] scoped Cypher failed")
        return ChannelResult.failed("graph", "GRAPH_INDEX_UNAVAILABLE", retryable=True)

    try:
        candidates = [Candidate(
            chunk_uid=row["chunk_uid"], item_id=row.get("item_id") or "",
            file_uid=row.get("file_uid") or "", channel="graph",
            raw_score=float(row.get("score", 0.0)), raw_rank=rank,
            metadata={**row, "kb_uid": scope.kb_uid, "graph_generation": scope.graph_generation},
        ) for rank, row in enumerate(rows, 1)]
    except Exception:
        return ChannelResult.failed("graph", "GRAPH_RESPONSE_INVALID", retryable=False)
    return ChannelResult.ok("graph", candidates)


def match_seed_entities(db, query: str, limit: int = 10) -> list[str]:
    """Return up to `limit` entity ids whose alias/name matches query terms."""
    normalized_query = normalize_entity_key(query)
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
            if name and normalize_entity_key(name) in normalized_query:
                ids.add(eid)
                if len(ids) >= limit:
                    break

    return list(ids)[:limit]


def _entity_community(graph, entity_id: str) -> int | None:
    try:
        return graph.entity_community(entity_id)
    except Exception:
        return None


def _build_path_steps(entity_id: str, dedupe_key: str, evidence_type: str, marker: str) -> list[dict]:
    return [
        {"node_id": entity_id, "node_type": "entity"},
        {"edge_type": marker.upper(), "evidence_type": evidence_type},
        {"node_id": dedupe_key, "node_type": "source"},
    ]


def _route_entry(entity_id: str, marker: str, dedupe_key: str, evidence_type: str) -> dict:
    return {
        "source_marker": marker,
        "matched_entity_ids": [entity_id],
        "steps": _build_path_steps(entity_id, dedupe_key, evidence_type, marker),
    }


def _path_route_list(path: list[dict], explain: dict, source_marker: str) -> list[dict]:
    if path and isinstance(path[0], dict) and "steps" in path[0]:
        return [dict(route) for route in path]
    return [
        {
            "source_marker": source_marker,
            "matched_entity_ids": list(explain.get("matched_entity_ids") or []),
            "steps": list(path or []),
        }
    ]


def _merge_route_metadata(existing: dict, entity_id: str, marker: str, dedupe_key: str) -> None:
    explain = dict(existing.get("explain") or {})
    evidence_type = str(explain.get("evidence_type") or "INFERRED")
    routes = _path_route_list(list(existing.get("path") or []), explain, existing.get("source_marker") or marker)
    new_route = _route_entry(entity_id, marker, dedupe_key, evidence_type)

    if not any(route.get("steps") == new_route["steps"] for route in routes):
        routes.append(new_route)

    matched_entity_ids = sorted(
        {
            str(matched_id)
            for route in routes
            for matched_id in route.get("matched_entity_ids") or []
            if matched_id not in (None, "")
        }
    )
    source_markers: list[str] = []
    for route in routes:
        route_marker = route.get("source_marker")
        if route_marker and route_marker not in source_markers:
            source_markers.append(route_marker)

    existing["path"] = routes
    existing["explain"] = {
        **explain,
        "matched_entity_ids": matched_entity_ids,
        "why": (
            f"{len(routes)} graph expansion routes reached source"
            if len(routes) > 1
            else explain.get("why") or f"{marker} expansion reached source"
        ),
        "evidence_type": evidence_type,
        "source_markers": source_markers,
        "route_count": len(routes),
    }


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
    """Walk the graph from seeds and return source-aware candidate payloads."""
    candidates: list[dict] = []
    seen_sources: set[str] = set()
    _source_index: dict[str, int] = {}

    def _add_source(entity_id: str, node_id: str, marker: str):
        if not node_id:
            return

        if node_id.startswith("document_chunk:"):
            source_kind = "document_chunk"
            source_id = node_id.split("document_chunk:", 1)[1]
            payload = {
                "chunk_id": source_id,
                "item_id": None,
                "source_marker": marker,
            }
        elif node_id.startswith("personal_asset_unit:"):
            source_kind = "personal_asset_unit"
            source_id = node_id.split("personal_asset_unit:", 1)[1]
            payload = {
                "source_kind": source_kind,
                "source_id": source_id,
                "source_marker": marker,
            }
        else:
            return

        dedupe_key = f"{source_kind}:{source_id}"
        explain = {
            "matched_entity_ids": [entity_id],
            "why": f"{marker} expansion reached source",
            "evidence_type": "INFERRED",
            "source_markers": [marker],
            "route_count": 1,
        }
        path = [_route_entry(entity_id, marker, dedupe_key, explain["evidence_type"])]
        payload = {
            **payload,
            "path": path,
            "explain": explain,
        }
        if dedupe_key in seen_sources:
            idx = _source_index.get(dedupe_key)
            if idx is not None:
                _merge_route_metadata(candidates[idx], entity_id, marker, dedupe_key)
                existing = candidates[idx].get("source_marker")
                if existing and marker not in existing:
                    candidates[idx]["source_marker"] = f"{existing}+{marker}"
            return

        seen_sources.add(dedupe_key)
        idx = len(candidates)
        _source_index[dedupe_key] = idx
        candidates.append(payload)

    def _walk(entity_id: str, marker: str, hop_limit: int):
        try:
            for n in graph.neighbors(entity_id, hops=hop_limit, limit=neighbors_per_node):
                if n.get("kind") == "Source":
                    _add_source(entity_id, n["id"], marker)
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
