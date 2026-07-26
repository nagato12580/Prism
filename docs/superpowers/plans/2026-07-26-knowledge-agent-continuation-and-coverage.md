# Knowledge Agent Continuation and Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make forced synthesis retain the newest decisive evidence, make bare “继续” requests resume the original document objective and cursor, and make all-document questions report verified per-file coverage.

**Architecture:** Keep the five-open and ten-iteration limits unchanged. Add a small pure continuation-state module, carry its versioned state through the existing assistant `process` JSON, and make Runner clean synthesis consume an effective objective plus a recency-aware evidence selection. Extend `query_kb` with bounded per-file coverage that diversifies global hits and targets only missing files.

**Tech Stack:** Python 3, LangChain messages/tools, Pydantic, SQLAlchemy, FastAPI NDJSON streaming, React 18, TypeScript, Zustand, Node test runner, pytest.

---

## File Map

- Create `engine/app/agent/continuation.py`: validate continuation metadata, recognize bare continuation commands, resolve the effective objective, and build resume guidance.
- Modify `engine/app/agent/runner.py`: typed synthesis candidates, newest/final-batch evidence selection, resume guidance, stale-open correction, continuation event emission, and trace metadata.
- Modify `engine/app/agent/events.py`: public bounded `continuation` NDJSON event.
- Modify `engine/app/agent/tools/knowledge_base.py`: `next_offset`, coverage request/response contracts, per-file retrieval orchestration, and coverage paging.
- Modify `engine/app/chat/answer.py`: allow the governed retrieval service to receive an explicit `top_k`.
- Modify `engine/app/agent/knowledge_skill.py`: instruct all-document requests to use per-file coverage and prohibit unsupported completeness claims.
- Modify `frontend/src/app/chatStore.ts`: typed continuation state, restoration from `process`, and message update action.
- Modify `frontend/src/pages/ChatPage.tsx`: stream handling, history transport, and persistence in `process.agent_continuation`.
- Modify `engine/tests/test_agent_runner.py`: synthesis and end-to-end Runner regressions.
- Create `engine/tests/test_agent_continuation.py`: pure continuation-contract tests.
- Modify `engine/tests/test_knowledge_base_tools.py`: `next_offset` and coverage behavior.
- Modify `engine/tests/test_knowledge_skill.py`: coverage prompt contract.
- Modify `backend/tests/test_agent_chat_proxy.py`: public continuation history is forwarded unchanged without leaking scope data.
- Create `frontend/tests/chat-continuation-state.test.mjs`: frontend state, history, stream, and persistence wiring checks.

## Task 1: Add the Pure Continuation Contract

**Files:**
- Create: `engine/app/agent/continuation.py`
- Create: `engine/tests/test_agent_continuation.py`

- [ ] **Step 1: Write failing contract tests**

