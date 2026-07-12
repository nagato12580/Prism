from typing import Literal

from pydantic import BaseModel, Field
from typing_extensions import TypeAliasType


GraphJsonValue = TypeAliasType(
    "GraphJsonValue",
    str | int | float | bool | None | list["GraphJsonValue"] | dict[str, "GraphJsonValue"],
)


class GraphNodePayload(BaseModel):
    id: str
    node_type: str
    label: str
    properties: dict[str, GraphJsonValue] = Field(default_factory=dict)


class GraphEdgePayload(BaseModel):
    source: str
    target: str
    edge_type: str
    evidence_type: Literal["EXTRACTED", "INFERRED"] = "EXTRACTED"
    properties: dict[str, GraphJsonValue] = Field(default_factory=dict)


class GraphSourceEnvelope(BaseModel):
    source_kind: Literal["document_chunk", "personal_asset_unit"]
    source_id: str
    item_id: str | None = None
    text: str = ""
    extraction_mode: Literal["llm", "deterministic", "hybrid"] = "llm"
    nodes: list[GraphNodePayload] = Field(default_factory=list)
    edges: list[GraphEdgePayload] = Field(default_factory=list)
    provenance: dict[str, GraphJsonValue] = Field(default_factory=dict)
