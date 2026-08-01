# Chat Capture → Review Station Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture personal thoughts in the chat page via a new `capture_thought` agent tool. Captured items land as `pending_review` `PersonalAssetItem` rows in the review station (today's inbox page, "添加碎片" form removed, renamed `审核台`). Confirmation semantics are unchanged: confirmed item → asset layer + optional memory + entity graph.

**Architecture:** The Engine process already shares the MySQL database and imports `backend.app.models` directly. We extract the asset-item creation logic from `backend/app/api/assets.py` into a FastAPI-free shared service `backend/app/services/asset_items.py` with a `use_llm` flag. The new `capture_thought` tool (in `engine/app/agent/tools/assets.py`, `default_enabled=True`) calls the service with `use_llm=False` (heuristic-only, fast, non-blocking). The chat page renders the tool result and offers a "去审核台" jump; the review station keeps the list + editor + confirm/reject flows.

**Tech Stack:** FastAPI, SQLAlchemy, MySQL (shared by Backend and Engine), LangChain agent tools, React/TypeScript.

---

## File Structure

Create:

- `backend/app/services/asset_items.py` — shared asset-item creation service (FastAPI-free), owns the parse/keyword helpers.
- `backend/tests/test_asset_items_service.py` — unit tests for the shared service (`use_llm` both paths, empty-content error).
- `engine/tests/test_capture_thought_tool.py` — tool creates a `pending_review` item and returns ok.

Modify:

- `backend/app/api/assets.py` — delegate `_create_asset_item_from_raw` to the service; re-import shared helpers used by update/confirm endpoints.
- `engine/app/agent/tools/assets.py` — add `capture_thought` tool + registration (`default_enabled=True`).
- `engine/app/agent/prompts.py` — add `capture_thought` usage guidance.
- `frontend/src/pages/ChatPage.tsx` — `toolLabel('capture_thought')`, capture-success chip, `VoiceRecordButton` in the input toolbar.
- `frontend/src/pages/InboxPage.tsx` — remove right capture form + voice; rename to 审核台.
- `frontend/src/layouts/MainLayout.tsx` — `/inbox` nav label `收件箱` → `审核台`.

Test:

- `backend/tests/test_assets_api.py`, `backend/tests/test_personal_asset_items_api.py`, `backend/tests/test_asset_voice.py` — must stay green after the refactor.
- `frontend/tests/main-layout-navigation.test.mjs` — label assertion update if it asserts `收件箱`.
- `frontend/tests/chat-*.test.mjs` — add a capture_thought tool-label / chip test.

---

### Task 1: Extract the shared asset-item service

**Files:**
- Create: `backend/app/services/asset_items.py`
- Create: `backend/tests/test_asset_items_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_asset_items_service.py`:

```python
def test_create_asset_item_use_llm_false_creates_pending_review_item(db_session):
    from backend.app.services.asset_items import create_asset_item_from_raw

    item = create_asset_item_from_raw(
        db_session,
        raw_text="下周要给季度评审准备一份自动化测试复盘。",
        raw_title="",
        raw_source_type="chat",
        raw_metadata={"entrypoint": "chat_capture"},
        use_llm=False,
    )

    assert item.status == "pending_review"
    assert item.source_type == "chat"
    assert item.raw_metadata == {"entrypoint": "chat_capture"}
    assert item.title
    assert item.user_id == "default-user"


def test_create_asset_item_empty_content_raises_value_error(db_session):
    from backend.app.services.asset_items import create_asset_item_from_raw

    try:
        create_asset_item_from_raw(db_session, raw_text="   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty content")


def test_create_asset_item_use_llm_true_uses_ai_parse(db_session, monkeypatch):
    from backend.app.services import asset_items

    monkeypatch.setattr(
        asset_items,
        "_ai_parse_asset",
        lambda **kwargs: {
            "title": "LLM title",
            "summary": "LLM summary",
            "asset_kind": "knowledge",
            "tags": ["tag-a"],
            "category": "分类",
            "rewritten_content": "rewritten",
            "confidence": {"overall": 0.9},
            "rationale": "ok",
        },
    )

    item = asset_items.create_asset_item_from_raw(
        db_session,
        raw_text="some knowledge content",
        use_llm=True,
    )

    assert item.title == "LLM title"
    assert item.asset_kind == "knowledge"
    assert item.status == "pending_review"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest backend/tests/test_asset_items_service.py -v
```

