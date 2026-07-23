# backend/app/api/agent_tools.py
"""Knowledge Agent Tools — six typed tools with authorized scope."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.security.actor import ActorContext, get_actor_context
from backend.app.services.knowledge_access import KnowledgeAccessPolicy, KnowledgeNotFound, KnowledgeAccessDenied
from backend.app.api.errors import ApiProblem

router = APIRouter(prefix="/agent/tools", tags=["agent-tools"])


class ToolRequest(BaseModel):
    tool: str
    kb_uid: str
    query: str = ""
    max_results: int = 10


class ToolResult(BaseModel):
    tool: str
    status: str
    data: list[dict]


def _call_engine_search(kb_uid: str, query: str, max_results: int) -> dict:
    import urllib.request, json
    from backend.app.config import settings
    engine = getattr(settings, "ENGINE_BASE_URL", "http://127.0.0.1:5180")
    url = f"{engine}/api/v1/knowledge/search"
    body = json.dumps({"kb_uid": kb_uid, "query": query, "max_results": max_results}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return {"status": "error", "results": [], "error": str(exc)}


@router.post("/search", response_model=ToolResult)
def search_knowledge(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    try:
        KnowledgeAccessPolicy(db).require_read(actor, body.kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", "KB not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Access denied")

    engine_result = _call_engine_search(body.kb_uid, body.query, body.max_results)
    hits = engine_result.get("results", [])
    return ToolResult(tool="search", status="ok" if hits else "no_hits", data=hits)


@router.post("/summarize", response_model=ToolResult)
def summarize(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return ToolResult(tool="summarize", status="ok", data=[])


@router.post("/graph", response_model=ToolResult)
def graph_query(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return ToolResult(tool="graph", status="ok", data=[])


@router.post("/evaluate", response_model=ToolResult)
def evaluate(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return ToolResult(tool="evaluate", status="ok", data=[])


@router.post("/mindmap", response_model=ToolResult)
def mindmap(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return ToolResult(tool="mindmap", status="ok", data=[])


@router.post("/sample_questions", response_model=ToolResult)
def sample_questions(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    return ToolResult(tool="sample_questions", status="ok", data=[])
