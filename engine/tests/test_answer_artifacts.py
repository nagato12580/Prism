from pathlib import Path

from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
from engine.eval.collect_answer_artifacts import (
    CachedChunkTextLookup,
    _collect_one,
    _load_active_index_generation_in_session,
    _lookup_chunk_text_in_session,
    build_artifact,
    summarize_artifacts,
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
    assert parsed["sources"] == [
        {"chunk_uid": "c1", "text": "ctx"},
        {"chunk_uid": "c2", "text": "ctx2"},
    ]
    assert parsed["token_count"] == 2
    assert parsed["tool_calls"] == 1
    assert parsed["status"] == "error"
    assert parsed["error"] == "late warning"


def test_parse_ndjson_events_preserves_error_status_after_later_done():
    lines = [
        '{"type":"error","data":{"message":"endpoint failed"}}\n',
        '{"type":"done","data":{"answer":"partial final answer"}}\n',
    ]

    parsed = parse_ndjson_events(lines)

    assert parsed["answer"] == "partial final answer"
    assert parsed["status"] == "error"
    assert parsed["error"] == "endpoint failed"


def test_parse_ndjson_events_uses_tool_result_evidence_items_as_sources():
    lines = [
        (
            '{"type":"tool_result","data":{"tool":"query_kb",'
            '"evidence_items":[{"chunk_id":"c1","excerpt":"ctx"}]}}\n'
        ),
        (
            '{"type":"tool_result","data":{"tool":"open_kb_document",'
            '"evidence_items":[{"chunk_id":"c2","excerpt":"ctx2"}]}}\n'
        ),
    ]

    parsed = parse_ndjson_events(lines)

    assert parsed["sources"] == [
        {"chunk_id": "c1", "excerpt": "ctx"},
        {"chunk_id": "c2", "excerpt": "ctx2"},
    ]


def test_parse_ndjson_events_reads_v2_sources_evidence_shape():
    lines = [
        (
            '{"type":"sources","evidence":[{"chunk_id":"c1","excerpt":"ctx"}],'
            '"retrieval_health":{"status":"ok"}}\n'
        ),
    ]

    parsed = parse_ndjson_events(lines)

    assert parsed["sources"] == [{"chunk_id": "c1", "excerpt": "ctx"}]


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


def test_build_artifact_maps_dataset_and_events():
    question = {
        "id": "q1",
        "question": "What is Prism?",
        "question_type": "single",
        "item_title": "Doc",
        "relevant_children": [{"chunk_id": "gold1", "chunk_text": "gold text"}],
    }
    events = {
        "answer": "Prism is a RAG system.",
        "sources": [{"chunk_uid": "c1", "text": "context text"}],
        "token_count": 5,
        "tool_calls": 1,
        "status": "done",
    }

    artifact = build_artifact(
        question,
        events,
        ttfb_ms=11,
        total_latency_ms=22,
        lookup_chunk_text=lambda chunk_id: None,
    )

    assert artifact.query_id == "q1"
    assert artifact.question == "What is Prism?"
    assert artifact.answer == "Prism is a RAG system."
    assert artifact.sources == [{"chunk_uid": "c1", "text": "context text"}]
    assert artifact.retrieved_contexts == ["context text"]
    assert artifact.reference == "gold text"
    assert artifact.metadata["question_type"] == "single"
    assert artifact.metadata["paper_title"] == "Doc"
    assert artifact.metadata["missing_context_count"] == 0
    assert artifact.metadata["ttfb_ms"] == 11
    assert artifact.metadata["total_latency_ms"] == 22
    assert artifact.metadata["tool_calls"] == 1
    assert artifact.metadata["token_count"] == 5
    assert artifact.metadata["status"] == "done"


def test_collect_one_sends_topic_id_for_scoped_kb():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self):
            return ['{"type":"done"}']

    class Client:
        def stream(self, method, url, *, json, headers):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return Response()

    _collect_one(
        Client(),
        engine_url="http://engine",
        question="q",
        scope_token="scope-token",
        deep_search=False,
        kb_uid="kb-a",
    )

    assert captured["json"]["topic_id"] == "kb-a"
    assert captured["headers"] == {"x-prism-knowledge-scope": "scope-token"}


def test_build_artifact_can_lookup_missing_gold_and_context_text():
    question = {
        "query_id": "q2",
        "question": "How does lookup work?",
        "paper_titles": ["Lookup Paper"],
        "relevant_children": [{"chunk_uid": "gold2"}],
    }
    events = {
        "answer": "With chunk lookups.",
        "sources": [{"chunk_uid": "ctx2"}, {"chunk_uid": "ctx3"}],
        "status": "done",
    }

    artifact = build_artifact(
        question,
        events,
        ttfb_ms=3,
        total_latency_ms=7,
        lookup_chunk_text=lambda chunk_id: {
            "gold2": "looked up gold",
            "ctx2": "looked up context",
        }.get(chunk_id),
    )

    assert artifact.query_id == "q2"
    assert artifact.metadata["paper_title"] == "Lookup Paper"
    assert artifact.reference == "looked up gold"
    assert artifact.retrieved_contexts == ["looked up context"]
    assert artifact.metadata["missing_context_count"] == 1


