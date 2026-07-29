from pathlib import Path
import sys

import pytest

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_build_judge_prompt_includes_all_sections():
    """Judge prompt should include question, gold chunks, answer, and scoring criteria."""
    from engine.eval.run_answer_eval import build_judge_prompt

    question = "什么是多视图聚类？"
    gold_text = "多视图聚类是一种将多个视图的数据进行联合聚类的方法。"
    answer = "多视图聚类是将不同视图的数据进行联合聚类的方法。"

    prompt = build_judge_prompt(question, gold_text, answer)
    assert question in prompt
    assert gold_text in prompt
    assert answer in prompt
    assert "忠实度" in prompt
    assert "相关性" in prompt
    assert "完整性" in prompt
    assert "faithfulness" in prompt  # JSON key
    assert "relevance" in prompt
    assert "completeness" in prompt


def test_parse_judge_response_valid_json():
    """Valid JSON response should be parsed correctly."""
    from engine.eval.run_answer_eval import parse_judge_response

    response = '{"faithfulness": 5, "relevance": 4, "completeness": 3, "rationale": "回答基本准确"}'
    scores = parse_judge_response(response)
    assert scores["faithfulness"] == 5
    assert scores["relevance"] == 4
    assert scores["completeness"] == 3
    assert scores["overall"] == pytest.approx((5 * 0.4 + 4 * 0.3 + 3 * 0.3), rel=1e-2)
    assert "rationale" in scores


def test_parse_judge_response_malformed():
    """Malformed JSON should return error sentinel."""
    from engine.eval.run_answer_eval import parse_judge_response

    response = "这不是 JSON"
    scores = parse_judge_response(response)
    assert scores["faithfulness"] == -1  # error sentinel
    assert scores["relevance"] == -1


def test_parse_ndjson_events_sample():
    """Should parse NDJSON lines into structured events."""
    from engine.eval.run_answer_eval import parse_ndjson_events

    lines = [
        '{"type":"agent_status","data":{"status":"analyzing"}}\n',
        '{"type":"token","data":{"token":"你好"}}\n',
        '{"type":"token","data":{"token":"世界"}}\n',
        '{"type":"sources","data":{"sources":[{"chunk_uid":"c1","excerpt":"text"}]}}\n',
        '{"type":"done","data":{"answer":"你好世界"}}\n',
    ]

    events = parse_ndjson_events(lines)
    assert events["answer"] == "你好世界"
    assert len(events["sources"]) == 1
    assert events["sources"][0]["chunk_uid"] == "c1"
    assert events["token_count"] >= 2
