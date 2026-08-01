# Chat Capture → Review Station Design

Date: 2026-08-01

## Goal

Move personal-thought capture into the chat page. When a user asks the agent to record a thought, idea, opinion, snippet, to-do, or resource during a chat, the agent calls a new `capture_thought` tool that creates a pending `PersonalAssetItem`. The item lands in the review station (today's inbox page, form removed) where the user reviews, edits, and confirms it. Confirmation keeps today's semantics exactly: the confirmed item flows into the asset layer, optional long-term memory, and entity graph.

Capture becomes the chat page's responsibility; the review station becomes a pure audit surface. The manual "添加碎片" form is removed.

## Current Context

The inbox page (`frontend/src/pages/InboxPage.tsx`) is currently a two-in-one surface:

1. **Capture (right panel):** a manual form (`标题/内容/来源/标签`) and a voice record button.
   - `POST /api/v1/assets/items` → `_create_asset_item_from_raw()` runs AI parse (title/summary/kind/tags), creates `PersonalAssetItem(status="pending_review")`.
   - `POST /api/v1/assets/voice` → ASR transcription → same creation path.
2. **Review (left list + center editor):** list pending items, edit fields, `确认入库` / `拒绝`.
   - `POST /api/v1/assets/items/{id}/confirm` → `status="confirmed"`, optional `MemoryEntry`, entity-graph ingestion.

The chat page (`frontend/src/pages/ChatPage.tsx`) is a pure QA surface streaming NDJSON events from the Engine agent loop. The agent already has tools registered through `engine/app/agent/tools/base.py` (`BUILTIN_REGISTRY`, `build_enabled_tools`), and the Engine process shares the same MySQL database and already imports `backend.app.models` directly (see `engine/app/agent/tools/assets.py`, which queries confirmed assets in-process).

The downstream confirm path is out of scope to change: a confirmed item does **not** automatically sync into the `个人随手记` system KB (that remains the separate `PersonalAssetUnit` flow).

## Product Decisions

1. Capture is triggered by an agent tool `capture_thought`, enabled by default in normal chat (`default_enabled=True`).
2. The chat input stays a normal QA surface. `capture_thought` fires only when the user explicitly asks to record/save something (e.g. "帮我记一下", "记下来", "收藏这个"). The system prompt defines when to call it.
3. The review station is the current inbox page with the "添加碎片" form removed and the surface renamed to `审核台`.
4. Confirmation keeps existing semantics: confirmed item → asset layer + optional memory + entity graph. No auto-sync to `个人随手记` KB.
5. Capture is independent of knowledge base and session. No knowledge-scope changes; no KB/session gate on the tool.
6. Voice capture moves to the chat page (mic button beside the input) and feeds the same review station.
7. v1 uses heuristic-only enrichment inside the tool (no LLM call) so capture returns fast and does not stall the agent loop. LLM background enrichment is a follow-up.

## Architecture

```text
ChatPage: user types "帮我记一下：..."
  -> Engine agent loop
    -> tool capture_thought (default_enabled=True)
      -> shared service create_asset_item_from_raw(use_llm=False)
         - heuristic parse only (title/summary/kind/tags via existing fallback)
         - inserts PersonalAssetItem(status="pending_review",
             source_type="chat", raw_metadata={entrypoint:"chat_capture"})
  -> tool result NDJSON event -> ChatPage renders "已记录，去审核台确认" chip
ReviewStationPage (formerly InboxPage):
  - list pending items (unchanged: GET /assets/items?status=pending_review)
  - edit fields (unchanged)
  - 确认入库 -> POST /assets/items/{id}/confirm (unchanged downstream)
```

`PersonalAssetItem` remains the source of truth. No new tables, no new columns.

## Data Model

No schema changes.

Each captured item is created as:

```json
{
  "status": "pending_review",
  "source_type": "chat",
  "source_platform": "",
  "raw_metadata": { "entrypoint": "chat_capture" },
  "title": "<heuristic or provided>",
  "summary": "<heuristic>",
  "asset_kind": "<heuristic>",
  "tags": ["<heuristic>"]
}
```

The heuristic fields come from the existing `_fallback_parse` (rule-based title / kind / category / summary). The user can edit all of them in the review station before confirming.

## Backend Changes

### 1. Extract a shared asset-item creation service

Create `backend/app/services/asset_items.py` with:

```python
def create_asset_item_from_raw(
    db: Session,
    *,
    raw_text: str,
    raw_title: str = "",
    raw_source_type: str = "manual",
    raw_source_platform: str = "",
    raw_source_url: str = "",
    raw_author: str = "",
    raw_tags: list[str] | None = None,
    raw_metadata: dict[str, Any] | None = None,
    use_llm: bool = True,
) -> PersonalAssetItem:
```

- Contains the current logic of `backend/app/api/assets.py::_create_asset_item_from_raw` (preference recall → AI or fallback parse → normalize → keyword index → insert → `status="pending_review"`).
- `use_llm=True` (default) keeps today's behavior exactly: `_ai_parse_asset` + `_normalize_parse`.
- `use_llm=False` skips the LLM call and uses only `_fallback_parse` (fast; used by the engine tool).
- Must not import FastAPI (`HTTPException` stays in the API layer). The service raises `ValueError` for empty content; `backend/app/api/assets.py` maps it back to `HTTPException(400)`.
- Move the needed helpers (`_short_title`, `_clean_tags`, `_normalize_parse`, `_fallback_parse`, `_extract_keywords`, `_keyword_index_text`) into the service or import them from a shared location.

### 2. Refactor the backend API to delegate

- `backend/app/api/assets.py::_create_asset_item_from_raw` becomes a thin wrapper around the service (`use_llm=True`) so the `/assets/items` and `/assets/voice` endpoints keep identical behavior.
- Move or delete the duplicated helpers in the API module after the service owns them.

## Engine Changes

### 1. Add the `capture_thought` tool

In `engine/app/agent/tools/assets.py` (already has the DB session factory and `backend.app.models` imports):

```python
class CaptureThoughtInput(BaseModel):
    text: str = Field(..., description="The thought/idea/opinion content to record.")
    title: str | None = Field(None, description="Optional short title.")


def _build_capture_thought(ctx: ToolContext) -> StructuredTool:
    def run(text: str, title: str | None = None) -> str:
        text = (text or "").strip()
        if not text:
            return json.dumps({"status": "error", "message": "没有可记录的内容。"}, ensure_ascii=False)
        db = _Session()
        try:
            from backend.app.services.asset_items import create_asset_item_from_raw
            item = create_asset_item_from_raw(
                db,
                raw_text=text,
                raw_title=title or "",
                raw_source_type="chat",
                raw_metadata={"entrypoint": "chat_capture"},
                use_llm=False,
            )
        finally:
            db.close()
        ctx.stats_holder["capture_thought"] = {"item_id": item.id, "title": item.title}
        return json.dumps({
            "status": "ok",
            "item_id": item.id,
            "title": item.title,
            "summary": item.summary,
            "message": f"已记录「{item.title}」，等待你在审核台确认入库。",
        }, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="capture_thought",
        description=(
            "Record a thought, idea, opinion, snippet, to-do, or resource the user explicitly asks to save. "
            "Creates a pending item that the user confirms later in the review station. "
            "Use when the user says things like '帮我记一下', '记下来', '收藏这个', '记录：...'."
        ),
        args_schema=CaptureThoughtInput,
    )


register_tool(
    ToolSpec(
        key="capture_thought",
        name="capture_thought",
        description="Record a thought/idea the user asks to save into the review station.",
        builder=_build_capture_thought,
        default_enabled=True,
    )
)
```

`default_enabled=True` makes it active in every normal chat via `build_enabled_tools` (`engine/app/chat/answer.py:517`). No knowledge-scope change needed.

### 2. System prompt guidance

In `engine/app/agent/prompts.py`, add a short section under the tool principles (e.g. after the `memory_search` bullet):

- Call `capture_thought` when the user explicitly asks to record/save a thought, idea, opinion, snippet, to-do, or resource.
- Do NOT call it for questions (use `knowledge_search` / `deep_knowledge_search`).
- Do NOT confuse it with `memory_search` (retrieving existing long-term memory). `capture_thought` is for new knowledge fragments that go to the review station.

## Frontend Changes

### 1. ChatPage (`frontend/src/pages/ChatPage.tsx`)

- Add `capture_thought: '记录想法'` to the `toolLabel()` map so the thinking panel renders a friendly label.
- On a successful `capture_thought` `tool_result`, render a small "去审核台确认" link chip (navigates to `/inbox`).
- Add `VoiceRecordButton` beside the chat input (mic button). On success, show a toast "语音已记录，去审核台确认" with a link to `/inbox`. Reuses the existing `POST /api/v1/assets/voice` endpoint, which already creates a pending item.

### 2. Review station (formerly InboxPage)

- Remove the right "添加碎片" form panel and the `VoiceRecordButton` from `frontend/src/pages/InboxPage.tsx`.
- Rename the surface heading to `审核台`; keep the title/empty-state copy aligned ("待确认碎片").
- Remove now-unused draft state (`draftText`, `draftTitle`, `draftSourceType`, `draftSourcePlatform`, `draftSourceUrl`, `draftTags`) and the `createItem` handler.
- Keep the left pending list, the center editor, and confirm/reject flows unchanged.

### 3. Navigation (`frontend/src/layouts/MainLayout.tsx`)

- Change the `/inbox` nav label from `收件箱` to `审核台`. Route path stays `/inbox` to avoid link churn.

## Testing Plan

Backend:

- New service tests: `create_asset_item_from_raw(use_llm=False)` creates a `pending_review` item with heuristic title/summary/kind and `raw_metadata={"entrypoint": "chat_capture"}`; empty content raises `ValueError`.
- Existing `test_assets_api.py` create/confirm/voice tests still pass after the refactor (mocked AI path unchanged).

Engine:

- `capture_thought` tool test: with a stubbed DB session, calling the tool inserts a `pending_review` `PersonalAssetItem` and returns `status="ok"` with the item id/title. (Follow the existing tool-test style; stub `_Session` / the shared service if needed.)

Frontend:

- `toolLabel('capture_thought')` renders `记录想法`.
- Review station page no longer renders the add-form / voice button.
- Chat page renders the capture success chip / mic button (per existing `frontend/tests/*.test.mjs` style, or covered by build).

## Non-Goals

- No automatic/scheduled extraction of every chat message (that is the memory-extraction path). Capture only on explicit user request.
- No dedup/merge of captured items in v1.
- No LLM enrichment inside the tool in v1 (heuristic-only; LLM background enrichment is a follow-up).
- No change to confirm downstream: confirmed items stay in the asset layer only; no auto-sync into the `个人随手记` KB.

## Open Implementation Notes

- Route naming: keep `/inbox` and change only the label, unless a `/review` alias is wanted for clarity.
- Whether the mic button lands in the first cut or a follow-up.
- Whether a later version runs LLM enrichment on captured items in a background job so the review station shows richer AI fields.
- Whether the agent should be allowed to pass a suggested `asset_kind`/`category` when the user's phrasing makes it obvious (e.g. "记个待办").
