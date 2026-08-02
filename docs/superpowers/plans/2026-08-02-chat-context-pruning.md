# Chat Context Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add context-aware intent classification and dynamic agent loop history pruning so long chat sessions avoid unbounded model context while preserving recent conversation and continuation behavior.

**Architecture:** Keep the frontend protocol unchanged. Add small backend helpers for recent-turn slicing and token estimation, update `classify_intent` to consume recent history, and make `LangChainAgentRunner._build_messages()` switch between full history and compressed history based on estimated context size.

**Tech Stack:** Python, FastAPI engine layer, LangChain message classes, pytest, existing `engine.app.llm.client.chat` wrapper.

---

## File Structure

- Modify `engine/app/config.py`: add context pruning settings with environment variable overrides.
- Modify `engine/app/chat/answer.py`: add recent-turn slicing for intent classification and update the classify prompt/input.
- Modify `engine/app/agent/runner.py`: add context token estimation, loop history preparation, older-history summarization, and compressed message assembly.
- Modify `engine/tests/test_answer_stream_agent.py`: cover intent recent-history behavior and delegation.
- Modify `engine/tests/test_agent_runner.py`: cover full mode, compressed mode, continuation preservation, and summary failure fallback.
- Optionally modify `engine/tests/test_graph_insights.py` only if existing `_build_messages()` assertions need adapting to extra system messages.

The first implementation should not change frontend request shape or database schema. Summary caching can stay runner-local for this pass; persistent session-level summary can be a later feature.

## Task 1: Add Configuration

**Files:**
- Modify: `engine/app/config.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Add configuration fields**

In `engine/app/config.py`, add these settings near `AGENT_TOOL_TIMEOUT_SECONDS`:

```python
    INTENT_RECENT_TURNS: int = int(os.getenv("INTENT_RECENT_TURNS", "5"))
    LOOP_RECENT_TURNS: int = int(os.getenv("LOOP_RECENT_TURNS", "10"))
    MIN_LOOP_RECENT_TURNS: int = int(os.getenv("MIN_LOOP_RECENT_TURNS", "6"))
    CONTEXT_COMPRESSION_THRESHOLD: float = float(os.getenv("CONTEXT_COMPRESSION_THRESHOLD", "0.8"))
    MAX_SUMMARY_TOKENS: int = int(os.getenv("MAX_SUMMARY_TOKENS", "1200"))
    DEFAULT_MAX_CONTEXT_TOKENS: int = int(os.getenv("DEFAULT_MAX_CONTEXT_TOKENS", "32000"))
```

- [ ] **Step 2: Run a config import smoke test**

Run:

```powershell
python -c "from engine.app.config import settings; print(settings.INTENT_RECENT_TURNS, settings.LOOP_RECENT_TURNS, settings.DEFAULT_MAX_CONTEXT_TOKENS)"
```

Expected: prints `5 10 32000`.

- [ ] **Step 3: Commit**

```powershell
git add engine/app/config.py
git commit -m "feat: add chat context pruning settings"
```

## Task 2: Add Recent Turn Slicing For Intent

**Files:**
- Modify: `engine/app/chat/answer.py`
- Test: `engine/tests/test_answer_stream_agent.py`

- [ ] **Step 1: Write failing tests for recent-history slicing**

Add tests near the existing `test_answer_stream_delegates_to_agent_runner` tests in `engine/tests/test_answer_stream_agent.py`:

```python
def test_answer_stream_classifies_with_recent_five_turns(monkeypatch):
    captured = {}

    def fake_classify(query, history=None):
        captured["query"] = query
        captured["history"] = history
        return {"groups": [], "kb_specs": [], "reasoning": "ok"}

    history = []
    for index in range(1, 8):
        history.append({"role": "user", "content": f"user {index}"})
        history.append({"role": "assistant", "content": f"assistant {index}"})

    monkeypatch.setattr(answer, "classify_intent", fake_classify)
    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: FakeRunner())
    monkeypatch.setattr(answer.AgentTraceRecorder, "start", lambda self: None)

    list(answer.answer_stream("这些方法的出处呢", history=history))

    assert captured["query"] == "这些方法的出处呢"
    assert [item["content"] for item in captured["history"]] == [
        "user 3",
        "assistant 3",
        "user 4",
        "assistant 4",
        "user 5",
        "assistant 5",
        "user 6",
        "assistant 6",
        "user 7",
        "assistant 7",
    ]


