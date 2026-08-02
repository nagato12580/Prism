# Knowledge Base Selection Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Prism detects a knowledge-base question but no knowledge base is selected or authorized, return a structured `needs_kb_selection` event and let the frontend prompt the user to choose a knowledge base instead of exposing internal tool-scope errors.

**Architecture:** Keep the existing backend authorization model unchanged. Add the primary preflight in Engine after intent classification and before Agent/tool execution; add frontend handling for the new stream event plus a light client-side precheck for obvious document/knowledge queries.

**Tech Stack:** FastAPI streaming proxy, Engine NDJSON chat stream, Python event helpers, React/TypeScript ChatPage state and stream handling.

## Global Constraints

- Do not weaken or bypass the existing signed knowledge-scope authorization model.
- Keep `_require_scope()` / knowledge tool authorization checks as the final safety boundary.
- Do not move intent classification into Backend for v1.
- Do not expose `authorized knowledge scope is not configured` to users in this scenario.
- First version supports selecting a knowledge base and rerunning the original query; “仅基于当前对话回答” is out of scope.

---

## File Structure

- Modify `engine/app/agent/events.py`: add a reusable NDJSON event helper for `needs_kb_selection`.
- Modify `engine/app/chat/answer.py`: add the knowledge-intent/no-scope preflight before runner construction.
- Modify `frontend/src/pages/ChatPage.tsx`: handle the new stream event, store a pending query, open the knowledge-base selector, and rerun after selection.
- Modify or add tests under `engine/tests/` for Engine preflight behavior.
- Modify or add frontend tests if the current test harness covers ChatPage stream handling.

---

### Task 1: Add Engine `needs_kb_selection` Event

**Files:**
- Modify: `engine/app/agent/events.py`
- Test: existing Engine tests can import the helper directly or assert stream output in Task 2.

**Interfaces:**
- Produces: `needs_kb_selection_event(query: str, reasoning: str = "") -> str`
- Event shape:

```json
{
  "type": "needs_kb_selection",
  "data": {
    "message": "这个问题需要访问资料，但当前还没有选择知识库。请选择知识库后我再继续回答。",
    "pending_query": "<original user query>",
    "reasoning": "<intent classifier reasoning>"
  }
}
```

- [ ] Add the event helper in `engine/app/agent/events.py`.

```python
def needs_kb_selection_event(query: str, reasoning: str = "") -> str:
    return json.dumps(
        {
            "type": "needs_kb_selection",
            "data": {
                "message": "这个问题需要访问资料，但当前还没有选择知识库。请选择知识库后我再继续回答。",
                "pending_query": query,
                "reasoning": reasoning,
            },
        },
        ensure_ascii=False,
    ) + "\n"
```

- [ ] If `events.py` does not already import `json`, add it.

- [ ] Run a focused import check.

```bash
python - <<'PY'
from engine.app.agent.events import needs_kb_selection_event
print(needs_kb_selection_event("总结上传资料的核心观点"))
PY
```

Expected: one NDJSON line with `type` equal to `needs_kb_selection`.

---

### Task 2: Add Engine Preflight After Intent Classification

**Files:**
- Modify: `engine/app/chat/answer.py`
- Test: `engine/tests/test_answer_stream_agent.py` or a nearby existing answer-stream test file.

**Interfaces:**
- Consumes: `needs_kb_selection_event(query, reasoning)` from Task 1.
- Behavior: in `answer_stream()`, if intent groups include `knowledge`, no `knowledge_scope` is present, and no legacy `topic_id` exists, yield the event and return before building the runner.

- [ ] Write a failing test for knowledge intent with no scope and no topic.

```python
def test_answer_stream_returns_needs_kb_selection_for_knowledge_intent_without_scope(monkeypatch):
    from engine.app.chat import answer as answer_mod

    monkeypatch.setattr(
        answer_mod,
        "classify_intent",
        lambda query, history=None: {
            "groups": ["knowledge"],
            "kb_specs": [],
            "reasoning": "用户要求总结上传资料，需要知识库。",
        },
    )

    def fail_build_agent_runner(**kwargs):
        raise AssertionError("runner should not be built when KB selection is required")

    monkeypatch.setattr(answer_mod, "build_agent_runner", fail_build_agent_runner)

    events = list(answer_mod.answer_stream("总结上传资料的核心观点", history=[]))

    assert len(events) == 1
    assert '"type": "needs_kb_selection"' in events[0]
    assert "总结上传资料的核心观点" in events[0]
```

