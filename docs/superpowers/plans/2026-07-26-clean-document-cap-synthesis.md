# Clean Document-Cap Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the forced answer after five document opens use a fresh, tool-free context containing only the current query and extracted document excerpts.

**Architecture:** Extract valid document windows through one pure helper shared by the fallback and synthesis builder. Build a fresh `SystemMessage` plus `HumanMessage` for the forced invocation, while retaining the five-call cap, DSML rejection, continuation wording, trace marker, and fallback.

**Tech Stack:** Python, LangChain message types, pytest

---

## File Structure

- Modify `engine/app/agent/runner.py`: extract windows, build clean synthesis messages, and use them only in the document-cap branch.
- Modify `engine/tests/test_agent_runner.py`: prove the forced invocation contains no agent/tool history.

### Task 1: Add the failing regression assertion

**Files:**
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Extend the existing forced-answer test**

In `test_runner_gives_model_one_no_tool_answer_pass_at_open_limit`, after collecting `token_text`, add:

```python
    forced_messages = model.last_messages
    assert [message.type for message in forced_messages] == ["system", "human"]
    assert not any(isinstance(message, ToolMessage) for message in forced_messages)
    assert "Explain the paper in detail" in forced_messages[1].content
    assert "window 1" in forced_messages[1].content
    assert "window 5" in forced_messages[1].content
```

Keep the existing assertions for five tool calls, six model calls, emitted synthesis text, and absence of fallback text.

- [ ] **Step 2: Run the test and verify RED**

Run `python -m pytest engine/tests/test_agent_runner.py::test_runner_gives_model_one_no_tool_answer_pass_at_open_limit -q`.

Expected: FAIL because `model.last_messages` contains the full agent history, including tool messages, rather than exactly `system` and `human`.

### Task 2: Build and use the clean synthesis context

**Files:**
- Modify: `engine/app/agent/runner.py:120-163`
- Modify: `engine/app/agent/runner.py:775-820`
- Test: `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Extract document-window parsing**

Add immediately before `_partial_document_answer_from_messages`:

```python
def _document_windows_from_messages(messages: list[Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            payload = json.loads(str(message.content))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        content = data.get("content")
        file_uid = data.get("file_uid")
        if not isinstance(content, str) or not content.strip() or not file_uid:
            continue
        windows.append(
            {
                "file_uid": str(file_uid),
                "offset": data.get("offset"),
                "content": content.strip(),
                "has_more_after": bool(data.get("has_more_after")),
            }
        )
    return windows
```

Replace the duplicated parsing loop at the start of `_partial_document_answer_from_messages` with `windows = _document_windows_from_messages(messages)`.

- [ ] **Step 2: Add the synthesis builder**

Add after `_partial_document_answer_from_messages`:

```python
def _document_cap_synthesis_messages(query: str, messages: list[Any]) -> list[Any]:
    windows = _document_windows_from_messages(messages)[-OPEN_KB_DOCUMENT_PER_FILE_LIMIT:]
    excerpts: list[str] = []
    for index, window in enumerate(windows, start=1):
        text = re.sub(r"\s+", " ", str(window["content"])).strip()
        if len(text) > 700:
            text = text[:700].rstrip() + "..."
        offset = window.get("offset")
        location = f"offset {offset}" if offset is not None else f"窗口 {index}"
        excerpts.append(f"{index}. {location}: {text}")

    evidence = "\n\n".join(excerpts) or "没有可用的文档片段。"
    return [
        SystemMessage(
            content=(
                "你负责基于给定的文档片段直接回答用户问题。"
                "只输出自然语言答案，不得调用工具，不得输出 XML、DSML 或任何工具调用协议。"
                "请明确说明文档尚未完整读取，并在回答末尾询问用户是否继续读取。"
            )
        ),
        HumanMessage(
            content=(
                f"用户问题：{query}\n\n"
                "以下是本轮已经读取的文档片段：\n\n"
                f"{evidence}"
            )
        ),
    ]
```

- [ ] **Step 3: Invoke the model with clean messages**

In the `open_kb_document` cap branch, add:

```python
                        synthesis_messages = _document_cap_synthesis_messages(query, messages)
```

Use `len(synthesis_messages)` and `_message_roles(synthesis_messages)` in the `forced_final_after_open_limit` trace input, then replace `self.model.invoke(messages)` with:

```python
                        forced_response = self.model.invoke(synthesis_messages)
```

Do not change DSML rejection, `_partial_document_answer_from_messages(messages)`, the call counter, or continuation behavior.

- [ ] **Step 4: Verify GREEN**

Run `python -m pytest engine/tests/test_agent_runner.py::test_runner_gives_model_one_no_tool_answer_pass_at_open_limit -q`.

Expected: `1 passed`.

- [ ] **Step 5: Run cap regressions**

Run `python -m pytest engine/tests/test_agent_runner.py -q -k "open_limit or five_open or partial_document"`.

Expected: all selected tests pass, including DSML suppression and deterministic fallback.

- [ ] **Step 6: Run the complete module**

Run `python -m pytest engine/tests/test_agent_runner.py -q`.

Expected: all tests pass with no failures or errors.

- [ ] **Step 7: Review scope and whitespace**

Run `git diff --check`, then inspect `git diff -- engine/app/agent/runner.py engine/tests/test_agent_runner.py`.

Expected: no whitespace errors. Preserve the pre-existing uncommitted general iteration-limit and grounded-fallback hunks.

- [ ] **Step 8: Commit only new hunks**

Use `git add -p -- engine/app/agent/runner.py engine/tests/test_agent_runner.py`, inspect `git diff --cached`, run `git diff --cached --check`, and commit with `git commit -m "fix(agent): isolate document cap synthesis context"`.

Exclude all pre-existing unrelated hunks from the commit.
