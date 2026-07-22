# Knowledge React Product and Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the deep-link React knowledge product, close the Chat-to-Evidence loop, migrate legacy Prism knowledge data to stable scoped generations, and cut over with a verified rollback path.

**Architecture:** The browser talks only to Backend public APIs through focused feature modules. React Router owns knowledge-base and tab selection, Zustand owns transient workspace state, Job progress uses snapshot plus resumable SSE, and Chat NDJSON reuses the same Evidence components as retrieval. Cutover backfills MySQL facts, builds Milvus/Elasticsearch/Neo4j generations beside legacy indexes, validates them, then changes one read flag without long-term dual writes.

**Tech Stack:** React 18, TypeScript 5.7, React Router 7, Zustand 5, Vite 6, Tailwind CSS 4, Lucide React, Vitest, Testing Library, Playwright, Python 3.11, FastAPI, Alembic, MySQL 8, Redis 7, Milvus 2.4, Elasticsearch 8.17, Neo4j 5.28

---

## Prerequisites

Complete and verify Plans 1–5. This plan consumes their `kb_uid`, `file_uid`, `chunk_uid`, `job_id`, `active_index_generation`, `active_graph_generation`, `Evidence`, Job SSE, graph governance, evaluation, enrichment, and Chat event contracts. Do not duplicate retrieval, authorization, projection, or Job state logic in React or migration scripts.

Before implementation:

```powershell
git status --short
git log -1 --oneline
docker compose up -d mysql redis etcd minio milvus elasticsearch neo4j
docker compose ps
```

Expected: no unrelated worktree changes; all listed infrastructure containers are running and healthy. Start applications with the repository's documented Mode B in separate terminals: `python -m engine.run`, `$env:SKIP_ENGINE='1'; python -m backend.run`, and `pnpm.cmd --dir frontend dev -- --host 127.0.0.1 --port 5173`. Preserve existing user changes and use `superpowers:using-git-worktrees` when isolation is required.

## File Structure

- Modify: `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/vite.config.ts` — component-test and E2E tooling.
- Create: `frontend/src/features/knowledge/api/client.ts`, `contracts.ts`, `knowledgeBases.ts`, `files.ts`, `jobs.ts`, `retrieval.ts`, `graph.ts`, `enrichment.ts`, `evaluation.ts` — public Backend contracts grouped by domain.
- Create: `frontend/src/features/knowledge/stores/knowledgeWorkspaceStore.ts`, `jobStore.ts` — URL-adjacent workspace state and live Job snapshots.
- Create: `frontend/src/features/knowledge/pages/KnowledgeIndexPage.tsx`, `KnowledgeWorkspacePage.tsx`, `KnowledgeFilesPage.tsx`, `KnowledgeRetrievalPage.tsx`, `KnowledgeGraphPage.tsx`, `KnowledgeGovernancePage.tsx`, `KnowledgeMindmapPage.tsx`, `KnowledgeEvaluationPage.tsx`, `KnowledgeSettingsPage.tsx`.
- Create: `frontend/src/features/knowledge/components/KnowledgeShell.tsx`, `FileUploadPanel.tsx`, `FileTable.tsx`, `DocumentDrawer.tsx`, `JobProgress.tsx`, `RetrievalResultList.tsx`, `RetrievalHealth.tsx`, `MindmapView.tsx`.
- Create: `frontend/src/features/graph/GraphCanvas.tsx`, `GraphControls.tsx`, `GraphInspector.tsx`, `GovernanceWorkbench.tsx` — extracted reusable graph product surfaces.
- Create: `frontend/src/features/chat/RetrievalScopePicker.tsx`, `ToolRunTimeline.tsx`, `EvidenceList.tsx`, `CitationCard.tsx`, `EvidenceDrawer.tsx` — one citation/evidence UI.
- Modify: `frontend/src/app/routes.tsx`, `frontend/src/app/chatStore.ts`, `frontend/src/pages/ChatPage.tsx`, `frontend/src/pages/KnowledgePage.tsx`, `frontend/src/pages/KnowledgeGraphPage.tsx`, `frontend/src/app/api.ts` — route to features, adapt existing pages, and remove migrated knowledge contracts.
- Create: `frontend/src/components/ui/Button.tsx`, `Input.tsx`, `Badge.tsx`, `Card.tsx`, `Dialog.tsx`, `Progress.tsx`, `Toast.tsx`, `Tabs.tsx`, `EmptyState.tsx` — shared primitives using existing Prism tokens.
- Create: `frontend/src/test/setup.ts`, `frontend/src/test/server.ts`, `frontend/src/test/knowledgeHandlers.ts`, and focused `*.test.ts(x)` files beside feature modules.
- Create: `scripts/knowledge_backfill.py`, `scripts/knowledge_cutover.py`, `scripts/knowledge_rollback.py`, `scripts/verify_knowledge_system.py` — idempotent migration, flag switch, rollback, and release verification.
- Create: `backend/tests/integration/test_knowledge_backfill.py`, `backend/tests/integration/test_knowledge_cutover.py` — real MySQL migration/cutover tests.
- Create: `frontend/playwright.config.ts`, `frontend/e2e/knowledge-product.spec.ts`, `frontend/e2e/knowledge-failure-modes.spec.ts`, `frontend/e2e/chat-citations.spec.ts` — browser acceptance tests.
- Modify: `.env.prod.example`, `README.md` — bootstrap read mode and release/cutover operations.

## Task 1: Establish Typed Frontend API Boundaries

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/server.ts`
- Create: `frontend/src/test/knowledgeHandlers.ts`
- Create: `frontend/src/features/knowledge/api/client.ts`
- Create: `frontend/src/features/knowledge/api/contracts.ts`
- Create: `frontend/src/features/knowledge/api/knowledgeBases.ts`
- Create: `frontend/src/features/knowledge/api/files.ts`
- Create: `frontend/src/features/knowledge/api/jobs.ts`
- Create: `frontend/src/features/knowledge/api/retrieval.ts`
- Create: `frontend/src/features/knowledge/api/graph.ts`
- Create: `frontend/src/features/knowledge/api/enrichment.ts`
- Create: `frontend/src/features/knowledge/api/evaluation.ts`
- Create: `frontend/src/features/knowledge/api/contracts.test.ts`
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: Add the test dependencies and scripts**

Run:

```powershell
pnpm --dir frontend add -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test msw
```

Add scripts:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test"
  }
}
```

