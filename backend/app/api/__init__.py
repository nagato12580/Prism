# prism/backend/app/api/__init__.py
from fastapi import APIRouter

from .knowledge import router as knowledge_router


def register_routers(app):
    """注册所有路由到 app，统一加 /api/v1 前缀。"""
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    app.include_router(api_prefix)