```python
from engine.app.agent.continuation import (
    AgentContinuation,
    continuation_from_history,
    is_bare_continuation,
    resolve_effective_objective,
)


STATE = {
    "version": 1,
    "objective": "层次锚定的超参数怎么设置？",
    "kb_uid": "kb-a",
    "file_uid": "file-a",
    "next_offset": 35766,
    "has_more_after": True,
}


def test_bare_continuation_allowlist_is_narrow():
    assert is_bare_continuation("继续")
    assert is_bare_continuation("继续读？")
    assert is_bare_continuation("接着读")
    assert not is_bare_continuation("继续找学习率并比较各数据集")


def test_latest_assistant_state_resolves_original_objective():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {"role": "assistant", "content": "是否继续？", "continuation": STATE},
    ]
    state = continuation_from_history(history)
    assert state == AgentContinuation(**STATE)
    assert resolve_effective_objective("继续", history, state) == STATE["objective"]


def test_only_latest_assistant_message_can_activate_state():
    history = [
        {"role": "assistant", "content": "旧回答", "continuation": STATE},
        {"role": "user", "content": "新问题"},
        {"role": "assistant", "content": "新回答"},
    ]
    assert continuation_from_history(history) is None


def test_invalid_state_falls_back_to_latest_substantive_user_question():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {"role": "assistant", "content": "是否继续？", "continuation": {"version": 99}},
    ]
    assert continuation_from_history(history) is None
    assert resolve_effective_objective("继续", history, None) == "层次锚定的超参数怎么设置？"


def test_substantive_query_supersedes_saved_state():
    state = AgentContinuation(**STATE)
    assert resolve_effective_objective("比较不同数据集的参数", [], state) == "比较不同数据集的参数"
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run:

```powershell
pytest engine/tests/test_agent_continuation.py -q
```

Expected: collection fails with `ModuleNotFoundError: engine.app.agent.continuation`.

- [ ] **Step 3: Implement the versioned, bounded contract**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


_BARE_CONTINUATION = re.compile(
    r"^\s*(继续|继续读|继续读取|接着读|往下读)[。.!！?？]?\s*$"
)


@dataclass(frozen=True)
class AgentContinuation:
    version: int
    objective: str
    kb_uid: str
    file_uid: str
    next_offset: int
    has_more_after: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_bare_continuation(query: str) -> bool:
    return bool(_BARE_CONTINUATION.fullmatch(query or ""))


def _parse_state(value: Any) -> AgentContinuation | None:
    if not isinstance(value, dict) or value.get("version") != 1:
        return None
    objective = value.get("objective")
    kb_uid = value.get("kb_uid")
    file_uid = value.get("file_uid")
    next_offset = value.get("next_offset")
    has_more_after = value.get("has_more_after")
    if not all(isinstance(item, str) and item.strip() for item in (objective, kb_uid, file_uid)):
        return None
    if not isinstance(next_offset, int) or isinstance(next_offset, bool) or next_offset < 0:
        return None
    if not isinstance(has_more_after, bool) or not has_more_after:
        return None
    return AgentContinuation(
        version=1,
        objective=objective.strip()[:8000],
        kb_uid=kb_uid.strip()[:128],
        file_uid=file_uid.strip()[:128],
        next_offset=next_offset,
        has_more_after=True,
    )


def continuation_from_history(history: list[dict[str, Any]]) -> AgentContinuation | None:
    if not history:
        return None
    latest = history[-1]
    if latest.get("role") != "assistant":
        return None
    return _parse_state(latest.get("continuation"))


def resolve_effective_objective(
    query: str,
    history: list[dict[str, Any]],
    continuation: AgentContinuation | None,
) -> str:
    if not is_bare_continuation(query):
        return query
    if continuation is not None:
        return continuation.objective
    for item in reversed(history):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content and not is_bare_continuation(content):
            return content
    return query
```

- [ ] **Step 4: Run the focused tests**

Run: `pytest engine/tests/test_agent_continuation.py -q`

Expected: `5 passed`.

- [ ] **Step 5: Commit the contract**

```powershell
git add engine/app/agent/continuation.py engine/tests/test_agent_continuation.py
git commit -m "feat(agent): define durable continuation state"
```

## Task 2: Replace First-12 Evidence Truncation with Final-Batch Selection

**Files:**
- Modify: `engine/app/agent/runner.py:120-253`
- Modify: `engine/tests/test_agent_runner.py:577-900`

- [ ] **Step 1: Add failing evidence-priority tests**

Add tests that construct production-shaped `ToolMessage` values directly:

```python
def _tool_message(call_id, data):
    return ToolMessage(
        content=json.dumps({"status": "success", "payload": {"summary": {"status": "ok", "data": data}}}),
        tool_call_id=call_id,
    )


def test_synthesis_selection_keeps_last_exact_match_after_ten_query_hits():
    messages = [
        _tool_message(
            "query-1",
            {"evidence": [{"file_uid": "file-a", "excerpt": f"old semantic hit {index}"} for index in range(10)]},
        ),
        _tool_message(
            "find-final",
            {"file_uid": "file-a", "matches": [{"line": 1652, "snippet": "Adam, initial learning rate 0.01"}]},
        ),
    ]
    selected = runner_mod._select_synthesis_evidence(
        messages,
        required_tool_call_ids={"find-final"},
    )
    assert any("learning rate 0.01" in item.text for item in selected)


def test_synthesis_selection_preserves_file_diversity_for_coverage_results():
    messages = [
        _tool_message(
            "coverage",
            {
                "coverage": {
                    "requested_file_uids": ["file-a", "file-b", "file-c"],
                    "covered_file_uids": ["file-a", "file-b", "file-c"],
                    "missing_file_uids": [],
                    "complete": True,
                },
                "evidence": [
                    {"file_uid": "file-a", "excerpt": "A1"},
                    {"file_uid": "file-a", "excerpt": "A2"},
                    {"file_uid": "file-b", "excerpt": "B1"},
                    {"file_uid": "file-c", "excerpt": "C1"},
                ],
            },
        )
    ]
    selected = runner_mod._select_synthesis_evidence(messages)
    first_files = [item.file_uid for item in selected[:3]]
    assert first_files == ["file-a", "file-b", "file-c"]
```

