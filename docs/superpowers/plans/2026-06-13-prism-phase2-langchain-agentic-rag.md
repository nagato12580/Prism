# Prism Phase 2 LangChain Agentic RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Prism chat from basic RAG to a LangChain function-calling agent with Agentic RAG, tool process events, and user clarification interruptions.

**Architecture:** Keep the existing `/chat/answer` NDJSON endpoint, but route answer generation through a new `engine/app/agent` package. The agent uses `ChatOpenAI.bind_tools()` with a small tool registry; `knowledge_search` delegates to a bounded Agentic RAG loop that can judge sufficiency, rewrite queries, return sources, or request clarification.

**Tech Stack:** FastAPI, Python, LangChain (`langchain`, `langchain-openai`, `langchain-core`), OpenAI-compatible chat configuration, pytest, React, TypeScript, Vite.

---

## File Structure

- Modify: `requirements.txt`
  - Add LangChain dependencies.
- Create: `engine/app/agent/__init__.py`
  - Package marker.
- Create: `engine/app/agent/events.py`
  - NDJSON event helpers.
- Create: `engine/app/agent/prompts.py`
  - Agent and RAG judge prompts.
- Create: `engine/app/agent/rag/__init__.py`
  - RAG package marker.
- Create: `engine/app/agent/rag/agentic.py`
  - Agentic RAG loop and result types.
- Create: `engine/app/agent/tools/__init__.py`
  - Tool package exports and built-in registration imports.
- Create: `engine/app/agent/tools/base.py`
  - Tool spec, tool context, registry, enabled tool builder.
- Create: `engine/app/agent/tools/knowledge.py`
  - LangChain `knowledge_search` tool.
- Create: `engine/app/agent/tools/clarify.py`
  - LangChain `clarify_user` tool and interrupt result.
- Create: `engine/app/agent/tools/datetime.py`
  - Datetime tool.
- Create: `engine/app/agent/tools/web_search.py`
  - Disabled stub tool.
- Create: `engine/app/agent/runner.py`
  - LangChain function-calling loop that emits Prism NDJSON events.
- Modify: `engine/app/chat/answer.py`
  - Replace basic RAG internals with the new runner while preserving `answer_stream(query, history)`.
- Modify: `frontend/src/app/chatStore.ts`
  - Add message fields for tool runs and clarification.
- Modify: `frontend/src/pages/ChatPage.tsx`
  - Parse new NDJSON events and render tool chips plus clarification options.
- Test: `engine/tests/test_agent_events.py`
- Test: `engine/tests/test_agentic_rag.py`
- Test: `engine/tests/test_agent_tools.py`
- Test: `engine/tests/test_agent_runner.py`
- Test: `engine/tests/test_answer_stream_agent.py`

---

### Task 1: Dependencies And Event Helpers

**Files:**
- Modify: `requirements.txt`
- Create: `engine/app/agent/__init__.py`
- Create: `engine/app/agent/events.py`
- Test: `engine/tests/test_agent_events.py`

- [ ] **Step 1: Write failing event helper tests**

Create `engine/tests/test_agent_events.py`:

```python
import json

from engine.app.agent.events import (
    agent_status_event,
    done_event,
    error_event,
    sources_event,
    token_event,
    tool_call_event,
    tool_result_event,
    clarify_event,
)


def parse(line: str) -> dict:
    assert line.endswith("\n")
    return json.loads(line)


def test_event_helpers_emit_ndjson_lines():
    assert parse(agent_status_event("analyzing")) == {
        "type": "agent_status",
        "data": {"label": "analyzing"},
    }
    assert parse(token_event("hello")) == {"type": "token", "data": "hello"}
    assert parse(done_event()) == {"type": "done"}
    assert parse(error_event("boom")) == {"type": "error", "data": "boom"}


def test_tool_and_clarify_events_have_stable_shape():
    assert parse(tool_call_event("knowledge_search", "phase 2")) == {
        "type": "tool_call",
        "data": {"tool": "knowledge_search", "query": "phase 2"},
    }

    tool_result = parse(
        tool_result_event(
            tool="knowledge_search",
            status="success",
            summary="3 hits",
            query="phase 2",
            stats={"hit_count": 3},
            latency_ms=24,
        )
    )
    assert tool_result["type"] == "tool_result"
    assert tool_result["data"]["tool"] == "knowledge_search"
    assert tool_result["data"]["status"] == "success"
    assert tool_result["data"]["stats"] == {"hit_count": 3}
    assert tool_result["data"]["latency_ms"] == 24

    clarify = parse(
        clarify_event(
            "Which scope?",
            [
                {"label": "Current knowledge base", "value": "scope:knowledge"},
                {"label": "Allow web", "value": "scope:web"},
            ],
        )
    )
    assert clarify == {
        "type": "clarify",
        "data": {
            "question": "Which scope?",
            "options": [
                {"label": "Current knowledge base", "value": "scope:knowledge"},
                {"label": "Allow web", "value": "scope:web"},
            ],
        },
    }


def test_sources_event_preserves_existing_shape():
    sources = [{"chunk_id": "c1", "item_id": "i1", "score": 0.91}]
    assert parse(sources_event(sources)) == {"type": "sources", "data": sources}
```