def test_answer_stream_keeps_runner_full_history_when_intent_uses_recent_history(monkeypatch):
    captured = {}

    history = [
        {"role": "user", "content": "old user"},
        {"role": "assistant", "content": "old assistant"},
    ]

    monkeypatch.setattr(
        answer,
        "classify_intent",
        lambda query, history=None: {"groups": [], "kb_specs": [], "reasoning": "ok"},
    )

    class CapturingHistoryRunner:
        def stream(self, query, history, trace_recorder=None):
            captured["history"] = history
            yield json.dumps({"type": "done"}) + "\n"

    monkeypatch.setattr(answer, "build_agent_runner", lambda **kwargs: CapturingHistoryRunner())
    monkeypatch.setattr(answer.AgentTraceRecorder, "start", lambda self: None)

    list(answer.answer_stream("hello", history=history))

    assert captured["history"] == history
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py::test_answer_stream_classifies_with_recent_five_turns engine/tests/test_answer_stream_agent.py::test_answer_stream_keeps_runner_full_history_when_intent_uses_recent_history -q
```

Expected: first test fails because `classify_intent` currently receives full history or no recent slicing.

- [ ] **Step 3: Implement recent-turn slicing helper**

In `engine/app/chat/answer.py`, add this helper after `_as_string_list`:

```python
def _recent_turn_history(history: list[dict[str, Any]], turns: int) -> list[dict[str, Any]]:
    if turns <= 0:
        return []

    selected: list[dict[str, Any]] = []
    user_turns = 0
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        selected.append(item)
        if role == "user":
            user_turns += 1
            if user_turns >= turns:
                break
    return list(reversed(selected))
```

- [ ] **Step 4: Use recent history in `answer_stream`**

Change:

```python
    intent = classify_intent(query, history)
```

to:

```python
    intent_history = _recent_turn_history(history, settings.INTENT_RECENT_TURNS)
    intent = classify_intent(query, intent_history)