def test_build_artifact_uses_query_id_override_for_index_fallback():
    question = {"question": "No explicit id?"}
    events = {"answer": "yes", "sources": [], "status": "done"}

    artifact = build_artifact(
        question,
        events,
        ttfb_ms=1,
        total_latency_ms=2,
        query_id_override="7",
    )

    assert artifact.query_id == "7"


def test_cached_chunk_text_lookup_reuses_missing_text_results():
    calls: list[str] = []

    def lookup(chunk_id: str) -> str | None:
        calls.append(chunk_id)
        return {"shared": "shared text"}.get(chunk_id)

    cached_lookup = CachedChunkTextLookup(lookup)
    question = {
        "id": "q-cache",
        "question": "Cache repeated IDs?",
        "relevant_children": [{"chunk_id": "shared"}, {"chunk_id": "shared"}],
    }
    events = {
        "answer": "cached",
        "sources": [{"chunk_uid": "shared"}, {"chunk_uid": "shared"}],
        "status": "done",
    }

    artifact = build_artifact(
        question,
        events,
        ttfb_ms=1,
        total_latency_ms=2,
        lookup_chunk_text=cached_lookup,
    )

    assert artifact.reference == "shared text\n\n---\n\nshared text"
    assert artifact.retrieved_contexts == ["shared text", "shared text"]
    assert calls == ["shared"]


def test_scoped_chunk_lookup_filters_tenant_kb_and_active_generation():
    base = declarative_base()

    class TestChunk(base):
        __tablename__ = "test_chunk"

        id = Column(String, primary_key=True)
        chunk_uid = Column(String, nullable=False)
        tenant_id = Column(String, nullable=False)
        kb_uid = Column(String, nullable=False)
        generation = Column(String, nullable=False)
        chunk_text = Column(String, nullable=False)

    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all(
            [
                TestChunk(
                    id="wrong-tenant",
                    chunk_uid="shared",
                    tenant_id="tenant-b",
                    kb_uid="kb-a",
                    generation="gen-active",
                    chunk_text="wrong tenant",
                ),
                TestChunk(
                    id="lexically-newer-stale",
                    chunk_uid="shared",
                    tenant_id="tenant-a",
                    kb_uid="kb-a",
                    generation="zzzz-stale",
                    chunk_text="stale lexically newer",
                ),
                TestChunk(
                    id="active",
                    chunk_uid="shared",
                    tenant_id="tenant-a",
                    kb_uid="kb-a",
                    generation="gen-active",
                    chunk_text="active scoped",
                ),
            ]
        )
        session.commit()

        text = _lookup_chunk_text_in_session(
            session,
            TestChunk,
            "shared",
            tenant_id="tenant-a",
            kb_uid="kb-a",
            active_index_generation="gen-active",
        )

        assert text == "active scoped"
    finally:
        session.close()
        engine.dispose()


def test_load_active_index_generation_filters_topic_by_tenant_and_kb():
    base = declarative_base()

    class TestTopic(base):
        __tablename__ = "test_topic"

        id = Column(String, primary_key=True)
        tenant_id = Column(String, nullable=False)
        kb_uid = Column(String, nullable=False)
        active_index_generation = Column(String)

    engine = create_engine("sqlite:///:memory:")
    base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all(
            [
                TestTopic(
                    id="wrong-tenant",
                    tenant_id="tenant-b",
                    kb_uid="kb-a",
                    active_index_generation="wrong",
                ),
                TestTopic(
                    id="active-topic",
                    tenant_id="tenant-a",
                    kb_uid="kb-a",
                    active_index_generation="gen-active",
                ),
            ]
        )
        session.commit()

        generation = _load_active_index_generation_in_session(
            session,
            TestTopic,
            tenant_id="tenant-a",
            kb_uid="kb-a",
        )

        assert generation == "gen-active"
    finally:
        session.close()
        engine.dispose()


def test_build_artifact_preserves_endpoint_error_metadata():
    question = {"id": "q3", "question": "Will this fail?"}
    events = {
        "answer": "",
        "sources": [],
        "token_count": 0,
        "tool_calls": 0,
        "status": "error",
        "error": "HTTP 500",
    }

    artifact = build_artifact(
        question,
        events,
        ttfb_ms=0,
        total_latency_ms=15,
        lookup_chunk_text=lambda chunk_id: None,
    )

    assert artifact.query_id == "q3"
    assert artifact.answer == ""
    assert artifact.metadata["status"] == "error"
    assert artifact.metadata["error"] == "HTTP 500"


def test_summarize_artifacts_counts_statuses_and_missing_contexts():
    artifacts = [
        AnswerArtifact("q1", "q", "a", [], ["ctx"], "ref", {"status": "done"}).to_dict(),
        AnswerArtifact(
            "q2",
            "q",
            "",
            [],
            [],
            "",
            {"status": "error", "missing_context_count": 2},
        ).to_dict(),
        AnswerArtifact("q3", "q", "a", [], [], "ref", {}).to_dict(),
    ]

    summary = summarize_artifacts("dataset.json", artifacts, failures=[{"query_id": "q2"}])

    assert summary["meta"]["dataset"] == "dataset.json"
    assert summary["meta"]["total_artifacts"] == 3
    assert summary["meta"]["failed"] == 1
    assert "run_at" in summary["meta"]
    assert summary["status_counts"] == {"done": 1, "error": 1, "unknown": 1}
    assert summary["missing_context_count"] == 2
    assert summary["failures"] == [{"query_id": "q2"}]
