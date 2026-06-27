# Prism Deep Knowledge Search Interview Design

## Problem

The old `knowledge_search` path can search raw chunks early, which is expensive and noisy for a large personal knowledge base. The redesign makes the agent search governed knowledge first: CKP and PKU define the candidate scope, then source-backed evidence is collected only inside that scope.

## Architecture

The main chat agent does not run the deep loop directly. It receives a tool named `deep_knowledge_search` only when the user enables the chat toggle. The tool runs a central `DeepSearchOrchestrator` with two in-process A2A-shaped agents:

- `SearcherAgent`: finds scope and retrieves evidence.
- `JudgeAgent`: scores completeness and emits follow-up directives.

The judge does not search. This keeps evaluation separate from retrieval and prevents the judge from confirming its own assumptions.

## Retrieval Flow

1. Scope Finder searches CKP and PKU metadata, statements, keywords, concepts, and entities.
2. Source Backtrack maps seed CKP/PKU to PKU source anchors such as `document_chunk`.
3. EvidencePool dedupes evidence and scores retrieval score, relation confidence, knowledge confidence, source quality, coverage, scope distance, strategy penalty, and relation penalty.
4. Judge evaluates coverage, grounding, source diversity, conflict handling, and structure handling.
5. If incomplete, Searcher follows judge directives: PKU re-query, PKU graph expansion, or CKP re-scope.

## Why Scope-First

The PKU is the unit that mounts raw document chunks or assets, so it is the right bridge between semantic governance and original evidence. Starting with CKP/PKU avoids full-library chunk search for English or Chinese questions that belong to a specific knowledge area.

## Current Capabilities

- Find governed topics and evidence without global chunk search first.
- Trace answers from CKP to PKU to source chunks.
- Expand same-level PKU relations when evidence is incomplete.
- Score evidence with multidimensional quality signals.
- Expose deep search only when the user enables it.
- Produce benchmarkable metrics for recall, judge accuracy, latency, iterations, and fallback rate.

## Future Extensions

- Replace deterministic judge with a structured LLM judge using the same JSON schema.
- Add scoped chunk vector search after CKP/PKU scope is known.
- Add a graph database backend if SQL traversal becomes too slow.
- Link memory search as a separate optional channel, not part of v1 governed search.

