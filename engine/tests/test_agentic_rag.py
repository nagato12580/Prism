from engine.app.agent.rag.agentic import AgenticRagRunner, RagJudgeResult


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
    assert result.sources == [{"chunk_id": "c1", "item_id": "i1", "score": 0.95}]
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


def test_agentic_rag_uses_default_clarification_when_judge_provides_none():
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
    assert result.clarify == {
        "question": "I need one more detail to answer accurately. What should I use as the scope?",
        "options": [
            {"label": "Current knowledge base", "value": "scope:knowledge"},
            {"label": "Specific directory", "value": "scope:directory"},
            {"label": "Allow web supplement", "value": "scope:web"},
        ],
    }


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
    assert result.sources == [{"chunk_id": "c1", "item_id": "i1", "score": 0.95}]
