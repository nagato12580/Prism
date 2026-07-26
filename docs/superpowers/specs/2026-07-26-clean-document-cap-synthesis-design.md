# Clean Document-Cap Synthesis Design

## Context

`LangChainAgentRunner` stops opening the same knowledge-base document after five calls in one answer. It then asks the model for a final partial answer. The current forced-final invocation reuses the complete agent message history, including prior assistant tool calls and `ToolMessage` results. With `deepseek-v4-flash`, that history can cause the model to emit another DSML tool call as plain text instead of answering the user.

This change addresses only the forced synthesis performed after the per-file document-open cap. The five-call limit, continuation behavior, cursor behavior, DSML detection, and partial-answer fallback remain unchanged.

## Decision

Build a new, tool-free synthesis context instead of filtering or reusing the agent conversation.

The synthesis invocation receives exactly:

1. A `SystemMessage` that instructs the model to answer from the supplied excerpts, disclose that the document is incomplete, avoid tools and tool-call syntax, and invite the user to continue.
2. A `HumanMessage` containing the current user query and the excerpts from the most recent five successful document windows.

The original assistant messages, tool-call metadata, tool schemas, and `ToolMessage` objects are not included.

## Components

### Document-window extraction

A pure helper extracts valid document windows from the runner messages. It accepts only JSON tool results whose `data` object contains non-empty `content` and `file_uid`. It retains the existing offset and `has_more_after` metadata and selects the most recent five windows.

The existing deterministic partial-answer fallback will reuse the same extracted representation where practical, avoiding two subtly different parsers for the same tool results.

### Clean synthesis message construction

A pure helper accepts the current user query and extracted windows, then returns the two-message synthesis context. Excerpts are normalized and bounded using the same per-window truncation currently used by the fallback so the forced call cannot grow without limit.

### Runner integration

When `_record_open_kb_document_call()` reaches `OPEN_KB_DOCUMENT_PER_FILE_LIMIT`, the runner invokes `self.model` with the clean synthesis messages. It continues to inspect both structured tool calls and textual DSML. If the response attempts another tool call or contains no usable text, the existing deterministic partial-document answer is returned.

Trace steps keep the `forced_final_after_open_limit` iteration marker. Their message count and roles describe the clean synthesis invocation rather than the original agent history.

## Error Handling

- Missing or malformed tool-result JSON is ignored during extraction.
- If no valid document windows can be extracted, the existing fixed partial-document fallback remains available.
- Structured or textual tool calls from the forced synthesis are rejected exactly as today.
- No retry or second model is introduced in this change.

## Testing

Add a regression test that drives five successful `open_kb_document` calls and captures the sixth, forced-final model invocation. The test asserts that:

- the forced invocation contains exactly one system and one human message;
- it contains no `ToolMessage`, historical `AIMessage`, or tool-call metadata;
- the human message contains the current query and extracted document content;
- a normal synthesis response is emitted as the final answer;
- the five-call cap and continuation wording remain intact.

Existing DSML-suppression and partial-fallback tests remain passing.

## Out of Scope

- Changing `OPEN_KB_DOCUMENT_PER_FILE_LIMIT`.
- Removing the “continue” interaction.
- Persisting a cross-turn document cursor or incremental summary.
- Changing normal knowledge retrieval or the general maximum-iteration fallback.
- Introducing a separate model configuration or summarization service.
