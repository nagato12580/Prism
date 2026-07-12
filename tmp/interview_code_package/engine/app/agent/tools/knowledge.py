from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool
from engine.app.agent.tools.evidence import normalize_evidence_items


KEY = "knowledge_search"


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question or search query for Prism knowledge.")


def _graph_explanations_from_evidence_items(evidence_items: list[dict[str, Any]]) -> list[str]:
    explanations: list[str] = []
    seen: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        explain = metadata.get("graph_explain")
        if not isinstance(explain, dict):
            continue
        why = str(explain.get("why") or "").strip().rstrip(".。")
        evidence_type = str(explain.get("evidence_type") or "").upper()
        if not why or evidence_type not in {"EXTRACTED", "INFERRED"}:
            continue
        prefix = "Graph inference" if evidence_type == "INFERRED" else "Direct source evidence"
        line = f"{prefix}: {why}."
        path_text = _graph_path_text(metadata.get("graph_path"))
        if path_text:
            line += f" Path: {path_text}."
        if line not in seen:
            seen.add(line)
            explanations.append(line)
    return explanations


def _graph_path_text(graph_path: Any) -> str:
    if not isinstance(graph_path, list):
        return ""
    for route in graph_path:
        if not isinstance(route, dict):
            continue
        steps = route.get("steps")
        if not isinstance(steps, list):
            continue
        labels: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            label = step.get("label") or step.get("node_id") or step.get("edge_type")
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
        if labels:
            return " -> ".join(labels)
    return ""


def _citation_key(source: Any) -> tuple[str, str]:
    if isinstance(source, dict) and source.get("chunk_id") is not None:
        return ("chunk_id", str(source["chunk_id"]))
    return (
        "json",
        json.dumps(source, ensure_ascii=False, sort_keys=True, default=str),
    )


def _append_unique_citations(citations: list[Any], sources: list[Any]) -> None:
    seen = {_citation_key(citation) for citation in citations}
    for source in sources:
        key = _citation_key(source)
        if key not in seen:
            citations.append(source)
            seen.add(key)


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        if ctx.rag_runner is None:
            ctx.stats_holder[KEY] = {"hit_count": 0, "iterations": 0}
            return json.dumps(
                {
                    "status": "insufficient",
                    "summary": "Knowledge search is not configured.",
                    "missing": ["No RAG runner is available."],
                    "clarify": None,
                    "sources": [],
                    "evidence": [],
                    "evidence_items": [],
                },
                ensure_ascii=False,
            )

        result = ctx.rag_runner.run(query)
        sources = list(getattr(result, "sources", []))
        # 如果 sources 为空（insufficient 场景），用 evidence 补充
        if not sources:
            sources = list(getattr(result, "evidence", []))
        _append_unique_citations(ctx.citations, sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(sources),
            "iterations": getattr(result, "iterations", 0),
        }
        summary = getattr(result, "summary", "")
        if not summary:
            count = len(sources)
            if count > 0:
                summary = f"检索到 {count} 条相关内容，证据不足，正在追问"
            else:
                summary = f"完成 {getattr(result, 'iterations', 0)} 轮检索，未找到匹配内容"
        payload: dict[str, Any] = {
            "status": getattr(result, "status", "insufficient"),
            "summary": summary,
            "missing": getattr(result, "missing", []),
            "clarify": getattr(result, "clarify", None),
            "sources": sources,
            "evidence": result.evidence,
        }
        payload["evidence_items"] = normalize_evidence_items(KEY, payload)
        payload["graph_explanations"] = _graph_explanations_from_evidence_items(payload["evidence_items"])
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Search Prism's indexed knowledge and return grounded evidence.",
        args_schema=KnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description="Search Prism's indexed knowledge and return grounded evidence.",
        builder=build,
        default_enabled=True,
    )
)
