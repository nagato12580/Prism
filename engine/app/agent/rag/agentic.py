from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypeAlias


RagStatus: TypeAlias = Literal["sufficient", "insufficient"]
SearchHit: TypeAlias = dict[str, Any]
Evidence: TypeAlias = dict[str, Any]
ClarifyOption: TypeAlias = dict[str, str]
ClarifyRequest: TypeAlias = dict[str, Any]
SearchFn: TypeAlias = Callable[[str, int], list[SearchHit]]
LoadChunksFn: TypeAlias = Callable[[list[str]], dict[str, str]]
JudgeFn: TypeAlias = Callable[
    [str, str, list[Evidence], list[str]], "RagJudgeResult"
]


DEFAULT_CLARIFY: ClarifyRequest = {
    "question": "What would you like me to focus on?",
    "options": [
        {"label": "Current knowledge base", "value": "scope:knowledge"},
        {"label": "Provide more detail", "value": "scope:clarify"},
    ],
}


@dataclass(slots=True)
class RagJudgeResult:
    status: RagStatus
    answer_basis: str = ""
    useful_chunk_ids: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    rewrite_query: str = ""
    clarify: ClarifyRequest | None = None


@dataclass(slots=True)
class AgenticRagResult:
    status: RagStatus
    summary: str = ""
    sources: list[SearchHit] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    clarify: ClarifyRequest = field(default_factory=lambda: DEFAULT_CLARIFY.copy())
    iterations: int = 0


class AgenticRagRunner:
    def __init__(
        self,
        search: SearchFn,
        load_chunks: LoadChunksFn,
        judge: JudgeFn,
        *,
        max_iterations: int = 3,
        top_k: int = 8,
    ) -> None:
        self.search = search
        self.load_chunks = load_chunks
        self.judge = judge
        self.max_iterations = max_iterations
        self.top_k = top_k

    def run(self, question: str) -> AgenticRagResult:
        query = question
        missing: list[str] = []
        clarify: ClarifyRequest | None = None

        for iteration in range(1, self.max_iterations + 1):
            hits = self.search(query, self.top_k)
            evidence = self._build_evidence(hits)
            judgment = self.judge(question, query, evidence, missing)

            if judgment.status == "sufficient":
                return AgenticRagResult(
                    status="sufficient",
                    summary=judgment.answer_basis,
                    sources=self._useful_sources(hits, judgment.useful_chunk_ids),
                    iterations=iteration,
                )

            missing = judgment.missing or missing
            clarify = judgment.clarify or clarify
            if judgment.rewrite_query and iteration < self.max_iterations:
                query = judgment.rewrite_query

        return AgenticRagResult(
            status="insufficient",
            missing=missing,
            clarify=clarify or DEFAULT_CLARIFY.copy(),
            iterations=self.max_iterations,
        )

    def _build_evidence(self, hits: list[SearchHit]) -> list[Evidence]:
        hits = self._first_hits_by_chunk(hits)
        chunk_ids = [hit["chunk_id"] for hit in hits if "chunk_id" in hit]
        chunk_text_by_id = self.load_chunks(chunk_ids)
        return [
            {**hit, "text": chunk_text_by_id.get(hit.get("chunk_id"), "")}
            for hit in hits
        ]

    @staticmethod
    def _useful_sources(
        hits: list[SearchHit], useful_chunk_ids: list[str]
    ) -> list[SearchHit]:
        hits = AgenticRagRunner._first_hits_by_chunk(hits)
        useful = set(useful_chunk_ids)
        if not useful:
            return hits
        return [hit for hit in hits if hit.get("chunk_id") in useful]

    @staticmethod
    def _first_hits_by_chunk(hits: list[SearchHit]) -> list[SearchHit]:
        seen_chunk_ids: set[str] = set()
        unique_hits: list[SearchHit] = []
        for hit in hits:
            chunk_id = hit.get("chunk_id")
            if chunk_id is None:
                unique_hits.append(hit)
                continue
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            unique_hits.append(hit)
        return unique_hits
