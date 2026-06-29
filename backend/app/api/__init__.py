# prism/backend/app/api/__init__.py
from fastapi import APIRouter

from .knowledge import router as knowledge_router
from .upload import router as upload_router
from .chat import router as chat_router
from .wiki import router as wiki_router
from .assets import router as assets_router
from .knowledge_graph import router as knowledge_graph_router
from .memories import router as memories_router
from .traces import router as traces_router
from .graph_explore import router as graph_explore_router


def register_routers(app):
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    api_prefix.include_router(upload_router)
    api_prefix.include_router(chat_router)
    api_prefix.include_router(wiki_router)
    api_prefix.include_router(assets_router)
    api_prefix.include_router(knowledge_graph_router)
    api_prefix.include_router(memories_router)
    api_prefix.include_router(traces_router)
    api_prefix.include_router(graph_explore_router)
    app.include_router(api_prefix)