- [ ] **Step 2: Verify the old selector fails**

Run:

```powershell
pytest engine/tests/test_agent_runner.py -q -k "synthesis_selection"
```

Expected: failure because `_select_synthesis_evidence` does not exist.

- [ ] **Step 3: Add typed candidates and a character-budget selector**

In `runner.py`, add a frozen `SynthesisEvidence` dataclass with `text`, `kind`, `tool_call_id`, `file_uid`, and `result_index`. Replace `_tool_evidence_texts` internals with:

```python
SYNTHESIS_EVIDENCE_CHAR_BUDGET = 8400


@dataclass(frozen=True)
class SynthesisEvidence:
    text: str
    kind: str
    tool_call_id: str
    file_uid: str | None
    result_index: int


def _select_synthesis_evidence(
    messages: list[Any],
    *,
    required_tool_call_ids: set[str] | None = None,
    char_budget: int = SYNTHESIS_EVIDENCE_CHAR_BUDGET,
) -> list[SynthesisEvidence]:
    candidates = _synthesis_evidence_candidates(messages)
    required_ids = required_tool_call_ids or set()
    selected: list[SynthesisEvidence] = []
    selected_keys: set[str] = set()
    used_chars = 0

    def add(candidate: SynthesisEvidence) -> None:
        nonlocal used_chars
        key = re.sub(r"\s+", " ", candidate.text).strip()
        if not key or key in selected_keys:
            return
        if selected and used_chars + len(key) > char_budget:
            return
        selected.append(candidate)
        selected_keys.add(key)
        used_chars += len(key)

    for candidate in candidates:
        if candidate.tool_call_id in required_ids:
            add(candidate)

    for kind in ("match", "document"):
        for candidate in sorted(candidates, key=lambda item: item.result_index, reverse=True):
            if candidate.kind == kind:
                add(candidate)

    coverage_candidates = [candidate for candidate in candidates if candidate.kind == "coverage"]
    coverage_files: set[str] = set()
    for candidate in coverage_candidates:
        if candidate.file_uid and candidate.file_uid not in coverage_files:
            add(candidate)
            coverage_files.add(candidate.file_uid)

    for candidate in sorted(candidates, key=lambda item: item.result_index, reverse=True):
        add(candidate)
    return selected
```

Implement `_synthesis_evidence_candidates(messages)` by iterating `ToolMessage` objects in message order, normalizing their JSON with `_normalized_tool_result`, preserving list order inside each result, and assigning kinds as follows:

```python
kind_by_key = {
    "matches": "match",
    "evidence": "coverage" if isinstance(data.get("coverage"), dict) else "semantic",
    "sources": "semantic",
    "evidence_items": "semantic",
    "memories": "memory",
    "materials": "semantic",
}
```

Create document candidates from non-empty `data.content`. Bound each candidate to 700 characters exactly as the old collector did.

- [ ] **Step 4: Pass required final tool IDs into both clean synthesis paths**

Change `_document_cap_synthesis_messages` to accept `effective_query` and `required_tool_call_ids`. At the per-file cap pass the current `tool_call_id`. At global iteration exhaustion pass every ID in the just-executed `tool_calls` batch:

```python
required_ids = {
    str(_call_value(call, "id", ""))
    for call in tool_calls
    if _call_value(call, "id", "")
}
synthesis_messages = _document_cap_synthesis_messages(
    effective_query,
    messages,
    required_tool_call_ids=required_ids,
)
```

Make `_grounded_fallback_answer_from_messages` use `_select_synthesis_evidence` so deterministic fallback has the same priority.

- [ ] **Step 5: Run Runner tests**

