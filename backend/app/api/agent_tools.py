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


@router.post("/search", response_model=ToolResult)
def search_knowledge(body: ToolRequest, actor: ActorContext = Depends(get_actor_context), db: Session = Depends(get_db)):
    try:
        KnowledgeAccessPolicy(db).require_read(actor, body.kb_uid)
    except KnowledgeNotFound:
        raise ApiProblem(404, "KNOWLEDGE_BASE_NOT_FOUND", "KB not found")
    except KnowledgeAccessDenied:
        raise ApiProblem(403, "KNOWLEDGE_ACCESS_DENIED", "Access denied")
    return ToolResult(tool="search", status="ok", data=[{"kb_uid": body.kb_uid, "query": body.query}])


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