Expected: FAIL — `backend.app.services.asset_items` does not exist.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/asset_items.py`. Move the core of `backend/app/api/assets.py::_create_asset_item_from_raw` here, plus its parse helpers, and make it FastAPI-free (no `from fastapi import`):

```python
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import PersonalAssetItem
from backend.app.prompts.asset_parse import build_asset_parse_messages
from backend.app.services.memory_context import recall_preference_context

DEFAULT_USER_ID = "default-user"
```

Move these helpers from `assets.py` into the service (import them back in the API module afterward): `_short_title`, `_clean_tags`, `_clean_dict_list`, `_extract_keywords`, `_keyword_index_text`, `_fallback_parse`, `_ai_parse_asset`, `_normalize_parse`.

Core function:

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
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("Content is required")

    parsed = None
    if use_llm:
        user_preferences = ""
        try:
            user_preferences = recall_preference_context(db, raw_text)
        except Exception:
            user_preferences = ""
        parsed = _ai_parse_asset(
            content=raw_text,
            title=raw_title,
            source_type=raw_source_type,
            source_platform=raw_source_platform,
            source_url=raw_source_url,
            user_preferences=user_preferences,
        )
    data = _normalize_parse(
        content=raw_text,
        title=raw_title,
        source_type=raw_source_type,
        source_platform=raw_source_platform,
        source_url=raw_source_url,
        parsed=parsed,
    )
    raw_tags = _clean_tags(raw_tags or [])
    keywords = _extract_keywords(raw_text, [*raw_tags, *data["tags"]])
    item = PersonalAssetItem(
        user_id=DEFAULT_USER_ID,
        raw_text=raw_text,
        raw_title=(raw_title or "")[:255],
        raw_source_type=(raw_source_type or "manual")[:64],
        raw_source_platform=(raw_source_platform or "")[:128],
        raw_source_url=(raw_source_url or "")[:1000],
        raw_author=(raw_author or "")[:255],
        raw_tags=raw_tags,
        raw_metadata=raw_metadata or {},
        raw_keywords=keywords,
        keyword_index_text=_keyword_index_text(
            raw_title, raw_text, raw_tags, keywords,
            data["title"], data["summary"], data["rewritten_content"],
            data["tags"], data["category"],
        ),
        raw_embedding_status="pending",
        title=data["title"],
        summary=data["summary"],
        asset_kind=data["asset_kind"],
        source_type=data["source_type"],
        source_platform=data["source_platform"],
        source_url=data["source_url"],
        media_type=data["media_type"],
        category=data["category"],
        tags=data["tags"],
        extracts=data["extracts"],
        suggested_relations=data["suggested_relations"],
        suggested_extensions=data["suggested_extensions"],
        confidence=data["confidence"],
        rationale=data["rationale"],
        rewritten_content=data["rewritten_content"],
        extra_meta={"raw_metadata": raw_metadata or {}},
        capabilities=["searchable", "summarizable"],
        source_ref_type="fragment",
        importance=float((data["confidence"] or {}).get("overall", 0.5) or 0.5),
        status="pending_review",
    )
    db.add(item)
    db.flush()
    item.source_ref_id = item.id
    db.commit()
    db.refresh(item)
    return item
```

Constraint: the service module must not import from `backend.app.api` or FastAPI. If `recall_preference_context` or `build_asset_parse_messages` pull in FastAPI, stop and split those imports before proceeding.

- [ ] **Step 4: Run service tests**

Run:

```bash
python -m pytest backend/tests/test_asset_items_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/asset_items.py backend/tests/test_asset_items_service.py
git commit -m "feat(assets): extract shared asset-item creation service"
```

---

### Task 2: Refactor the assets API to delegate

**Files:**
- Modify: `backend/app/api/assets.py`

- [ ] **Step 1: Delegate the create path**

In `backend/app/api/assets.py`:

- Import from the service:

```python
from backend.app.services.asset_items import (
    create_asset_item_from_raw,
    _clean_tags,
    _clean_dict_list,
    _extract_keywords,
    _keyword_index_text,
    _normalize_parse,
    _short_title,
)
```

- Replace the body of `_create_asset_item_from_raw` with:

```python
def _create_asset_item_from_raw(
    *,
    db: Session,
    raw_text: str,
    raw_title: str = "",
    raw_source_type: str = "manual",
    raw_source_platform: str = "",
    raw_source_url: str = "",
    raw_author: str = "",
    raw_tags: list[str] | None = None,
    raw_metadata: dict[str, Any] | None = None,
) -> PersonalAssetItem:
    try:
        return create_asset_item_from_raw(
            db,
            raw_text=raw_text,
            raw_title=raw_title,
            raw_source_type=raw_source_type,
            raw_source_platform=raw_source_platform,
            raw_source_url=raw_source_url,
            raw_author=raw_author,
            raw_tags=raw_tags,
            raw_metadata=raw_metadata,
            use_llm=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "empty_content", "message": str(exc)}) from exc
```

- Delete the moved helper definitions from `assets.py` (they now live in the service; the module-level `from ... import` above re-exposes them for the update/confirm endpoints that still use `_clean_tags`, `_clean_dict_list`, `_keyword_index_text`).
- If `_ai_parse_asset`, `_fallback_parse`, or `build_asset_parse_messages` become unused in `assets.py`, remove their now-unused imports.

- [ ] **Step 2: Run existing API tests**

Run:

```bash
python -m pytest backend/tests/test_assets_api.py backend/tests/test_personal_asset_items_api.py backend/tests/test_asset_voice.py -v
```

Expected: PASS (create/confirm/voice behavior unchanged).

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/assets.py
git commit -m "refactor(assets): delegate create path to shared service"
```

---

### Task 3: Add the `capture_thought` engine tool

**Files:**
- Modify: `engine/app/agent/tools/assets.py`
- Create: `engine/tests/test_capture_thought_tool.py`

- [ ] **Step 1: Write failing tool test**

Create `engine/tests/test_capture_thought_tool.py` (follow `test_asset_search_multiterm.py`: in-memory SQLite + monkeypatch `_Session`):

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import PersonalAssetItem
from engine.app.agent.tools.base import ToolContext, build_enabled_tools
import engine.app.agent.tools.assets as asset_tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.memory  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


def test_capture_thought_creates_pending_review_item(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.close()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    ctx = ToolContext(citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "capture_thought")

    payload = json.loads(tool.invoke({"text": "下周给季度评审准备自动化测试复盘。", "title": None}))

    assert payload["status"] == "ok"
    assert payload["item_id"]
    row = Session().query(PersonalAssetItem).filter_by(id=payload["item_id"]).one()
    assert row.status == "pending_review"
    assert row.source_type == "chat"
    assert row.raw_metadata == {"entrypoint": "chat_capture"}
```

> Note: the shared service uses `recall_preference_context` only when `use_llm=True`; the tool passes `use_llm=False`, so no LLM/preference DB dependency in the test. If the test still hits a missing table for memory models, add those models via `Base.metadata.create_all` in the same test (the Base already includes memory tables).

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m pytest engine/tests/test_capture_thought_tool.py -v
```

Expected: FAIL — no tool named `capture_thought` in the registry.

- [ ] **Step 3: Implement the tool**

In `engine/app/agent/tools/assets.py`, add:

```python
class CaptureThoughtInput(BaseModel):
    text: str = Field(..., description="The thought/idea/opinion content to record.")
    title: str | None = Field(None, description="Optional short title.")


def _build_capture_thought(ctx: ToolContext) -> StructuredTool:
    def run(text: str, title: str | None = None) -> str:
        from backend.app.services.asset_items import create_asset_item_from_raw

        text = (text or "").strip()
        if not text:
            return json.dumps({"status": "error", "message": "没有可记录的内容。"}, ensure_ascii=False)
        db = _Session()
        try:
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
        return json.dumps(
            {
                "status": "ok",
                "item_id": item.id,
                "title": item.title,
                "summary": item.summary,
                "message": f"已记录「{item.title}」，等待你在审核台确认入库。",
            },
            ensure_ascii=False,
        )

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

- [ ] **Step 4: Run the tool test and existing asset tool tests**

Run:

```bash
python -m pytest engine/tests/test_capture_thought_tool.py engine/tests/test_asset_search_multiterm.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/app/agent/tools/assets.py engine/tests/test_capture_thought_tool.py
git commit -m "feat(agent): add capture_thought tool"
```