Run: `pytest engine/tests/test_agent_runner.py -q`

Expected: all Runner tests pass, including the two new selector tests and the existing production-envelope tests.

- [ ] **Step 6: Commit the evidence repair**

```powershell
git add engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "fix(agent): retain decisive final evidence"
```

## Task 3: Expose an Exact Document Cursor

**Files:**
- Modify: `engine/app/agent/tools/knowledge_base.py:146-153,690-733`
- Modify: `engine/tests/test_knowledge_base_tools.py:230-278`

- [ ] **Step 1: Add failing full-window and tail-window assertions**

```python
def test_open_document_returns_exact_next_offset(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    tool = build_tools(_context(db_session))["open_kb_document"]
    first = tool.invoke({"kb_uid": "kb-a", "file_uid": "file-a", "offset": 0, "window_size": 12})
    tail = tool.invoke({"kb_uid": "kb-a", "file_uid": "file-a", "offset": 35, "window_size": 100})

    assert first["data"]["next_offset"] == 12
    assert tail["data"]["next_offset"] == len("alpha line\nneedle appears here\nomega line")
    assert tail["data"]["has_more_after"] is False
```

- [ ] **Step 2: Verify the contract fails before implementation**

Run: `pytest engine/tests/test_knowledge_base_tools.py -q -k next_offset`

Expected: `KeyError: 'next_offset'`.

- [ ] **Step 3: Add the field to the DTO and tool result**

```python
class OpenDocumentData(_StrictDTO):
    file_uid: str
    kb_uid: str
    offset: int
    next_offset: int
    window_size: int
    content: str
    has_more_before: bool
    has_more_after: bool
```

Populate it with `next_offset=end` in `_build_open_kb_document`.

- [ ] **Step 4: Run all knowledge-base tool tests**

Run: `pytest engine/tests/test_knowledge_base_tools.py -q`

Expected: all tests pass and existing path-safety assertions remain green.

- [ ] **Step 5: Commit the cursor contract**

```powershell
git add engine/app/agent/tools/knowledge_base.py engine/tests/test_knowledge_base_tools.py
git commit -m "feat(knowledge): expose document next offset"
```

## Task 4: Resume the Effective Objective and Emit Continuation State

**Files:**
- Modify: `engine/app/agent/events.py:1-110`
- Modify: `engine/app/agent/runner.py:14-25,480-948`
- Modify: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Add failing end-to-end Runner tests**

Add a model fixture that opens the same production-shaped document five times, captures the clean synthesis messages, and returns a natural-language answer. Assert:

```python
def test_open_cap_emits_continuation_for_effective_hyperparameter_objective():
    history = [
        {"role": "user", "content": "层次锚定的超参数怎么设置？"},
        {
            "role": "assistant",
            "content": "是否继续？",
            "continuation": {
                "version": 1,
                "objective": "层次锚定的超参数怎么设置？",
                "kb_uid": "kb-a",
                "file_uid": "file-a",
                "next_offset": 5000,
                "has_more_after": True,
            },
        },
    ]
    events = list(runner.stream("继续", history))
    payloads = [json.loads(line) for line in events]
    continuation = next(item["data"] for item in payloads if item["type"] == "continuation")
    assert continuation["objective"] == "层次锚定的超参数怎么设置？"
    assert continuation["next_offset"] > 5000
    assert "用户问题：层次锚定的超参数怎么设置？" in synthesis_model.last_messages[1].content


def test_resume_rewrites_stale_beginning_open_to_saved_offset():
    list(runner.stream("继续", history))
    assert open_tool.calls[0]["file_uid"] == "file-a"
    assert open_tool.calls[0]["offset"] == 5000
    assert "line" not in open_tool.calls[0]


def test_explicit_exact_line_after_find_is_not_rewritten():
    list(runner.stream("继续", history))
    assert open_tool.calls[0]["line"] == 1652
```

Also assert the forced answer says “5 个窗口” and does not contain “第5页”.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
pytest engine/tests/test_agent_runner.py -q -k "continuation or resume_rewrites or exact_line"
```

Expected: failures because no continuation event or effective-objective wiring exists.

- [ ] **Step 3: Add the bounded stream event**

In `events.py`:

```python
def continuation_event(state: dict[str, Any]) -> str:
    allowed = {
        "version": state.get("version"),
        "objective": state.get("objective"),
        "kb_uid": state.get("kb_uid"),
        "file_uid": state.get("file_uid"),
        "next_offset": state.get("next_offset"),
        "has_more_after": state.get("has_more_after"),
    }
    return ndjson_event("continuation", allowed)
