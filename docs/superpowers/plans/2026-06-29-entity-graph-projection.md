# Entity Graph Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Neo4j-backed entity and knowledge graph projection layer that indexes existing CKP/PKU/Source relationships, extracts bottom-layer entities from chunks/assets, and lets the agent resolve entity-centric questions such as `yanchaotan` -> `Yanchao Tan` with source-backed evidence.

**Architecture:** MySQL remains the source of truth for chunks, assets, PKU, CKP, governance state, and original text. Neo4j is a derived graph index containing `CKP`, `PKU`, `Source`, and `Entity` nodes plus explainable relationships with `source_kind`, `source_id`, `evidence_span`, `confidence`, and `extraction_method`. Retrieval uses graph lookup and expansion, then returns to MySQL for source evidence.

**Tech Stack:** Python, SQLAlchemy/MySQL, Neo4j Python driver, FastAPI service modules, pytest, Docker Compose, existing Prism engine/backend structure.

---

## File Structure

Create:
- `backend/app/models/entity.py` - MySQL audit tables for extracted entities, mentions, aliases, relations, and graph sync checkpoints.
- `backend/app/services/entity_extraction.py` - rule-first entity candidate extraction from `KnowledgeChunk`, `PersonalAssetItem`, and `PersonalAssetUnit`.
- `backend/app/services/entity_resolution.py` - normalization, alias candidate generation, deterministic merge keys, and confidence scoring.
- `backend/app/services/graph_client.py` - Neo4j connection wrapper and idempotent upsert helpers.
- `backend/app/services/graph_projection.py` - project MySQL CKP/PKU/Source/Entity rows into Neo4j.
- `backend/scripts/backfill_entity_graph.py` - CLI backfill for existing data.
- `engine/app/agent/tools/entity_graph_search.py` - agent tool for entity lookup, graph expansion, and MySQL evidence backtracking.
- `backend/tests/test_entity_extraction.py`
- `backend/tests/test_entity_resolution.py`
- `backend/tests/test_graph_projection.py`
- `engine/tests/test_entity_graph_search_tool.py`

Modify:
- `requirements.txt` - add `neo4j`.
- `.env.prod.example` - document Neo4j settings.
- `docker-compose.yml` and `docker-compose.prod.yml` - add Neo4j service.
- `backend/app/config.py` and `engine/app/config.py` - add Neo4j settings.
- `backend/app/models/__init__.py` - export entity models.
- `backend/app/utils/auto_migrate.py` - create entity tables in dev auto-migration.
- `backend/app/services/knowledge_governance.py` - trigger entity extraction/projection after document/asset governance.
- `engine/app/agent/tools/__init__.py` - register `entity_graph_search`.
- `engine/app/agent/prompts.py` - instruct agent to use entity graph for named-person/object questions before declaring not found.

---

## Graph Model

Neo4j node labels:
- `(:CKP {id, user_id, title, ckp_type, status, confidence})`
- `(:PKU {id, user_id, unit_type, statement_hash, confidence, status})`
- `(:Source {id, source_kind, source_id, item_id, title})`
- `(:Entity {id, user_id, entity_type, canonical_name, normalized_key, status, confidence})`
- `(:Alias {key, surface_text})`

Neo4j relationships:
- `(:CKP)-[:HAS_CHILD {confidence, reason, source_kind, source_id}]->(:CKP)`
- `(:CKP)-[:SUPPORTED_BY {relation_type, role, confidence}]->(:PKU)`
- `(:CKP)-[:RELATED_TO {relation_type, confidence, reason}]->(:CKP)`
- `(:PKU)-[:RELATED_TO {relation_type, confidence, reason}]->(:PKU)`
- `(:PKU)-[:EVIDENCED_BY {source_kind, source_id}]->(:Source)`
- `(:PKU)-[:MENTIONS_ENTITY {confidence, evidence_span}]->(:Entity)`
- `(:CKP)-[:ABOUT_ENTITY {confidence, evidence_span}]->(:Entity)`
- `(:Entity)-[:MENTIONED_IN {confidence, evidence_span, extraction_method}]->(:Source)`
- `(:Alias)-[:ALIAS_OF {confidence, extraction_method}]->(:Entity)`
- `(:Entity)-[:AUTHORED | AFFILIATED_WITH | EDUCATED_AT | HAS_EMAIL | CO_AUTHOR {confidence, evidence_span, source_kind, source_id}]->(:Entity)`

Do not duplicate CKP as generic `Entity`. CKP stays a first-class node label; Entity covers named objects such as people, organizations, papers, emails, projects, datasets, venues, and products.

---

## Execution Note

The original full plan was drafted in the main workspace. In this isolated worktree, execute the same migration as task batches:

1. Neo4j configuration and Docker wiring.
2. Entity audit models and normalization.
3. Rule-first source-layer entity extraction and persistence.
4. Neo4j graph client.
5. CKP/PKU/Source graph projection.
6. Entity graph projection.
7. Backfill CLI.
8. Entity graph search tool.
9. Governance integration and prompt update.
10. Badcase regression and full verification.

For each batch, follow TDD: write failing tests, verify red, implement minimal code, verify green, then commit.
