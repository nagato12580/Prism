# Agent Long-Term Memory Design

> Date: 2026-06-21
> Status: Draft pending user review
> Scope: Prism agent long-term memory module, phase 1 through later graph evolution

## 1. Goal

Prism needs a long-term memory system that lets the agent remember what the user cares about, what the user is exploring, what questions have been discussed repeatedly, and what project context has accumulated across conversations.

The target direction is a full long-term memory system rather than a small preference store. The system should eventually preserve atomic statements, entities, relations, events, lightweight insights, and later full user-profile reflections. Phase 1 focuses on conversation extraction while reserving the data model for knowledge assets and task execution traces.

## 2. Confirmed Product Decisions

- Memory shape: full long-term memory.
- Write policy: hybrid mode.
- Storage path: phased hybrid.
- Agent usage: active recall plus `memory_search`.
- Inputs: conversation, knowledge assets, and task execution traces in the long term; conversation extraction first.
- Auto-confirm policy: medium automation.
- Conflict handling: low-risk state changes can supersede old memory automatically; important identity, preference, and long-term goal conflicts go to review.
- Reflection: lightweight reflection in phase 1, later evolving into a complete user profile.
- Product experience: Memory Inbox first.

## 3. Architecture

Phase 1 uses a relational database, but models the domain as a graph abstraction so the same concepts can later map to Neo4j or another graph store.

The system has five chains.

### 3.1 Source Chain

Every memory must be traceable to its origin. Phase 1 uses chat messages as the only extraction source. The model reserves `source_type`, `source_id`, and source metadata for later sources:

- `chat_message`
- `knowledge_item`
- `wiki_entry`
- `asset_item`
- `task_run`
- `task_artifact`

Each memory should be able to answer: which conversation, which message, which text span, which extraction model, and which extraction run produced it.

### 3.2 Extraction Chain

After a chat exchange completes, Prism asynchronously extracts memory candidates.

The extraction flow is:

```text
ChatMessage saved
  -> enqueue memory extraction job
  -> extract atomic statements
  -> extract entities, relations, and events
  -> classify write policy
  -> create drafts
  -> auto-confirm safe drafts
  -> send uncertain or conflicting drafts to Memory Inbox
```

Extraction should use a small context window: the latest user message and assistant response, with the previous 3-5 messages included only when needed for pronoun or topic resolution.

Atomic statements are the first-class intermediate layer. Entity, relation, and event extraction should happen from statements rather than directly from long conversation text.

### 3.3 Governance Chain

Hybrid writing is the core safety and quality mechanism.

Auto-confirm candidates:

- Clear facts.
- Explicit user preferences.
- Current project context.
- Repeatedly mentioned topics.
- Continuing exploration directions.

Review-required candidates:

- High-level insights.
- Sensitive content.
- Low-confidence extraction.
- Inferred preferences or goals not explicitly stated by the user.
- Candidates that conflict with important existing memory.

The Memory Inbox supports confirm, reject, merge, and supersede operations.

### 3.4 Reflection Chain

Phase 1 reflection is lightweight and focused on exploration state, not a complete personality profile.

Reflection produces `memory_insight` records such as:

- Recent focus.
- Open questions.
- Next directions worth exploring.
- Current project context.

Later phases can evolve this into a full user profile layer with stable traits, goals, working style, and long-term interests.

### 3.5 Recall Chain

The agent uses memory through two tracks.

Active recall runs before each answer. It retrieves a small number of relevant confirmed memories and injects them into the system prompt as weak background context.

`memory_search` remains available as a tool for deeper lookup when the agent needs more detail.

Recall must be gated:

- Only use `confirmed` memories.
- Exclude `superseded`, `rejected`, and `archived` memories.
- Apply similarity and confidence thresholds.
- Apply a strict character budget.
- Skip recall on timeout or errors.
- Do not proactively inject sensitive memory unless the current query is clearly related.

## 4. Module Boundaries

`backend` owns:

- Persistence models.
- Memory review APIs.
- Memory Inbox API state transitions.
- Source traceability.
- Conflict governance.
- Compatibility with existing `MemoryEntry`.

`engine` owns:

- LLM extraction.
- Lightweight reflection.
- Active recall orchestration.
- Recall context formatting.
- Agent memory tools.

Phase 1 does not introduce Neo4j, but all names and concepts should remain graph-friendly.

## 5. Data Model

### 5.1 `memory_source`

Represents the origin of an extracted memory.

Important fields:

- `id`
- `user_id`
- `source_type`
- `source_id`
- `session_id`
- `message_id`
- `span_text`
- `occurred_at`
- `metadata`

### 5.2 `memory_statement`

Atomic statement layer. This is the key durable fact layer and the best review surface.

Important fields:

- `id`
- `user_id`
- `content`
- `statement_type`
- `temporal_type`
- `confidence`
- `importance`
- `status`
- `valid_from`
- `valid_until`
- `superseded_by_id`
- `source_id`

Suggested statement types:

- `fact`
- `preference`
- `goal`
- `project_context`
- `topic_interest`
- `decision`
- `question`
- `constraint`

