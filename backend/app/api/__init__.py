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
from .unified_graph import router as unified_graph_router
from .graph_exports import router as graph_exports_router
from .knowledge_bases import router as knowledge_bases_router
from .knowledge_files import router as knowledge_files_router
from .agent_tools import router as agent_tools_router
from .citations import router as citations_router
from .knowledge_retrieval import router as knowledge_retrieval_router
from .knowledge_evaluation import router as knowledge_evaluation_router
from .knowledge_enrichment import router as knowledge_enrichment_router
from .agent_chat_proxy import router as agent_chat_proxy_router
from .team_admin import router as team_admin_router
from .auth import router as auth_router
from .model_providers import router as model_providers_router


def register_routers(app):
    api_prefix = APIRouter(prefix="/api/v1")
    api_prefix.include_router(knowledge_router)
    api_prefix.include_router(upload_router)
    api_prefix.include_router(chat_router)
    api_prefix.include_router(wiki_router)
    api_prefix.include_router(assets_router)
    api_prefix.include_router(knowledge_graph_router)
    api_prefix.include_router(unified_graph_router)
    api_prefix.include_router(graph_exports_router)
    api_prefix.include_router(memories_router)
    api_prefix.include_router(traces_router)
    api_prefix.include_router(knowledge_bases_router)
    api_prefix.include_router(knowledge_files_router)
    api_prefix.include_router(agent_tools_router)
    api_prefix.include_router(citations_router)
    api_prefix.include_router(knowledge_retrieval_router)
    api_prefix.include_router(knowledge_evaluation_router)
    api_prefix.include_router(knowledge_enrichment_router)
    api_prefix.include_router(agent_chat_proxy_router)
    api_prefix.include_router(team_admin_router)
    api_prefix.include_router(auth_router)
    api_prefix.include_router(model_providers_router)
    app.include_router(api_prefix)