- [ ] **Step 2: Run event tests to verify they fail**

Run:

```powershell
python -m pytest engine/tests/test_agent_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'engine.app.agent'`.

- [ ] **Step 3: Add dependencies and event implementation**

Before editing, verify dependency resolution:

```powershell
python -m pip install --dry-run langchain==0.2.17 langchain-core==0.2.43 langchain-openai==0.1.25 openai==1.30.0
```

Expected: dependency resolution starts without a version conflict between `langchain-openai` and `openai`. If the command fails because the active interpreter is Python 3.14 and tries to build `numpy==1.26.4`, record that as an environment issue and continue editing `requirements.txt`; do not install packages in this step.

Modify `requirements.txt` by adding these lines after `openai==1.30.0`:

```text
langchain==0.2.17
langchain-core==0.2.43
langchain-openai==0.1.25
```

Create `engine/app/agent/__init__.py`:

```python
"""LangChain agent package for Prism chat."""
```

Create `engine/app/agent/events.py`:

```python
import json
from typing import Any


def ndjson_event(event_type: str, data: Any = None) -> str:
    payload: dict[str, Any] = {"type": event_type}
    if data is not None:
        payload["data"] = data
    return json.dumps(payload, ensure_ascii=False) + "\n"


def agent_status_event(label: str) -> str:
    return ndjson_event("agent_status", {"label": label})


def tool_call_event(tool: str, query: str = "") -> str:
    return ndjson_event("tool_call", {"tool": tool, "query": query})


def tool_result_event(
    tool: str,
    status: str,
    summary: str,
    query: str = "",
    stats: dict[str, Any] | None = None,
    latency_ms: int | None = None,
) -> str:
    data: dict[str, Any] = {
        "tool": tool,
        "status": status,
        "summary": summary,
        "query": query,
    }
    if stats is not None:
        data["stats"] = stats
    if latency_ms is not None:
        data["latency_ms"] = latency_ms
    return ndjson_event("tool_result", data)


def clarify_event(question: str, options: list[dict[str, str]]) -> str:
    return ndjson_event("clarify", {"question": question, "options": options})


def sources_event(sources: list[dict[str, Any]]) -> str:
    return ndjson_event("sources", sources)


def token_event(text: str) -> str:
    return ndjson_event("token", text)


def error_event(message: str) -> str:
    return ndjson_event("error", message)


def done_event() -> str:
    return ndjson_event("done")
```

- [ ] **Step 4: Run event tests to verify they pass**

Run:

```powershell
python -m pytest engine/tests/test_agent_events.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt engine/app/agent/__init__.py engine/app/agent/events.py engine/tests/test_agent_events.py
git commit -m "feat: add agent stream event helpers"
```

---

### Task 2: Agentic RAG Loop

**Files:**
- Create: `engine/app/agent/prompts.py`
- Create: `engine/app/agent/rag/__init__.py`
- Create: `engine/app/agent/rag/agentic.py`
- Test: `engine/tests/test_agentic_rag.py`

- [ ] **Step 1: Write failing Agentic RAG tests**

Create `engine/tests/test_agentic_rag.py`:

```python
from engine.app.agent.rag.agentic import AgenticRagRunner, RagJudgeResult


def test_agentic_rag_returns_sufficient_evidence_without_rewrite():
    searches = []

    def search(query: str, top_k: int):
        searches.append((query, top_k))
        return [{"chunk_id": "c1", "item_id": "i1", "score": 0.95}]

    def load_chunks(chunk_ids: list[str]):
        return {"c1": "Phase 2 uses LangChain function calling."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="sufficient",
            answer_basis="LangChain function calling is specified.",
            useful_chunk_ids=["c1"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=3, top_k=8).run(
        "How is Phase 2 implemented?"
    )

    assert result.status == "sufficient"
    assert result.summary == "LangChain function calling is specified."
    assert result.sources == [{"chunk_id": "c1", "item_id": "i1", "score": 0.95}]
    assert searches == [("How is Phase 2 implemented?", 8)]


def test_agentic_rag_rewrites_then_succeeds():
    searches = []

    def search(query: str, top_k: int):
        searches.append(query)
        if len(searches) == 1:
            return []
        return [{"chunk_id": "c2", "item_id": "i2", "score": 0.88}]

    def load_chunks(chunk_ids: list[str]):
        return {"c2": "The knowledge tool runs a bounded retrieval loop."}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        if not evidence:
            return RagJudgeResult(
                status="insufficient",
                missing=["No evidence found"],
                rewrite_query="bounded retrieval loop",
            )
        return RagJudgeResult(
            status="sufficient",
            answer_basis="Bounded retrieval loop found.",
            useful_chunk_ids=["c2"],
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=3, top_k=8).run(
        "What does knowledge search do?"
    )

    assert result.status == "sufficient"
    assert searches == ["What does knowledge search do?", "bounded retrieval loop"]
    assert result.iterations == 2


def test_agentic_rag_returns_clarification_when_still_insufficient():
    def search(query: str, top_k: int):
        return []

    def load_chunks(chunk_ids: list[str]):
        return {}

    def judge(question: str, query: str, evidence: list[dict], missing: list[str]):
        return RagJudgeResult(
            status="insufficient",
            missing=["Need a directory scope"],
            rewrite_query="",
            clarify={
                "question": "Which scope should I use?",
                "options": [
                    {"label": "Current knowledge base", "value": "scope:knowledge"},
                    {"label": "Specific directory", "value": "scope:directory"},
                ],
            },
        )

    result = AgenticRagRunner(search, load_chunks, judge, max_iterations=2, top_k=8).run(
        "Summarize it"
    )

    assert result.status == "insufficient"
    assert result.missing == ["Need a directory scope"]
    assert result.clarify["question"] == "Which scope should I use?"
    assert result.iterations == 2
```