```

- [ ] **Step 4: Resolve state and objective once per Runner request**

At the start of `stream`:

```python
resume_state = continuation_from_history(history)
effective_query = resolve_effective_objective(query, history, resume_state)
self._resume_state = resume_state if is_bare_continuation(query) else None
self._resume_consumed = False
messages = self._build_messages(query, history)
if self._resume_state is not None:
    messages.append(SystemMessage(content=(
        "This is a document continuation. Continue answering this objective: "
        f"{effective_query}. Resume file {self._resume_state.file_uid} at offset "
        f"{self._resume_state.next_offset}. Do not restart at the beginning."
    )))
```

Record `effective_objective_source` in trace input as `current`, `continuation_state`, or `history_fallback`.

- [ ] **Step 5: Correct only stale restart-style open arguments**

Before `_invoke_tool`, add a helper that applies once:

```python
def _apply_resume_to_open_args(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
    state = self._resume_state
    if name != "open_kb_document" or state is None or self._resume_consumed:
        return args
    candidate = dict(args)
    file_uid = str(candidate.get("file_uid") or "")
    line = candidate.get("line")
    offset = candidate.get("offset")
    is_stale_restart = line in (None, 1) and (offset is None or offset < state.next_offset)
    if file_uid not in ("", state.file_uid) or not is_stale_restart:
        return args
    candidate["kb_uid"] = state.kb_uid
    candidate["file_uid"] = state.file_uid
    candidate["offset"] = state.next_offset
    candidate.pop("line", None)
    self._resume_consumed = True
    return candidate
```

An explicit line greater than one remains untouched so a `find_kb_document` result can jump directly to the matching hyperparameter paragraph.

- [ ] **Step 6: Build and emit the next state at the five-open cap**

Track normalized successful document windows by file. Build the state from the greatest `next_offset` reached for the capped file, not from a backward window:

```python
furthest_window = max(file_windows, key=lambda item: item["next_offset"])
continuation = AgentContinuation(
    version=1,
    objective=effective_query,
    kb_uid=str(furthest_window["kb_uid"]),
    file_uid=str(furthest_window["file_uid"]),
    next_offset=int(furthest_window["next_offset"]),
    has_more_after=bool(furthest_window["has_more_after"]),
)
```

Emit `continuation_event(continuation.to_dict())` immediately before `done_event()` only when `has_more_after` is true. Use `effective_query` in both forced-synthesis branches.

- [ ] **Step 7: Run the complete Runner and continuation tests**

Run:

```powershell
pytest engine/tests/test_agent_continuation.py engine/tests/test_agent_runner.py -q
```

Expected: all tests pass; the existing five-open and final-iteration behaviors remain unchanged.

- [ ] **Step 8: Commit Runner continuation**

```powershell
git add engine/app/agent/events.py engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "feat(agent): resume capped document reads"
```

## Task 5: Persist and Return Continuation State in Chat History

**Files:**
- Modify: `frontend/src/app/chatStore.ts:84-120,232-257,339-430`
- Modify: `frontend/src/pages/ChatPage.tsx:184-203,370-373,462-511,589-612`
- Create: `frontend/tests/chat-continuation-state.test.mjs`
- Modify: `backend/tests/test_agent_chat_proxy.py`

- [ ] **Step 1: Add failing frontend contract checks**

```javascript
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const store = readFileSync(resolve(root, 'src/app/chatStore.ts'), 'utf8')
const page = readFileSync(resolve(root, 'src/pages/ChatPage.tsx'), 'utf8')

assert.match(store, /export interface AgentContinuation/)
assert.match(store, /agentContinuation\?: AgentContinuation/)
assert.match(store, /process\?\.agent_continuation/)
assert.match(store, /setLastContinuation/)
assert.match(page, /msg\.type === 'continuation'/)
assert.match(page, /agent_continuation:\s*message\.agentContinuation \|\| null/)
assert.match(page, /continuation:\s*m\.agentContinuation/)
```

- [ ] **Step 2: Add a failing backend forwarding test**

```python
def test_backend_proxy_forwards_public_continuation_history(client, db_session, monkeypatch):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    captured = {}

    async def fake_stream(_signed_token, payload):
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)
    continuation = {
        "version": 1,
        "objective": "参数是多少",
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "next_offset": 5000,
        "has_more_after": True,
    }
    response = client.post(
        "/api/v1/chat/answer",
        json={
            "query": "继续",
            "kb_uids": ["kb-a"],
            "history": [{"role": "assistant", "content": "继续？", "continuation": continuation}],
        },
    )
    assert response.status_code == 200
    assert captured["payload"]["history"][0]["continuation"] == continuation
    assert "tenant_id" not in str(captured["payload"])