```

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py::test_answer_stream_classifies_with_recent_five_turns engine/tests/test_answer_stream_agent.py::test_answer_stream_keeps_runner_full_history_when_intent_uses_recent_history -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```powershell
git add engine/app/chat/answer.py engine/tests/test_answer_stream_agent.py
git commit -m "feat: classify chat intent with recent history"
```

## Task 3: Make Intent Prompt Use Recent History

**Files:**
- Modify: `engine/app/chat/answer.py`
- Test: `engine/tests/test_answer_stream_agent.py`

- [ ] **Step 1: Write failing prompt-input test**

Add this test to `engine/tests/test_answer_stream_agent.py`:

```python
def test_classify_intent_sends_recent_history_to_llm(monkeypatch):
    captured = {}

    def fake_chat(messages, timeout_seconds=None, max_retries=None):
        captured["messages"] = messages
        return json.dumps({"groups": ["knowledge"], "kb_specs": [], "reasoning": "history says document follow-up"})

    monkeypatch.setattr(answer, "chat", fake_chat)

    result = answer.classify_intent(
        "这些方法的出处呢",
        [
            {"role": "user", "content": "我的论文的对比方法有哪些"},
            {"role": "assistant", "content": "方法包括 LMVSC 和 FPMVS。"},
        ],
    )

    assert result["groups"] == ["knowledge"]
    user_payload = captured["messages"][1]["content"]
    assert "这些方法的出处呢" in user_payload
    assert "我的论文的对比方法有哪些" in user_payload
    assert "方法包括 LMVSC 和 FPMVS" in user_payload
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py::test_classify_intent_sends_recent_history_to_llm -q
```

Expected: fails because `classify_intent` sends only `query`.

- [ ] **Step 3: Update intent prompt and payload**

Replace `_INTENT_CLASSIFY_PROMPT` with a Chinese prompt that says it must use recent history. Keep the JSON output contract unchanged:

```python
_INTENT_CLASSIFY_PROMPT = """你是一个意图分类器。请结合当前用户输入和最近几轮完整对话，判断本轮需要启用哪些工具组。

工具组定义：
- record：用户明确要求记录、保存、收藏想法、观点、待办或资源。
- memory：用户需要查询自己的长期记忆、偏好、目标、个人背景、历史设定或之前确认过的个人上下文。
- knowledge：用户需要检索知识库、上传资料、论文、文档、PDF、参考文献、表格、章节或文件内容。

分类规则：
1. 当前输入不能孤立判断，必须结合 recent_history。
2. 如果当前输入包含“这些、它、它们、继续、刚才那个、这篇、上述、前面”等指代或省略表达，优先用 recent_history 补全语义后再分类。
3. 如果最近对话围绕知识库、文档、论文、上传资料、参考文献、表格或章节展开，当前短追问通常应继承该任务域并启用 knowledge。
4. 如果最近 assistant 刚列出一组对象，而用户追问“出处、分别、展开、继续、对比”，通常应按同一知识任务继续。
5. 如果问题同时需要用户长期背景来解释“我的论文、我的项目、我之前的设定”等表达，可以同时启用 memory。
6. 闲聊、问候、简单常识问答不需要工具组。
7. 如果用户明确提到具体知识库名称，在 kb_specs 中列出。

只返回 JSON，不要返回 markdown 代码块：
{"groups": ["knowledge", "memory"], "kb_specs": [], "reasoning": "简短中文说明"}

如果不需要任何工具组，groups 返回空数组。"""
```

Then change `classify_intent` message assembly to:

```python
def _intent_history_payload(history: list[dict] | None) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        payload.append({"role": role, "content": content})
    return payload
```

Add it near `_recent_turn_history`, then update messages:

```python
    classifier_input = {
        "query": query,
        "recent_history": _intent_history_payload(history),
    }
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _INTENT_CLASSIFY_PROMPT},
        {"role": "user", "content": json.dumps(classifier_input, ensure_ascii=False)},
    ]
```

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py::test_classify_intent_sends_recent_history_to_llm engine/tests/test_answer_stream_agent.py::test_answer_stream_classifies_with_recent_five_turns -q
```

Expected: both pass.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/chat/answer.py engine/tests/test_answer_stream_agent.py
git commit -m "feat: include recent history in intent classifier prompt"
```

## Task 4: Add Loop History Preparation Helpers

**Files:**
- Modify: `engine/app/agent/runner.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write helper-level tests**

Add these tests near existing runner helper tests in `engine/tests/test_agent_runner.py`:

```python
def test_recent_turn_history_keeps_last_ten_user_turns():
    history = []
    for index in range(1, 13):
        history.append({"role": "user", "content": f"user {index}"})
        history.append({"role": "assistant", "content": f"assistant {index}"})

    recent = runner_mod._recent_turn_history(history, 10)

    assert [item["content"] for item in recent][:2] == ["user 3", "assistant 3"]
    assert [item["content"] for item in recent][-2:] == ["user 12", "assistant 12"]
    assert len(recent) == 20


def test_estimate_tokens_uses_characters_divided_by_three():
    assert runner_mod._estimate_text_tokens("abcdef") == 2
    assert runner_mod._estimate_text_tokens("") == 0
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_recent_turn_history_keeps_last_ten_user_turns engine/tests/test_agent_runner.py::test_estimate_tokens_uses_characters_divided_by_three -q
```

Expected: fails because helpers do not exist.

- [ ] **Step 3: Implement helpers**

