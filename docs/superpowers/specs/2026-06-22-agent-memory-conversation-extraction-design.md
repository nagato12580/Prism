# Agent Memory Conversation Extraction Phase 2 Design

> Date: 2026-06-22
> Status: Approved for implementation
> Scope: Prism agent long-term memory Phase 2, conversation-to-memory extraction

## 1. Goal

Phase 2 closes the first real memory loop: Prism can read saved conversation history, extract candidate long-term memories, and place uncertain or review-worthy candidates into Memory Inbox.

The target flow is:

```text
chat_session / chat_message
  -> extraction trigger
  -> LLM candidate extraction
  -> memory_source + memory_draft
  -> Memory Inbox review
  -> confirmed memory_statement
```

This phase intentionally stops at draft creation and statement confirmation. Active recall, full user profile generation, graph relation extraction, and Neo4j sync remain later phases.

## 2. Product Behavior

### 2.1 Manual Extraction First

Phase 2 adds a manual backend endpoint:

```text
POST /api/v1/memories/extract/session/{session_id}
```

This lets a reviewer or developer extract memory candidates from a specific conversation on demand. The endpoint returns:

- session id
- number of messages scanned
- number of candidates returned by extraction
- number of drafts created
- number of candidates skipped
- created draft objects

Manual extraction is the primary Phase 2 verification path because it is debuggable and does not surprise users during normal chat.

### 2.2 Optional Automatic Extraction

Automatic extraction is supported behind an environment flag:

```text
MEMORY_EXTRACTION_AUTO_ENABLED=1
```

When enabled, saving an assistant message can trigger extraction for that session. The attempt is best-effort:

- It must not block the chat API response.
- It must not fail message persistence if extraction fails.
- It should be idempotent enough that repeated calls do not create obvious duplicates.

The default is disabled.

### 2.3 Statement-Only Candidates

Phase 2 extracts only statement memories. Each candidate becomes a `memory_draft` with:

- `draft_type = "statement"`
- `payload.content`
- `payload.statement_type`
- `payload.temporal_type`
- `payload.importance`
- `decision_hint`
- `risk_level`
- `confidence`
- `conflict_ids`
- `source` linked to a concrete chat message

Supported `statement_type` values are flexible strings, but the prompt and parser prefer:

- `preference`
- `goal`
- `constraint`
- `decision`
- `current_focus`
- `project_context`
- `interest`
- `fact`

Supported `temporal_type` values:

- `stable`
- `current`
- `episodic`

## 3. Extraction Policy

The extractor should remember durable user and project context, not every line of conversation.

Good candidates:

- Explicit preferences: "I prefer review-first memory."
- Long-term goals: "I want the agent to remember what topics I care about."
- Constraints: "Do not touch Docker deployment while debugging locally."
- Decisions: "Phase 1 will implement conversation extraction first."
- Current focus: "The user is designing Prism's long-term memory system."
- Repeated interests: "The user is exploring AI tools, PKU/CKP, and fine-tuning."

Bad candidates:

- Temporary phrasing or one-off commands.
- Assistant implementation details that are not user-relevant.
- Secrets, passwords, tokens, or credentials.
- Low-signal acknowledgements.
- Raw copied stack traces unless they express a durable project constraint.

## 4. Architecture

### 4.1 Prompt Module

Create:

```text
backend/app/prompts/memory_extraction.py
```

It builds OpenAI-compatible chat messages for extraction. The prompt requires strict JSON:

```json
{
  "candidates": [
    {
      "content": "...",
      "statement_type": "preference",
      "temporal_type": "stable",
      "confidence": 0.86,
      "importance": 0.8,
      "risk_level": "medium",
      "decision_hint": "review",
      "evidence_message_id": "..."
    }
  ]
}
```

### 4.2 Extraction Service

Create:

```text
backend/app/services/memory_extraction.py
```

Responsibilities:

- Load recent messages for a session.
- Format messages for LLM extraction.
- Call the configured OpenAI-compatible LLM.
- Parse JSON robustly, including fenced JSON.
- Normalize and validate candidates.
- Skip duplicates against existing confirmed statements and draft payload content.
- Create `MemorySource` and `MemoryDraft` rows.
- Return a structured result object.

The service owns extraction logic. API routes and chat persistence should call this service rather than duplicating behavior.

### 4.3 API Route

Extend:

```text
backend/app/api/memories.py
```

Add:

```text
POST /memories/extract/session/{session_id}
```

Optional request payload:

```json
{
  "limit": 20
}
```

### 4.4 Optional Chat Hook

Extend:

```text
backend/app/api/chat.py
```

After an assistant message is saved, if `settings.MEMORY_EXTRACTION_AUTO_ENABLED` is true, start a daemon thread that calls the extraction service with a new database session.

This hook must swallow extraction exceptions after logging them.

## 5. Deduplication

Phase 2 uses simple deterministic deduplication:

- Normalize content by lowercasing and collapsing whitespace.
- Skip if an existing confirmed `MemoryStatement` has the same normalized content.
- Skip if an existing draft `payload.content` has the same normalized content.

Semantic similarity and conflict detection are later enhancements.

## 6. Failure Handling

If LLM configuration is missing, manual extraction returns a clear API error.

If LLM returns invalid JSON, manual extraction returns a clear API error.

If automatic extraction fails, message persistence still succeeds.

If a candidate lacks valid content, it is skipped, not written.

## 7. Testing Strategy

Backend tests cover:

- Prompt includes recent message context and strict schema instructions.
- Parser accepts JSON and fenced JSON.
- Invalid candidates are skipped.
- Manual endpoint creates `memory_source` and `memory_draft` from chat history.
- Manual endpoint deduplicates existing draft/confirmed memory.
- Missing session returns 404.
- Auto extraction hook runs only when enabled and never breaks message creation.

Frontend changes are not required in Phase 2 because Memory Inbox already lists drafts.

## 8. Out of Scope

- Active recall upgrade.
- `memory_search` migration from `memory_entry` to `memory_statement`.
- Entity/relation/event automatic extraction.
- Lightweight reflection generation from statements.
- Full user profile synthesis.
- Neo4j sync.
- Advanced Memory Inbox merge UI.