Suggested temporal types:

- `stable`
- `current`
- `event_bound`
- `atemporal`

### 5.3 `memory_entity`

Represents people, projects, topics, technologies, preferences, goals, organizations, resources, and other named concepts.

Important fields:

- `id`
- `user_id`
- `name`
- `entity_type`
- `description`
- `aliases`
- `confidence`
- `importance`
- `mention_count`
- `status`
- `source_ids`

### 5.4 `memory_relation`

Represents structured relationships between entities.

Important fields:

- `id`
- `user_id`
- `subject_entity_id`
- `predicate`
- `object_entity_id`
- `statement_id`
- `confidence`
- `status`
- `valid_from`
- `valid_until`

Predicates should come from a controlled vocabulary to avoid relation-name drift.

### 5.5 `memory_event`

Represents time-bound events or decisions.

Important fields:

- `id`
- `user_id`
- `title`
- `description`
- `event_time`
- `event_type`
- `related_entity_ids`
- `statement_id`
- `confidence`
- `status`

### 5.6 `memory_insight`

Represents lightweight reflection output.

Important fields:

- `id`
- `user_id`
- `theme`
- `content`
- `insight_type`
- `source_statement_ids`
- `confidence`
- `importance`
- `valid_from`
- `updated_at`

Suggested insight types:

- `recent_focus`
- `open_question`
- `next_direction`
- `project_context`

### 5.7 `memory_draft`

The review queue and governance entry point.

Important fields:

- `id`
- `user_id`
- `draft_type`
- `payload`
- `decision_hint`
- `risk_level`
- `confidence`
- `status`
- `conflict_ids`
- `created_at`
- `reviewed_at`

Draft types should correspond to the target record type: `statement`, `entity`, `relation`, `event`, or `insight`.

### 5.8 Status Values

Use consistent status values across memory records:

- `draft`
- `confirmed`
- `rejected`
- `superseded`
- `archived`

## 6. Extraction and Review Flow

### 6.1 Extraction Window

The extraction job should avoid rescanning entire conversations on every turn. It should process the most recent exchange with a small context window when needed.

Each extraction run should record enough metadata to support debugging and later re-extraction:

- Prompt version.
- Model name.
- Source message IDs.
- Extraction time.
- Parse status.
- Error text when parsing fails.

### 6.2 Statement-First Extraction

The extractor should produce strict JSON. It should first produce atomic statements. A second extraction pass may derive entities, relations, and events from those statements.

This is safer than direct triple extraction because each memory can be reviewed as natural language and traced back to a source sentence.

### 6.3 Auto-Confirm Rules

Candidates can be auto-confirmed when they are:

- Clear and explicit.
- Low risk.
- High confidence.
- Not sensitive.
- Not in conflict with important confirmed memory.

Examples:

- "The user chose Memory Inbox first for phase 1."
- "Prism's memory design uses a phased hybrid storage path."

### 6.4 Review Rules

Candidates should go to Memory Inbox when they are:

- High-level interpretation.
- Sensitive.
- Low confidence.
- Ambiguous.
- Inferred rather than directly stated.
- Conflicting with stable identity, long-term goals, or important preferences.

### 6.5 Conflict Handling

When a new candidate conflicts with existing memory:

- Low-risk state changes may automatically mark the old record `superseded` and confirm the new record.
- Important conflicts create a draft with `conflict_ids`.
- The reviewer can confirm and supersede, confirm and keep both, or reject the candidate.

Superseded records remain available for audit but must not participate in default active recall.

### 6.6 Deduplication

Phase 1 should use a simple rule-plus-LLM strategy.

- Same-name same-type entities reuse the existing entity.
- Highly similar statements merge or add source support rather than duplicate.
- Controlled predicates reduce relation fragmentation.
- Ambiguous or low-confidence entity resolution goes to review.

## 7. Memory Inbox

Memory Inbox is the phase 1 product priority because the system uses hybrid writing.

The first version should support:

- List drafts by risk, type, status, and time.
- Show extracted content.
- Show source text.
- Show confidence and decision hint.
- Show conflicts with existing memory.
- Confirm draft.
- Reject draft.
- Merge with existing memory.
- Confirm and supersede existing memory.

The UI should make uncertainty visible. A reviewer should not need to inspect database rows to understand why a draft exists.

## 8. Active Recall

Before each agent answer, the engine should retrieve a compact memory context.

Suggested recall mix:

- Top 2 relevant `memory_insight` records.
- Top 5 relevant `memory_statement` records.
- Top 3 relevant `memory_entity` or relation facts.

Suggested prompt block:

```text
[Long-term memory about the user. Use only as background. Blend it in naturally and do not mention it unless useful.]
Recent focus: ...
Relevant facts: ...
Related projects/topics: ...
```

The block should be weakly worded. The model should not be forced to mention memory.

Recall constraints:

- Confirmed only.
- Exclude superseded records.
- Similarity threshold.
- Confidence threshold.
- Total length budget around 800-1200 Chinese characters.
- Timeout returns empty context.
- Errors return empty context.

