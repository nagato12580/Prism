# prism/engine/app/api/ingest.py
from fastapi import APIRouter
from pydantic import BaseModel
from ..ingestion.pipeline import ingest_item

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestRequest(BaseModel):
    item_id: str


@router.post("")
def ingest(req: IngestRequest):
    count = ingest_item(req.item_id)
    return {"item_id": req.item_id, "chunks": count, "status": "done"}
