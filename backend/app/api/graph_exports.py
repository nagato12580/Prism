from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field


router = APIRouter(prefix="/graph-exports", tags=["graph-exports"])


class GraphExportNode(BaseModel):
    id: str
    label: str
    type: str = "entity"


class GraphExportEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str = "related_to"
    label: str


class GraphExportSubgraphResponse(BaseModel):
    nodes: list[GraphExportNode]
    edges: list[GraphExportEdge]


class GraphExportReportResponse(BaseModel):
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


def _build_subgraph(entity_id: str) -> GraphExportSubgraphResponse:
    node = GraphExportNode(id=entity_id, label=entity_id)
    return GraphExportSubgraphResponse(nodes=[node], edges=[])


def _build_report() -> GraphExportReportResponse:
    return GraphExportReportResponse(
        summary="Graph export report is available.",
        details={"node_count": 0, "edge_count": 0},
    )


@router.get("/subgraph", response_model=GraphExportSubgraphResponse)
def get_graph_export_subgraph(entity_id: str = Query(..., min_length=1)):
    return _build_subgraph(entity_id)


@router.get("/report", response_model=GraphExportReportResponse)
def get_graph_export_report():
    return _build_report()
