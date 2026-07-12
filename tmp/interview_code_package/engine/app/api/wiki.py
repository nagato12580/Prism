# prism/engine/app/api/wiki.py
"""Engine Wiki extract endpoint"""
import threading
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..wiki.extraction_engine import run_extraction

router = APIRouter(prefix="/wiki", tags=["wiki"])
logger = logging.getLogger(__name__)


class WikiExtractRequest(BaseModel):
    doc_id: str = Field(..., description="wiki_document.id")
    file_id: str = Field(..., description="knowledge_file.id")


@router.post("/extract")
def extract(request: WikiExtractRequest):
    """异步启动 Wiki 知识抽取管线。"""
    logger.info(f"Wiki extraction triggered: doc_id={request.doc_id}")

    def _run():
        try:
            run_extraction(request.doc_id, request.file_id)
        except Exception as e:
            logger.exception(f"Wiki extraction failed: doc_id={request.doc_id}: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return {"doc_id": request.doc_id, "status": "processing"}