In `engine/app/agent/runner.py`, add constants and helpers after `DOCUMENT_WINDOW_SUCCESS_STATUSES`:

```python
CONTEXT_SUMMARY_HEADER = "会话早期摘要："


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 2) // 3


def _message_dict_text(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "")
    content = message.get("content")
    if not isinstance(content, str):
        return ""
    return f"{role}: {content}"


def _recent_turn_history(history: list[dict[str, Any]], turns: int) -> list[dict[str, Any]]:
    if turns <= 0:
        return []
    selected: list[dict[str, Any]] = []
    user_turns = 0
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        selected.append(item)
        if role == "user":
            user_turns += 1
            if user_turns >= turns:
                break
    return list(reversed(selected))


def _history_token_estimate(history: list[dict[str, Any]]) -> int:
    return sum(_estimate_text_tokens(_message_dict_text(item)) for item in history)
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_recent_turn_history_keeps_last_ten_user_turns engine/tests/test_agent_runner.py::test_estimate_tokens_uses_characters_divided_by_three -q
```

Expected: both pass.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "feat: add agent history pruning helpers"
```

## Task 5: Implement Loop Compression Mode

**Files:**
- Modify: `engine/app/agent/runner.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write full-mode and compressed-mode tests**

Add these tests to `engine/tests/test_agent_runner.py`:

```python
def _history_with_turns(count, content_size=20):
    history = []
    for index in range(1, count + 1):
        history.append({"role": "user", "content": f"user {index} " + ("u" * content_size)})
        history.append({"role": "assistant", "content": f"assistant {index} " + ("a" * content_size)})
    return history


def test_build_messages_uses_full_history_below_threshold(monkeypatch):
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 32000, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    history = _history_with_turns(3, content_size=10)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")

    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert any("user 1" in content for content in contents)
    assert any("assistant 1" in content for content in contents)
    assert not any("会话早期摘要" in content for content in contents)


def test_build_messages_compresses_history_at_threshold(monkeypatch):
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：旧任务")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 80, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)
    monkeypatch.setattr(runner_mod.settings, "LOOP_RECENT_TURNS", 10, raising=False)

    history = _history_with_turns(12, content_size=50)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")

    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert any("会话早期摘要" in content for content in contents)
    assert not any("user 1 " in content for content in contents if not content.startswith("会话早期摘要"))
    assert any("user 3 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_build_messages_uses_full_history_below_threshold engine/tests/test_agent_runner.py::test_build_messages_compresses_history_at_threshold -q
```

Expected: compressed-mode test fails because `_build_messages()` still injects all history.

- [ ] **Step 3: Add summary prompt and preparation helper**

In `engine/app/agent/runner.py`, add:

```python
def _summary_budget_chars() -> int:
    return max(int(getattr(settings, "MAX_SUMMARY_TOKENS", 1200) or 1200), 1) * 3


def _summarize_older_history(older_history: list[dict[str, Any]]) -> str:
    if not older_history:
        return ""
    transcript = "\n".join(_message_dict_text(item) for item in older_history if _message_dict_text(item))
    if not transcript.strip():
        return ""
    prompt = (
        "请把以下会话早期历史压缩成中文摘要，只保留会影响后续回答的信息。\n"
        "摘要必须包含：用户当前主要任务、已确认的对象/文档/范围、关键结论、"
        "assistant 已列出的关键对象或中间结果、尚未解决的问题、用户明确约束。\n"
        "不要保留寒暄、重复追问、无关闲聊和大段原文。\n\n"
        f"{transcript}"
    )
    summary = chat([{"role": "user", "content": prompt}], timeout_seconds=10, max_retries=0).strip()
    if not summary:
        return ""
    if not summary.startswith(CONTEXT_SUMMARY_HEADER):
        summary = f"{CONTEXT_SUMMARY_HEADER}\n{summary}"
    return summary[: _summary_budget_chars()]


def _estimate_fixed_context_tokens(*parts: str) -> int:
    return sum(_estimate_text_tokens(part) for part in parts if part)
```

