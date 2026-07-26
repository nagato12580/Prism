# Normalized Tool Results and Final-Iteration Synthesis Design

## Context

Knowledge tools use a production response envelope whose useful result is commonly stored at `payload.summary`, with evidence below `payload.summary.data`. The agent runner currently recognizes only flattened top-level `data`, `evidence`, and related keys. As a result, document-cap synthesis receives no excerpts and the runner can consider successful document reads ungrounded.

The global iteration limit has a second timing flaw: its current forced-answer branch runs before the final requested tool is executed and only when the stale grounding flag is true. If the flag is false, the final tool runs and the loop terminates with an internal iteration-limit error instead of an answer.

## Decision

Introduce one explicit tool-result normalizer and use it for evidence extraction throughout the runner. After all requested tools in the last global iteration execute, synthesize a final answer from the normalized evidence.

## Tool-Result Normalization

The normalizer accepts a decoded tool-result dictionary and returns the semantic result dictionary. It supports these contracts in priority order:

1. A production envelope at `payload.summary`.
2. A result dictionary at `payload.data`.
3. A result dictionary at `summary.data`.
4. The original top-level dictionary, including the existing flattened test contract.

Only dictionaries are accepted at each level. Strings, nulls, and malformed values fall back safely without raising.

Normalization remains explicit rather than recursively scanning arbitrary JSON. This prevents status messages, errors, and unrelated metadata from being mistaken for evidence.

## Evidence Collection

A shared evidence collector reads normalized results and extracts bounded text from:

- `data.content` for document windows;
- `data.evidence[].excerpt` for knowledge queries;
- `data.matches[].snippet` for document searches;
- existing top-level `sources`, `evidence`, `evidence_items`, `memories`, and `materials` contracts.

Duplicate text is removed while preserving tool-call order. Document-cap synthesis retains the most recent five valid windows and may include other relevant query or match evidence already obtained in the same answer.

`_payload_has_meaningful_evidence()` uses the same normalized representation. A non-empty document body, evidence excerpt, or match snippet marks the run as grounded.

## Document-Cap Synthesis

The existing clean two-message synthesis context remains in place. Its human message contains the current user query plus normalized, bounded evidence. Historical assistant messages, tool-call metadata, tool schemas, and raw `ToolMessage` objects remain excluded.

The per-file five-open cap and continuation prompt do not change. Structured or textual tool calls returned by synthesis continue to use the deterministic partial-answer fallback.

## Final Global Iteration

The pre-tool `iteration == max_iterations` forced-answer branch is removed. During the final iteration, every tool call requested by that model response executes normally. After the complete tool-call batch has been appended to the message history, the runner performs one clean, tool-free synthesis using the current query and all normalized evidence.

This post-tool synthesis occurs whether or not a previous grounding flag was set. If no usable evidence exists, the response must clearly state that limitation. Tool-call syntax from the synthesis response is rejected and replaced with a deterministic grounded or no-evidence fallback.

The trace records this pass as `forced_final_after_iteration_limit`, including the clean message roles and count. A successfully synthesized or deterministic partial response finishes the trace as success rather than emitting `Agent reached the maximum tool iteration limit`.

## Error Handling

- Malformed tool JSON remains ignored by evidence extraction.
- Tool execution errors remain represented in their `ToolMessage`; they are not treated as evidence.
- A final iteration containing multiple tool calls executes the entire batch before synthesis.
- An empty or tool-like synthesis response uses an evidence-based deterministic fallback, or the existing no-evidence response if nothing usable exists.

## Testing

Regression tests use production-shaped responses with `payload.summary.data` rather than only flattened fakes.

Required cases:

1. Five production-shaped document reads produce a clean synthesis message containing real excerpts.
2. Query evidence and find-document snippets are available to clean synthesis.
3. Production-shaped document content and query excerpts count as meaningful grounding evidence.
4. A tool requested in the final global iteration executes, then synthesis returns an answer without an iteration-limit error.
5. Multiple final-iteration tool calls all execute before synthesis.
6. Existing flattened responses, DSML suppression, the five-open cap, and continuation wording remain compatible.

## Out of Scope

- Changing the per-file limit of five.
- Changing the global maximum iteration count.
- Persisting document cursors across turns.
- Adding retries or a separate synthesis model.
- Changing knowledge-tool response contracts at their source.
