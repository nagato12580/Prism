import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_stage_a_test.db"

from engine.app.extraction.prompts import parse_stage_a_json, STAGE_A_EXTRACTION_PROMPT


def test_parse_stage_a_json_clean_array():
    raw = '[{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"..."}]'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["entity_type"] == "concept"
    assert result[0]["surface"] == "混合检索"
    assert result[0]["score"] == 0.85


def test_parse_stage_a_json_strips_fences_and_prose():
    raw = '好的，结果如下：\n```json\n[{"entity_type":"person","surface":"张三","tier":"EXTRACTED","score":1.0,"evidence":""}]\n```\n以上。'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["surface"] == "张三"


def test_parse_stage_a_json_empty_returns_empty():
    assert parse_stage_a_json("") == []
    assert parse_stage_a_json("no json here") == []


def test_parse_stage_a_json_rejects_score_out_of_range():
    raw = '[{"entity_type":"concept","surface":"x","tier":"EXTRACTED","score":0.5,"evidence":""}]'
    result = parse_stage_a_json(raw)
    # EXTRACTED must be 1.0; invalid tier/score combos are dropped
    assert result == []


def test_prompt_contains_required_fields():
    for token in ["entity_type", "surface", "tier", "score", "evidence", "EXTRACTED", "INFERRED", "AMBIGUOUS"]:
        assert token in STAGE_A_EXTRACTION_PROMPT


from unittest.mock import patch

from backend.app.services.entity_extraction import EntityCandidate
from engine.app.extraction.stage_a import extract_entities_for_chunk


_FAKE_LLM_OUTPUT = (
    '{"entities": ['
    '{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"结合向量与关键词"},'
    '{"entity_type":"method","surface":"RRF融合","tier":"EXTRACTED","score":1.0,"evidence":"RRF"}'
    ']}'
)


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_returns_candidates(mock_chat):
    mock_chat.return_value = _FAKE_LLM_OUTPUT
    candidates = extract_entities_for_chunk("some chunk text", chunk_id="c1")
    assert len(candidates) == 2
    assert all(c.kind == "entity" for c in candidates)
    types = {c.entity_type for c in candidates}
    assert types == {"concept", "method"}
    concept = next(c for c in candidates if c.entity_type == "concept")
    assert concept.surface_text == "混合检索"
    assert concept.confidence == 0.85
    assert concept.extraction_method.startswith("llm_stage_a:INFERRED")


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_llm_failure_returns_empty(mock_chat):
    mock_chat.side_effect = RuntimeError("llm down")
    assert extract_entities_for_chunk("text", chunk_id="c1") == []
