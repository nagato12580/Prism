# Knowledge Agent Continuation and Coverage Design

## Context

The July 26 trace exposes three failures that share one theme: the agent has enough information to make progress, but its orchestration layer discards either document coverage, continuation intent, or the newest evidence.

First, the knowledge base inventory contains 11 files, while each unrestricted `query_kb` call returns the globally ranked top 10 chunks. Four follow-up searches cover only 10 distinct files and omit `11521_AF_UMC_An_Alignment_Free.pdf`. A global chunk limit cannot guarantee one result per document.

Second, the current five-open response tells the user to reply with “继续” but does not preserve a machine-readable objective or cursor. The next request receives visible chat text without the previous tool transcript, so the model starts the document again or guesses unrelated offsets.

Third, clean forced synthesis collects at most 12 evidence excerpts from oldest to newest. Earlier query results can exhaust this limit before the last, decisive `find_kb_document` or `open_kb_document` result is considered. The trace therefore says that no hyperparameter setting was found even though the final tool result contains Adam, an initial learning rate of 0.01, and a layer-count search over `{3, 4, 5}`.

## Goals

1. Preserve the five `open_kb_document` calls per file per answer.
2. Make a bare continuation request resume the prior objective and document position deterministically.
3. Guarantee that the final requested tool result is available to forced synthesis.
4. Provide document-level coverage for requests about every file in a knowledge base.
5. Keep continuation durable across browser refreshes and service restarts without adding a new database table or column.

## Non-Goals

- Raising or removing the five-open limit.
- Raising the global agent iteration limit.
- Persisting raw document excerpts in chat-message metadata.
- Precomputing a new document-summary index or adding a background summarization job.
- Treating a larger global `top_k` as proof of document coverage.

## Chosen Architecture

The implementation uses three bounded changes:

1. A clean-synthesis input builder that resolves the effective user objective and selects evidence by recency and evidence type.
2. A versioned continuation state carried in the existing `ChatMessage.process` JSON field and returned to Engine with chat history.
3. An optional per-file coverage mode on `query_kb` that reports requested, covered, and missing files explicitly.

This avoids in-process state, so multiple workers and restarts do not lose the cursor. It also avoids a schema migration because assistant process metadata is already persisted and restored.

## Continuation State Contract

The Engine emits this public, bounded state when it stops because of the per-file open limit:

```json
{
  "version": 1,
  "objective": "层次锚定的超参数怎么设置？",
  "kb_uid": "76951d8e-6a56-40f0-a7f6-19d4e63496a0",
  "file_uid": "3251ff03-2330-4724-a347-3cd271de70ce",
  "next_offset": 37766,
  "has_more_after": true
}
```

`objective` is the most recent substantive user request, not the literal word “继续”. The identifiers must already be authorized in the current run. `next_offset` is the end of the latest successful document window and is never inferred from user-visible prose.

The state is emitted through a `continuation` NDJSON event. The frontend stores it on the in-memory assistant message and inside `process.agent_continuation` when persisting the assistant message. When constructing the next request history, the frontend includes only the most recent assistant continuation state as a `continuation` property on that history entry.

No raw excerpt, tool result, storage path, tenant identifier, or authorization token is stored in the state.

## Continuation Recognition and Lifecycle

A request is treated as a bare continuation only when its normalized text exactly matches a small allowlist such as `继续`, `继续读`, `继续读取`, `接着读`, or `往下读`, with optional terminal punctuation. A longer request such as “继续找学习率并比较各数据集” remains a new substantive objective.

For a valid bare continuation with valid state:

1. The effective objective becomes `state.objective`.
2. The runner adds a short system instruction saying that this turn must resume that objective.
3. The first relevant document read is anchored to `state.kb_uid`, `state.file_uid`, and `state.next_offset`.
4. Clean forced synthesis receives the effective objective, not the literal continuation command.

The state is ignored when its version or types are invalid, when it does not belong to the latest assistant message, or when the referenced knowledge base is outside the authorized scope. A successful read with `has_more_after=false` clears the continuation state. A new substantive user request also supersedes old state.

The model is still allowed to use `find_kb_document` before opening a window when the objective asks for a precise value. Continuation state determines the fallback resume point; it does not prevent a more relevant exact match from being opened.

## Document Tool Contract

`OpenDocumentData` adds `next_offset`, equal to `offset + len(content)`. Existing `offset`, `window_size`, `has_more_before`, and `has_more_after` fields remain unchanged.

The runner records the latest successful normalized `open_kb_document` result for each file. When the fifth call for a file completes, it creates continuation state from that result. Failed or empty reads do not advance the cursor.

The forced answer must describe the unit as a document window, not claim that five calls equal five pages.

## Effective Objective Resolution

The runner introduces a pure resolver with these rules:

1. If the current query is substantive, return it unchanged.
2. If the current query is a bare continuation and the latest assistant history entry has valid continuation state, return the state's objective.
3. If the current query is a bare continuation without state, fall back to the latest substantive user history entry.
4. If neither exists, retain the current query and let the normal agent ask for clarification or report insufficient context.

This resolver is used by normal tool guidance, document-cap synthesis, global iteration-limit synthesis, and trace metadata. Historical assistant prose and raw tool messages remain excluded from the clean synthesis context.

## Evidence Selection for Clean Synthesis

Evidence collection changes from “first 12 excerpts win” to a typed, bounded selection. Each normalized tool result produces candidates with a kind, result order, text, and provenance identifiers when present.

Selection uses the following rules:

