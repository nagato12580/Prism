# Prism Phase 2 LangChain Agentic RAG Design

## Summary

Phase 2 upgrades Prism chat from basic RAG to a LangChain-based function-calling agent. The first implementation path will mirror Comet's strong-model path: use `ChatOpenAI.bind_tools()` to let the model call registered tools, stream tool progress to the frontend, and keep Prism's existing `/chat/answer` NDJSON contract compatible.

The knowledge-base tool will be stronger than Comet's current single-pass retrieval. It will delegate to an Agentic RAG sub-loop that retrieves, judges evidence sufficiency, rewrites the query when needed, and either returns evidence or asks the outer agent to clarify with the user.

## Goals

- Add a LangChain function-calling agent runner for chat answers.
- Keep the current FastAPI endpoint and NDJSON streaming shape usable by the existing frontend.
- Add a lightweight tool registry inspired by Comet.
- Implement `knowledge_search` as an Agentic RAG sub-agent.
- Support user interruption through a `clarify` event with 2-3 suggested options.
- Avoid exposing raw model chain-of-thought; show status summaries and tool events only.

## Non-Goals

- Do not implement Comet's weak-model ReAct prompt fallback in the first Phase 2 slice.
- Do not add the full Comet tool ecosystem, MCP integration, memory graph, or tool settings UI.
- Do not replace the current chat endpoint with SSE. Prism will continue using NDJSON for this phase.
- Do not change ingestion, embedding, or database schema unless implementation discovers a direct blocker.

## Architecture

```text
POST /chat/answer
  -> answer_stream(query, history)
     -> LangChainAgentRunner
        -> ChatOpenAI.bind_tools(enabled_tools)
        -> ToolRegistry
           -> knowledge_search
              -> AgenticRagRunner
                 -> hybrid_search
                 -> load chunks
                 -> judge sufficiency
                 -> rewrite query if needed
                 -> return sufficient / insufficient
           -> clarify_user
           -> datetime
           -> web_search disabled stub
        -> NDJSON events
```

`engine/app/chat/answer.py` remains the entry point, but its internals should move toward orchestration rather than owning all retrieval and prompting. New code should be split into focused modules so each unit is independently testable.

Recommended module layout:

```text
engine/app/agent/
  __init__.py
  runner.py              # LangChain function-calling loop
  events.py              # event helpers and schemas
  prompts.py             # agent-facing system prompt text
  tools/
    __init__.py
    base.py              # ToolSpec, ToolContext, registry
    knowledge.py         # knowledge_search tool builder
    clarify.py           # clarify_user tool
    datetime.py          # datetime tool
    web_search.py        # disabled stub first
  rag/
    __init__.py
    agentic.py           # AgenticRagRunner
    judge.py             # sufficiency/rewrite LLM calls
```

## LangChain Model Client

Use the existing OpenAI-compatible environment settings:

```python
ChatOpenAI(
    model=settings.LLM_MODEL,
    base_url=settings.LLM_API_BASE,
    api_key=settings.LLM_API_KEY,
)
```

The first implementation assumes the configured model supports tool/function calling. If a model or provider rejects tool calls, the runner should emit a clear `error` event instead of silently falling back to basic RAG. Prompt ReAct fallback can be a later phase.

Dependencies to add:

```text
langchain
langchain-openai
langchain-core
```

Pin versions conservatively in `requirements.txt` and verify compatibility with the installed OpenAI client.

## Tool Registry

Follow Comet's shape, but keep it smaller:

- `ToolSpec`: stable tool key, display name, description, default enabled flag, builder.
- `ToolContext`: access to settings, citation collection, stats holder, and retrieval helpers.
- `build_enabled_tools()`: returns LangChain `StructuredTool` instances.

Initial tools:

- `knowledge_search`: enabled. Delegates to Agentic RAG and returns structured evidence or insufficiency.
- `clarify_user`: enabled. Produces a `clarify` event and ends the current stream as an interruption.
- `datetime`: enabled. Gives the agent current date/time when needed.
- `web_search`: registered as a disabled stub. It should not pretend to search the web before a real provider is configured.