- [ ] **Step 4: Update `_build_messages()` to choose full or compressed history**

Inside `_build_messages()`, keep active recall and graph insights generation, then compute:

```python
        fixed_context_tokens = _estimate_fixed_context_tokens(
            self.system_prompt,
            recall_block if "recall_block" in locals() else "",
            insights_block if "insights_block" in locals() else "",
            query,
            effective_query or "",
        )
        max_context_tokens = int(getattr(settings, "DEFAULT_MAX_CONTEXT_TOKENS", 32000) or 32000)
        threshold = float(getattr(settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8) or 0.8)
        total_estimate = fixed_context_tokens + _history_token_estimate(history)
        use_compression = total_estimate >= int(max_context_tokens * threshold)
        loop_history = history
        older_summary = ""
        if use_compression:
            recent_turns = int(getattr(settings, "LOOP_RECENT_TURNS", 10) or 10)
            loop_history = _recent_turn_history(history, recent_turns)
            recent_ids = {id(item) for item in loop_history}
            older_history = [item for item in history if id(item) not in recent_ids]
            try:
                older_summary = _summarize_older_history(older_history)
            except Exception as exc:
                logger.warning("[agent] history_summary_failed error=%s", quoted(str(exc), limit=200))
                older_summary = ""
            if not older_summary:
                loop_history = _recent_turn_history(history, recent_turns)
```

Then before appending active recall system messages, insert `older_summary` after the base system prompt:

```python
        if older_summary:
            messages.append(SystemMessage(content=older_summary))
```

Finally, replace:

```python
        for item in history:
```

with:

```python
        for item in loop_history:
```

Keep continuation injection independent of `loop_history`.

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_build_messages_uses_full_history_below_threshold engine/tests/test_agent_runner.py::test_build_messages_compresses_history_at_threshold -q
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "feat: compress long agent chat history"
```

## Task 6: Preserve Continuation And Add Fallback Behavior

**Files:**
- Modify: `engine/app/agent/runner.py`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write continuation and summary-failure tests**

Add these tests to `engine/tests/test_agent_runner.py`:

```python
def test_compressed_history_still_injects_active_continuation(monkeypatch):
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.graph_insights_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.chat", lambda messages, **kwargs: "会话早期摘要：\n- 用户当前主要任务：读文档")
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 80, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    state = AgentContinuation(
        version=1,
        objective="读取论文后续内容",
        kb_uid="kb-a",
        file_uid="file-a",
        next_offset=123,
        has_more_after=True,
    )
    history = _history_with_turns(12, content_size=50)
    messages = runner._build_messages(
        "继续",
        history=history,
        effective_query="读取论文后续内容",
        active_continuation=state,
    )
    contents = [getattr(message, "content", "") for message in messages]

    assert any("file_uid: file-a" in content for content in contents)
    assert any("next_offset: 123" in content for content in contents)


def test_compressed_history_falls_back_to_recent_history_when_summary_fails(monkeypatch):
    monkeypatch.setattr("engine.app.agent.runner.recall_memory_context", lambda q, **kw: "")
    monkeypatch.setattr("engine.app.agent.runner.graph_insights_context", lambda q, **kw: "")

    def fail_chat(*args, **kwargs):
        raise RuntimeError("summary failed")

    monkeypatch.setattr("engine.app.agent.runner.chat", fail_chat)
    monkeypatch.setattr(runner_mod.settings, "DEFAULT_MAX_CONTEXT_TOKENS", 80, raising=False)
    monkeypatch.setattr(runner_mod.settings, "CONTEXT_COMPRESSION_THRESHOLD", 0.8, raising=False)

    history = _history_with_turns(12, content_size=50)
    runner = LangChainAgentRunner(model=None, tools=[], system_prompt="BASE")
    messages = runner._build_messages("current query", history=history)
    contents = [getattr(message, "content", "") for message in messages]

    assert not any("会话早期摘要" in content for content in contents)
    assert not any("user 1 " in content for content in contents)
    assert any("user 3 " in content for content in contents)
    assert any("assistant 12 " in content for content in contents)
