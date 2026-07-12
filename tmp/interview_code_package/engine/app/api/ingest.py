# prism/engine/app/api/ingest.py
import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..ingestion.pipeline import ingest_item

router = APIRouter(prefix="/ingest", tags=["ingest"])
logger = logging.getLogger("uvicorn.error")
_ingest_lock = threading.Lock()


class IngestRequest(BaseModel):
    item_id: str


@router.post("")
def ingest(req: IngestRequest):
    try:
        with _ingest_lock:
            count = ingest_item(req.item_id)
    except Exception as exc:
        logger.exception("[ingest] failed item_id=%s", req.item_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "ingest_failed", "message": str(exc)},
        ) from exc
    return {"item_id": req.item_id, "chunks": count, "status": "done"}