---

### Task 4: Add `capture_thought` guidance to the system prompt

**Files:**
- Modify: `engine/app/agent/prompts.py`

- [ ] **Step 1: Edit the prompt**

In `AGENT_SYSTEM_PROMPT`, after the tool-boundary bullets (`knowledge_search` / `deep_knowledge_search` / `memory_search`), add:

```text
* `capture_thought`：当用户明确要求记录/收藏一个想法、观点、心得、片段、待办或资源时调用。它会创建一个待确认项，稍后用户在「审核台」确认后进入资产层。
  - 只在用户明确说「帮我记一下」「记下来」「收藏这个」「记录：…」这类采集意图时调用；普通提问不要调用，继续走 knowledge_search。
  - 不要和 memory_search 混淆：memory_search 是检索已有长期记忆；capture_thought 是新增一条待入库的知识碎片。
```

- [ ] **Step 2: Sanity-check prompt rendering**

Run:

```bash
python -m pytest engine/tests/test_agent_tools.py engine/tests/test_knowledge_base_tools.py -q
```

Expected: PASS (no prompt-structure assertions break).

- [ ] **Step 3: Commit**

```bash
git add engine/app/agent/prompts.py
git commit -m "feat(agent): prompt guidance for capture_thought"
```

---

### Task 5: Turn the inbox page into the review station

**Files:**
- Modify: `frontend/src/pages/InboxPage.tsx`

- [ ] **Step 1: Remove the capture form**

In `frontend/src/pages/InboxPage.tsx`:

- Remove the `VoiceRecordButton` import.
- Remove the draft state (`draftText`, `draftTitle`, `draftSourceType`, `draftSourcePlatform`, `draftSourceUrl`, `draftTags`), the `createItem` handler, and `splitTags`/`joinTags` if no longer used.
- Remove the right `<section>` that renders `VoiceRecordButton` + the "添加碎片" form + the `放入收件箱` button.
- Update the grid so the left list + center editor fill the width: `<main className="grid min-h-0 gap-3 overflow-hidden xl:grid-cols-[minmax(0,1fr)_22rem]">` → single column or keep editor wider.
- Empty-state copy: `可以在右侧添加新的碎片。` → `在对话页说「帮我记一下…」即可采集想法，稍后来这里确认入库。`

- [ ] **Step 2: Rename the surface**

- Header subtitle `收件箱` stays as the nav context but the page `<h1>` `待确认碎片` → `审核台 · 待确认碎片`.
- Editor empty-state `收件箱现在直接操作 personal_asset_item...` → `想法从对话页采集，在这里确认后进入资产层。`

- [ ] **Step 3: Run build**

Run:

```bash
cd frontend && pnpm build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InboxPage.tsx
git commit -m "feat(frontend): inbox page becomes review station, drop capture form"
```

---

### Task 6: Chat page capture surface

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`
- Test: `frontend/tests/chat-capture.test.mjs` (new) or extend an existing chat test

- [ ] **Step 1: Add tool label + capture chip**

In `ChatPage.tsx`:

- In `toolLabel()`, add `capture_thought: '记录想法'`.
- In the `tool_result` branch of `handleStreamLine`, when `msg.data?.tool === 'capture_thought'` and status is success, set a small piece of state (e.g. `lastCapture`, `{title, itemId, messageId}`) so a "去审核台确认" chip can render under the assistant message. Render the chip as a `<Link to="/inbox">去审核台确认 →</Link>` pill.

- [ ] **Step 2: Add the mic button**

- Import `VoiceRecordButton`.
- Render it in the input toolbar (next to the send button).
- `onResult`: set the same capture chip state (title from `item.title`, `itemId` from `item.id`) and keep the input focused.
- `onError`: show a transient inline error under the input (or reuse an existing error surface).

- [ ] **Step 3: Add a test**

Create `frontend/tests/chat-capture.test.mjs` (match existing `.test.mjs` style):

```js
import assert from 'node:assert/strict'

function toolLabel(tool) {
  const labels = { chat: '闲聊', knowledge_search: '检索知识库', capture_thought: '记录想法', clarify_user: '补充信息', tool: '工具' }
  return labels[tool] ?? tool
}

