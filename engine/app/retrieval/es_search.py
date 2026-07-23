"""Natively scoped Elasticsearch BM25 retrieval."""
import os

from ..es_client import get_es
from ..indexing.es_index import V2_INDEX_NAME
from .contracts import Candidate, ChannelResult, SearchScope


def es_fulltext_search(query: str, scope: SearchScope, top_k: int) -> ChannelResult:
    filters = [
        {"term": {"tenant_id": scope.tenant_id}},
        {"term": {"kb_uid": scope.kb_uid}},
        {"term": {"generation": scope.index_generation}},
    ]
    if scope.file_uids:
        filters.append({"terms": {"file_uid": list(scope.file_uids)}})
    if scope.source_types:
        filters.append({"terms": {"source_type": list(scope.source_types)}})
    try:
        response = get_es().search(
            index=os.getenv("PRISM_RETRIEVAL_ES_INDEX", V2_INDEX_NAME), routing=scope.kb_uid, size=top_k,
            query={"bool": {
                "must": [{"match": {"content": {"query": query}}}],
                "filter": filters,
            }},
        )
    except Exception:
        return ChannelResult.failed("bm25", "FULLTEXT_INDEX_UNAVAILABLE", retryable=True)

    try:
        candidates = []
        for rank, hit in enumerate(response["hits"]["hits"], 1):
            source = hit["_source"]
            candidates.append(Candidate(
                chunk_uid=source.get("chunk_uid", hit.get("_id", "")),
                item_id=source.get("item_id", ""), file_uid=source.get("file_uid", ""),
                channel="bm25", raw_score=float(hit.get("_score", 0.0)), raw_rank=rank,
                metadata=dict(source),
            ))
    except Exception:
        return ChannelResult.failed("bm25", "FULLTEXT_RESPONSE_INVALID", retryable=False)
    return ChannelResult.ok("bm25", candidates)