- [ ] Run the failing test.

```bash
pytest engine/tests/test_answer_stream_agent.py::test_answer_stream_returns_needs_kb_selection_for_knowledge_intent_without_scope -q
```

Expected: FAIL before implementation.

- [ ] Implement the preflight in `answer_stream()` after:

```python
has_knowledge = "knowledge" in tool_groups
```

Add:

```python
if has_knowledge and knowledge_scope is None and not topic_id:
    from ..agent.events import needs_kb_selection_event

    yield needs_kb_selection_event(query, intent.get("reasoning", ""))
    return
```

- [ ] Run the focused test again.

```bash
pytest engine/tests/test_answer_stream_agent.py::test_answer_stream_returns_needs_kb_selection_for_knowledge_intent_without_scope -q
```

Expected: PASS.

- [ ] Add regression tests for non-intercept cases.

```python
def test_answer_stream_does_not_request_kb_selection_for_non_knowledge_intent(monkeypatch):
    from engine.app.chat import answer as answer_mod

    monkeypatch.setattr(
        answer_mod,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "普通聊天"},
    )

    class FakeRunner:
        def stream(self, query, history, trace_recorder=None):
            yield '{"type":"delta","data":"你好"}\n'

    monkeypatch.setattr(answer_mod, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer_mod.AgentTraceRecorder, "start", lambda self: None)

    events = list(answer_mod.answer_stream("你好", history=[]))

    assert not any("needs_kb_selection" in event for event in events)
```

```python
def test_answer_stream_keeps_legacy_topic_fallback_for_knowledge_intent(monkeypatch):
    from engine.app.chat import answer as answer_mod

    monkeypatch.setattr(
        answer_mod,
        "classify_intent",
        lambda query, history=None: {"groups": ["knowledge"], "kb_specs": [], "reasoning": "知识库问题"},
    )

    class FakeRunner:
        def stream(self, query, history, trace_recorder=None):
            yield '{"type":"delta","data":"ok"}\n'

    monkeypatch.setattr(answer_mod, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer_mod.AgentTraceRecorder, "start", lambda self: None)
    monkeypatch.setattr(answer_mod, "_resolve_scope_for_topic", lambda topic_id: None)

    events = list(answer_mod.answer_stream("总结资料", history=[], topic_id="legacy-topic"))

    assert not any("needs_kb_selection" in event for event in events)
```

- [ ] Run the answer stream test file.

```bash
pytest engine/tests/test_answer_stream_agent.py -q
```

Expected: PASS.

---

### Task 3: Handle `needs_kb_selection` in ChatPage

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

**Interfaces:**
- Consumes stream event `type: "needs_kb_selection"`.
- Produces local state:
  - `kbSelectorOpen: boolean`
  - `pendingKbQuery: string | null`
- Extends send logic to allow overriding selected KB ids for automatic rerun.

- [ ] Add state near existing ChatPage state declarations.

```ts
const [kbSelectorOpen, setKbSelectorOpen] = useState(false)
const [pendingKbQuery, setPendingKbQuery] = useState<string | null>(null)
```

- [ ] Extend the send-message function signature to support KB override.

Use the existing function name in `ChatPage.tsx`; if it is currently `sendMessage(query)`, change it to:

```ts
async function sendMessage(
  content: string,
  options?: { overrideKbUids?: string[] }
) {
  const effectiveTopicIds = options?.overrideKbUids ?? selectedTopicIds
  // keep the existing body unchanged after replacing the original
  // effectiveTopicIds assignment
}
```

- [ ] Add a stream-event branch in `handleStreamLine`.

```ts
else if (msg.type === 'needs_kb_selection') {
  await flushTypewriterText()

  const data = msg.data || {}
  const nextPendingQuery = safeString(data.pending_query) || query
  const message =
    safeString(data.message) ||
    '这个问题需要访问资料，但当前还没有选择知识库。请选择知识库后我再继续回答。'

  setPendingKbQuery(nextPendingQuery)
  setKbSelectorOpen(true)

  appendToLast(message, sessionId, assistantMessageId)
  finishLast(sessionId, assistantMessageId, 'success')
  return
}
```