Configure `vite.config.ts` with `environment: 'jsdom'`, `setupFiles: ['./src/test/setup.ts']`, and `restoreMocks: true`. Add the shared MSW server and lifecycle:

```ts
// frontend/src/test/server.ts
import { setupServer } from 'msw/node'

export const server = setupServer()

// frontend/src/test/setup.ts
import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

`knowledgeHandlers.ts` exports the focused-test harnesses referenced below: `makeMemoryRouter`, `tabLabel`, `locationPath`, `folderFile`, `trackedUpload`, `previewResponse`, `createJobStoreForTest`, `job`, `event`, `openedEventUrls`, `snapshotCalls`, `emitSseError`, `retrievalResponse`, `denseWarning`, `renderRetrieval`, `renderRetrievalWithEvidence`, `fullEvidence`, `savedItem`, `renderGovernance`, `lastRequest`, `renderEvaluation`, `run`, `kb`, `renderChatWithEvents`, `sourcesEvent`, `evidence`, `tokenEvent`, `doneEvent`, and `previewRequest`. Implement network handlers with `http`/`HttpResponse` from MSW, render helpers with `MemoryRouter`, timer helpers with `vi.useFakeTimers()`, and DTO factories with fixed public IDs (`kb-a`, `file-a`, `chunk-a`, `g1`). Factories must omit `storage_uri`, actor, tenant, and secret values.

- [ ] **Step 2: Write the failing contract/error tests**

```ts
import { describe, expect, it, vi } from 'vitest'
import { ApiProblem, request } from './client'
import { parseEvidence } from './contracts'

describe('knowledge API contracts', () => {
  it('preserves typed error state and trace id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'RETRIEVAL_UNAVAILABLE', message: 'down', retryable: true, trace_id: 'trace-1' },
    }), { status: 503, headers: { 'Content-Type': 'application/json' } })))
    await expect(request('/knowledge-bases/kb-a/retrieval/query')).rejects.toMatchObject({
      code: 'RETRIEVAL_UNAVAILABLE', retryable: true, traceId: 'trace-1', status: 503,
    } satisfies Partial<ApiProblem>)
  })

  it('accepts only public Evidence fields', () => {
    const evidence = parseEvidence({
      evidence_id: 'K1', kb_uid: 'kb-a', file_uid: 'file-a', chunk_uid: 'chunk-a',
      display_title: 'A', excerpt: 'text', channel_scores: {}, rrf_score: 0.02,
      retrieval_channels: ['dense'], index_generation: 'g1', storage_uri: 'private/path',
    })
    expect(evidence.chunk_uid).toBe('chunk-a')
    expect('storage_uri' in evidence).toBe(false)
  })
})
```

- [ ] **Step 3: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/api/contracts.test.ts`

Expected: FAIL because the feature API modules do not exist.

- [ ] **Step 4: Implement the shared client and exact public contracts**

```ts
export type RetrievalStatus = 'ok' | 'no_hits' | 'degraded' | 'unavailable' | 'invalid_request'
export type StageStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'stale' | 'skipped'

export interface ChannelScore { raw_score: number; raw_rank: number }
export interface Evidence {
  evidence_id?: string
  kb_uid: string
  file_uid: string
  item_id?: string | null
  chunk_uid: string
  parent_chunk_uid?: string | null
  display_title: string
  original_filename?: string | null
  excerpt: string
  page_start?: number | null
  page_end?: number | null
  char_start?: number | null
  char_end?: number | null
  channel_scores: Record<string, ChannelScore>
  rrf_score: number
  rerank_score?: number | null
  rerank_model?: string | null
  retrieval_channels: Array<'dense' | 'bm25' | 'graph'>
  graph_path: string[]
  graph_explanation?: string | null
  evidence_type: 'chunk' | 'graph_path' | 'entity'
  index_generation: string
  degradation_flags: string[]
}
```

Define `KnowledgeBaseSummary`, `KnowledgeFile`, `DocumentPreview`, `KnowledgeJob`, `JobEvent`, `RetrievalResponse`, graph status/subgraph/governance DTOs, `MindmapSnapshot`, evaluation dataset/run DTOs, and settings DTOs with the field names produced by Plans 1–5. `parseEvidence` constructs a new object from allowed keys; it never spreads server data.

`request<T>()` must parse the shared error envelope and throw `ApiProblem(status, code, message, retryable, traceId, details)`. It handles JSON, `204`, and ZIP responses without logging response bodies. Domain modules call only `/api/v1/knowledge-bases...`, `/api/v1/jobs...`, and `/api/v1/chat...` Backend paths.

- [ ] **Step 5: Move knowledge calls out of the monolithic API**

Move current topic/resource calls behind the new modules while legacy pages still import a temporary re-export from `app/api.ts`. Do not move Chat, memory, wiki, or unrelated APIs. Add a source assertion that `features/knowledge/api` contains no Engine base URL and no `storage_uri` field.

- [ ] **Step 6: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/api/contracts.test.ts
pnpm --dir frontend build
git add frontend/package.json frontend/pnpm-lock.yaml frontend/vite.config.ts frontend/src/test frontend/src/features/knowledge/api frontend/src/app/api.ts
git commit -m "refactor(frontend): 拆分知识库 API 契约"
```

Expected: focused tests pass and TypeScript/Vite build succeeds.

## Task 2: Add Deep-Link Routes, Knowledge Shell, and Zustand Workspace State

**Files:**
- Create: `frontend/src/features/knowledge/stores/knowledgeWorkspaceStore.ts`
- Create: `frontend/src/features/knowledge/components/KnowledgeShell.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeIndexPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeWorkspacePage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeGraphPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeGovernancePage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeMindmapPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeEvaluationPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeSettingsPage.tsx`
- Create: `frontend/src/features/knowledge/pages/knowledgeRoutes.test.tsx`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/layouts/MainLayout.tsx`