- [ ] **Step 2: Run Agentic RAG tests to verify they fail**

Run:

```powershell
python -m pytest engine/tests/test_agentic_rag.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `engine.app.agent.rag`.

- [ ] **Step 3: Add prompts and Agentic RAG implementation**

Create `engine/app/agent/prompts.py`:

```python
AGENT_SYSTEM_PROMPT = """You are Prism, a personal knowledge assistant.
Use tools when the answer depends on the user's knowledge base, time, or missing user intent.
Do not expose hidden reasoning. Return concise Chinese answers with citations when available.
If available evidence is insufficient, call clarify_user instead of inventing facts."""

RAG_JUDGE_PROMPT = """Judge whether the evidence can answer the user's question.
Return only JSON. Use one of these shapes:
{"status":"sufficient","answer_basis":"short summary","useful_chunk_ids":["chunk id"]}
{"status":"insufficient","missing":["specific missing point"],"rewrite_query":"better query","clarify":{"question":"short question","options":[{"label":"A","value":"a"},{"label":"B","value":"b"}]}}"""
```

Create `engine/app/agent/rag/__init__.py`:

```python
"""Agentic RAG utilities."""
```

Create `engine/app/agent/rag/agentic.py`:

```python
from dataclasses import dataclass, field
from typing import Callable, Literal, Any


@dataclass
class RagJudgeResult:
    status: Literal["sufficient", "insufficient"]
    answer_basis: str = ""
    useful_chunk_ids: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    rewrite_query: str = ""
    clarify: dict[str, Any] | None = None


@dataclass
class AgenticRagResult:
    status: Literal["sufficient", "insufficient"]
    summary: str
    evidence: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    missing: list[str] = field(default_factory=list)
    clarify: dict[str, Any] | None = None
    iterations: int = 0


SearchFn = Callable[[str, int], list[dict[str, Any]]]
LoadChunksFn = Callable[[list[str]], dict[str, str]]
JudgeFn = Callable[[str, str, list[dict[str, Any]], list[str]], RagJudgeResult]


