# Agent Trace and Evidence Audit Design

## Context

This design addresses a hallucination badcase in Prism chat where the assistant
invented a `chunk_id` while explaining a previous retrieval mistake. The
underlying failure was not only model behavior. The system did not preserve a
machine-readable trace of tool calls, returned evidence, and final answer
grounding, so later questions such as "which chunk caused this answer?" could
not be answered reliably.

The goal is to make every assistant answer auditable as structured JSON,
including answers that do not call tools.

## Goals

- Create a machine-analyzable trace for every `/chat/answer` run.
- Persist model steps, tool calls, tool results, final answers, and errors.
- Normalize retrieval evidence into a stable Evidence Schema.
- Store evidence in queryable tables, not only inside `chat_message.process`.
- Export one complete trace as JSON for debugging and automated analysis.
- Keep existing chat streaming and UI process state working.

## Non-Goals

- Do not redesign retrieval ranking or chunking in this phase.
- Do not build a full trace viewer UI in this phase.
- Do not require all non-knowledge tools to produce evidence.
- Do not block normal chat if trace recording fails.

## Data Model

### `agent_trace`

One row represents one assistant answer attempt.

Fields:

- `id`: trace id.
- `session_id`: chat session id.
- `user_message_id`: triggering user message id, nullable during migration or
  unusual clients.
- `assistant_message_id`: final assistant message id, nullable until bound.
- `user_query`: user query text.
- `status`: `running`, `success`, `error`, or `orphaned`.
- `model`: model name used by the runner.
- `started_at`: trace start time.
- `ended_at`: trace end time.
- `trace_json`: optional exported snapshot cache.

### `agent_trace_step`

One row represents one event inside a trace.

Fields:

- `id`: step id.
- `trace_id`: parent trace id.
- `step_index`: monotonic order within the trace.
- `step_type`: one of `model_invoke`, `model_response`, `tool_call`,
  `tool_result`, `final_answer`, or `error`.
- `tool_name`: tool name for tool steps.
- `tool_call_id`: model-generated tool call id when available.
- `input_json`: structured step input.
- `output_json`: structured step output.
- `status`: `running`, `success`, or `error`.
- `latency_ms`: step latency when known.
- `started_at`: step start time.
- `ended_at`: step end time.

### `agent_trace_evidence`

One row represents one normalized evidence item returned by a tool result.

Fields:

- `id`: evidence row id.
- `trace_step_id`: parent `tool_result` step.
- `evidence_id`: stable evidence key, such as `document_chunk:<chunk_id>`.
- `source_kind`: source kind, such as `document_chunk`.
- `source_id`: source id.
- `chunk_id`: document chunk id when available.
- `parent_chunk_id`: parent chunk id when available.
- `item_id`: knowledge item id when available.
- `display_title`: human-readable source title.
- `excerpt`: bounded raw excerpt used by the model.
- `hit_reason`: short reason this evidence matched.
- `score`: retrieval score when available.
- `retrieval_path_json`: retrieval path, such as `["raw_document_search"]`.
- `metadata_json`: extra structured metadata, such as `chunk_type` and
  `chunk_index`.

Evidence is split into its own table because it is the most useful part for
machine analysis. Examples include finding answers that cited nonexistent
chunks, checking which tool produced a source, and measuring timeout or empty
evidence rates.

## Evidence Schema

Knowledge tools return `evidence_items` in their JSON payload:

```json
{
  "evidence_items": [
    {
      "evidence_id": "document_chunk:272d7490-8999-482e-b138-be62f420ed6a",
      "source_kind": "document_chunk",
      "source_id": "272d7490-8999-482e-b138-be62f420ed6a",
      "chunk_id": "272d7490-8999-482e-b138-be62f420ed6a",
      "parent_chunk_id": null,
      "item_id": "f2155cd1-9dbd-461f-a7e9-da6c026778ae",
      "display_title": "Representation Learning Meets Optimization-Derived Networks",
      "excerpt": "degree from the College of Computer Science, Zhe-jiang University...",
      "hit_reason": "matched raw document search result",
      "score": 1.0,
      "retrieval_path": ["raw_document_search"],
      "metadata": {
        "chunk_type": "parent",
        "chunk_index": 13
      }
    }
  ]
}
```

The first phase covers:

- `raw_document_search`
- `knowledge_evidence_search`
- `knowledge_material_search`
- `knowledge_topic_search`

Other tools still produce trace steps, but may have empty `evidence_items`.

## Runtime Flow

1. The frontend creates or knows the current user message id.
2. The frontend calls `/chat/answer` with `session_id`, `user_message_id`,
   `query`, and history.
3. The engine creates `agent_trace` immediately with `status=running`.
4. The engine emits a stream event:

```json
{
  "type": "trace",
  "data": {
    "trace_id": "<trace-id>"
  }
}
```

5. The runner records `model_invoke` before model invocation.
6. The runner records `model_response` after model invocation, including content
   preview and tool call ids.
7. For each tool call, the runner records `tool_call`.
8. After each tool returns, the runner records `tool_result` and expands
   `payload.evidence_items` into `agent_trace_evidence`.
9. When the model produces final text, the runner records `final_answer`.
10. The trace status becomes `success` or `error`, and `ended_at` is set.
11. The frontend saves the assistant message and stores `trace_id` in
    `chat_message.process.trace_id`.
12. After the assistant message is saved, the frontend calls a bind endpoint:

```http
POST /traces/{trace_id}/bind-message
{
  "session_id": "<session-id>",
  "assistant_message_id": "<assistant-message-id>"
}
```

