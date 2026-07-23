import pytest

from engine.app.agent.rag import agentic
from engine.app.agent.rag.agentic import AgenticRagRunner, RagJudgeResult


def test_agentic_rag_stops_when_rewrite_normalizes_to_current_query():
    searches = []

    def search(query: str, top_k: int):
        searches.append(query)
        return []

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need more evidence"],
            rewrite_query="  SAME   query  ",
        )

    result = AgenticRagRunner(search, lambda _: {}, judge).run("same query")

    assert searches == ["same query"]
    assert result.iterations == 1


def test_agentic_rag_accumulates_evidence_across_distinct_rewrites_in_first_seen_order():
    searches = []

    def search(query: str, top_k: int):
        searches.append(query)
        if query == "first query":
            return [{"chunk_uid": "chunk-1", "item_id": "item-1", "score": 0.9}]
        return [
            {"chunk_uid": "chunk-2", "item_id": "item-2", "score": 0.8},
            {"chunk_uid": "chunk-1", "item_id": "duplicate", "score": 0.7},
        ]

    def load_chunks(chunk_ids: list[str]):
        return {
            "chunk-1": {"text": "first evidence"},
            "chunk-2": {"text": "second evidence"},
        }

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        if query == "first query":
            return RagJudgeResult(status="insufficient", rewrite_query="second query")
        return RagJudgeResult(status="sufficient", answer_basis="combined evidence")

    result = AgenticRagRunner(search, load_chunks, judge).run("first query")

    assert searches == ["first query", "second query"]
    assert [item["chunk_uid"] for item in result.evidence] == ["chunk-1", "chunk-2"]
    assert {item["chunk_uid"] for item in result.evidence} == {"chunk-1", "chunk-2"}
    assert result.iterations == 2


def test_rag_run_config_validates_control_boundaries():
    assert agentic.RagRunConfig(mode="deep", top_k=30, graph_hops=3, max_iterations=10).top_k == 30

    for kwargs in (
        {"mode": "invalid"},
        {"top_k": 0},
        {"top_k": 31},
        {"graph_hops": 0},
        {"graph_hops": 4},
        {"max_iterations": 0},
        {"max_iterations": 11},
    ):
        with pytest.raises(ValueError):
            agentic.RagRunConfig(**kwargs)


def test_agentic_rag_passes_controls_to_explicit_keyword_only_search():
    calls = []

    def search(
        query: str,
        top_k: int,
        *,
        mode: str = "fast",
        graph_hops: int = 1,
    ):
        calls.append((query, top_k, mode, graph_hops))
        return []

    runner = AgenticRagRunner(
        search,
        lambda _: {},
        lambda *args: RagJudgeResult(status="insufficient"),
    )
    runner.run(
        "controlled query",
        config=agentic.RagRunConfig(
            mode="deep",
            top_k=17,
            graph_hops=3,
            max_iterations=1,
        ),
    )

    assert calls == [("controlled query", 17, "deep", 3)]


def test_agentic_rag_keeps_legacy_two_argument_search_compatible():
    calls = []

    def search(query: str, top_k: int):
        calls.append((query, top_k))
        return []

    runner = AgenticRagRunner(
        search,
        lambda _: {},
        lambda *args: RagJudgeResult(status="insufficient"),
    )
    runner.run(
        "legacy query",
        config=agentic.RagRunConfig(
            mode="deep",
            top_k=17,
            graph_hops=3,
            max_iterations=1,
        ),
    )

    assert calls == [("legacy query", 17)]


