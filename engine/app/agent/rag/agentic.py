from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import re
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


@dataclass(frozen=True, slots=True)
class RagRunConfig:
    mode: Literal["fast", "deep"] = "fast"
    top_k: int = 8
    graph_hops: int = 1
    max_iterations: int = 3

    def __post_init__(self) -> None:
        if self.mode not in ("fast", "deep"):
            raise ValueError("mode must be 'fast' or 'deep'")
        if not 1 <= self.top_k <= 30:
            raise ValueError("top_k must be between 1 and 30")
        if not 1 <= self.graph_hops <= 3:
            raise ValueError("graph_hops must be between 1 and 3")
        if not 1 <= self.max_iterations <= 10:
            raise ValueError("max_iterations must be between 1 and 10")


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
        config: RagRunConfig | None = None,
    ) -> None:
        self.search = search
        self.load_chunks = load_chunks
        self.judge = judge
        self.config = config or RagRunConfig(top_k=top_k, max_iterations=max_iterations)
        self.max_iterations = self.config.max_iterations
        self.top_k = self.config.top_k

    def run(self, question: str, *, config: RagRunConfig | None = None) -> AgenticRagResult:
        config = config or self.config
        query = question
        missing: list[str] = []
        clarify: ClarifyRequest | None = None
        accumulated_hits: list[SearchHit] = []
        seen_queries = {self._normalize_query(query)}

        for iteration in range(1, config.max_iterations + 1):
            hits = self._search(query, config)
            accumulated_hits = self._first_hits_by_chunk([*accumulated_hits, *hits])
            evidence = self._build_evidence(accumulated_hits)
            judgment = self.judge(question, query, evidence, missing)

            if judgment.status == "sufficient":
                return AgenticRagResult(
                    status="sufficient",
                    summary=judgment.answer_basis,
                    evidence=evidence,
                    sources=self._useful_sources(evidence, judgment.useful_chunk_ids),
                    iterations=iteration,
                )

            missing = judgment.missing or missing
            clarify = judgment.clarify or clarify
            if judgment.rewrite_query and iteration < config.max_iterations:
                normalized_rewrite = self._normalize_query(judgment.rewrite_query)
                if not normalized_rewrite or normalized_rewrite in seen_queries:
                    break
                seen_queries.add(normalized_rewrite)
                query = judgment.rewrite_query.strip()

        return AgenticRagResult(
            status="insufficient",
            evidence=self._build_evidence(accumulated_hits),
            missing=missing,
            clarify=clarify or default_clarify_request(),
            iterations=iteration,
        )

    def _search(self, query: str, config: RagRunConfig) -> list[SearchHit]:
        parameters = inspect.signature(self.search).parameters
        supports_any_keyword = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        controls: dict[str, Any] = {}
        for name, value in (
            ("mode", config.mode),
            ("graph_hops", config.graph_hops),
        ):
            parameter = parameters.get(name)
            if supports_any_keyword or (
                parameter is not None
                and parameter.kind
                in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            ):
                controls[name] = value
        return self.search(query, config.top_k, **controls)

    def _build_evidence(self, hits: list[SearchHit]) -> list[Evidence]:
        hits = self._first_hits_by_chunk(hits)
        chunk_ids = [self._chunk_key(hit) for hit in hits if self._chunk_key(hit) is not None]
        chunk_details = self.load_chunks(chunk_ids)
        return [
            self._enrich_hit(hit, chunk_details)
            for hit in hits
        ]

    def _useful_sources(
        self, hits: list[SearchHit], useful_chunk_ids: list[str]
    ) -> list[SearchHit]:
        enriched = self._first_hits_by_chunk(hits)
        useful = set(useful_chunk_ids)
        if not useful:
            return enriched
        return [hit for hit in enriched if self._chunk_key(hit) in useful]

    @staticmethod
    def _enrich_hit(
        hit: SearchHit, chunk_details: dict[str, dict[str, str]]
    ) -> Evidence:
        details = chunk_details.get(AgenticRagRunner._chunk_key(hit), {})
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
            chunk_id = AgenticRagRunner._chunk_key(hit)
            if chunk_id is None:
                unique_hits.append(hit)
                continue
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            unique_hits.append(hit)
        return unique_hits

    @staticmethod
    def _chunk_key(hit: SearchHit) -> str | None:
        return hit.get("chunk_uid") or hit.get("chunk_id")

    @staticmethod
    def _normalize_query(query: str) -> str:
        return re.sub(r"\s+", " ", query).strip().casefold()
