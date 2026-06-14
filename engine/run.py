# prism/engine/run.py
import uvicorn
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from engine.app.config import settings
from engine.app.milvus_client import connect, ensure_collection
from engine.app.es_client import ensure_index
from engine.app.api.ingest import router as ingest_router
from engine.app.api.chat import router as chat_router


def create_app():
    app = FastAPI(title="Prism Engine")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    prefixed = APIRouter(prefix="/api/v1")
    prefixed.include_router(ingest_router)
    prefixed.include_router(chat_router)
    app.include_router(prefixed)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.on_event("startup")
    def startup():
        connect()
        ensure_collection()
        print("[engine] Milvus 已连接")
        try:
            ensure_index()
            print("[engine] ES 索引已就绪")
        except Exception as e:
            print(f"[engine] ES 初始化失败（检索将回退到 MySQL BM25）: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("engine.run:app", host=settings.ENGINE_HOST, port=settings.ENGINE_PORT, reload=False)