class AgenticRagRunner:
    def __init__(
        self,
        search: SearchFn,
        load_chunks: LoadChunksFn,
        judge: JudgeFn,
        max_iterations: int = 3,
        top_k: int = 8,
    ) -> None:
        self.search = search
        self.load_chunks = load_chunks
        self.judge = judge
        self.max_iterations = max_iterations
        self.top_k = top_k

    def run(self, question: str) -> AgenticRagResult:
        query = question
        seen_sources: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        last_clarify: dict[str, Any] | None = None
        last_evidence: list[dict[str, Any]] = []

        for iteration in range(1, self.max_iterations + 1):
            hits = self.search(query, self.top_k)
            chunk_ids = [str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")]
            chunk_map = self.load_chunks(chunk_ids) if chunk_ids else {}
            evidence = []
            for hit in hits:
                chunk_id = str(hit.get("chunk_id", ""))
                if chunk_id and chunk_id not in seen_sources:
                    seen_sources[chunk_id] = hit
                text = chunk_map.get(chunk_id, "")
                if text:
                    evidence.append({**hit, "text": text})
            last_evidence = evidence

            decision = self.judge(question, query, evidence, missing)
            if decision.status == "sufficient":
                useful = set(decision.useful_chunk_ids)
                sources = [
                    source
                    for chunk_id, source in seen_sources.items()
                    if not useful or chunk_id in useful
                ]
                return AgenticRagResult(
                    status="sufficient",
                    summary=decision.answer_basis,
                    evidence=evidence,
                    sources=sources,
                    iterations=iteration,
                )

            missing = decision.missing or missing
            last_clarify = decision.clarify or last_clarify
            if decision.rewrite_query and iteration < self.max_iterations:
                query = decision.rewrite_query
                continue

        return AgenticRagResult(
            status="insufficient",
            summary="Knowledge base evidence is insufficient.",
            evidence=last_evidence,
            sources=list(seen_sources.values()),
            missing=missing,
            clarify=last_clarify
            or {
                "question": "I need one more detail to answer accurately. What should I use as the scope?",
                "options": [
                    {"label": "Current knowledge base", "value": "scope:knowledge"},
                    {"label": "Specific directory", "value": "scope:directory"},
                    {"label": "Allow web supplement", "value": "scope:web"},
                ],
            },
            iterations=self.max_iterations,
        )
```

- [ ] **Step 4: Run Agentic RAG tests to verify they pass**

Run:

```powershell
python -m pytest engine/tests/test_agentic_rag.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/prompts.py engine/app/agent/rag engine/tests/test_agentic_rag.py
git commit -m "feat: add agentic rag loop"
```

---

### Task 3: Tool Registry And Built-In Tools

**Files:**
- Create: `engine/app/agent/tools/__init__.py`
- Create: `engine/app/agent/tools/base.py`
- Create: `engine/app/agent/tools/knowledge.py`
- Create: `engine/app/agent/tools/clarify.py`
- Create: `engine/app/agent/tools/datetime.py`
- Create: `engine/app/agent/tools/web_search.py`
- Test: `engine/tests/test_agent_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `engine/tests/test_agent_tools.py`:

```python
from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


class FakeRagRunner:
    def run(self, query: str):
        return AgenticRagResult(
            status="sufficient",
            summary=f"evidence for {query}",
            evidence=[{"chunk_id": "c1", "text": "hello"}],
            sources=[{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
            iterations=1,
        )


def test_builtin_registry_contains_initial_tools():
    assert {"knowledge_search", "clarify_user", "datetime", "web_search"}.issubset(
        BUILTIN_REGISTRY
    )
    assert BUILTIN_REGISTRY["web_search"].default_enabled is False


def test_build_enabled_tools_skips_disabled_web_search():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tools = build_enabled_tools(ctx)
    names = {tool.name for tool in tools}
    assert "knowledge_search" in names
    assert "clarify_user" in names
    assert "datetime" in names
    assert "web_search" not in names


def test_knowledge_search_records_sources_and_stats():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_search")

    text = tool.invoke({"query": "phase 2"})

    assert "evidence for phase 2" in text
    assert ctx.citations == [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}]
    assert ctx.stats_holder["knowledge_search"]["hit_count"] == 1
    assert ctx.stats_holder["knowledge_search"]["iterations"] == 1
```

- [ ] **Step 2: Run tool tests to verify they fail**

Run:

```powershell
python -m pytest engine/tests/test_agent_tools.py -v
```

Expected: FAIL with missing `engine.app.agent.tools` modules.

- [ ] **Step 3: Implement registry and tools**

Create `engine/app/agent/tools/base.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool


@dataclass
class ToolContext:
    rag_runner: Any | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    stats_holder: dict[str, dict[str, Any]] = field(default_factory=dict)
    clarify_holder: dict[str, Any] | None = None


BuilderFn = Callable[[ToolContext], StructuredTool | None]


@dataclass
class ToolSpec:
    key: str
    name: str
    description: str
    builder: BuilderFn
    default_enabled: bool = True


BUILTIN_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    BUILTIN_REGISTRY[spec.key] = spec
    return spec


def build_enabled_tools(ctx: ToolContext, overrides: dict[str, bool] | None = None):
    overrides = overrides or {}
    tools = []
    for key, spec in BUILTIN_REGISTRY.items():
        enabled = overrides.get(key, spec.default_enabled)
        if not enabled:
            continue
        tool = spec.builder(ctx)
        if tool is not None:
            tools.append(tool)
    return tools
```

Create `engine/app/agent/tools/knowledge.py`:

```python
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from .base import ToolContext, ToolSpec, register_tool

KEY = "knowledge_search"


class KnowledgeSearchInput(BaseModel):
    query: str = Field(..., description="Question or keywords to search in Prism knowledge base")


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        if ctx.rag_runner is None:
            ctx.stats_holder[KEY] = {"hit_count": 0, "iterations": 0}
            return json.dumps(
                {"status": "insufficient", "summary": "Knowledge search is unavailable."},
                ensure_ascii=False,
            )

        result = ctx.rag_runner.run(query)
        ctx.citations.extend(result.sources)
        ctx.stats_holder[KEY] = {
            "hit_count": len(result.sources),
            "iterations": result.iterations,
        }
        payload = {
            "status": result.status,
            "summary": result.summary,
            "missing": result.missing,
            "clarify": result.clarify,
            "sources": result.sources,
            "evidence": result.evidence,
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Search the user's Prism knowledge base. Use this for uploaded documents and notes.",
        args_schema=KnowledgeSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name="Knowledge Search",
        description="Search uploaded Prism knowledge.",
        builder=build,
        default_enabled=True,
    )
)
```

Create `engine/app/agent/tools/clarify.py`:

```python
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from .base import ToolContext, ToolSpec, register_tool

KEY = "clarify_user"


class ClarifyInput(BaseModel):
    question: str = Field(..., description="Short user-facing clarification question")
    options: list[dict[str, str]] = Field(..., description="Two or three clickable options")


def build(ctx: ToolContext) -> StructuredTool:
    def run(question: str, options: list[dict[str, str]]) -> str:
        if ctx.clarify_holder is not None:
            ctx.clarify_holder["question"] = question
            ctx.clarify_holder["options"] = options[:3]
        return json.dumps({"status": "clarify", "question": question, "options": options[:3]}, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Ask the user for missing information. Use when evidence is insufficient.",
        args_schema=ClarifyInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name="Clarify User",
        description="Ask the user a clarification question.",
        builder=build,
        default_enabled=True,
    )
)
```

Create `engine/app/agent/tools/datetime.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool

from .base import ToolContext, ToolSpec, register_tool

KEY = "datetime"


def build(ctx: ToolContext) -> StructuredTool:
    def run() -> str:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Get the current date and time in Asia/Shanghai.",
    )


register_tool(
    ToolSpec(
        key=KEY,
        name="Date Time",
        description="Get current date and time.",
        builder=build,
        default_enabled=True,
    )
)
```

Create `engine/app/agent/tools/web_search.py`:

```python
from langchain_core.tools import StructuredTool

from .base import ToolContext, ToolSpec, register_tool

KEY = "web_search"


def build(ctx: ToolContext) -> StructuredTool:
    def run(query: str) -> str:
        return "Web search is not configured for this Prism phase."

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description="Disabled web search stub. Do not use unless explicitly enabled.",
    )


register_tool(
    ToolSpec(
        key=KEY,
        name="Web Search",
        description="Disabled web search stub.",
        builder=build,
        default_enabled=False,
    )
)
```

Create `engine/app/agent/tools/__init__.py`:

```python
from .base import BUILTIN_REGISTRY, ToolContext, ToolSpec, build_enabled_tools, register_tool

from . import clarify, datetime, knowledge, web_search  # noqa: F401

__all__ = [
    "BUILTIN_REGISTRY",
    "ToolContext",
    "ToolSpec",
    "build_enabled_tools",
    "register_tool",
]
```

- [ ] **Step 4: Run tool tests to verify they pass**

Run:

```powershell
python -m pytest engine/tests/test_agent_tools.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/tools engine/tests/test_agent_tools.py
git commit -m "feat: add langchain agent tools"
```

---

### Task 4: LangChain Function-Calling Runner

**Files:**
- Create: `engine/app/agent/runner.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write failing runner tests**

Create `engine/tests/test_agent_runner.py`:

```python
import json

from engine.app.agent.runner import LangChainAgentRunner


class FakeToolCall:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeTool:
    name = "knowledge_search"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "sufficient",
                "summary": "Found evidence.",
                "sources": [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
            }
        )


class FakeModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return FakeToolCall(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "knowledge_search",
                        "args": {"query": "phase 2"},
                    }
                ]
            )
        return FakeToolCall(content="Final answer")


def event_types(lines):
    return [json.loads(line)["type"] for line in lines]


def test_runner_emits_tool_sources_tokens_and_done():
    runner = LangChainAgentRunner(model=FakeModel(), tools=[FakeTool()])

    lines = list(runner.stream("How?", []))

    assert event_types(lines) == [
        "agent_status",
        "tool_call",
        "tool_result",
        "sources",
        "token",
        "done",
    ]
    assert json.loads(lines[-2])["data"] == "Final answer"


class FakeClarifyTool:
    name = "clarify_user"

    def invoke(self, args):
        return json.dumps(
            {
                "status": "clarify",
                "question": "Which scope?",
                "options": [{"label": "Knowledge", "value": "scope:knowledge"}],
            }
        )


class FakeClarifyModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return FakeToolCall(
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "clarify_user",
                    "args": {
                        "question": "Which scope?",
                        "options": [{"label": "Knowledge", "value": "scope:knowledge"}],
                    },
                }
            ]
        )


def test_runner_emits_clarify_and_stops():
    runner = LangChainAgentRunner(model=FakeClarifyModel(), tools=[FakeClarifyTool()])

    lines = list(runner.stream("Summarize it", []))

    assert event_types(lines) == ["agent_status", "tool_call", "tool_result", "clarify", "done"]
```

- [ ] **Step 2: Run runner tests to verify they fail**

Run:

```powershell
python -m pytest engine/tests/test_agent_runner.py -v
```

Expected: FAIL with missing `engine.app.agent.runner`.

- [ ] **Step 3: Implement runner**

Create `engine/app/agent/runner.py`:

```python
import json
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from .events import (
    agent_status_event,
    clarify_event,
    done_event,
    error_event,
    sources_event,
    token_event,
    tool_call_event,
    tool_result_event,
)
from .prompts import AGENT_SYSTEM_PROMPT

MAX_TOOL_ITERATIONS = 5


def create_chat_model(settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_API_BASE,
        api_key=settings.LLM_API_KEY,
    )


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


