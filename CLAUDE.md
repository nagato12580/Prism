# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Prism (棱镜)** is a personal knowledge management and RAG chat application. Users ingest documents/URLs into a personal knowledge base, then chat with an LLM agent that searches that knowledge base to answer questions.

## Commands

### Backend

```bash
# Start backend (auto-spawns engine as subprocess)
python -m backend.run

# Start engine separately (useful for development)
SKIP_ENGINE=1 python -m backend.run   # backend only
python -m engine.run                  # engine only

# Run tests
cd backend && pytest
cd engine && pytest
```

### Frontend

```bash
cd frontend
pnpm dev          # dev server at localhost:5173
pnpm build        # tsc -b && vite build
pnpm preview      # preview production build
```

### Infrastructure

```bash
docker-compose up -d   # Start MySQL, Redis, etcd, MinIO, Milvus
```

## Architecture

Three processes share one MySQL database:

```
Browser (React SPA :5173)
    |
    ├── /api/v1/chat/answer ──→ Engine (FastAPI :5180)
    ├── /api/v1/ingest ────────→ Engine (FastAPI :5180)
    └── /api/v1/* ─────────────→ Backend (FastAPI :5175)
```

**Backend (:5175)** handles CRUD, file parsing, session persistence, and triggers ingestion by POSTing to Engine after saving uploads.

**Engine (:5180)** is the AI/RAG core: runs the ingestion pipeline and streams NDJSON chat events.

**Frontend** proxies are configured in `frontend/vite.config.ts`.

## Key Data Flows

### Ingestion
1. User uploads file/URL → `backend/app/api/upload.py`
2. Backend saves `KnowledgeItem` to MySQL, fires background HTTP POST to Engine `/api/v1/ingest`
3. Engine `engine/app/ingestion/pipeline.py`: chunks (500 chars/100 overlap) → embeds via Jina API → stores `KnowledgeChunk` to MySQL + vectors to Milvus

### Chat Streaming
1. Frontend POSTs to `/api/v1/chat/answer` (proxied to Engine)
2. `engine/app/agent/runner.py` (`LangChainAgentRunner`) runs the agent loop with DeepSeek LLM
3. If `knowledge_search` tool is called: `engine/app/agent/rag/agentic.py` runs up to 3 iterations of hybrid search (60% vector via Milvus + 40% BM25 via MySQL LIKE, fused with RRF)
4. If `clarify_user` tool is called: emits a `clarify` event; frontend shows option buttons
5. NDJSON events streamed: `agent_status`, `tool_call`, `tool_result`, `sources`, `token`, `done`
6. Frontend (`frontend/src/pages/ChatPage.tsx`) parses stream, updates Zustand store, renders UI

## Module Map

### Backend (`backend/app/`)
- `main.py` — FastAPI app factory, engine subprocess management, auto-migrate on startup
- `config.py` — Settings from root `.env`
- `api/upload.py` — File/URL parsing and ingestion trigger
- `api/chat.py` — Chat session and message persistence
- `utils/file_parser.py` — PDF/DOCX/XLSX/PPTX/MD/TXT text extraction
- `utils/auto_migrate.py` — `CREATE TABLE IF NOT EXISTS` schema sync

### Engine (`engine/app/`)
- `agent/runner.py` — Core LangChain agent loop and NDJSON event emission
- `agent/rag/agentic.py` — Multi-iteration RAG search+judge loop
- `agent/tools/` — `knowledge_search`, `clarify_user`, `datetime`, `web_search` (stub, disabled)
- `agent/events.py` — NDJSON event factory functions
- `agent/prompts.py` — System prompt and RAG judge prompt
- `retrieval/hybrid.py` — RRF fusion of vector and BM25 results
- `retrieval/vector_search.py` — Milvus semantic search
- `retrieval/bm25_search.py` — jieba + SQL LIKE keyword search
- `ingestion/pipeline.py` — End-to-end ingestion orchestration
- `milvus_client.py` — Milvus connection and collection management (`prism_knowledge`)
- `llm/client.py` — OpenAI-compat client for DeepSeek streaming/non-streaming
- `observability.py` — Structured logging helpers

### Frontend (`frontend/src/`)
- `app/chatStore.ts` — Zustand store: messages, streaming state, tool runs, clarify requests, sources
- `pages/ChatPage.tsx` — Chat UI with NDJSON stream parsing
- `pages/KnowledgePage.tsx` — Knowledge base CRUD UI
- `app/api.ts` — All REST calls to backend
- `app/routes.tsx` — React Router: `/` or `/chat` → ChatPage, `/knowledge` → KnowledgePage

## Configuration

All service configuration lives in the root `.env` file (DB, Redis, Milvus, LLM/embedding API keys). Both backend and engine share the same settings via their respective `app/config.py` (both read from root `.env`).

LLM: DeepSeek (OpenAI-compatible API)
Embeddings: Jina AI (OpenAI-compatible API)
Vector DB: Milvus 2.4 (collection: `prism_knowledge`)