```

- [ ] **Step 3: Verify the frontend test fails and proxy test already preserves public history**

Run:

```powershell
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend test
pytest backend/tests/test_agent_chat_proxy.py -q
```

Expected: the new frontend regex test fails; the backend forwarding test passes without a backend production-code change.

- [ ] **Step 4: Add typed Zustand state and restoration**

In `chatStore.ts`:

```typescript
export interface AgentContinuation {
  version: 1
  objective: string
  kb_uid: string
  file_uid: string
  next_offset: number
  has_more_after: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  agentContinuation?: AgentContinuation
}
```

Keep the existing `Message` fields, add `setLastContinuation` to `ChatState`, restore a validated object from `process?.agent_continuation` in `toMessages`, and implement the action with `replaceMessage`.

- [ ] **Step 5: Handle stream events, history, and persistence**

In `ChatPage.tsx`, add continuation to process snapshots:

```typescript
function buildAssistantProcess(message: Message) {
  return {
    trace_id: message.traceId || null,
    agent_status: message.agentStatus || null,
    tool_runs: message.toolRuns || [],
    thinking_steps: message.thinkingSteps || [],
    agent_continuation: message.agentContinuation || null,
  }
}
```

Build history with metadata only on the latest assistant message. The project targets ES2020, so find the index with a reverse loop instead of `Array.findLastIndex`:

```typescript
let latestAssistantIndex = -1
for (let index = messages.length - 1; index >= 0; index -= 1) {
  if (messages[index]?.role === 'assistant') {
    latestAssistantIndex = index
    break
  }
}
const history = messages
  .filter((message) => !message.streaming)
  .map((message, index) => ({
    role: message.role,
    content: historyContent(message),
    ...(index === latestAssistantIndex && message.agentContinuation
      ? { continuation: message.agentContinuation }
      : {}),
  }))
```

Handle the event before `done`:

```typescript
} else if (msg.type === 'continuation') {
  setLastContinuation(msg.data, sessionId, assistantMessageId)
  if (assistantPersistedId) queueAssistantProcessSnapshot(sessionId, assistantPersistedId)
```

- [ ] **Step 6: Run frontend tests and TypeScript build**

Run:

```powershell
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend test
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend build
```

Expected: all Node tests pass and the TypeScript/Vite build exits with code 0.

- [ ] **Step 7: Commit the transport and persistence wiring**

```powershell
git add frontend/src/app/chatStore.ts frontend/src/pages/ChatPage.tsx frontend/tests/chat-continuation-state.test.mjs backend/tests/test_agent_chat_proxy.py
git commit -m "feat(chat): persist agent continuation state"
```

## Task 6: Add Bounded Per-File Coverage to `query_kb`

**Files:**
- Modify: `engine/app/agent/tools/knowledge_base.py:105-181,495-559`
- Modify: `engine/app/chat/answer.py:18-75`
- Modify: `engine/app/agent/knowledge_skill.py:13-36`
- Modify: `engine/tests/test_knowledge_base_tools.py`
- Modify: `engine/tests/test_knowledge_skill.py`

- [ ] **Step 1: Add failing coverage tests with duplicate global hits**

Extend the fake retrieval service so `top_k>1` returns duplicate hits from `file-a`, while targeted calls return one hit for the requested file. Seed 11 files and assert:

```python
def test_query_kb_per_file_coverage_returns_all_eleven_files(db_session):
    _seed_eleven_files(db_session)
    ctx = _coverage_context(db_session)
    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "总结所有论文的核心观点",
        "coverage": "per_file",
    })

    coverage = result["data"]["coverage"]
    assert coverage["complete"] is True
    assert len(coverage["requested_file_uids"]) == 11
    assert len(coverage["covered_file_uids"]) == 11
    assert coverage["missing_file_uids"] == []
    assert {item["file_uid"] for item in result["data"]["evidence"]} == {
        f"file-{index:02d}" for index in range(11)
    }
