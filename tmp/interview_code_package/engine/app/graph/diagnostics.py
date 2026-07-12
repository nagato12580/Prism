_GENERIC_ENTITY_TERMS = {
    "这个",
    "那个",
    "这篇",
    "文本",
    "内容",
    "资料",
    "data",
    "entity",
    "information",
    "item",
    "object",
    "system",
    "thing",
}


def diagnose_graph_payload(payload: dict) -> dict:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []

    node_ids = {
        node.get("id")
        for node in nodes
        if isinstance(node, dict) and node.get("id") is not None
    }

    dangling_endpoint_edges = 0
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            dangling_endpoint_edges += 1

    generic_entities = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        label = node.get("label")
        if not isinstance(label, str):
            continue
        normalized = label.strip().lower()
        if normalized in _GENERIC_ENTITY_TERMS:
            generic_entities.append(node_id)

    return {
        "dangling_endpoint_edges": dangling_endpoint_edges,
        "generic_entities": generic_entities,
    }