- [ ] **Step 1: Write failing route restoration tests**

```tsx
it.each(['files', 'retrieval', 'graph', 'governance', 'mindmap', 'evaluation', 'settings'])(
  'restores %s from a deep link', async (tab) => {
    render(<RouterProvider router={makeMemoryRouter(`/knowledge/kb-a/${tab}`)} />)
    expect(await screen.findByTestId(`knowledge-${tab}-page`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: tabLabel(tab) })).toHaveAttribute('aria-current', 'page')
  },
)

it('redirects a selected KB to files without storing the tab globally', async () => {
  render(<RouterProvider router={makeMemoryRouter('/knowledge/kb-a')} />)
  await waitFor(() => expect(locationPath()).toBe('/knowledge/kb-a/files'))
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/pages/knowledgeRoutes.test.tsx`

Expected: FAIL because nested knowledge routes and pages are absent.

- [ ] **Step 3: Implement nested routes**

```tsx
{
  path: 'knowledge',
  children: [
    { index: true, element: <KnowledgeIndexPage /> },
    {
      path: ':kbUid', element: <KnowledgeWorkspacePage />, children: [
        { index: true, element: <Navigate to="files" replace /> },
        { path: 'files', element: <KnowledgeFilesPage /> },
        { path: 'retrieval', element: <KnowledgeRetrievalPage /> },
        { path: 'graph', element: <KnowledgeGraphPage /> },
        { path: 'governance', element: <KnowledgeGovernancePage /> },
        { path: 'mindmap', element: <KnowledgeMindmapPage /> },
        { path: 'evaluation', element: <KnowledgeEvaluationPage /> },
        { path: 'settings', element: <KnowledgeSettingsPage /> },
      ],
    },
  ],
}
```

`KnowledgeShell` reads `kbUid` from params, loads the authorized KB summary, renders tab links relative to the route, and renders `<Outlet />`. A missing/forbidden KB shows the typed error state and never redirects to a different KB.

`KnowledgeIndexPage` renders the authorized, server-paged KB list with file/index/graph/job statistics and explicit empty/error states. Create submits name/description, then navigates with the returned `kb_uid` to `/knowledge/{kbUid}/files`; rename and delete use optimistic `version` and never place numeric legacy Topic IDs in URLs.

- [ ] **Step 4: Add minimal Zustand workspace state**

```ts
interface KnowledgeWorkspaceState {
  selectedFileUids: Record<string, string[]>
  drawerByKb: Record<string, { fileUid: string; view: 'original' | 'markdown' | 'chunks' | 'history' } | null>
  setSelectedFiles(kbUid: string, fileUids: string[]): void
  openDrawer(kbUid: string, fileUid: string, view?: 'original' | 'markdown' | 'chunks' | 'history'): void
  closeDrawer(kbUid: string): void
}
```

Keep `kbUid`, active tab, pagination cursor, filters, and retrieval query in the URL. The store holds only transient selections/drawer state keyed by `kbUid`, so refresh/deep links do not depend on persisted Zustand state.

- [ ] **Step 5: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/pages/knowledgeRoutes.test.tsx
pnpm --dir frontend build
git add frontend/src/features/knowledge/stores/knowledgeWorkspaceStore.ts frontend/src/features/knowledge/components/KnowledgeShell.tsx frontend/src/features/knowledge/pages frontend/src/app/routes.tsx frontend/src/layouts/MainLayout.tsx
git commit -m "feat(frontend): 增加知识库深链工作区"
```

## Task 3: Build the File Workbench and Read-Only Document Drawer

**Files:**
- Create: `frontend/src/components/ui/Button.tsx`
- Create: `frontend/src/components/ui/Input.tsx`
- Create: `frontend/src/components/ui/Badge.tsx`
- Create: `frontend/src/components/ui/Card.tsx`
- Create: `frontend/src/components/ui/Dialog.tsx`
- Create: `frontend/src/components/ui/Progress.tsx`
- Create: `frontend/src/components/ui/Toast.tsx`
- Create: `frontend/src/components/ui/Tabs.tsx`
- Create: `frontend/src/components/ui/EmptyState.tsx`
- Create: `frontend/src/features/knowledge/components/FileUploadPanel.tsx`
- Create: `frontend/src/features/knowledge/components/FileTable.tsx`
- Create: `frontend/src/features/knowledge/components/DocumentDrawer.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx`
- Create: `frontend/src/features/knowledge/components/FileWorkbench.test.tsx`

- [ ] **Step 1: Write failing workbench tests**

```tsx
it('preserves directory-relative paths and bounds concurrent uploads', async () => {
  const files = Array.from({ length: 20 }, (_, index) => folderFile(`dir/${index}.md`, `${index}`))
  render(<FileUploadPanel kbUid="kb-a" upload={trackedUpload(4)} />)
  await userEvent.upload(screen.getByLabelText('选择文件夹'), files)
  await waitFor(() => expect(uploadStats.maxActive).toBeLessThanOrEqual(4))
  expect(uploadStats.relativePaths).toContain('dir/0.md')
})

