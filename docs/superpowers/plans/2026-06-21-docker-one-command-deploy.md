# Docker One Command Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a production Docker Compose stack that starts Prism frontend, backend, engine, and infrastructure with one command while preserving the current local development workflow.

**Architecture:** Keep `docker-compose.yml` as the development infrastructure stack. Add `docker-compose.prod.yml` for full deployment, with backend and engine as separate Python containers and frontend as a static Nginx container that proxies API traffic to the right internal services.

**Tech Stack:** Docker Compose, Python 3.11 slim, Node 20 Alpine, Nginx Alpine, FastAPI/Uvicorn, Vite.

---

### Task 1: Add Runtime Dockerfiles

**Files:**
- Create: `docker/backend.Dockerfile`
- Create: `docker/engine.Dockerfile`
- Create: `docker/frontend.Dockerfile`

- [ ] Build Python backend and engine images from the repo root using `requirements.txt`.
- [ ] Build the frontend with `pnpm build` and serve `frontend/dist` through Nginx.

### Task 2: Add Nginx Production Routing

**Files:**
- Create: `docker/nginx/default.conf`

- [ ] Serve the SPA from `/usr/share/nginx/html`.
- [ ] Route `/api/v1/chat/answer`, `/api/v1/ingest`, and `/api/v1/wiki` to `engine:5180`.
- [ ] Route all remaining `/api` traffic to `backend:5175`.

### Task 3: Add Production Compose Stack

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `.env.prod.example`

- [ ] Include all infrastructure services from `docker-compose.yml`.
- [ ] Add `backend`, `engine`, and `frontend` services.
- [ ] Set `SKIP_ENGINE=1` in backend so engine runs only as its own container.
- [ ] Use Docker service names for internal URLs.
- [ ] Expose only frontend on host port `8080` for the app entrypoint.

### Task 4: Make Backend Engine URL Configurable

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/upload.py`
- Modify: `backend/app/api/knowledge.py`
- Modify: `backend/app/api/wiki.py`

- [ ] Add `ENGINE_BASE_URL`, defaulting to `http://127.0.0.1:${ENGINE_PORT}` for local development.
- [ ] Replace hardcoded `http://127.0.0.1:{settings.ENGINE_PORT}` calls with `settings.ENGINE_BASE_URL`.

### Task 5: Verify

**Commands:**
- `docker compose -f docker-compose.prod.yml config`
- `python -m py_compile backend/app/config.py backend/app/api/upload.py backend/app/api/knowledge.py backend/app/api/wiki.py`

- [ ] Confirm Compose renders successfully.
- [ ] Confirm changed Python files compile.