```

Add tests that normal relevance mode makes one call with `top_k=10`, targeted calls happen only for missing files, an unavailable file appears in `missing_file_uids`, and 31 files return 30 requested IDs plus a non-empty `next_cursor`.

- [ ] **Step 2: Add a failing prompt contract**

```python
def test_knowledge_skill_requires_per_file_coverage_for_all_document_requests():
    from engine.app.agent.knowledge_skill import render_knowledge_skill

    prompt = render_knowledge_skill()
    assert 'coverage="per_file"' in prompt
    assert "missing_file_uids" in prompt
    assert "complete" in prompt
```

- [ ] **Step 3: Verify focused tests fail**

Run:

```powershell
pytest engine/tests/test_knowledge_base_tools.py engine/tests/test_knowledge_skill.py -q -k "coverage or all_document"
```

Expected: schema rejects `coverage` and the prompt lacks the required instruction.

- [ ] **Step 4: Extend the retrieval-service adapter with explicit `top_k`**

In `answer.py`, import `RetrievalOverrides`, add `top_k: int = 10` to `_KnowledgeRetrievalService.query`, and construct:

```python
request = RetrievalRequest(
    query=query,
    mode="deep" if mode == "deep" else "fast",
    filters={"file_uids": tuple(file_uids), "source_types": ()},
    config=RetrievalOverrides(top_k=top_k),
)
```

- [ ] **Step 5: Add typed coverage input and output contracts**

```python
class QueryCoverage(_StrictDTO):
    requested_file_uids: list[str] = Field(default_factory=list)
    covered_file_uids: list[str] = Field(default_factory=list)
    missing_file_uids: list[str] = Field(default_factory=list)
    complete: bool = False
    next_cursor: str | None = None


class QueryKbData(_StrictDTO):
    evidence: list[EvidenceItem] = Field(default_factory=list)
    retrieval_health: dict[str, Any] = Field(default_factory=dict)
    coverage: QueryCoverage | None = None


class QueryKbInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_uid: str | None = Field(default=None, min_length=1, max_length=128)
    query_text: str = Field(min_length=1, max_length=4000)
    mode: Literal["standard", "deep"] = "standard"
    file_filter: tuple[str, ...] = Field(default=(), max_length=100)
    coverage: Literal["relevance", "per_file"] = "relevance"
    coverage_cursor: str | None = Field(default=None, min_length=1, max_length=512)
