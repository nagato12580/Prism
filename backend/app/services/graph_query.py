from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from backend.app.config import settings


def _label_from_node(node: dict[str, Any]) -> str:
    labels = node.get("_labels") or []
    if isinstance(labels, (list, set, tuple)) and labels:
        return next(iter(labels))
    return node.get("_label") or "Unknown"


def _node_label_text(node: dict[str, Any], label: str) -> str:
    candidates = [
        node.get("title"),
        node.get("canonical_name"),
        node.get("statement"),
        node.get("normalized_statement"),
        node.get("name"),
        node.get("surface_text"),
        node.get("label"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return label


def _node_to_dict(node: dict[str, Any]) -> dict[str, Any]:
    label = _label_from_node(node)
    properties = {k: v for k, v in node.items() if k not in {"_labels", "_label"}}
    return {
        "id": node.get("id", ""),
        "label": _node_label_text(node, label),
        "type": label,
        "properties": properties,
    }


def _link_to_dict(link: dict[str, Any]) -> dict[str, Any]:
    props = {k: v for k, v in link.items() if k not in {"source", "target", "type"}}
    return {
        "source": link.get("source", ""),
        "target": link.get("target", ""),
        "type": link.get("type", "RELATED_TO"),
        "properties": props,
    }


def _extract_subgraph_from_record(record: Any) -> dict[str, Any]:
    nodes_raw = record.get("nodes", []) or []
    links_raw = record.get("links", []) or []
    nodes = [_node_to_dict(n) if isinstance(n, dict) else _node_to_dict(dict(n)) for n in nodes_raw]
    links = [_link_to_dict(l) if isinstance(l, dict) else _link_to_dict(dict(l)) for l in links_raw]
    node_ids = {n["id"] for n in nodes}
    links = [l for l in links if l["source"] in node_ids and l["target"] in node_ids]
    return {
        "nodes": nodes,
        "links": links,
        "node_count": record.get("node_count", len(nodes)),
        "link_count": record.get("link_count", len(links)),
    }


def _node_props_map(node: Any) -> dict[str, Any]:
    raw = dict(node) if not isinstance(node, dict) else node
    return raw


def _serialize_node_dict(node: dict[str, Any]) -> dict[str, Any]:
    label = _label_from_node(node)
    properties = {k: v for k, v in node.items() if k not in {"_labels", "_label"}}
    return {
        "id": node.get("id", ""),
        "label": _node_label_text(node, label),
        "type": label,
        "properties": properties,
    }


def _serialize_link_dict(link: dict[str, Any]) -> dict[str, Any]:
    props = {k: v for k, v in link.items() if k not in {"source", "target", "type"}}
    return {
        "source": link.get("source", ""),
        "target": link.get("target", ""),
        "type": link.get("type", "RELATED_TO"),
        "properties": props,
    }


_NODE_PROPS_CYPHER_NODE = """
    id: node.id,
    title: node.title,
    canonical_name: node.canonical_name,
    statement: node.statement,
    normalized_statement: node.normalized_statement,
    name: node.name,
    surface_text: node.surface_text,
    user_id: node.user_id,
    status: node.status,
    confidence: node.confidence,
    entity_type: node.entity_type,
    normalized_key: node.normalized_key,
    ckp_type: node.ckp_type,
    unit_type: node.unit_type,
    topic_level: node.topic_level,
    group_type: node.group_type,
    source_kind: node.source_kind,
    source_id: node.source_id,
    _labels: labels(node)
"""

_NODE_PROPS_CYPHER_M = """
    id: m.id,
    title: m.title,
    canonical_name: m.canonical_name,
    statement: m.statement,
    normalized_statement: m.normalized_statement,
    name: m.name,
    surface_text: m.surface_text,
    user_id: m.user_id,
    status: m.status,
    confidence: m.confidence,
    entity_type: m.entity_type,
    normalized_key: m.normalized_key,
    ckp_type: m.ckp_type,
    unit_type: m.unit_type,
    topic_level: m.topic_level,
    group_type: m.group_type,
    source_kind: m.source_kind,
    source_id: m.source_id,
    _labels: labels(m)
"""

_NODE_PROPS_CYPHER_N = """
    id: n.id,
    title: n.title,
    canonical_name: n.canonical_name,
    statement: n.statement,
    normalized_statement: n.normalized_statement,
    name: n.name,
    surface_text: n.surface_text,
    user_id: n.user_id,
    status: n.status,
    confidence: n.confidence,
    entity_type: n.entity_type,
    normalized_key: n.normalized_key,
    ckp_type: n.ckp_type,
    unit_type: n.unit_type,
    topic_level: n.topic_level,
    group_type: n.group_type,
    source_kind: n.source_kind,
    source_id: n.source_id,
    _labels: labels(n)
"""

_REL_PROPS_CYPHER = """
    source: startNode(r).id,
    target: endNode(r).id,
    type: type(r),
    confidence: r.confidence,
    reason: r.reason,
    rank: r.rank,
    source_kind: r.source_kind,
    source_id: r.source_id
"""


def explore_subgraph(
    driver: Any,
    database: str,
    *,
    node_types: list[str],
    limit: int,
    user_id: str,
) -> dict[str, Any]:
    nodes_query = f"""
    MATCH (n)
    WHERE any(label IN labels(n) WHERE label IN $types)
      AND n.user_id = $user_id
    WITH collect(DISTINCT n)[..$limit] AS seed_nodes
    UNWIND seed_nodes AS node
    WITH collect(DISTINCT {{ {_NODE_PROPS_CYPHER_NODE} }}) AS nodes
    RETURN nodes, size(nodes) AS node_count
    """
    links_query = f"""
    MATCH (n)
    WHERE any(label IN labels(n) WHERE label IN $types)
      AND n.user_id = $user_id
    WITH collect(DISTINCT n)[..$limit] AS seed_nodes
    UNWIND seed_nodes AS n
    MATCH (n)-[r]-(m)
    WITH collect(DISTINCT {{ {_REL_PROPS_CYPHER} }}) AS links
    RETURN links, size(links) AS link_count
    """
    params = {"types": node_types, "limit": limit, "user_id": user_id}
    with driver.session(database=database) as session:
        nodes_record = session.run(nodes_query, params).single()
        links_record = session.run(links_query, params).single()

    nodes_raw = nodes_record.get("nodes", []) if nodes_record else []
    links_raw = links_record.get("links", []) if links_record else []
    nodes = [_serialize_node_dict(n) for n in nodes_raw]
    links = [_serialize_link_dict(l) for l in links_raw]
    node_ids = {n["id"] for n in nodes}
    links = [l for l in links if l["source"] in node_ids and l["target"] in node_ids]
    return {
        "nodes": nodes,
        "links": links,
        "node_count": len(nodes),
        "link_count": len(links),
    }


def get_node_detail(driver: Any, database: str, node_id: str) -> dict[str, Any]:
    query = f"""
    MATCH (n {{id: $node_id}})
    OPTIONAL MATCH (n)-[r]-(m)
    WITH n,
         collect(DISTINCT {{
            {_NODE_PROPS_CYPHER_M}
         }}) AS neighbors,
         collect(DISTINCT {{
            {_REL_PROPS_CYPHER}
         }}) AS links,
         {{
            {_NODE_PROPS_CYPHER_N}
         }} AS node_data
    RETURN node_data, neighbors, links
    """
    params = {"node_id": node_id}
    with driver.session(database=database) as session:
        result = session.run(query, params)
        record = result.single()
    if record is None:
        return {"node": None, "neighbors": [], "links": []}
    node_raw = record.get("node_data")
    node = _serialize_node_dict(node_raw) if node_raw else None
    neighbors_raw = record.get("neighbors", []) or []
    neighbors = [_serialize_node_dict(n) for n in neighbors_raw]
    links_raw = record.get("links", []) or []
    links = [_serialize_link_dict(l) for l in links_raw]
    return {"node": node, "neighbors": neighbors, "links": links}


def expand_neighbors(driver: Any, database: str, node_id: str, depth: int = 1) -> dict[str, Any]:
    query = """
    MATCH (seed {id: $node_id})
    CALL {
        WITH seed
        MATCH path = (seed)-[*1..$depth]-(connected)
        UNWIND nodes(path) AS pn
        UNWIND relationships(path) AS pr
        RETURN collect(DISTINCT pn) AS path_nodes, collect(DISTINCT pr) AS path_rels
    }
    UNWIND path_nodes AS node
    WITH collect(DISTINCT {
        id: node.id,
        title: node.title,
        canonical_name: node.canonical_name,
        statement: node.statement,
        normalized_statement: node.normalized_statement,
        name: node.name,
        surface_text: node.surface_text,
        user_id: node.user_id,
        status: node.status,
        confidence: node.confidence,
        entity_type: node.entity_type,
        normalized_key: node.normalized_key,
        ckp_type: node.ckp_type,
        unit_type: node.unit_type,
        topic_level: node.topic_level,
        group_type: node.group_type,
        source_kind: node.source_kind,
        source_id: node.source_id,
        _labels: labels(node)
    }) AS nodes, path_rels
    UNWIND path_rels AS rel
    WITH nodes, collect(DISTINCT {
        source: startNode(rel).id,
        target: endNode(rel).id,
        type: type(rel),
        confidence: rel.confidence,
        reason: rel.reason,
        rank: rel.rank,
        source_kind: rel.source_kind,
        source_id: rel.source_id
    }) AS links
    RETURN nodes, links, size(nodes) AS node_count, size(links) AS link_count
    """
    params = {"node_id": node_id, "depth": depth}
    with driver.session(database=database) as session:
        result = session.run(query, params)
        record = result.single()
    if record is None:
        return {"nodes": [], "links": [], "node_count": 0, "link_count": 0}
    return _extract_subgraph_from_record(record)


def search_nodes(
    driver: Any,
    database: str,
    *,
    query: str,
    node_types: list[str],
    limit: int,
) -> dict[str, Any]:
    cypher = """
    MATCH (n)
    WHERE any(label IN labels(n) WHERE label IN $types)
      AND (
        n.title CONTAINS $query
        OR n.canonical_name CONTAINS $query
        OR n.statement CONTAINS $query
        OR n.normalized_statement CONTAINS $query
        OR n.name CONTAINS $query
        OR n.surface_text CONTAINS $query
      )
    WITH collect(DISTINCT n)[..$limit] AS matched
    UNWIND matched AS n
    MATCH (n)-[r]-(m)
    WHERE m IN matched
    WITH matched, collect(DISTINCT {
        source: startNode(r).id,
        target: endNode(r).id,
        type: type(r),
        confidence: r.confidence,
        reason: r.reason,
        source_kind: r.source_kind,
        source_id: r.source_id
    }) AS links
    UNWIND matched AS node
    WITH collect(DISTINCT {
        id: node.id,
        title: node.title,
        canonical_name: node.canonical_name,
        statement: node.statement,
        normalized_statement: node.normalized_statement,
        name: node.name,
        surface_text: node.surface_text,
        user_id: node.user_id,
        status: node.status,
        confidence: node.confidence,
        entity_type: node.entity_type,
        normalized_key: node.normalized_key,
        ckp_type: node.ckp_type,
        unit_type: node.unit_type,
        topic_level: node.topic_level,
        group_type: node.group_type,
        source_kind: node.source_kind,
        source_id: node.source_id,
        _labels: labels(node)
    }) AS nodes, links
    RETURN nodes, links, size(nodes) AS node_count, size(links) AS link_count
    """
    params = {"query": query, "types": node_types, "limit": limit}
    with driver.session(database=database) as session:
        result = session.run(cypher, params)
        record = result.single()
    if record is None:
        return {"nodes": [], "links": [], "node_count": 0, "link_count": 0}
    return _extract_subgraph_from_record(record)


class GraphQueryClient:
    def __init__(self, driver: Any | None = None, database: str | None = None):
        self.driver = driver or GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
        self.database = database or settings.NEO4J_DATABASE

    def close(self) -> None:
        close = getattr(self.driver, "close", None)
        if close is not None:
            close()

    def explore(self, *, node_types: list[str], limit: int, user_id: str) -> dict[str, Any]:
        return explore_subgraph(self.driver, self.database, node_types=node_types, limit=limit, user_id=user_id)

    def node_detail(self, node_id: str) -> dict[str, Any]:
        return get_node_detail(self.driver, self.database, node_id)

    def expand(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        return expand_neighbors(self.driver, self.database, node_id, depth=depth)

    def search(self, query: str, node_types: list[str], limit: int) -> dict[str, Any]:
        return search_nodes(self.driver, self.database, query=query, node_types=node_types, limit=limit)
