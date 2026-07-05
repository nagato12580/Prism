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
