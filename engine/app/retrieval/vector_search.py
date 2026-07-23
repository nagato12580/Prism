"""Natively scoped dense retrieval."""

from ..indexing.milvus_index import search_index
from .contracts import Candidate, ChannelResult, SearchScope


def vector_search(
    query_embedding: list[float], scope: SearchScope, top_k: int
) -> ChannelResult:
    try:
        rows = search_index(query_embedding=query_embedding, scope=scope, top_k=top_k)
    except Exception:
        return ChannelResult.failed("dense", "VECTOR_INDEX_UNAVAILABLE", retryable=True)
    try:
        candidates = [Candidate(
            chunk_uid=row["chunk_uid"], item_id=row.get("item_id") or "",
            file_uid=row.get("file_uid") or "", channel="dense",
            raw_score=float(row.get("score", 0.0)), raw_rank=rank,
            metadata={**row, "kb_uid": row.get("kb_uid") or scope.kb_uid},
        ) for rank, row in enumerate(rows, 1)]
    except Exception:
        return ChannelResult.failed("dense", "VECTOR_RESPONSE_INVALID", retryable=False)
    return ChannelResult.ok("dense", candidates)
