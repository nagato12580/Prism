from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypeAlias


RagStatus: TypeAlias = Literal["sufficient", "insufficient"]
SearchHit: TypeAlias = dict[str, Any]
Evidence: TypeAlias = dict[str, Any]
ClarifyOption: TypeAlias = dict[str, str]
ClarifyRequest: TypeAlias = dict[str, Any]
SearchFn: TypeAlias = Callable[[str, int], list[SearchHit]]
LoadChunksFn: TypeAlias = Callable[[list[str]], dict[str, dict[str, str]]]
JudgeFn: TypeAlias = Callable[
    [str, str, list[Evidence], list[str]], "RagJudgeResult"
]


# P0: No longer emit a meaningless scope clarify by default.
# When the RAG judge returns insufficient without a specific clarify question,
# return None so the agent answers based on whatever evidence it has.
DEFAULT_CLARIFY: ClarifyRequest | None = None


def default_clarify_request() -> ClarifyRequest | None:
    return None


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
    evidence: list[Evidence] = field(default_factory=list)
    sources: list[SearchHit] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    clarify: ClarifyRequest | None = field(default_factory=default_clarify_request)
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
        last_evidence: list[Evidence] = []

        for iteration in range(1, self.max_iterations + 1):
            hits = self.search(query, self.top_k)
            evidence = self._build_evidence(hits)
            last_evidence = evidence
            judgment = self.judge(question, query, evidence, missing)

            if judgment.status == "sufficient":
                return AgenticRagResult(
                    status="sufficient",
                    summary=judgment.answer_basis,
                    evidence=evidence,
                    sources=self._useful_sources(hits, judgment.useful_chunk_ids),
                    iterations=iteration,
                )

            missing = judgment.missing or missing
            clarify = judgment.clarify or clarify
            if judgment.rewrite_query and iteration < self.max_iterations:
                query = judgment.rewrite_query

        return AgenticRagResult(
            status="insufficient",
            evidence=last_evidence,
            missing=missing,
            clarify=clarify or default_clarify_request(),
            iterations=self.max_iterations,
        )

    def _build_evidence(self, hits: list[SearchHit]) -> list[Evidence]:
        hits = self._first_hits_by_chunk(hits)
        chunk_ids = [hit["chunk_id"] for hit in hits if "chunk_id" in hit]
        chunk_details = self.load_chunks(chunk_ids)
        return [
            self._enrich_hit(hit, chunk_details)
            for hit in hits
        ]

    def _useful_sources(
        self, hits: list[SearchHit], useful_chunk_ids: list[str]
    ) -> list[SearchHit]:
        hits = self._first_hits_by_chunk(hits)
        chunk_ids = [hit["chunk_id"] for hit in hits if "chunk_id" in hit]
        chunk_details = self.load_chunks(chunk_ids)
        enriched = [
            self._enrich_hit(hit, chunk_details)
            for hit in hits
        ]
        useful = set(useful_chunk_ids)
        if not useful:
            return enriched
        return [hit for hit in enriched if hit.get("chunk_id") in useful]

    @staticmethod
    def _enrich_hit(
        hit: SearchHit, chunk_details: dict[str, dict[str, str]]
    ) -> Evidence:
        details = chunk_details.get(hit.get("chunk_id"), {})
        if isinstance(details, str):
            text = details
            doc_name = None
        else:
            text = details.get("text")
            doc_name = details.get("doc_name")
        enriched = dict(hit)
        if text not in (None, ""):
            enriched["text"] = text
        else:
            enriched["text"] = hit.get("text", "")
        if doc_name not in (None, ""):
            enriched["doc_name"] = doc_name
        elif "doc_name" in hit:
            enriched["doc_name"] = hit.get("doc_name", "")
        return enriched

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