class LangChainAgentRunner:
    def __init__(
        self,
        model: Any,
        tools: list[Any],
        system_prompt: str = AGENT_SYSTEM_PROMPT,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        self.model = model
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

    def stream(self, query: str, history: list[dict] | None = None):
        history = history or []
        yield agent_status_event("analyzing question")

        messages: list[Any] = [SystemMessage(content=self.system_prompt)]
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "user":
                messages.append(HumanMessage(content=content))
        messages.append(HumanMessage(content=query))

        try:
            model_with_tools = self.model.bind_tools(self.tools) if self.tools else self.model
            for _ in range(self.max_iterations):
                response = model_with_tools.invoke(messages)
                tool_calls = getattr(response, "tool_calls", None) or []
                if not tool_calls:
                    text = _message_content(response)
                    if text:
                        yield token_event(text)
                    yield done_event()
                    return

                messages.append(response)
                for call in tool_calls:
                    name = call.get("name", "")
                    args = call.get("args", {}) or {}
                    query_arg = str(args.get("query", args.get("question", "")))
                    yield tool_call_event(name, query_arg)

                    tool = self.tool_map.get(name)
                    status = "success"
                    started = time.monotonic()
                    if tool is None:
                        result_text = json.dumps({"status": "error", "summary": f"Unknown tool: {name}"})
                        status = "error"
                    else:
                        try:
                            result_text = tool.invoke(args)
                        except Exception as exc:
                            result_text = json.dumps({"status": "error", "summary": str(exc)}, ensure_ascii=False)
                            status = "error"
                    latency_ms = int((time.monotonic() - started) * 1000)

                    payload = {}
                    try:
                        payload = json.loads(result_text)
                    except Exception:
                        payload = {"summary": result_text}
                    if payload.get("status") == "clarify":
                        status = "success"

                    yield tool_result_event(
                        tool=name,
                        status=status,
                        summary=str(payload.get("summary") or payload.get("question") or result_text),
                        query=query_arg,
                        stats=payload.get("stats"),
                        latency_ms=latency_ms,
                    )

                    sources = payload.get("sources") or []
                    if sources:
                        yield sources_event(sources)

                    if payload.get("status") == "clarify":
                        yield clarify_event(
                            str(payload.get("question", "I need more information.")),
                            list(payload.get("options") or []),
                        )
                        yield done_event()
                        return

                    messages.append(
                        ToolMessage(
                            content=result_text,
                            tool_call_id=call.get("id", name),
                        )
                    )

            yield error_event("Agent reached the maximum tool iteration limit.")
            yield done_event()
        except Exception as exc:
            yield error_event(str(exc))
            yield done_event()
```

- [ ] **Step 4: Run runner tests to verify they pass**

Run:

```powershell
python -m pytest engine/tests/test_agent_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "feat: add langchain function calling runner"
```

---

### Task 5: Wire Agent Into Chat Answer Stream

**Files:**
- Modify: `engine/app/chat/answer.py`
- Test: `engine/tests/test_answer_stream_agent.py`

- [ ] **Step 1: Write failing answer stream integration tests**

Create `engine/tests/test_answer_stream_agent.py`:

```python
import json

from engine.app.chat import answer


class FakeRunner:
    def stream(self, query, history):
        yield json.dumps({"type": "agent_status", "data": {"label": query}}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


def test_answer_stream_delegates_to_agent_runner(monkeypatch):
    monkeypatch.setattr(answer, "build_agent_runner", lambda: FakeRunner())

    lines = list(answer.answer_stream("hello", [{"role": "user", "content": "old"}]))

    assert json.loads(lines[0]) == {"type": "agent_status", "data": {"label": "hello"}}
    assert json.loads(lines[1]) == {"type": "done"}


def test_answer_stream_emits_error_when_runner_build_fails(monkeypatch):
    def fail():
        raise RuntimeError("no model")

    monkeypatch.setattr(answer, "build_agent_runner", fail)

    lines = list(answer.answer_stream("hello", []))

    assert json.loads(lines[0]) == {"type": "error", "data": "no model"}
```

- [ ] **Step 2: Run integration tests to verify they fail**

Run:

```powershell
python -m pytest engine/tests/test_answer_stream_agent.py -v
```

Expected: FAIL because `build_agent_runner` is not defined or `answer_stream` still uses basic RAG directly.

- [ ] **Step 3: Update `answer.py` to build and use the agent**

Modify `engine/app/chat/answer.py` to this shape, preserving existing imports needed by `_load_chunks`:

```python
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..agent.events import error_event
from ..agent.rag.agentic import AgenticRagRunner, RagJudgeResult
from ..agent.runner import LangChainAgentRunner, create_chat_model
from ..agent.tools import ToolContext, build_enabled_tools
from ..config import settings
from ..llm.client import chat
from ..retrieval.hybrid import hybrid_search

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _load_chunks(chunk_ids: list[str]) -> dict[str, str]:
    from backend.app.models.knowledge_item import KnowledgeChunk

    db = _Session()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        return {c.id: c.chunk_text for c in chunks}
    finally:
        db.close()


def _judge_rag(question: str, query: str, evidence: list[dict], missing: list[str]) -> RagJudgeResult:
    import json as json_module

    evidence_text = "\n\n".join(
        f"[{item.get('chunk_id')}] {item.get('text', '')}" for item in evidence
    )
    prompt = [
        {
            "role": "system",
            "content": (
                "Return only JSON. Decide whether the evidence answers the user question. "
                "Use status sufficient or insufficient."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question}\nSearch query: {query}\nPrevious missing: {missing}\n"
                f"Evidence:\n{evidence_text}\n\n"
                "If sufficient, return {\"status\":\"sufficient\",\"answer_basis\":\"...\","
                "\"useful_chunk_ids\":[\"...\"]}. If insufficient, return "
                "{\"status\":\"insufficient\",\"missing\":[\"...\"],\"rewrite_query\":\"...\","
                "\"clarify\":{\"question\":\"...\",\"options\":[{\"label\":\"...\",\"value\":\"...\"}]}}."
            ),
        },
    ]
    raw = chat(prompt)
    try:
        data = json_module.loads(raw)
    except Exception:
        data = {"status": "insufficient", "missing": ["The evidence judge returned invalid JSON."]}

    if data.get("status") == "sufficient":
        return RagJudgeResult(
            status="sufficient",
            answer_basis=str(data.get("answer_basis", "")),
            useful_chunk_ids=list(data.get("useful_chunk_ids") or []),
        )
    return RagJudgeResult(
        status="insufficient",
        missing=list(data.get("missing") or ["The knowledge base evidence is insufficient."]),
        rewrite_query=str(data.get("rewrite_query", "")),
        clarify=data.get("clarify"),
    )


def build_agent_runner() -> LangChainAgentRunner:
    rag_runner = AgenticRagRunner(
        search=lambda query, top_k: hybrid_search(query, top_k=top_k),
        load_chunks=_load_chunks,
        judge=_judge_rag,
        max_iterations=3,
        top_k=8,
    )
    ctx = ToolContext(rag_runner=rag_runner, citations=[], stats_holder={}, clarify_holder={})
    tools = build_enabled_tools(ctx)
    model = create_chat_model(settings)
    return LangChainAgentRunner(model=model, tools=tools)


def answer_stream(query: str, history: list[dict] | None = None):
    try:
        runner = build_agent_runner()
        yield from runner.stream(query, history or [])
    except Exception as exc:
        yield error_event(str(exc))
```

- [ ] **Step 4: Run integration tests**

Run:

```powershell
python -m pytest engine/tests/test_answer_stream_agent.py -v
```

Expected: PASS.

- [ ] **Step 5: Run engine tests touched so far**

Run:

```powershell
python -m pytest engine/tests/test_agent_events.py engine/tests/test_agentic_rag.py engine/tests/test_agent_tools.py engine/tests/test_agent_runner.py engine/tests/test_answer_stream_agent.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add engine/app/chat/answer.py engine/tests/test_answer_stream_agent.py
git commit -m "feat: route chat answers through agent runner"
```

---

### Task 6: Frontend Tool Events And Clarification UI

**Files:**
- Modify: `frontend/src/app/chatStore.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Inspect current chat store before editing**

Run:

```powershell
Get-Content -Raw 'frontend/src/app/chatStore.ts'
```

Expected: shows the current `Message` type and store actions. Preserve existing fields and actions.

- [ ] **Step 2: Add message metadata fields and store actions**

Modify `frontend/src/app/chatStore.ts` so the exported types include:

```ts
export type ToolRunStatus = 'running' | 'success' | 'error'

export interface ToolRun {
  id: string
  tool: string
  query: string
  status: ToolRunStatus
  summary?: string
  stats?: Record<string, unknown>
  latencyMs?: number
}

export interface ClarifyOption {
  label: string
  value: string
}

export interface ClarifyRequest {
  question: string
  options: ClarifyOption[]
}
```

Extend `Message` with:

```ts
toolRuns?: ToolRun[]
clarify?: ClarifyRequest
agentStatus?: string
```

Add actions to the store implementation:

```ts
setLastAgentStatus: (label: string) =>
  set((state) => ({
    messages: state.messages.map((message, index) =>
      index === state.messages.length - 1 ? { ...message, agentStatus: label } : message,
    ),
  })),

addLastToolRun: (run: ToolRun) =>
  set((state) => ({
    messages: state.messages.map((message, index) =>
      index === state.messages.length - 1
        ? { ...message, toolRuns: [...(message.toolRuns ?? []), run] }
        : message,
    ),
  })),

finishLastToolRun: (tool: string, data: Partial<ToolRun>) =>
  set((state) => ({
    messages: state.messages.map((message, index) => {
      if (index !== state.messages.length - 1) return message
      const runs = message.toolRuns ?? []
      const lastIndex = [...runs].reverse().findIndex((run) => run.tool === tool && run.status === 'running')
      if (lastIndex < 0) return message
      const actualIndex = runs.length - 1 - lastIndex
      return {
        ...message,
        toolRuns: runs.map((run, runIndex) =>
          runIndex === actualIndex ? { ...run, ...data, status: data.status ?? 'success' } : run,
        ),
      }
    }),
  })),

setLastClarify: (clarify: ClarifyRequest) =>
  set((state) => ({
    messages: state.messages.map((message, index) =>
      index === state.messages.length - 1 ? { ...message, clarify } : message,
    ),
  })),
```

Make sure the store type includes these action signatures.

- [ ] **Step 3: Update `ChatPage.tsx` parser**

In `frontend/src/pages/ChatPage.tsx`, import the new types/actions from the store. Add store selectors:

```ts
const setLastAgentStatus = useChatStore((s) => s.setLastAgentStatus)
const addLastToolRun = useChatStore((s) => s.addLastToolRun)
const finishLastToolRun = useChatStore((s) => s.finishLastToolRun)
const setLastClarify = useChatStore((s) => s.setLastClarify)
```

Extend `handleStreamLine`:

```ts
if (msg.type === 'agent_status') {
  setLastAgentStatus(msg.data?.label ?? '')
} else if (msg.type === 'tool_call') {
  addLastToolRun({
    id: crypto.randomUUID(),
    tool: msg.data?.tool ?? 'tool',
    query: msg.data?.query ?? '',
    status: 'running',
  })
} else if (msg.type === 'tool_result') {
  finishLastToolRun(msg.data?.tool ?? 'tool', {
    status: msg.data?.status === 'error' ? 'error' : 'success',
    summary: msg.data?.summary ?? '',
    stats: msg.data?.stats,
    latencyMs: msg.data?.latency_ms,
  })
} else if (msg.type === 'clarify') {
  setLastClarify({
    question: msg.data?.question ?? '我需要你补充一点信息。',
    options: msg.data?.options ?? [],
  })
}
```

Keep existing `sources`, `token`, `done`, and `error` handling unchanged.

- [ ] **Step 4: Render tool process and clarification card**

In `MessageBlock`, render a `ToolProcess` component above assistant markdown:

```tsx
{!isUser && msg.toolRuns && msg.toolRuns.length > 0 && <ToolProcess runs={msg.toolRuns} />}
```

Render clarification below assistant content:

```tsx
{!isUser && msg.clarify && (
  <ClarifyCard clarify={msg.clarify} onSelect={(option) => onClarifySelect(option.label)} />
)}
```

Thread `onClarifySelect` from `ChatPage` to `MessageBlock`:

```tsx
onClarifySelect={(value) => send(value)}
```

Add components at the bottom of `ChatPage.tsx`:

```tsx
function ToolProcess({ runs }: { runs: ToolRun[] }) {
  return (
    <div className="mb-3 flex flex-wrap gap-2 text-xs">
      {runs.map((run) => (
        <span
          key={run.id}
          className={cn(
            'inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium',
            run.status === 'running' && 'border-blue-100 bg-blue-50 text-blue-700',
            run.status === 'success' && 'border-emerald-100 bg-emerald-50 text-emerald-700',
            run.status === 'error' && 'border-red-100 bg-red-50 text-red-700',
          )}
          title={run.summary || run.query}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          <span className="truncate">{toolLabel(run.tool)}</span>
          {run.status === 'running' && <span>运行中</span>}
          {run.summary && <span className="truncate text-slate-500">{run.summary}</span>}
        </span>
      ))}
    </div>
  )
}

function ClarifyCard({
  clarify,
  onSelect,
}: {
  clarify: ClarifyRequest
  onSelect: (option: ClarifyOption) => void
}) {
  return (
    <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-left">
      <p className="text-sm font-semibold text-slate-800">{clarify.question}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {clarify.options.slice(0, 3).map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onSelect(option)}
            className="rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-amber-300 hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function toolLabel(tool: string) {
  if (tool === 'knowledge_search') return '知识库检索'
  if (tool === 'clarify_user') return '追问'
  if (tool === 'datetime') return '时间'
  if (tool === 'web_search') return '联网搜索'
  return tool
}
```

- [ ] **Step 5: Run frontend build**

Run:

```powershell
pnpm.cmd build
```

Workdir: `frontend`

Expected: PASS. If TypeScript reports missing imports or store signature mismatches, fix the exact type names in `chatStore.ts` and `ChatPage.tsx`, then rerun.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/app/chatStore.ts frontend/src/pages/ChatPage.tsx
git commit -m "feat: render agent tool events in chat"
```

---

### Task 7: Final Verification And Visual Check

**Files:**
- No planned source edits unless verification finds a bug.

- [ ] **Step 1: Run backend and engine regression tests**

Run from repo root:

```powershell
python -m pytest backend engine
```

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
pnpm.cmd build
```

Workdir: `frontend`

Expected: PASS.

- [ ] **Step 3: Start local frontend if it is not already running**

Run:

```powershell
pnpm.cmd dev -- --host 127.0.0.1
```

Workdir: `frontend`

Expected: Vite prints a local URL. Keep the process running for visual verification.

- [ ] **Step 4: Visual verification checklist**

Open the Vite URL in the in-app browser and verify:

- Desktop chat layout still has the conversation list on the left and chat on the right.
- Mobile width does not overlap message bubbles, input, or sidebar controls.
- A mocked or real tool event response shows tool chips above the assistant answer.
- A `clarify` event shows a clarification card with 2-3 clickable options.
- Clicking a clarification option sends a follow-up message.
- Existing source disclosure still opens and displays source rows.

- [ ] **Step 5: Commit verification fixes only if needed**

If visual or regression fixes were required:

```powershell
git add <fixed-files>
git commit -m "fix: polish agent chat verification issues"
```

If no fixes were required, do not create an empty commit.

---

## Execution Notes

- Execute tasks sequentially. The runner depends on events, RAG, and tools being in place.
- Preserve unrelated workspace changes. Check `git status --short` before each task.
- Do not add the ReAct prompt fallback in this plan.
- Do not enable real web search in this plan.
- Do not expose raw chain-of-thought in backend events or frontend UI.
