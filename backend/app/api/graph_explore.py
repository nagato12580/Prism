from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.app.services.graph_query import GraphQueryClient

router = APIRouter(prefix="/graph", tags=["graph-explore"])

DEFAULT_NODE_TYPES = ["CKP", "PKU", "Source", "Entity", "Alias"]
DEFAULT_USER_ID = "default-user"

_query_client: GraphQueryClient | None = None


def get_graph_query_client() -> GraphQueryClient:
    global _query_client
    if _query_client is None:
        _query_client = GraphQueryClient()
    return _query_client


def _parse_types(types_param: str | None) -> list[str]:
    if not types_param:
        return DEFAULT_NODE_TYPES
    return [t.strip() for t in types_param.split(",") if t.strip()]


@router.get("/explore")
def explore(
    types: str | None = Query(None, description="Comma-separated node types to include"),
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(None, description="Search query to filter nodes by label"),
) -> dict[str, Any]:
    client = get_graph_query_client()
    node_types = _parse_types(types)
    if q:
        return client.search(q, node_types, limit)
    return client.explore(node_types=node_types, limit=limit, user_id=DEFAULT_USER_ID)


@router.get("/explore/nodes/{node_id}")
def node_detail(node_id: str) -> dict[str, Any]:
    client = get_graph_query_client()
    return client.node_detail(node_id)


@router.get("/explore/nodes/{node_id}/expand")
def expand_neighbors(
    node_id: str,
    depth: int = Query(1, ge=1, le=3),
) -> dict[str, Any]:
    client = get_graph_query_client()
    return client.expand(node_id, depth=depth)
