# prism/backend/app/api/__init__.py
from fastapi import APIRouter

from .knowledge import router as knowledge_router
from .upload import router as upload_router
from .chat import router as chat_router


def register_routers(app):
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    api_prefix.include_router(upload_router)
    api_prefix.include_router(chat_router)
    app.include_router(api_prefix)
