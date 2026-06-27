# Deep Knowledge Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scope-first governed-knowledge deep search tool that is only visible when the chat request enables deep search, with quantitative benchmark scaffolding.

**Architecture:** Add an in-process A2A-shaped deep search package under `engine/app/agent/deep_search`. The orchestrator loops over scope discovery, evidence collection, judge evaluation, and follow-up directives; a LangChain `deep_knowledge_search` tool wraps the orchestrator and reuses governed CKP/PKU/source helpers from existing tools. Chat request state controls tool registration and a prompt suffix asks the main agent to prefer deep search when enabled.

**Tech Stack:** Python, SQLAlchemy ORM, Pydantic, LangChain `StructuredTool`, existing Prism governance tables, React/TypeScript chat UI, pytest, frontend TypeScript build.

---

### Task 1: A2A Models And Evidence Pool

**Files:**
- Create: `engine/app/agent/deep_search/__init__.py`
- Create: `engine/app/agent/deep_search/a2a.py`
- Create: `engine/app/agent/deep_search/schemas.py`
- Create: `engine/app/agent/deep_search/evidence_pool.py`
- Test: `engine/tests/test_deep_search_core.py`

- [ ] Write failing tests for A2A serialization and EvidencePool dedupe/scoring.
- [ ] Run `cd engine && pytest tests/test_deep_search_core.py -v` and verify failure.
- [ ] Implement core schemas and scoring.
- [ ] Re-run the test and verify pass.

### Task 2: Scope-First Executors

**Files:**
- Create: `engine/app/agent/deep_search/executors.py`
- Test: `engine/tests/test_deep_search_executors.py`

- [ ] Write failing tests for scope finding, source backtracking, PKU graph expansion, and scoped PKU re-query.
- [ ] Implement deterministic SQLAlchemy executors using CKP, PKU, PKUCanonicalLink, PKURelation, CanonicalRelation, and document chunks.
- [ ] Run `cd engine && pytest tests/test_deep_search_executors.py -v`.

### Task 3: Searcher, Judge, Orchestrator, And Tool

**Files:**
- Create: `engine/app/agent/deep_search/searcher.py`
- Create: `engine/app/agent/deep_search/judge.py`
- Create: `engine/app/agent/deep_search/orchestrator.py`
- Create: `engine/app/agent/tools/deep_knowledge_search.py`
- Modify: `engine/app/agent/tools/__init__.py`
- Test: `engine/tests/test_deep_knowledge_search_tool.py`

- [ ] Write failing tests for default-disabled registration and enabled tool JSON output.
- [ ] Implement Searcher directive routing, deterministic Judge gates, orchestrator loop, and tool wrapper.
- [ ] Run `cd engine && pytest tests/test_deep_knowledge_search_tool.py -v`.

### Task 4: Chat Toggle Backend Wiring

**Files:**
- Modify: `engine/app/api/chat.py`
- Modify: `engine/app/chat/answer.py`
- Test: `engine/tests/test_answer_stream_agent.py`

- [ ] Write/extend tests for `deep_search_enabled` and `deep_search_depth` request forwarding.
- [ ] Enable `deep_knowledge_search` only when the request toggle is true.
- [ ] Append a prompt suffix asking the main agent to prefer deep search when enabled.
- [ ] Run `cd engine && pytest tests/test_answer_stream_agent.py tests/test_agent_tools.py -v`.

### Task 5: Frontend Deep Search Toggle

**Files:**
- Modify: `frontend/src/app/chatStore.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] Add chat store state for deep search enabled/depth.
- [ ] Add a compact toggle under the chat input.
- [ ] Include `deep_search_enabled` and `deep_search_depth` in chat requests.
- [ ] Run `cd frontend && pnpm build`.

### Task 6: Benchmark Runner And Docs

**Files:**
- Create: `engine/eval/run_deep_knowledge_search_eval.py`
- Create: `evaluation/datasets/deep_knowledge_search_v1.example.json`
- Create: `docs/deep_knowledge_search_interview_design.md`
- Create: `docs/deep_knowledge_search_benchmark_design.md`

- [ ] Implement a benchmark runner reporting CKP/PKU/source recall@K, judged completeness accuracy, average iterations, p95 latency, and fallback rate.
- [ ] Add an example dataset and interview-ready design docs.
- [ ] Run `python engine/eval/run_deep_knowledge_search_eval.py --help`.

### Task 7: Final Verification

- [ ] Run targeted backend tests.
- [ ] Run frontend build.
- [ ] Check `git status --short`.
