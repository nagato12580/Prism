import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_deterministic_extraction_test.db"


def test_extract_document_structure_candidates_from_heading_and_list():
    from engine.app.extraction.deterministic import extract_document_structure_candidates

    text = "# MiniMind-O\n- Training Flow\n- Data Pipeline"

    result = extract_document_structure_candidates(text, source_kind="document_chunk")

    entity_candidates = [item for item in result if item.kind == "entity"]
    surfaces = {item.surface_text for item in entity_candidates}
    methods = {item.surface_text: item.extraction_method for item in entity_candidates}

    assert surfaces == {"MiniMind-O", "Training Flow", "Data Pipeline"}
    assert all(item.entity_type == "concept" for item in entity_candidates)
    assert methods["MiniMind-O"] == "deterministic_heading"
    assert methods["Training Flow"] == "deterministic_list_item"
    assert methods["Data Pipeline"] == "deterministic_list_item"


def test_extract_document_structure_candidates_ignores_non_structural_lines():
    from engine.app.extraction.deterministic import extract_document_structure_candidates

    text = "MiniMind-O overview\n1. Not supported\n* Not supported\n"

    result = extract_document_structure_candidates(text, source_kind="document_chunk")

    assert result == []


def test_extract_document_structure_candidates_ignores_unsupported_heading_forms():
    from engine.app.extraction.deterministic import extract_document_structure_candidates

    text = "## Nested Heading\n#NoSpace\n"

    result = extract_document_structure_candidates(text, source_kind="document_chunk")

    assert result == []
