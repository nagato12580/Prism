# prism/engine/run.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine.app.api.chat import router as chat_router
from engine.app.api.ingest import router as ingest_router
from engine.app.api.wiki import router as wiki_router
from engine.app.config import settings
from engine.app.es_client import ensure_index
from engine.app.jobs.worker import KnowledgeWorkerManager
from engine.app.milvus_client import connect, ensure_collection


_worker_manager = None


def create_app():
    app = FastAPI(title="Prism Engine")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefixed = APIRouter(prefix="/api/v1")
    prefixed.include_router(ingest_router)
    prefixed.include_router(chat_router)
    prefixed.include_router(wiki_router)
    app.include_router(prefixed)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    def startup():
        global _worker_manager
        try:
            connect()
            ensure_collection()
            print("[engine] Milvus connected")
        except Exception as e:
            print(f"[engine] Milvus initialization failed: {e}")
        try:
            ensure_index()
            print("[engine] ES index ready")
        except Exception as e:
            print(f"[engine] ES initialization failed: {e}")
        try:
            _worker_manager = KnowledgeWorkerManager()
            _worker_manager.start()
            print("[engine] Knowledge workers started")
        except Exception as e:
            print(f"[engine] Knowledge workers failed to start: {e}")

    @app.on_event("shutdown")
    def shutdown():
        global _worker_manager
        if _worker_manager is not None:
            _worker_manager.stop()
            _worker_manager = None

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("engine.run:app", host=settings.ENGINE_HOST, port=settings.ENGINE_PORT, reload=False)