## Agentic RAG

`knowledge_search` should not do one-shot retrieval. It should run a bounded loop:

```text
initial query
  -> hybrid_search(top_k=8)
  -> load chunk text
  -> judge whether evidence is sufficient
  -> if sufficient: return evidence and sources
  -> if insufficient and iterations remain: rewrite query and search again
  -> if still insufficient: return missing info and clarification suggestions
```

Suggested defaults:

- `max_iterations`: 3
- `top_k`: 8
- Deduplicate sources by `chunk_id`.
- Preserve source objects compatible with existing `sources` frontend handling.

Sufficiency judgment should be an LLM call that returns structured JSON. The prompt must require one of:

```json
{
  "status": "sufficient",
  "answer_basis": "short evidence summary",
  "useful_chunk_ids": ["..."]
}
```

or:

```json
{
  "status": "insufficient",
  "missing": ["specific missing point"],
  "rewrite_query": "better search query",
  "clarify": {
    "question": "short user-facing question",
    "options": [
      {"label": "option A", "value": "option:a"},
      {"label": "option B", "value": "option:b"}
    ]
  }
}
```

If the model returns invalid JSON, the implementation should repair once if practical or fall back to a conservative insufficient result.

## Streaming Events

Keep the existing NDJSON format, adding event types rather than replacing the transport.

Existing events:

```json
{"type": "sources", "data": []}
{"type": "token", "data": "..."}
{"type": "done"}
{"type": "error", "data": "..."}
```

New events:

```json
{"type": "agent_status", "data": {"label": "analyzing question"}}
{"type": "tool_call", "data": {"tool": "knowledge_search", "query": "..."}}
{"type": "tool_result", "data": {"tool": "knowledge_search", "status": "success", "summary": "...", "stats": {"hit_count": 8, "doc_count": 3}}}
{"type": "clarify", "data": {"question": "...", "options": [{"label": "...", "value": "..."}]}}
```

Rules:

- Emit `tool_call` before a tool runs.
- Emit `tool_result` after tool completion, including latency and stats where available.
- Emit `sources` when knowledge evidence is available.
- Emit `clarify` when the agent needs user input. After `clarify`, emit `done` and do not fabricate a final answer.
- Do not stream raw hidden reasoning or prompt-internal thoughts.

## Frontend Behavior

The frontend should extend its current NDJSON parser to support:

- Tool process chips for `tool_call` and `tool_result`.
- A clarification card when `clarify` arrives.
- Clickable suggested options that submit a follow-up user message.
- Existing `sources`, `token`, `done`, and `error` behavior should continue working.

No major layout redesign is required for this phase. The existing Phase 1 chat layout should be preserved.

## Error Handling

- Tool call failure should produce a `tool_result` with `status: "error"` and then allow the agent to decide whether to continue or fail.
- Provider/model tool-call incompatibility should produce a clear `error` event.
- RAG sub-agent JSON parsing failure should become an insufficient result with a clarification prompt, not a crash.
- Retrieval/database errors should be reported through `error` events and covered by tests.

## Testing

Required backend tests:

- Tool registry builds expected tools.
- Agentic RAG returns sufficient when retrieval evidence is clearly enough.
- Agentic RAG rewrites and retries when evidence is initially insufficient.
- Agentic RAG returns clarification when evidence remains insufficient.
- `answer_stream` emits valid NDJSON for token, tool, sources, clarify, done, and error paths.

Required frontend tests or manual verification:

- Existing basic token streaming still renders.
- Tool process chips render and complete.
- Clarification options appear and can be clicked as follow-up prompts.
- Source display still works.

Required verification commands after implementation:

```powershell
pnpm.cmd build
python -m pytest backend engine
```

Run frontend build in `frontend/`. Run pytest from the repository root.

## Open Decisions For Later

- Whether to add Comet-style ReAct prompt fallback for models without tool calling.
- Which real web search provider to use.
- Whether tool enable/disable controls belong in settings.
- Whether multi-session conversation persistence should move from frontend-only state to backend storage.