```

- [ ] **Step 6: Implement stable, paged coverage orchestration**

For `coverage="per_file"`, resolve at most 30 authorized, non-deleted files after the optional cursor, including unparsed or retrieval-unavailable files so they cannot disappear from the denominator. Make one global call with `top_k=min(100, max(10, len(targets) * 2))`. Keep the highest-ranked evidence per file first. For each missing file, make a fast targeted call with `file_uids=(file_uid,)` and `top_k=1`; files without a retrievable indexed chunk remain explicit missing entries.

Merge warnings and retrieval health without aborting successful files. Construct `QueryCoverage` from the stable target order. Set `complete` only when there are no missing files and no next cursor. Relevance mode must retain its current single-call behavior and response shape except for `coverage=None`.

Use the existing `_encode_cursor` and `_decode_cursor` helpers with the last requested `file_uid`; do not accept raw offsets or database IDs from callers.

- [ ] **Step 7: Add model guidance for exhaustive requests**

Append to the knowledge skill policy:

```text
- When the user asks about all files, every paper, or the complete uploaded collection, call query_kb with coverage="per_file". Report covered/total and inspect coverage.missing_file_uids. Claim complete coverage only when coverage.complete is true; use coverage_cursor when another page is returned.
```

- [ ] **Step 8: Run knowledge-tool, skill, and answer-adapter tests**

Run:

```powershell
pytest engine/tests/test_knowledge_base_tools.py engine/tests/test_knowledge_skill.py engine/tests/test_answer_stream_agent.py -q
```

Expected: all tests pass, including 11-file coverage and unchanged relevance behavior.

- [ ] **Step 9: Commit coverage retrieval**

```powershell
git add engine/app/agent/tools/knowledge_base.py engine/app/chat/answer.py engine/app/agent/knowledge_skill.py engine/tests/test_knowledge_base_tools.py engine/tests/test_knowledge_skill.py
git commit -m "feat(knowledge): guarantee per-file query coverage"
```

## Task 7: Cross-Layer Regression, Trace Verification, and Runtime Handoff

**Files:**
- Modify: `engine/tests/test_agent_runner.py`
- Modify: `docs/superpowers/plans/2026-07-26-knowledge-agent-continuation-and-coverage.md` only to check completed boxes during execution

- [ ] **Step 1: Add one trace-shaped regression scenario**

Create a Runner fixture reproducing the critical order: 10 semantic evidence items, an exact hyperparameter match, a final document open, and a five-open stop. Assert the final answer model receives:

```python
assert "层次锚定的超参数怎么设置？" in synthesis_prompt
assert "Adam" in synthesis_prompt
assert "0.01" in synthesis_prompt
assert "file-a" in continuation_event_payload["file_uid"]
assert continuation_event_payload["next_offset"] > initial_resume_offset
```

Add a second request using the emitted state and assert its first stale restart open is rewritten to the emitted cursor.

- [ ] **Step 2: Run all focused suites**

```powershell
pytest engine/tests/test_agent_continuation.py engine/tests/test_agent_runner.py engine/tests/test_knowledge_base_tools.py engine/tests/test_knowledge_skill.py engine/tests/test_answer_stream_agent.py -q
pytest backend/tests/test_agent_chat_proxy.py backend/tests/test_chat_api.py -q
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend test
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend build
```

Expected: every command exits with code 0.

- [ ] **Step 3: Run the complete Engine test suite**

Run: `pytest engine/tests -q`

Expected: all Engine tests pass with no new failure or iteration-limit error.

- [ ] **Step 4: Inspect the final diff and worktree**

```powershell
git diff --check
git status --short
git log --oneline -8
```

Expected: `git diff --check` emits no output; only intentional uncommitted checklist updates may remain.

- [ ] **Step 5: Restart the three local services from this worktree**

Start each command in its own PowerShell process from the worktree:

```powershell
python -m engine.run
$env:SKIP_ENGINE='1'; python -m backend.run
E:\nvm\nvm\v21.5.0\node_global\pnpm.cmd --dir frontend dev -- --host 127.0.0.1 --port 5173
```

Verify:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5175/health | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5180/health | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173 | Select-Object StatusCode
```

Expected: all three status codes are 200.

- [ ] **Step 6: Manually replay the reported conversation**

In the frontend:

1. Ask `总结我上传资料里的核心观点` and verify the answer reports `11/11` covered documents or explicitly names any unavailable file.
2. Ask `层次锚定的超参数怎么设置？` and verify any already-found settings such as Adam and 0.01 appear in the first capped answer.
3. Send `继续` twice and verify each trace retains the hyperparameter objective and advances `next_offset` instead of returning to offset 0.
4. Export the session trace and confirm `forced_final_after_open_limit` includes the last exact match/open evidence and contains no unsupported “第5页” claim.

- [ ] **Step 7: Commit the final regression test**

```powershell
git add engine/tests/test_agent_runner.py
git commit -m "test(agent): cover trace continuation regressions"
```

## Completion Criteria

- The five-open limit and global iteration limit remain unchanged.
- The last tool batch is represented in clean synthesis even after 10 earlier evidence records.
- Bare “继续” resolves to the prior substantive objective and resumes a persisted cursor.
- Continuation state survives page reload and service restart through `ChatMessage.process`.
- All-document retrieval reports explicit coverage and covers all 11 retrievable files in the reported knowledge base.
- No answer equates five document windows with five pages without real page metadata.
- Focused backend/frontend tests, frontend build, full Engine tests, health checks, and manual trace replay all pass.
