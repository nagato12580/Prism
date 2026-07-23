"""Private Engine knowledge retrieval endpoints.

Ingestion is intentionally absent here: Backend creates durable Jobs and the
Engine worker consumes their IDs.  A synchronous parse/index endpoint would
bypass leases, retries, generation publication, and authorization.
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class SearchRequest(BaseModel):
    kb_uid: str
    query: str
    max_results: int = 5


@router.post("/search")
def search_knowledge(req: SearchRequest):
    """Compatibility search adapter pending the scoped retrieval contract."""
    from elasticsearch import Elasticsearch
    from engine.app.config import settings as engine_settings

    items = []
    try:
        es = Elasticsearch([engine_settings.ES_HOST], request_timeout=10)
        es_index = "prism_chunks"
        if es.indices.exists(index=es_index):
            body = {
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"topic_id": req.kb_uid}},
                            {"match": {"content": req.query}},
                        ]
                    }
                },
                "size": req.max_results,
                "_source": ["chunk_id", "item_id", "content", "chunk_type", "doc_name"],
            }
            resp = es.search(index=es_index, body=body)
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                items.append({
                    "chunk_id": src.get("chunk_id", ""),
                    "item_id": src.get("item_id", ""),
                    "text": src.get("content", "")[:500],
                    "score": hit.get("_score", 0.0),
                    "source_kind": "document_chunk",
                    "title": src.get("doc_name", ""),
                })
        es.transport.close()
    except Exception as exc:
        logger.warning("[knowledge.search] ES search failed: %s", exc)

    return {"status": "ok" if items else "no_hits", "results": items, "total": len(items)}