13. The backend updates `agent_trace.assistant_message_id`.

This binding step is needed because the engine starts the trace before the final
assistant message id exists.

## Export Format

Trace export endpoint:

```http
GET /traces/{trace_id}/export
```

Response shape:

```json
{
  "trace_id": "trace-uuid",
  "session_id": "session-uuid",
  "user_message_id": "user-message-uuid",
  "assistant_message_id": "assistant-message-uuid",
  "user_query": "chunk_id: 9ef0570c...这个内容是啥",
  "status": "success",
  "model": "deepseek-v4-flash",
  "started_at": "2026-06-28T23:18:00+08:00",
  "ended_at": "2026-06-28T23:18:18+08:00",
  "steps": [
    {
      "step_id": "step-1",
      "step_index": 1,
      "step_type": "model_invoke",
      "status": "success",
      "tool_name": null,
      "tool_call_id": null,
      "input": {
        "message_count": 51,
        "message_roles": "0:system | 1:human | ..."
      },
      "output": null,
      "latency_ms": null,
      "evidence_items": []
    },
    {
      "step_id": "step-2",
      "step_index": 2,
      "step_type": "tool_result",
      "status": "success",
      "tool_name": "raw_document_search",
      "tool_call_id": "call_00_Deme...",
      "input": {
        "query": "Representation Learning Meets ... 9ef0570c"
      },
      "output": {
        "status": "success",
        "summary": "Found the requested raw document chunk by source_id."
      },
      "latency_ms": 16824,
      "evidence_items": [
        {
          "evidence_id": "document_chunk:272d7490-8999-482e-b138-be62f420ed6a",
          "source_kind": "document_chunk",
          "source_id": "272d7490-8999-482e-b138-be62f420ed6a",
          "chunk_id": "272d7490-8999-482e-b138-be62f420ed6a",
          "parent_chunk_id": null,
          "item_id": "f2155cd1-9dbd-461f-a7e9-da6c026778ae",
          "display_title": "Representation Learning Meets Optimization-Derived Networks",
          "excerpt": "degree from the College of Computer Science...",
          "hit_reason": "matched raw document search result",
          "score": 1.0,
          "retrieval_path": ["raw_document_search"],
          "metadata": {
            "chunk_type": "parent",
            "chunk_index": 13
          }
        }
      ]
    },
    {
      "step_id": "step-3",
      "step_index": 3,
      "step_type": "final_answer",
      "status": "success",
      "tool_name": null,
      "tool_call_id": null,
      "input": null,
      "output": {
        "content": "抱歉，我需要坦诚地纠正自己..."
      },
      "latency_ms": null,
      "evidence_items": []
    }
  ]
}
```

## No-Tool Answers

Every assistant answer creates a trace, even when no tool is called. A no-tool
answer should still include:

- `model_invoke`
- `model_response`
- `final_answer`

This prevents ambiguity between "no tool was needed" and "trace recording
failed".

## Failure Handling

Tool timeout:

- Record `tool_call`.
- Record `tool_result` with `status=error`.
- Store timeout summary in `output_json`.
- Store no evidence.

Tool returns non-JSON:

- Record `tool_result`.
- Store `output_parse_error=true`.
- Store `raw_text_preview`, bounded to 1000 characters.
- Store no evidence.

Model invocation error:

- Record `model_invoke` if possible.
- Record `error`.
- Mark `agent_trace.status=error`.
- `assistant_message_id` may remain null.

Assistant message save fails:

- Trace remains persisted.
- If the run otherwise completed, mark status as `orphaned`.
- `assistant_message_id` remains null.

Trace system error:

- Chat should continue where possible.
- Log the trace error.
- Do not let audit failure break the user-facing answer.

Oversized evidence:

- Bound `excerpt` to a configured limit, initially 1200 to 2000 characters.
- Preserve ids so full text can be reloaded from source tables.

## Prompt and Answer Constraints

The trace tables make auditing possible, but the model still needs a behavior
constraint:

- When citing `chunk_id`, `source_id`, or another evidence id, the model must use
  ids present in the current tool payload's `evidence_items`.
- If no matching evidence id is present, the model must say it cannot confirm
  the id from this run.

This constraint should be added after the trace plumbing is in place, so it can
be tested against real `evidence_items`.

## Testing Strategy

Unit tests:

- Evidence adapter normalizes raw document sources into `evidence_items`.
- Knowledge governance tools include `evidence_items`.
- Runner records no-tool traces.
- Runner records tool traces and evidence rows.
- Runner records tool timeout as `tool_result status=error`.

Integration tests:

- A chat answer with `raw_document_search` creates `agent_trace`,
  `agent_trace_step`, and `agent_trace_evidence` rows.
- A casual no-tool answer creates a trace with no evidence.
- Export endpoint returns steps in `step_index` order and nests evidence under
  the producing `tool_result` step.
- Binding endpoint updates `assistant_message_id`.

Regression test for the badcase:

- Query a nonexistent chunk id.
- Verify the trace contains the actual evidence ids returned by tools.
- Verify no exported evidence item has the nonexistent id unless the source table
  really contains it.

## Open Sequencing

Implementation should proceed in small phases:

1. Add trace models, migration, and repository helpers.
2. Add Evidence Schema adapter.
3. Add trace recording to the runner.
4. Add stream `trace` event and frontend persistence of `trace_id`.
5. Add bind and export APIs.
6. Add model citation constraint and tests.