it('shows a read-only chunk window without private paths', async () => {
  server.use(previewResponse({ file_uid: 'file-a', chunks: [{ chunk_uid: 'chunk-a', text: 'body' }] }))
  render(<DocumentDrawer kbUid="kb-a" fileUid="file-a" initialView="chunks" />)
  expect(await screen.findByText('body')).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'Chunk 内容' })).not.toBeInTheDocument()
  expect(document.body.textContent).not.toContain('uploads_data')
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/components/FileWorkbench.test.tsx`

Expected: FAIL because the workbench components do not exist.

- [ ] **Step 3: Implement upload and server-paged file table**

The table sends `cursor`, `limit`, `relative_path`, stage/status, media type, and sort to Backend and uses the response cursor; it does not fetch all files to filter locally. Selection is `file_uid`-based and resets when `kbUid` changes.

`FileUploadPanel` supports:

```ts
type PendingUpload = {
  localId: string
  file: File
  relativePath: string
  state: 'queued' | 'uploading' | 'registered' | 'failed' | 'canceled'
  fileUid?: string
  jobId?: string
  error?: ApiProblem
}
```

Use a four-worker queue, one file request per file, `webkitRelativePath` as `relative_path`, and `AbortController` per active upload. URL import uses the same registered-file/Job response. Display parser capabilities from `/knowledge-bases/capabilities/parsers`; do not hardcode a broader extension list.

- [ ] **Step 4: Implement bulk commands and drawer**

Bulk parse, index, graph build, retry, cancel, and delete send explicit `file_uids`. Confirmation distinguishes tombstone deletion from cancel. The drawer tabs call public preview endpoints for original preview/download, normalized Markdown, cursor-paged chunks, and Job history. Highlight `page`, `char_start`, `char_end`, or a bounded text window from URL search params. Chunk content has no edit action in phase one.

- [ ] **Step 5: Use shared visual primitives**

Implement only the listed primitives, matching existing Prism CSS variables/Tailwind tokens and Lucide icons. Buttons have visible focus, dialogs restore focus, progress exposes `aria-valuenow`, status does not rely on color alone, and errors display safe `code`, message, retryability, and trace ID.

- [ ] **Step 6: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/components/FileWorkbench.test.tsx
pnpm --dir frontend build
git add frontend/src/components/ui frontend/src/features/knowledge/components/FileUploadPanel.tsx frontend/src/features/knowledge/components/FileTable.tsx frontend/src/features/knowledge/components/DocumentDrawer.tsx frontend/src/features/knowledge/pages/KnowledgeFilesPage.tsx frontend/src/features/knowledge/components/FileWorkbench.test.tsx
git commit -m "feat(frontend): 增加文件工作台与只读预览"
```

## Task 4: Consume Job Snapshot plus Resumable SSE

**Files:**
- Create: `frontend/src/features/knowledge/stores/jobStore.ts`
- Create: `frontend/src/features/knowledge/components/JobProgress.tsx`
- Create: `frontend/src/features/knowledge/stores/jobStore.test.ts`
- Modify: `frontend/src/features/knowledge/components/FileUploadPanel.tsx`
- Modify: `frontend/src/features/knowledge/components/FileTable.tsx`

- [ ] **Step 1: Write failing ordering and reconnect tests**

```ts
it('ignores duplicate/out-of-order events and reconnects from the snapshot sequence', async () => {
  const store = createJobStoreForTest()
  store.applySnapshot(job({ job_id: 'job-a', seq: 8, status: 'running' }))
  store.applyEvent(event({ job_id: 'job-a', seq: 8, progress: 1 }))
  store.applyEvent(event({ job_id: 'job-a', seq: 7, progress: 0 }))
  store.applyEvent(event({ job_id: 'job-a', seq: 9, progress: 2 }))
  expect(store.getState().jobs['job-a'].seq).toBe(9)
  expect(openedEventUrls.at(-1)).toContain('after_seq=8')
})

it('polls with capped backoff only after SSE transport failure', async () => {
  const store = createJobStoreForTest({ timers })
  await store.watch('job-a')
  expect(snapshotCalls).toBe(1)
  emitSseError()
  timers.advanceBy(1000)
  expect(snapshotCalls).toBe(2)
  expect(store.getState().transport).toBe('polling')
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/stores/jobStore.test.ts`

Expected: FAIL because the Job store is missing.

- [ ] **Step 3: Implement the Job store**

`watch(jobId)` first GETs the durable snapshot, stores its latest `seq`, then opens `/api/v1/jobs/{jobId}/events?after_seq={seq}`. Accept only the matching `job_id` and strictly increasing sequence. Terminal `succeeded`, `failed`, and `canceled` events close the stream.

On transport error, close the stream and poll the one Job snapshot after 1s, 2s, 4s, 8s, then 15s capped. A successful SSE reconnect returns transport state to `sse`. Do not refresh the entire file list every three seconds. Unmounting the last subscriber closes EventSource/timer; `cancel(jobId)` calls Backend and waits for the authoritative event/snapshot.

- [ ] **Step 4: Render stage-aware progress**

`JobProgress` displays stage, `progress_current/progress_total`, attempt, cancellation state, structured failure, and retry only when `retryable=true`. Wire upload rows and file status cells to the Job store by `job_id`.

- [ ] **Step 5: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/stores/jobStore.test.ts
pnpm --dir frontend build
git add frontend/src/features/knowledge/stores/jobStore.ts frontend/src/features/knowledge/components/JobProgress.tsx frontend/src/features/knowledge/stores/jobStore.test.ts frontend/src/features/knowledge/components/FileUploadPanel.tsx frontend/src/features/knowledge/components/FileTable.tsx
git commit -m "feat(frontend): 接入可恢复的任务进度流"
```

## Task 5: Build the Retrieval Laboratory

**Files:**
- Create: `frontend/src/features/knowledge/components/RetrievalHealth.tsx`
- Create: `frontend/src/features/knowledge/components/RetrievalResultList.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.tsx`
- Create: `frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.test.tsx`

- [ ] **Step 1: Write failing retrieval-state tests**

```tsx
it.each([
  ['no_hits', '未找到证据'],
  ['degraded', '部分检索通道不可用'],
  ['unavailable', '检索服务不可用'],
] as const)('renders %s distinctly', async (status, label) => {
  server.use(retrievalResponse({ status, evidence: [], warnings: status === 'degraded' ? [denseWarning()] : [] }))
  renderRetrieval('/knowledge/kb-a/retrieval?q=退款&mode=deep')
  await userEvent.click(screen.getByRole('button', { name: '运行检索' }))
  expect(await screen.findByText(label)).toBeInTheDocument()
})

