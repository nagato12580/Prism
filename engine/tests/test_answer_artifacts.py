from pathlib import Path

from engine.eval.answer_artifacts import (
    AnswerArtifact,
    aggregate_numeric_metrics,
    bad_case_tags,
    build_reference_from_gold,
    extract_retrieved_contexts,
    parse_ndjson_events,
    read_jsonl,
    write_jsonl,
)


def test_answer_artifact_serializes_to_dict():
    artifact = AnswerArtifact(
        query_id="q1",
        question="What is Prism?",
        answer="A RAG system.",
        sources=[{"chunk_uid": "c1"}],
        retrieved_contexts=["ctx"],
        reference="ref",
        metadata={"status": "done"},
    )

    assert artifact.to_dict() == {
        "query_id": "q1",
        "question": "What is Prism?",
        "answer": "A RAG system.",
        "sources": [{"chunk_uid": "c1"}],
        "retrieved_contexts": ["ctx"],
        "reference": "ref",
        "metadata": {"status": "done"},
    }


def test_parse_ndjson_events_handles_tokens_sources_done_and_error():
    lines = [
        '{"type":"token","data":{"token":"hello "}}\n',
        '{"type":"token","data":"world"}\n',
        '{"type":"sources","data":{"sources":[{"chunk_uid":"c1","text":"ctx"}]}}\n',
        '{"type":"sources","data":[{"chunk_uid":"c2","text":"ctx2"}]}\n',
        '{"type":"tool_call","data":{"name":"knowledge"}}\n',
        '{"type":"done","data":{"answer":"final answer"}}\n',
        '{"type":"error","data":{"message":"late warning"}}\n',
        "not json\n",
    ]

    parsed = parse_ndjson_events(lines)

    assert parsed["answer"] == "final answer"
    assert parsed["sources"] == [{"chunk_uid": "c2", "text": "ctx2"}]
    assert parsed["token_count"] == 2
    assert parsed["tool_calls"] == 1
    assert parsed["status"] == "error"
    assert parsed["error"] == "late warning"


def test_build_reference_from_gold_uses_inline_chunk_texts():
    question = {
        "relevant_children": [
            {"chunk_id": "c1", "chunk_text": "first gold"},
            {"chunk_id": "c2", "chunk_text": "second gold"},
            {"chunk_id": "c3", "chunk_text": ""},
        ]
    }

    reference = build_reference_from_gold(question)

    assert reference == "first gold\n\n---\n\nsecond gold"


def test_build_reference_from_gold_falls_back_to_lookup_by_id_or_uid():
    question = {
        "relevant_children": [
            {"chunk_id": "c1"},
            {"chunk_uid": "c2"},
            {"chunk_id": "c3"},
        ]
    }

    reference = build_reference_from_gold(
        question,
        lookup_chunk_text=lambda cid: {"c1": "from id", "c2": "from uid"}.get(cid),
    )

    assert reference == "from id\n\n---\n\nfrom uid"


def test_build_reference_from_gold_returns_empty_string_when_no_text_found():
    question = {"relevant_children": [{"chunk_id": "c1"}]}

    reference = build_reference_from_gold(question, lookup_chunk_text=lambda cid: None)

    assert reference == ""


def test_extract_retrieved_contexts_prefers_text_then_snippet_excerpt_then_lookup():
    sources = [
        {"chunk_uid": "c1", "text": "full text", "snippet": "ignored"},
        {"chunk_uid": "c2", "snippet": "snippet text"},
        {"chunk_uid": "c3", "excerpt": "excerpt text"},
        {"chunk_uid": "c4"},
        {"chunk_id": "c5"},
        {"chunk_uid": "c6"},
    ]

    contexts, missing = extract_retrieved_contexts(
        sources,
        lookup_chunk_text=lambda cid: {"c4": "lookup uid", "c5": "lookup id"}.get(cid),
    )

    assert contexts == [
        "full text",
        "snippet text",
        "excerpt text",
        "lookup uid",
        "lookup id",
    ]
    assert missing == 1


def test_jsonl_round_trip(tmp_path: Path):
    path = tmp_path / "nested" / "artifacts.jsonl"
    rows = [
        {"query_id": "q1", "answer": "a1"},
        {"query_id": "q2", "answer": "a2"},
    ]

    write_jsonl(path, rows)

    assert read_jsonl(path) == rows


def test_bad_case_tags_detect_failures_and_low_scores():
    artifact = {
        "answer": "",
        "retrieved_contexts": [],
        "metadata": {"status": "error"},
    }
    scores = {
        "faithfulness": 0.69,
        "response_relevancy": 0.64,
        "context_precision": 0.49,
        "context_recall": 0.49,
    }

    tags = bad_case_tags(artifact, scores)

    assert tags == [
        "hallucination_risk",
        "off_topic",
        "noisy_context",
        "missing_context",
        "system_failure",
        "retrieval_failure",
    ]


def test_bad_case_tags_ignore_missing_or_non_numeric_scores():
    artifact = {
        "answer": "answered",
        "retrieved_contexts": ["ctx"],
        "metadata": {"status": "done"},
    }
    scores = {
        "faithfulness": None,
        "response_relevancy": "low",
        "context_precision": 0.5,
        "context_recall": 0.5,
    }

    assert bad_case_tags(artifact, scores) == []


def test_aggregate_numeric_metrics_ignores_missing_and_non_numeric_values():
    aggregate = aggregate_numeric_metrics(
        [
            {"faithfulness": 1.0, "response_relevancy": 0.5},
            {"faithfulness": 0.0, "response_relevancy": None},
            {"faithfulness": "bad"},
            {},
        ],
        ["faithfulness", "response_relevancy", "context_recall"],
    )

    assert aggregate == {
        "faithfulness": {
            "mean": 0.5,
            "median": 0.5,
            "min": 0.0,
            "max": 1.0,
        },
        "response_relevancy": {
            "mean": 0.5,
            "median": 0.5,
            "min": 0.5,
            "max": 0.5,
        },
    }


def test_aggregate_numeric_metrics_rounds_all_stats_to_four_decimals():
    aggregate = aggregate_numeric_metrics(
        [
            {"faithfulness": 0.11111},
            {"faithfulness": 0.22222},
            {"faithfulness": 0.33333},
            {"faithfulness": 0.44444},
        ],
        ["faithfulness"],
    )

    assert aggregate["faithfulness"] == {
        "mean": 0.2778,
        "median": 0.2778,
        "min": 0.1111,
        "max": 0.4444,
    }
