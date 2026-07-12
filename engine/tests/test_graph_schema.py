import pytest
from pydantic import ValidationError

from engine.app.graph.schema import GraphEdgePayload, GraphNodePayload, GraphSourceEnvelope


def test_graph_payload_models_capture_minimal_fields_and_defaults():
    node = GraphNodePayload(
        id="entity-1",
        node_type="person",
        label="Ada Lovelace",
    )
    edge = GraphEdgePayload(
        source="entity-1",
        target="doc-1",
        edge_type="MENTIONED_IN",
    )
    envelope = GraphSourceEnvelope(
        source_kind="document_chunk",
        source_id="chunk-1",
        item_id="item-1",
        text="Ada Lovelace wrote notes on the Analytical Engine.",
        nodes=[node],
        edges=[edge],
    )

    assert node.properties == {}
    assert edge.evidence_type == "EXTRACTED"
    assert edge.properties == {}
    assert envelope.extraction_mode == "llm"
    assert envelope.provenance == {}
    assert envelope.nodes[0].label == "Ada Lovelace"
    assert envelope.edges[0].target == "doc-1"


def test_graph_source_envelope_defaults_to_empty_optional_collections():
    envelope = GraphSourceEnvelope(
        source_kind="personal_asset_unit",
        source_id="asset-1",
    )

    assert envelope.item_id is None
    assert envelope.text == ""
    assert envelope.nodes == []
    assert envelope.edges == []
    assert envelope.provenance == {}


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"node_type": "person", "label": "Ada Lovelace"}, "id"),
        ({"id": "entity-1", "label": "Ada Lovelace"}, "node_type"),
        ({"id": "entity-1", "node_type": "person"}, "label"),
        ({"source": "entity-1", "target": "doc-1"}, "edge_type"),
        ({"source": "entity-1", "edge_type": "MENTIONED_IN"}, "target"),
        ({"target": "doc-1", "edge_type": "MENTIONED_IN"}, "source"),
        ({"source_id": "chunk-1"}, "source_kind"),
        ({"source_kind": "document_chunk"}, "source_id"),
    ],
)
def test_graph_payload_models_require_contract_fields(payload, missing_field):
    model_cls = {
        "id": GraphNodePayload,
        "node_type": GraphNodePayload,
        "label": GraphNodePayload,
        "source": GraphEdgePayload,
        "target": GraphEdgePayload,
        "edge_type": GraphEdgePayload,
        "source_kind": GraphSourceEnvelope,
        "source_id": GraphSourceEnvelope,
    }[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        model_cls(**payload)

    assert missing_field in str(exc_info.value)


def test_graph_source_envelope_parses_nested_raw_dict_payloads():
    envelope = GraphSourceEnvelope(
        source_kind="document_chunk",
        source_id="chunk-1",
        nodes=[
            {
                "id": "entity-1",
                "node_type": "person",
                "label": "Ada Lovelace",
                "properties": {"role": "mathematician"},
            }
        ],
        edges=[
            {
                "source": "entity-1",
                "target": "doc-1",
                "edge_type": "MENTIONED_IN",
                "properties": {"confidence": 0.9},
            }
        ],
    )

    assert len(envelope.nodes) == 1
    assert isinstance(envelope.nodes[0], GraphNodePayload)
    assert envelope.nodes[0].properties == {"role": "mathematician"}
    assert len(envelope.edges) == 1
    assert isinstance(envelope.edges[0], GraphEdgePayload)
    assert envelope.edges[0].properties == {"confidence": 0.9}


def test_graph_payload_models_accept_json_safe_property_bags():
    properties = {
        "name": "Ada Lovelace",
        "count": 3,
        "score": 0.9,
        "active": True,
        "notes": None,
        "tags": ["math", "computing"],
        "metadata": {"era": "victorian", "published": False},
    }

    node = GraphNodePayload(
        id="entity-1",
        node_type="person",
        label="Ada Lovelace",
        properties=properties,
    )
    edge = GraphEdgePayload(
        source="entity-1",
        target="doc-1",
        edge_type="MENTIONED_IN",
        properties=properties,
    )
    envelope = GraphSourceEnvelope(
        source_kind="document_chunk",
        source_id="chunk-1",
        provenance=properties,
    )

    assert node.properties == properties
    assert edge.properties == properties
    assert envelope.provenance == properties


def test_graph_payload_models_reject_non_json_safe_property_bags():
    class NonJsonSafeValue:
        pass

    bad_properties = {"bad": NonJsonSafeValue()}

    with pytest.raises(ValidationError) as node_exc:
        GraphNodePayload(
            id="entity-1",
            node_type="person",
            label="Ada Lovelace",
            properties=bad_properties,
        )

    with pytest.raises(ValidationError) as edge_exc:
        GraphEdgePayload(
            source="entity-1",
            target="doc-1",
            edge_type="MENTIONED_IN",
            properties=bad_properties,
        )

    with pytest.raises(ValidationError) as envelope_exc:
        GraphSourceEnvelope(
            source_kind="document_chunk",
            source_id="chunk-1",
            provenance=bad_properties,
        )

    assert "properties" in str(node_exc.value)
    assert "properties" in str(edge_exc.value)
    assert "provenance" in str(envelope_exc.value)


@pytest.mark.parametrize(
    ("model_cls", "payload", "field_name"),
    [
        (
            GraphEdgePayload,
            {
                "source": "entity-1",
                "target": "doc-1",
                "edge_type": "MENTIONED_IN",
                "evidence_type": "DERIVED",
            },
            "evidence_type",
        ),
        (
            GraphSourceEnvelope,
            {"source_kind": "memory", "source_id": "chunk-1"},
            "source_kind",
        ),
        (
            GraphSourceEnvelope,
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "extraction_mode": "manual",
            },
            "extraction_mode",
        ),
    ],
)
def test_graph_payload_models_reject_unknown_literal_values(model_cls, payload, field_name):
    with pytest.raises(ValidationError) as exc_info:
        model_cls(**payload)

    assert field_name in str(exc_info.value)