assert.equal(toolLabel('capture_thought'), '记录想法')
assert.equal(toolLabel('knowledge_search'), '检索知识库')
assert.equal(toolLabel('unknown_tool'), 'unknown_tool')
```

- [ ] **Step 4: Run build + test**

Run:

```bash
node frontend/tests/chat-capture.test.mjs
cd frontend && pnpm build
```

Expected: test exits 0, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx frontend/tests/chat-capture.test.mjs
git commit -m "feat(frontend): chat capture chip and mic button"
```

---

### Task 7: Rename the nav entry

**Files:**
- Modify: `frontend/src/layouts/MainLayout.tsx`
- Test: `frontend/tests/main-layout-navigation.test.mjs`

- [ ] **Step 1: Update label**

In `MainLayout.tsx`, change the `/inbox` nav label from `收件箱` to `审核台` (both in `NavList` and in the `navItems` array used by `CompactNav`). Route path stays `/inbox`.

- [ ] **Step 2: Update the navigation test**

If `main-layout-navigation.test.mjs` asserts the `收件箱` label, update it to `审核台`. Run:

```bash
node frontend/tests/main-layout-navigation.test.mjs
cd frontend && pnpm build
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/layouts/MainLayout.tsx frontend/tests/main-layout-navigation.test.mjs
git commit -m "feat(frontend): rename inbox nav to review station"
```

---

### Task 8: Final integration verification

- [ ] **Step 1: Run focused backend tests**

```bash
python -m pytest backend/tests/test_asset_items_service.py backend/tests/test_assets_api.py backend/tests/test_personal_asset_items_api.py backend/tests/test_asset_voice.py -v
```

Expected: PASS.

- [ ] **Step 2: Run focused engine tests**

```bash
python -m pytest engine/tests/test_capture_thought_tool.py engine/tests/test_asset_search_multiterm.py engine/tests/test_agent_tools.py -v
```

Expected: PASS.

- [ ] **Step 3: Run frontend build + tests**

```bash
node frontend/tests/chat-capture.test.mjs
node frontend/tests/main-layout-navigation.test.mjs
cd frontend && pnpm build
```

Expected: PASS.

- [ ] **Step 4: Runtime smoke (optional, requires approved `knowledge-system-full-*` stack)**

1. Open the chat page. In the input toolbar, the mic button is present.
2. Type `帮我记一下：下周一提交季度报告` and send.
3. The agent calls `capture_thought`; the thinking panel shows `记录想法`; the assistant reply includes a "去审核台确认" chip.
4. Open `/inbox` (审核台). The item appears at the top of `待确认碎片`, titled from the text.
5. Edit the item if desired, click `确认入库`; the item disappears from the list and appears under `/assets`.
6. Confirm the review station no longer shows the `添加碎片` form.

- [ ] **Step 5: Commit any verification-only fixture updates**

If tests require deterministic fixture changes, commit them. Do not create an empty commit.

---

## Self-Review

Spec coverage:

- Agent `capture_thought` tool, enabled by default: Task 3.
- Tool uses shared service with `use_llm=False` (fast, non-blocking): Tasks 1, 3.
- Review station = inbox page minus the capture form, renamed 审核台: Tasks 5, 7.
- Confirmation downstream unchanged (asset layer only): no task touches `confirm_asset_item` semantics; Task 2 keeps the API wrapper behavior.
- Voice capture moves to the chat page: Task 6.
- Capture independent of KB/session: Task 3 creates the item with no scope/session dependency.
- No auto-extraction, no dedup, no LLM-in-tool: captured as Non-Goals in the spec; no task implements them.

Red-flag wording scan:

- The shared service must stay FastAPI-free; Task 1 Step 3 states the constraint and the fallback (split imports) if a dependency pulls FastAPI.
- The API module re-imports helpers it still uses (Task 2 Step 1) to avoid breaking update/confirm endpoints.
- The engine tool test avoids LLM dependencies by using `use_llm=False`.

Type consistency:

- Service function name: `create_asset_item_from_raw`; param `use_llm: bool = True`.
- Tool name/key: `capture_thought`; `default_enabled=True`.
- Capture marker: `source_type="chat"`, `raw_metadata={"entrypoint": "chat_capture"}`.
- Frontend label: `capture_thought: '记录想法'`; nav label `审核台`; route stays `/inbox`.