1. Reserve space for every usable candidate from the final executed tool-call batch, preserving ranking inside each tool result.
2. Prefer exact `find_kb_document` matches over older semantic-search evidence.
3. Prefer recent document windows over older document windows.
4. Preserve file diversity for coverage-mode results before adding a second excerpt from the same file.
5. Fill the remaining character budget with newer semantic evidence.
6. Deduplicate normalized text without reordering candidates inside a result.

The limit becomes a character budget equivalent to the current bounded context rather than a hard count of 12. Individual excerpts remain truncated. The final batch is always represented unless it contains no usable evidence.

Both document-cap and global iteration-limit synthesis call the same selector. Deterministic fallback answers use the same selected evidence, so model failure cannot restore the old first-evidence bias.

## Per-File Coverage Retrieval

`QueryKbInput` adds:

```python
coverage: Literal["relevance", "per_file"] = "relevance"
```

Normal questions keep `relevance` behavior unchanged. For requests explicitly covering all documents, the knowledge skill instructs the model to use `coverage="per_file"`.

Per-file coverage works as follows:

1. Resolve the authorized file inventory, or the supplied `file_filter`, in stable file order.
2. Run one bounded global retrieval with an expanded candidate count.
3. Group evidence by `file_uid` and keep the best result per file first.
4. Run a targeted fast retrieval with `top_k=1` only for files still missing.
5. Return per-file evidence followed by additional globally relevant evidence that fits the response budget.

The response adds a coverage block:

```json
{
  "requested_file_uids": ["..."],
  "covered_file_uids": ["..."],
  "missing_file_uids": [],
  "complete": true
}
```

The agent may claim that all files were covered only when `complete` is true. An unparsed, empty, deleted, or retrieval-unavailable file remains in `missing_file_uids` and must be named as a limitation. The result is bounded to at most 30 requested files per call; larger inventories report truncation and require another paged request rather than unbounded fan-out.

This design guarantees document coverage when each requested file has at least one retrievable indexed chunk. It does not fabricate evidence for empty or unavailable files.

## Data Flow

### First capped answer

1. The runner executes five document opens.
2. The fifth successful result enters the newest-first evidence selector.
3. The runner synthesizes an answer against the substantive objective.
4. It emits answer text plus a `continuation` event containing the next cursor.
5. The frontend persists the state in the assistant message's existing `process` JSON.

### Bare “继续” request

1. The frontend sends normal history plus the latest assistant continuation property.
2. The runner validates the state and resolves the original objective.
3. Tool guidance supplies the saved document and offset.
4. The agent continues toward the original answer, using exact search when more appropriate.
5. A new state is emitted only if more document content remains after the new five-open limit.

### “Summarize all documents” request

1. The agent lists or otherwise establishes the file inventory.
2. It calls `query_kb(..., coverage="per_file")`.
3. Coverage retrieval supplies at least one hit per retrievable file and explicit missing-file metadata.
4. Clean synthesis preserves one candidate per covered file before taking duplicates.
5. The answer reports `covered/total` and does not silently omit a file.

## Error Handling and Security

- Continuation state is accepted only from history supplied through the existing authorized chat request and is revalidated against the current knowledge scope.
- A missing or malformed state falls back to textual history; it never causes an internal error.
- A stale cursor is clamped by `open_kb_document` as today. If it reaches end-of-file, the state is cleared and the answer reports completion.
- A file removed between turns returns the normal governed tool error and clears that stale continuation state.
- Coverage retrieval preserves tenant, knowledge-base, generation, and file filters on every global and targeted request.
- Targeted retrieval failures produce incomplete coverage metadata instead of aborting evidence from other files.
- Frontend persistence remains best-effort. If persistence fails, the current answer succeeds, while a later continuation falls back to textual intent without claiming a cursor was restored.

## Testing Strategy

### Engine runner tests

- The final `find_kb_document` result is present even after an earlier query contributes 10 evidence items.
- The final `open_kb_document` result is present in global iteration-limit synthesis.
- A bare continuation uses the stored hyperparameter objective in clean synthesis.
- A bare continuation starts with the stored file and next offset.
- Five opens still terminate the answer and emit a continuation event.
- Exact page claims such as “第5页” are absent unless page metadata actually supports them.
- Malformed, stale, and unauthorized continuation states are ignored safely.

### Knowledge-tool tests

- `open_kb_document` returns the exact next offset for full and final partial windows.
- Relevance mode retains the existing top-10 behavior.
- Per-file mode covers 11 indexed files even when global top results contain duplicate files.
- Targeted retrieval runs only for missing files.
- Missing and unavailable files are reported without fabricated evidence.
- The 30-file bound and stable ordering are enforced.

### Backend and frontend tests

- The proxy forwards continuation-bearing history without exposing private scope data.
- A continuation event updates the current assistant message.
- Assistant persistence stores the state in `process.agent_continuation`.
- Reloaded messages reconstruct history with only the latest continuation state.
- A new substantive request does not resend stale state as an active continuation.

### Regression verification

- Run the focused runner, knowledge-tool, backend proxy, and frontend chat tests.
- Run the complete Engine test suite affected by agent and retrieval changes.
- Manually replay the provided sequence: ask for all-paper summary, ask for hierarchical-anchoring hyperparameters, then send “继续” twice.
- Verify the summary reports 11/11 coverage, the first forced answer includes any hyperparameters already found, and each continuation advances from the saved cursor while keeping the hyperparameter objective.

## Rollout and Observability

Trace records add the effective objective source (`current`, `continuation_state`, or `history_fallback`), continuation file/cursor without document text, evidence candidate counts by kind, final selected counts, and coverage totals. These fields allow a future failure to show whether intent resolution, cursor restoration, evidence selection, or retrieval coverage failed.

The feature is backward compatible with messages that have no continuation state. No database migration or backfill is required.

