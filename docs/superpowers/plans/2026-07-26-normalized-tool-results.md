# Normalized Tool Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correctly consume production-shaped knowledge-tool results and always synthesize after executing the final iteration's requested tools.

**Architecture:** Add an explicit normalizer for supported response envelopes, then route window and evidence extraction through it. Move global-limit synthesis to the post-tool boundary and reuse a clean evidence-only message builder.

**Tech Stack:** Python, LangChain messages, pytest

---

## Files

- Modify `engine/app/agent/runner.py`: normalization, evidence collection, clean synthesis, and final-iteration control flow.
- Modify `engine/tests/test_agent_runner.py`: production-shaped response and post-final-tool regressions.

### Task 1: Normalize production tool results

- [ ] Add a fake document tool that returns `{"status":"success","payload":{"summary":{"status":"ok","data":...}}}` and update the clean-synthesis regression to use it.
- [ ] Assert the forced human message contains the nested document excerpts and add query/find evidence extraction assertions.
- [ ] Run the focused tests and verify they fail because the current parser only checks top-level `data`.
- [ ] Add `_normalized_tool_result(payload)` with explicit `payload.summary`, `payload.data`, `summary.data`, and flat fallbacks.
- [ ] Add `_tool_evidence_texts(messages)` to extract bounded `data.content`, `data.evidence[].excerpt`, and `data.matches[].snippet` without duplicates.
- [ ] Route `_document_windows_from_messages`, `_payload_has_meaningful_evidence`, `_grounded_fallback_answer_from_messages`, and clean synthesis through the normalized representation.
- [ ] Run the focused tests and verify they pass.

Representative production fixture:

```python
return json.dumps({
    "status": "success",
    "payload": {
        "summary": {
            "status": "ok",
            "data": {
                "file_uid": args["file_uid"],
                "offset": args.get("offset", 0),
                "content": f"nested window {self.calls}",
                "has_more_after": True,
            },
        }
    },
})
```

### Task 2: Synthesize after the final requested tools execute

- [ ] Add a model/tool regression where iteration 2 of 2 requests a tool, assert that tool executes, and assert a seventh clean synthesis call returns the final answer.
- [ ] Add a multiple-tool variant asserting the complete final batch executes before synthesis.
- [ ] Run both tests and verify the current code fails by either skipping the final tool or emitting the iteration-limit error.
- [ ] Remove the pre-tool `iteration == self.max_iterations` forced-answer branch.
- [ ] After processing all tool calls for an iteration, when `iteration == self.max_iterations`, build clean synthesis messages from all normalized evidence, invoke the unbound model once, reject structured/textual tool calls, and emit an evidence fallback when needed.
- [ ] Record this pass as `forced_final_after_iteration_limit` and finish the trace as success.
- [ ] Run focused final-iteration tests and verify they pass.

Required final flow:

```python
for iteration in range(1, self.max_iterations + 1):
    response = model.invoke(messages)
    for tool_call in tool_calls:
        execute_and_append(tool_call)
    if iteration == self.max_iterations:
        return synthesize_from_normalized_evidence(query, messages)
```

### Task 3: Verify and commit

- [ ] Run `python -m pytest engine/tests/test_agent_runner.py -q` and expect all tests to pass.
- [ ] Run `git diff --check` and inspect the scoped diff.
- [ ] Stage only this repair's hunks, preserving pre-existing uncommitted changes.
- [ ] Commit with `fix(agent): normalize tool results before synthesis`.
- [ ] Restart the worktree backend and engine because uvicorn reload is disabled.
- [ ] Verify HTTP 200 from ports 5173, 5175, and 5180.