- [ ] Wire the existing knowledge-base selector UI so it can also open from `kbSelectorOpen`.

If ChatPage already has an inline dropdown/popover for selecting `selectedTopicIds`, reuse that component/state. If there is no reusable component, add a small dialog using the current topic list already loaded by ChatPage.

- [ ] Add a selection handler for pending query rerun.

```ts
async function handleKnowledgeSelectionForPendingQuery(kbUids: string[], names: string[]) {
  setSelectedTopics(kbUids, names)
  setKbSelectorOpen(false)

  if (!pendingKbQuery) return
  const queryToResume = pendingKbQuery
  setPendingKbQuery(null)
  await sendMessage(queryToResume, { overrideKbUids: kbUids })
}
```

- [ ] Ensure canceling the selector clears only the dialog state, not the original chat messages.

```ts
function cancelKbSelection() {
  setKbSelectorOpen(false)
  setPendingKbQuery(null)
}
```

- [ ] Manually test in browser:
  - send `总结上传资料的核心观点` with no selected KB;
  - confirm selector opens;
  - choose a KB;
  - confirm the same query reruns with `kb_uids` populated.

---

### Task 4: Add Frontend Send-Time Light Precheck

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

**Interfaces:**
- Produces: `mayNeedKnowledge(query: string): boolean`
- Behavior: when no KB is selected and personal inbox is not included, obvious document/knowledge queries open the selector before calling `/api/v1/chat/answer`.

- [ ] Add a helper near other ChatPage helpers.

```ts
function mayNeedKnowledge(query: string) {
  const q = query.trim().toLowerCase()
  return [
    '上传资料',
    '上传的资料',
    '文档',
    '知识库',
    '资料里',
    '根据资料',
    '总结资料',
    '总结上传',
    'pdf',
    '论文',
    '这篇',
    '这份',
  ].some((kw) => q.includes(kw))
}
```

- [ ] Add the precheck at the start of the send path after trimming/empty-message validation but before creating the fetch request.

```ts
if (
  selectedTopicIds.length === 0 &&
  !includePersonalInbox &&
  mayNeedKnowledge(query)
) {
  setPendingKbQuery(query)
  setKbSelectorOpen(true)
  return
}
```

- [ ] Verify ordinary chat is not blocked:
  - `你好` should still call `/api/v1/chat/answer`;
  - `总结上传资料的核心观点` should open the selector without fetch.

---

### Task 5: Verification and Acceptance

**Files:**
- No production files unless tests reveal necessary corrections.

**Acceptance Criteria:**
- Users no longer see `authorized knowledge scope is not configured` for knowledge questions sent without a selected KB.
- Engine returns `needs_kb_selection` before Agent/tool execution for knowledge intent without scope.
- Existing authorized KB chat still works.
- Existing legacy `topic_id` fallback still works.
- Frontend can rerun the original query after KB selection.

- [ ] Run Engine focused tests.

```bash
pytest engine/tests/test_answer_stream_agent.py -q
```

- [ ] Run any existing frontend test that covers ChatPage or chat payload behavior.

```bash
cd frontend
npm test -- --runInBand
```

If the project does not have `npm test`, run the repository’s existing frontend verification command from `package.json`.

- [ ] Run manual acceptance:

```text
Case 1:
No KB selected → ask “总结上传资料的核心观点”
Expected: KB selector prompt, no internal scope error.

Case 2:
Select KB from prompt.
Expected: original query reruns and request payload includes selected kb_uids.

Case 3:
KB already selected → ask same question.
Expected: normal KB retrieval/answer flow.

Case 4:
No KB selected → ask “你好”.
Expected: normal chat answer, no selector.
```

- [ ] Commit after all checks pass.

```bash
git add engine/app/agent/events.py engine/app/chat/answer.py frontend/src/pages/ChatPage.tsx engine/tests/test_answer_stream_agent.py
git commit -m "feat: prompt for knowledge base selection before kb tool use"
```