```

- [ ] **Step 2: Run tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_compressed_history_still_injects_active_continuation engine/tests/test_agent_runner.py::test_compressed_history_falls_back_to_recent_history_when_summary_fails -q
```

Expected: pass after Task 5 implementation, or fail if continuation/fallback ordering is wrong.

- [ ] **Step 3: Add hard over-budget fallback if needed**

If tests reveal unbounded recent history, add a second-stage fallback after summary:

```python
            compressed_estimate = fixed_context_tokens + _estimate_text_tokens(older_summary) + _history_token_estimate(loop_history)
            if compressed_estimate >= int(max_context_tokens * threshold):
                min_turns = int(getattr(settings, "MIN_LOOP_RECENT_TURNS", 6) or 6)
                loop_history = _recent_turn_history(history, min_turns)
```

Do not drop `query` or `active_continuation`.

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py::test_compressed_history_still_injects_active_continuation engine/tests/test_agent_runner.py::test_compressed_history_falls_back_to_recent_history_when_summary_fails -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add engine/app/agent/runner.py engine/tests/test_agent_runner.py
git commit -m "test: cover compressed history continuation fallback"
```

## Task 7: Regression Test Existing Chat Runner Behavior

**Files:**
- Test only

- [ ] **Step 1: Run focused answer stream tests**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run focused runner tests**

Run:

```powershell
pytest engine/tests/test_agent_runner.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run graph insights build-message tests**

Run:

```powershell
pytest engine/tests/test_graph_insights.py::test_build_messages_injects_graph_insights engine/tests/test_graph_insights.py::test_build_messages_without_insights_when_disabled -q
```

Expected: both tests pass. If a failure is caused only by extra summary system messages, update assertions to search system-message contents rather than assume a fixed count.

- [ ] **Step 4: Run lint-style diff check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit any test-only assertion updates**

If Step 3 required assertion updates:

```powershell
git add engine/tests/test_graph_insights.py
git commit -m "test: adapt graph insight message assertions"
```

If no files changed, skip this commit.

## Task 8: Final Verification And Documentation Check

**Files:**
- Modify only if implementation drift requires a small note in `docs/superpowers/specs/2026-08-02-chat-context-pruning-design.md`

- [ ] **Step 1: Run final focused test set**

Run:

```powershell
pytest engine/tests/test_answer_stream_agent.py engine/tests/test_agent_runner.py engine/tests/test_graph_insights.py::test_build_messages_injects_graph_insights engine/tests/test_graph_insights.py::test_build_messages_without_insights_when_disabled -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Inspect final diff**

Run:

```powershell
git status --short
git diff -- engine/app/config.py engine/app/chat/answer.py engine/app/agent/runner.py engine/tests/test_answer_stream_agent.py engine/tests/test_agent_runner.py engine/tests/test_graph_insights.py
```

Expected: only files touched by this plan are changed, plus any pre-existing unrelated dirty files remain separate and unstaged.

- [ ] **Step 3: Commit final doc adjustment only if needed**

If implementation required a spec clarification, commit it separately:

```powershell
git add docs/superpowers/specs/2026-08-02-chat-context-pruning-design.md
git commit -m "docs: clarify chat context pruning behavior"
```

If the spec still matches implementation, skip this commit.

## Self-Review Notes

- Spec coverage: intent recent 5 turns is covered by Tasks 2 and 3; loop dynamic full/compressed behavior is covered by Tasks 4 and 5; continuation and fallback behavior are covered by Task 6; verification is covered by Tasks 7 and 8.
- Scope: this plan does not add persistent summary storage or frontend protocol changes because the approved spec marked those as out of first-pass scope.
- Risk: summary generation uses the existing `chat` wrapper and can add one LLM call only after threshold is crossed. The failure path preserves recent history and does not block the answer.