it('labels channel scores by native meaning and saves current Evidence', async () => {
  renderRetrievalWithEvidence(fullEvidence())
  expect(await screen.findByText('Dense 原始分数')).toBeInTheDocument()
  expect(screen.getByText('RRF 分数')).toBeInTheDocument()
  expect(screen.queryByText(/匹配百分比/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '保存为评估样例' }))
  expect(savedItem.evidence[0].chunk_uid).toBe('chunk-a')
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/pages/KnowledgeRetrievalPage.test.tsx`

Expected: FAIL because the retrieval lab is not implemented.

- [ ] **Step 3: Implement URL-backed query and temporary overrides**

The form owns `q`, `mode=standard|deep`, file filters, and bounded overrides for candidate counts, RRF weights/k, rerank top N, Evidence limit, graph hops, and deep iterations. Submit sends overrides only for this request and never PATCHes KB settings. Persist query/mode/filter to search params so back/forward restores the experiment.

- [ ] **Step 4: Render channel details and save evaluation samples**

For each Evidence show display title, excerpt, raw rank/raw score per channel, RRF, rerank score/model, graph path/explanation, generation, and degradation flags. `RetrievalHealth` renders `ok/no_hits/degraded/unavailable/invalid_request` distinctly. Clicking Evidence opens `DocumentDrawer` at the public file/chunk/page/span location. Save sends query, expected/current Evidence identifiers, response snapshot, config, and generation to the selected evaluation dataset.

- [ ] **Step 5: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/pages/KnowledgeRetrievalPage.test.tsx
pnpm --dir frontend build
git add frontend/src/features/knowledge/components/RetrievalHealth.tsx frontend/src/features/knowledge/components/RetrievalResultList.tsx frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.tsx frontend/src/features/knowledge/pages/KnowledgeRetrievalPage.test.tsx
git commit -m "feat(frontend): 增加知识检索实验室"
```

## Task 6: Productize Graph, Governance, Mindmap, Evaluation, and Settings

**Files:**
- Create: `frontend/src/features/graph/GraphCanvas.tsx`
- Create: `frontend/src/features/graph/GraphControls.tsx`
- Create: `frontend/src/features/graph/GraphInspector.tsx`
- Create: `frontend/src/features/graph/GovernanceWorkbench.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeGraphPage.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeGovernancePage.tsx`
- Create: `frontend/src/features/knowledge/components/MindmapView.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeMindmapPage.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeEvaluationPage.tsx`
- Modify: `frontend/src/features/knowledge/pages/KnowledgeSettingsPage.tsx`
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Modify: `frontend/tests/unified-graph-page.test.mjs`
- Modify: `frontend/tests/graph-workbench.test.mjs`
- Create: `frontend/src/features/knowledge/pages/KnowledgeSecondaryPages.test.tsx`

- [ ] **Step 1: Write failing scoped-action tests**

```tsx
it('separates projection replay from LLM re-extraction', async () => {
  renderGovernance('/knowledge/kb-a/governance')
  await userEvent.click(screen.getByRole('button', { name: '重建投影' }))
  expect(lastRequest()).toEqual({ method: 'POST', path: '/knowledge-bases/kb-a/graph/rebuild-projection' })
  await userEvent.click(screen.getByRole('button', { name: '重新抽取' }))
  expect(screen.getByText('将调用模型并产生费用')).toBeInTheDocument()
})

it('keeps evaluation run snapshot visible after KB generation changes', async () => {
  renderEvaluation(run({ index_generation: 'g1', graph_generation: 'gg1' }), kb({ active_index_generation: 'g2' }))
  expect(await screen.findByText('索引快照 g1')).toBeInTheDocument()
  expect(screen.getByText('当前索引 g2')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/knowledge/pages/KnowledgeSecondaryPages.test.tsx`

Expected: FAIL because the scoped routes have no implemented views.

- [ ] **Step 3: Extract and scope graph components**

Move reusable canvas, controls, inspector, and governance workbench from the current graph pages without changing graph layout behavior. Update the existing graph source-contract tests to inspect `features/graph/GraphCanvas.tsx` and `GovernanceWorkbench.tsx` while retaining their layout, label, hit-area, and action assertions. Every request includes route `kbUid`; views expose entity/source toggle, generation/build/projection status, filters, path explanation, Mention evidence span, and inferred/direct labels. Keep `/graph` as a compatibility redirect or all-scope non-knowledge view until Task 9 removes it; it must not silently open a private KB.

- [ ] **Step 4: Implement governance actions**

Show projector lag, failed receipts, dirty entities/communities, PKU/CKP queues, and per-file graph state. “重建投影” replays MySQL facts without model cost. “重新抽取” requires a second confirmation that states model cost and creates a new graph generation. Both surface Job progress through `jobStore`.

- [ ] **Step 5: Implement Mindmap, Evaluation, and Settings**

Mindmap displays active version/generation, stale state, collapsible nodes, file links, and a Generate/Refresh Job. Deterministic deletion updates are reflected without pretending an LLM reran. The same page lists versioned sample questions, shows stale status, starts the dedicated generation Job, opens a question in the retrieval lab, and can save it into an evaluation dataset.

Evaluation supports dataset JSONL import/export, sample/generated-item inspection, run creation/cancel/list/detail, per-item failure, Recall@K/MRR/NDCG, and immutable config/model/index/graph snapshots.

Settings edits parser/chunk/retrieval/graph profiles using optimistic `version`; explain that profile changes create a side generation. Expose export without secrets/vectors/absolute paths and tombstone deletion confirmation. No connector, online Chunk editor, organization/RBAC, or sandbox-mount UI is added.

- [ ] **Step 6: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/knowledge/pages/KnowledgeSecondaryPages.test.tsx
node --test frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs
pnpm --dir frontend build
git add frontend/src/features/graph frontend/src/features/knowledge/pages frontend/src/features/knowledge/components/MindmapView.tsx frontend/src/pages/KnowledgeGraphPage.tsx frontend/tests/unified-graph-page.test.mjs frontend/tests/graph-workbench.test.mjs
git commit -m "feat(frontend): 产品化图谱治理导图与评估页面"
```

## Task 7: Close the Chat Citation-to-Document Loop

**Files:**
- Create: `frontend/src/features/chat/RetrievalScopePicker.tsx`
- Create: `frontend/src/features/chat/ToolRunTimeline.tsx`
- Create: `frontend/src/features/chat/EvidenceList.tsx`
- Create: `frontend/src/features/chat/CitationCard.tsx`
- Create: `frontend/src/features/chat/EvidenceDrawer.tsx`
- Modify: `frontend/src/app/chatStore.ts`
- Modify: `frontend/src/pages/ChatPage.tsx`
- Modify: `frontend/tests/chat-trace-stream.test.mjs`
- Modify: `frontend/tests/chat-tool-run-cleanup.test.mjs`
- Modify: `frontend/tests/chat-typewriter-stream.test.mjs`
- Create: `frontend/src/features/chat/ChatCitations.test.tsx`

- [ ] **Step 1: Write failing current-run citation tests**

```tsx
it('opens a persisted current-run Evidence window from K1', async () => {
  renderChatWithEvents([
    sourcesEvent({ seq: 4, run_id: 'run-a', evidence: [evidence({ evidence_id: 'K1', index_generation: 'g1' })] }),
    tokenEvent('Answer [K1]'), doneEvent({ seq: 6 }),
  ])
  await userEvent.click(await screen.findByRole('button', { name: 'K1' }))
  expect(screen.getByTestId('evidence-drawer')).toHaveTextContent('chunk-a')
  expect(previewRequest()).toMatchObject({ kbUid: 'kb-a', fileUid: 'file-a', generation: 'g1' })
})

it('shows but does not resolve an unknown citation', async () => {
  renderChatWithEvents([sourcesEvent({ evidence: [evidence({ evidence_id: 'K1' })] }), tokenEvent('[K9]')])
  expect(await screen.findByText('无效引用 K9')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'K9' })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run and verify failure**

Run: `pnpm --dir frontend test -- src/features/chat/ChatCitations.test.tsx`

Expected: FAIL because the shared citation components and v2 event reducer are absent.

- [ ] **Step 3: Normalize Chat v2 events into one run-local Evidence registry**

`chatStore` rejects decreasing/duplicate `seq` per `run_id`, preserves `trace_id`, health/warnings, and stores Evidence keyed by `evidence_id` plus `(kb_uid,file_uid,chunk_uid,index_generation)`. Tool results and final Sources merge into that registry; later active generations never re-resolve old citations. Existing `agent_status/tool_call/tool_result/trace/clarify/sources/token/error/title/done` handling remains. Update the three existing source-contract tests to inspect the extracted feature modules and the thin Chat orchestrator instead of requiring moved rendering logic to remain inline.

- [ ] **Step 4: Implement scope picker, timeline, citations, and drawer**

`RetrievalScopePicker` lists only Backend-authorized KBs and sends selected `kb_uids` to `/api/v1/chat/answer`. It never accepts actor/tenant. `ToolRunTimeline` displays the six knowledge tools with typed `ok/no_hits/degraded/error` states. Markdown citation rendering replaces only validated `[Kx]` tokens with `CitationCard`; the shared `EvidenceList` renders tool/final sources. `EvidenceDrawer` opens highlighted document windows or graph paths through public Backend routes.

- [ ] **Step 5: Run and commit**

```powershell
pnpm --dir frontend test -- src/features/chat/ChatCitations.test.tsx
node --test frontend/tests/chat-trace-stream.test.mjs frontend/tests/chat-tool-run-cleanup.test.mjs frontend/tests/chat-typewriter-stream.test.mjs
pnpm --dir frontend build
git add frontend/src/features/chat frontend/src/app/chatStore.ts frontend/src/pages/ChatPage.tsx frontend/tests/chat-trace-stream.test.mjs frontend/tests/chat-tool-run-cleanup.test.mjs frontend/tests/chat-typewriter-stream.test.mjs
git commit -m "feat(chat): 闭环知识引用与原文跳转"
```

## Task 8: Backfill Legacy Data and Build Side Generations

**Files:**
- Create: `scripts/knowledge_backfill.py`
- Create: `backend/app/models/knowledge_migration.py`
- Create: `backend/app/models/knowledge_runtime_setting.py`
- Create: `backend/alembic/versions/20260722_04_knowledge_cutover_state.py`
- Create: `backend/tests/integration/test_knowledge_backfill.py`
- Modify: `.env.prod.example`

- [ ] **Step 1: Write the failing real-MySQL idempotency test**

```python
def test_backfill_is_idempotent_and_keeps_legacy_reads(mysql_session, service_stack):
    seed_legacy_topic_file_chunks(mysql_session, topic_id="12", chunk_count=3)
    first = run_backfill(batch_size=2, dry_run=False)
    second = run_backfill(batch_size=2, dry_run=False)
    topic = load_topic(mysql_session, "12")
    assert_uuid4(topic.kb_uid)
    assert all_uuid4(load_file_and_chunk_uids(mysql_session, topic.id))
    assert first.updated_rows > 0
    assert second.updated_rows == 0
    assert legacy_query("known phrase").evidence
```

Add a second test proving `tenant_id/owner_user_id` are filled by the configured compatibility actor, local `storage_path` becomes an opaque `storage_uri`, graph facts gain the same `kb_uid`, and no file content/path appears in the report.

- [ ] **Step 2: Run and verify failure against the real service profile**

Run:

```powershell
docker compose up -d mysql redis etcd minio milvus elasticsearch neo4j
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest backend/tests/integration/test_knowledge_backfill.py -v
```

Expected: FAIL because `scripts/knowledge_backfill.py` does not exist.

- [ ] **Step 3: Implement an explicit phased, resumable backfill**

```python
PHASES = (
    "stable_ids",
    "actor_scope",
    "storage_uri",
    "chunk_scope",
    "graph_scope",
    "index_generations",
    "graph_projection",
    "verification",
)
```

The Alembic revision has `revision = "20260722_04"` and `down_revision = "20260722_03"` (the Graph plan revision). It creates `KnowledgeMigrationRun` (phase, cursor, status, counts, timestamps, error code), `KnowledgeLegacyUidMap` (source table, legacy ID, resource kind, UUID v4 public UID) with a unique key on source table plus legacy ID, and the singleton `knowledge_runtime_setting` table consumed by Task 9. The script requires a phase and `--dry-run|--apply`, scans by primary-key cursor in bounded batches, commits checkpoints and legacy-row-to-public-UID mappings to those tables, and is safe to resume. On the first applied pass it generates and persists UUID v4 values; later passes reuse the non-null UID or the mapping row, never regenerate it. It fails explicitly on missing files, ambiguous ownership, duplicate content conflicts, malformed graph facts, or dimension/profile mismatch.

`index_generations` enqueues normal Plan 2 jobs to build Milvus/ES beside legacy indexes. `graph_projection` writes/replays Plan 5 Outbox facts into a non-active graph generation. The script never directly fabricates vector/Neo4j state and does not dual-write legacy/new stores.

- [ ] **Step 4: Add safe configuration**

Add bootstrap `KNOWLEDGE_READ_PATH=legacy|shadow|native` with default `legacy`. Runtime cutover state becomes MySQL-authoritative in Task 9; the environment value is used only when the singleton setting row is first created. Do not put database passwords, API keys, internal absolute paths, or provider payloads in CLI output.

- [ ] **Step 5: Run and commit**

```powershell
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
alembic upgrade head
python -m pytest backend/tests/integration/test_knowledge_backfill.py -v
git add scripts/knowledge_backfill.py backend/app/models/knowledge_migration.py backend/app/models/knowledge_runtime_setting.py backend/alembic/versions/20260722_04_knowledge_cutover_state.py backend/tests/integration/test_knowledge_backfill.py .env.prod.example
git commit -m "feat(migration): 增加知识数据幂等回填"
```

Expected: test passes twice against real MySQL; the second run changes zero rows.

## Task 9: Implement Shadow Verification, Atomic Cutover, and Rollback

**Files:**
- Create: `scripts/knowledge_cutover.py`
- Create: `scripts/knowledge_rollback.py`
- Create: `scripts/verify_knowledge_system.py`
- Create: `backend/tests/integration/test_knowledge_cutover.py`
- Create: `backend/app/services/knowledge_read_path.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/knowledge_bases.py`
- Modify: `backend/app/api/knowledge_files.py`
- Modify: `backend/app/api/knowledge_retrieval.py`
- Modify: `backend/app/api/knowledge_graph.py`

- [ ] **Step 1: Write failing gate and rollback tests**

```python
def test_cutover_refuses_incomplete_generation(real_services, migrated_kb):
    mark_es_count_mismatch(migrated_kb.kb_uid)
    result = run_cutover(kb_uid=migrated_kb.kb_uid, apply=True)
    assert result.exit_code == 2
    assert result.code == "INDEX_COUNT_MISMATCH"
    assert read_path() == "legacy"


def test_rollback_switches_reads_without_deleting_native_generations(real_services, cutover_kb):
    run_rollback(reason="error-rate gate")
    assert read_path() == "legacy"
    assert native_generation_exists(cutover_kb.active_index_generation)
    assert graph_generation_exists(cutover_kb.active_graph_generation)
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest backend/tests/integration/test_knowledge_cutover.py -v
```

Expected: FAIL because cutover and rollback commands are missing.

- [ ] **Step 3: Implement shadow comparison and release gates**

`verify_knowledge_system.py` checks per KB:

- MySQL file/item/chunk counts and non-null stable scopes;
- Milvus and ES counts for `tenant_id + kb_uid + active_index_generation`;
- embedding dimension/profile and sampled chunk identity;
- Neo4j scoped node/relation/Mention counts, Outbox lag, and active graph generation;
- sampled legacy/native queries for overlap, cross-KB leakage, and channel health;
- preview/citation resolution and tombstone exclusion.

It emits only aggregate counts, public IDs, codes, and trace IDs. Any cross-KB result, missing Evidence target, unavailable required channel, projection lag, or generation mismatch blocks cutover.

- [ ] **Step 4: Implement atomic flag switching and rollback**

Add a singleton `knowledge_runtime_setting` row with `read_path`, optimistic `version`, `updated_at`, `updated_by`, `reason`, and last verified generation snapshots. The Alembic migration initializes it from the bootstrap environment value. Every knowledge read entry resolves this MySQL row through `KnowledgeReadPath`; a bounded one-second cache may be used only if cutover publishes invalidation through Redis. The row, not a process environment variable, is authoritative across Backend replicas and restarts.

`knowledge_cutover.py --apply` acquires a MySQL advisory lock, reruns verification, records old/new modes and active generations, then transactionally changes the authoritative row from `shadow` to `native` with an optimistic-version check and publishes cache invalidation. It does not delete legacy indexes.

`knowledge_rollback.py --apply --reason ...` acquires the same lock, restores `legacy`, records the reason/trace, and leaves native generations for diagnosis. Define release rollback thresholds in the script: any scope leak or citation mismatch; unavailable rate above 1% for five minutes; or HTTP 5xx above 2% for five minutes. Degraded responses do not automatically count as empty hits.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest backend/tests/integration/test_knowledge_cutover.py -v
python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
git add scripts/knowledge_cutover.py scripts/knowledge_rollback.py scripts/verify_knowledge_system.py backend/app/services/knowledge_read_path.py backend/app/config.py backend/app/api/knowledge_bases.py backend/app/api/knowledge_files.py backend/app/api/knowledge_retrieval.py backend/app/api/knowledge_graph.py backend/tests/integration/test_knowledge_cutover.py
git commit -m "feat(release): 增加知识链路切换与回滚门禁"
```

Expected: integration tests pass and verification prints `PASS` for scoped resources, generations, retrieval, graph, citation, and tombstones.

## Task 10: Add Full Browser E2E and Remove Legacy Knowledge Paths

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/knowledge-product.spec.ts`
- Create: `frontend/e2e/knowledge-failure-modes.spec.ts`
- Create: `frontend/e2e/chat-citations.spec.ts`
- Modify: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/pages/KnowledgeGraphPage.tsx`
- Modify: `frontend/src/app/api.ts`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `README.md`

- [ ] **Step 1: Write E2E acceptance scenarios**

```ts
test('create, upload, index, query and open citation', async ({ page }) => {
  await page.goto('/knowledge')
  await page.getByRole('button', { name: '新建知识库' }).click()
  await page.getByLabel('名称').fill('E2E KB')
  await page.getByRole('button', { name: '创建' }).click()
  await page.getByLabel('选择文件').setInputFiles('e2e/fixtures/refund-policy.md')
  await expect(page.getByText('索引完成')).toBeVisible({ timeout: 120_000 })
  await page.getByRole('link', { name: '检索' }).click()
  await page.getByLabel('查询').fill('退款期限')
  await page.getByRole('button', { name: '运行检索' }).click()
  await page.getByRole('button', { name: /退款政策/ }).first().click()
  await expect(page.getByTestId('document-highlight')).toContainText('退款')
})
```

Add scenarios for directory relative paths and bounded upload, URL import, cancel/retry, refresh/deep link/back-forward, graph build/path Evidence, file deletion preserving shared entities, Outbox replay convergence, Mindmap, frozen evaluation run, Chat `[K1]` jump, and KB A/KB B cross-scope isolation.

Failure-mode E2E stops ES and expects `degraded`, stops Milvus plus ES and expects `unavailable`, and forces a failed side-generation build while proving the old generation still answers. Restore each service in `finally` and wait for health before the next scenario.

- [ ] **Step 2: Run E2E and verify at least one initial failure**

Run:

```powershell
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

Expected: at least one scenario fails until remaining legacy navigation/API assumptions are removed.

- [ ] **Step 3: Remove migrated legacy product paths**

Replace `KnowledgePage` with a route redirect to `/knowledge`; replace the knowledge-scoped behavior of the old graph page with the new scoped route or explicit global graph behavior. Remove knowledge DTOs/calls from `app/api.ts` after all imports use feature APIs. Remove timer-based whole-list refresh, direct Engine browser calls, numeric Topic IDs in URLs, raw `storage_path`, and overlapping legacy knowledge actions. Keep unrelated Chat/memory/wiki APIs untouched.

Do not delete legacy database/index data in this commit. After the observation window and only while `KNOWLEDGE_READ_PATH=native`, a separately approved cleanup migration may remove legacy indexes/code adapters; long-term dual write remains forbidden.

- [ ] **Step 4: Run the complete release gate**

```powershell
node --test frontend/tests/*.test.mjs
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend test:e2e
if (-not $env:PRISM_TEST_DATABASE_URL) { throw 'PRISM_TEST_DATABASE_URL must target the dedicated prism_test MySQL database' }
$env:DATABASE_URL=$env:PRISM_TEST_DATABASE_URL
python -m pytest backend/tests engine/tests -q
python scripts/verify_knowledge_system.py --base-url http://localhost:5175 --engine-url http://localhost:5180
git diff --check
```

Expected: all legacy Node tests, Vitest tests, TypeScript/Vite build, Playwright scenarios, Backend/Engine tests, and verification script pass; `git diff --check` reports no errors.

- [ ] **Step 5: Update release documentation and commit**

Document deep routes, Job SSE recovery, `KNOWLEDGE_READ_PATH`, backfill/cutover/rollback commands, observation/rollback gates, Evidence behavior, and explicit exclusions (Dify, Notion, LightRAG, online Chunk editing, sandbox mapping). Do not include secrets or local absolute storage paths.

```powershell
git add frontend/playwright.config.ts frontend/e2e frontend/src/pages/KnowledgePage.tsx frontend/src/pages/KnowledgeGraphPage.tsx frontend/src/app/api.ts frontend/src/app/routes.tsx README.md
git commit -m "feat(knowledge): 完成产品切换与端到端验收"
```

## Plan Verification

- [ ] Confirm every route restores the same `kbUid` and active tab after refresh, share, and browser back/forward.
- [ ] Confirm all browser knowledge traffic targets Backend `/api/v1` and never a private Engine URL.
- [ ] Confirm `kb_uid`, `file_uid`, `chunk_uid`, `job_id`, `active_index_generation`, and `active_graph_generation` remain stable and consistently named across Python and TypeScript.
- [ ] Confirm `no_hits`, `degraded`, `unavailable`, and `invalid_request` produce distinct API/store/UI states.
- [ ] Confirm Job reconnect performs snapshot then `after_seq`, ignores duplicates, and polls only after SSE transport failure.
- [ ] Confirm preview and Chat citation links use public IDs plus the persisted generation and never expose `storage_uri` or `uploads_data` paths.
- [ ] Confirm graph projection rebuild and model re-extraction are separate actions with different cost messages.
- [ ] Confirm evaluation runs display frozen model/config/index/graph snapshots.
- [ ] Confirm backfill is idempotent, cutover is gate-protected, rollback is one flag switch, and there is no long-term dual write.
- [ ] Confirm real MySQL/Redis/Milvus/Elasticsearch/Neo4j tests and all E2E scenarios pass.
- [ ] Confirm Dify, Notion, LightRAG, business S3 migration, full organization/RBAC, Chunk editing, knowledge-to-sandbox mapping, Agent mutation tools, vector export, and CLI remain absent.
- [ ] Record every task commit and final verification result in `2026-07-22-knowledge-system-roadmap.md` using a separate docs-only commit after execution.