The first implementation can use lexical search plus importance and recency when embeddings are unavailable. When an embedding client is configured, active recall should prefer hybrid retrieval: semantic similarity, lexical match, importance, and recency.

## 9. `memory_search` Tool

The current `memory_search` tool searches `MemoryEntry` with simple SQL `LIKE`. It should be upgraded to search the new memory model.

It should return:

- Matching statements.
- Related entities.
- Related relations or events.
- Relevant insights.
- Source citations.

The tool is for deeper lookup. Active recall is for natural background awareness.

## 10. Lightweight Reflection

Phase 1 reflection should summarize recent exploration, not infer a complete personality profile.

Triggers:

- Daily scheduled job.
- Confirmed statement count threshold.
- Manual user action.

Inputs:

- Recent confirmed statements.
- High-importance or high-mention entities.
- Active session titles and summaries.

Outputs:

- `recent_focus`
- `open_question`
- `next_direction`
- `project_context`

Example insights:

- "The user is currently designing Prism's long-term memory system, focusing on full extraction, hybrid review, active recall, and lightweight reflection."
- "The user is weighing a relational graph abstraction first, with later Neo4j migration."
- "A useful next step is to specify Memory Inbox and extraction quality evaluation."

Each insight must keep `source_statement_ids`.

## 11. Phased Implementation

### Phase 1: Memory Data Skeleton and Minimal Memory Inbox

Build the database models, review APIs, and a minimal Memory Inbox before connecting LLM extraction. This keeps the review surface ready before automatic extraction starts producing drafts.

Scope:

- Add new memory tables.
- Keep existing `MemoryEntry` compatibility.
- Add draft list, confirm, reject, merge, and supersede APIs.
- Add a minimal Memory Inbox UI for listing drafts, viewing source text, confirming, rejecting, and superseding.
- Add backend tests for source traceability and state transitions.
- Add focused frontend tests for the minimal review flow.

Acceptance:

- A draft can be manually created.
- A draft can be confirmed into durable memory.
- An old memory can be superseded.
- Superseded memory is excluded from default recall queries.
- The user can review manually created drafts in the frontend.

### Phase 2: Conversation Extraction MVP

Connect LLM extraction for chat sources only.

Scope:

- Trigger extraction after assistant response completion.
- Extract statements, entities, relations, and events.
- Classify candidates into auto-confirm or review.
- Implement basic deduplication and conflict detection.
- Use strict JSON schema prompts.
- Ensure extraction failure does not affect chat.

Acceptance:

- A real conversation creates memory drafts.
- Low-risk facts auto-confirm.
- Uncertain or conflicting candidates appear in Memory Inbox.

### Phase 3: Active Recall and Tool Upgrade

Make the agent use confirmed memory.

Scope:

- Add active recall orchestration in the engine.
- Inject a small memory context before each answer.
- Upgrade `memory_search` to search statements, entities, relations, events, and insights.
- Add thresholds, length budgets, timeout fallback, and source citations.

Acceptance:

- Asking "what did we decide before?" can use confirmed memory naturally.
- Recall failures do not block agent responses.

### Phase 4: Lightweight Reflection and Memory Inbox Enhancements

Complete the hybrid-writing product loop.

Scope:

- Generate `memory_insight` records.
- Add richer Memory Inbox filters.
- Improve conflict display and merge flow.
- Add manual reflection trigger.

Acceptance:

- The user can efficiently manage pending memory drafts by type, risk, status, and conflict state.
- The agent can use recent-focus and open-question insights in future answers.

## 12. Testing Strategy

### Backend Tests

Cover:

- Model defaults.
- Draft confirm and reject.
- Supersede behavior.
- Merge behavior.
- Source traceability.
- Basic conflict detection.
- Confirmed-only recall filtering.

### Engine Tests

Cover:

- Strict JSON parsing.
- Extraction failure fallback.
- Auto-confirm versus review classification.
- Recall ranking and gates.
- Recall timeout returning empty context.
- `memory_search` response shape and citations.

### Frontend Tests

Cover:

- Memory Inbox list rendering.
- Type/risk/status filters.
- Confirm and reject actions.
- Supersede conflict flow.
- Source text display.

## 13. Completion Standard

Phase 1 should not be judged by whether the full memory graph is complete. It should be judged by three closed loops:

- Prism can continuously extract long-term memory from conversation.
- Uncertain memory can be reviewed and governed in Memory Inbox.
- The agent can later use confirmed memory during conversation.

## 14. Later Neo4j Evolution

The relational phase should keep graph-friendly concepts so a later Neo4j sync is straightforward:

- `memory_source` maps to source nodes or provenance metadata.
- `memory_statement` maps to Statement nodes.
- `memory_entity` maps to Entity nodes.
- `memory_relation` maps to Entity-to-Entity edges.
- `memory_event` maps to Event nodes.
- `memory_insight` maps to Insight nodes with derived-from edges.

The first migration target should be read-side graph recall, not necessarily replacing all relational persistence immediately.