def test_agentic_rag_returns_sufficient_evidence_without_rewrite():
    searches = []

    def search(query: str, top_k: int):
        searches.append((query, top_k))
        return [{"chunk_id": "c1", "item_id": "i1", "score": 0.95}]

    def load_chunks(chunk_ids: list[str]):
        return {"c1": "Phase 2 uses LangChain function calling."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="sufficient",
            answer_basis="LangChain function calling is specified.",
            useful_chunk_ids=["c1"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=3, top_k=8).run(
        "How is Phase 2 implemented?"
    )

    assert result.status == "sufficient"
    assert result.summary == "LangChain function calling is specified."
    assert result.sources == [
        {
            "chunk_id": "c1",
            "item_id": "i1",
            "score": 0.95,
            "text": "Phase 2 uses LangChain function calling.",
        }
    ]
    assert result.evidence == [
        {
            "chunk_id": "c1",
            "item_id": "i1",
            "score": 0.95,
            "text": "Phase 2 uses LangChain function calling.",
        }
    ]
    assert searches == [("How is Phase 2 implemented?", 8)]


def test_agentic_rag_rewrites_then_succeeds():
    searches = []

    def search(query: str, top_k: int):
        searches.append(query)
        if len(searches) == 1:
            return []
        return [{"chunk_id": "c2", "item_id": "i2", "score": 0.88}]

    def load_chunks(chunk_ids: list[str]):
        return {"c2": "The knowledge tool runs a bounded retrieval loop."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        if not evidence:
            return RagJudgeResult(
                status="insufficient",
                missing=["No evidence found"],
                rewrite_query="bounded retrieval loop",
            )
        return RagJudgeResult(
            status="sufficient",
            answer_basis="Bounded retrieval loop found.",
            useful_chunk_ids=["c2"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=3, top_k=8).run(
        "What does knowledge search do?"
    )

    assert result.status == "sufficient"
    assert searches == ["What does knowledge search do?", "bounded retrieval loop"]
    assert result.iterations == 2


def test_agentic_rag_returns_clarification_when_still_insufficient():
    def search(query: str, top_k: int):
        return []

    def load_chunks(chunk_ids: list[str]):
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need a directory scope"],
            rewrite_query="",
            clarify={
                "question": "Which scope should I use?",
                "options": [
                    {"label": "Current knowledge base", "value": "scope:knowledge"},
                    {"label": "Specific directory", "value": "scope:directory"},
                ],
            },
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=2, top_k=8).run(
        "Summarize it"
    )

    assert result.status == "insufficient"
    assert result.missing == ["Need a directory scope"]
    assert result.clarify["question"] == "Which scope should I use?"
    assert result.iterations == 2
    assert result.evidence == []


def test_agentic_rag_returns_last_evidence_when_insufficient():
    def search(query: str, top_k: int):
        return [{"chunk_id": "c3", "item_id": "i3", "score": 0.72}]

    def load_chunks(chunk_ids: list[str]):
        return {"c3": "The retrieved chunk does not fully answer the question."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need a more specific target"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=1, top_k=8).run(
        "Summarize the selected target"
    )

    assert result.status == "insufficient"
    assert result.evidence == [
        {
            "chunk_id": "c3",
            "item_id": "i3",
            "score": 0.72,
            "text": "The retrieved chunk does not fully answer the question.",
        }
    ]


def test_agentic_rag_preserves_missing_when_later_iteration_has_none():
    calls = 0

    def search(query: str, top_k: int):
        return []

    def load_chunks(chunk_ids: list[str]):
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        nonlocal calls
        calls += 1
        if calls == 1:
            return RagJudgeResult(
                status="insufficient",
                missing=["Need scope"],
                rewrite_query="narrower scope",
            )
        return RagJudgeResult(status="insufficient", missing=[])

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=2, top_k=8).run(
        "Summarize it"
    )

    assert result.status == "insufficient"
    assert result.missing == ["Need scope"]


def test_agentic_rag_does_not_invent_clarification_when_judge_provides_none():
    def search(query: str, top_k: int):
        return []

    def load_chunks(chunk_ids: list[str]):
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need scope"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=1, top_k=8).run(
        "Summarize it"
    )

    assert result.status == "insufficient"
    assert result.clarify is None


def test_agentic_rag_does_not_share_judge_clarification_payloads():
    def search(query: str, top_k: int):
        return []

    def load_chunks(chunk_ids: list[str]):
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need scope"],
            clarify={"question": "Which scope?", "options": []},
        )

    runner = AgenticRagRunner(search, load_chunks, judge, max_iterations=1, top_k=8)

    result = runner.run("Summarize it")
    result.clarify["options"].append(
        {"label": "Mutated option", "value": "scope:mutated"}
    )

    next_result = runner.run("Summarize it")

    assert next_result.clarify["options"] == []


def test_agentic_rag_deduplicates_chunk_hits_for_loading_and_sources():
    loaded_chunk_ids = []

    def search(query: str, top_k: int):
        return [
            {"chunk_id": "c1", "item_id": "i1", "score": 0.95},
            {"chunk_id": "c1", "item_id": "i1-duplicate", "score": 0.9},
        ]

    def load_chunks(chunk_ids: list[str]):
        loaded_chunk_ids.append(chunk_ids)
        return {"c1": "Phase 2 uses LangChain function calling."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="sufficient",
            answer_basis="LangChain function calling is specified.",
            useful_chunk_ids=["c1"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=3, top_k=8).run(
        "How is Phase 2 implemented?"
    )

    assert loaded_chunk_ids == [["c1"]]
    assert result.sources == [
        {
            "chunk_id": "c1",
            "item_id": "i1",
            "score": 0.95,
            "text": "Phase 2 uses LangChain function calling.",
        }
    ]


def test_agentic_rag_preserves_non_chunk_source_payloads():
    def search(query: str, top_k: int):
        return [
            {
                "source_kind": "personal_asset_unit",
                "source_id": "unit-1",
                "display_title": "LoRA learning note",
                "text": "LoRA reduces trainable parameters for adaptation.",
                "snippet": "A short note about LoRA.",
                "score": 0.91,
            }
        ]

    def load_chunks(chunk_ids: list[str]):
        assert chunk_ids == []
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="sufficient",
            answer_basis="Found the relevant asset note.",
            useful_chunk_ids=[],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=1, top_k=8).run(
        "What do I know about LoRA?"
    )

    assert result.evidence == [
        {
            "source_kind": "personal_asset_unit",
            "source_id": "unit-1",
            "display_title": "LoRA learning note",
            "text": "LoRA reduces trainable parameters for adaptation.",
            "snippet": "A short note about LoRA.",
            "score": 0.91,
        }
    ]
    assert result.sources == result.evidence
