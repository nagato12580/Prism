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

### Task 1: Add Neo4j Configuration And Dependencies

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.prod.example`
- Modify: `backend/app/config.py`
- Modify: `engine/app/config.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Write failing config tests**

Add to `backend/tests/test_config.py`:

```python
import os


def test_backend_neo4j_settings_exist(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    from backend.app.config import Settings

    settings = Settings()
    assert settings.NEO4J_URI == "bolt://neo4j:7687"
    assert settings.NEO4J_USERNAME == "neo4j"
    assert settings.NEO4J_PASSWORD == "password"
    assert settings.NEO4J_DATABASE == "neo4j"
```

Add to `engine/tests/test_config.py`:

```python
def test_engine_neo4j_settings_exist(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    from engine.app.config import Settings

    settings = Settings()
    assert settings.NEO4J_URI == "bolt://neo4j:7687"
    assert settings.NEO4J_USERNAME == "neo4j"
    assert settings.NEO4J_PASSWORD == "password"
    assert settings.NEO4J_DATABASE == "neo4j"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest backend/tests/test_config.py engine/tests/test_config.py -q
```

Expected: both tests fail with missing `NEO4J_URI` attribute.

- [ ] **Step 3: Add dependency and settings**

Append to `requirements.txt`:

```text
neo4j==5.28.1
```

Add to both `backend/app/config.py` and `engine/app/config.py` inside `Settings`:

```python
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME: str = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")
    ENTITY_GRAPH_ENABLED: bool = os.getenv("ENTITY_GRAPH_ENABLED", "0") == "1"
```

Add to `.env.prod.example`:

```text
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=change-me
NEO4J_DATABASE=neo4j
ENTITY_GRAPH_ENABLED=0
```

- [ ] **Step 4: Add Neo4j service**

Add to `docker-compose.yml`:

```yaml
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/password
    volumes:
      - neo4j_data:/data
```

Add `neo4j_data:` under `volumes`.

Add to `docker-compose.prod.yml`:

```yaml
  neo4j:
    image: neo4j:5-community
    environment:
      - NEO4J_AUTH=${NEO4J_USERNAME:-neo4j}/${NEO4J_PASSWORD:-change-me}
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 >/dev/null || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 20
```

Add `neo4j_data:` under `volumes`. Add these environment overrides to `backend` and `engine` services:

```yaml
      NEO4J_URI: "bolt://neo4j:7687"
      NEO4J_USERNAME: "${NEO4J_USERNAME:-neo4j}"
      NEO4J_PASSWORD: "${NEO4J_PASSWORD:-change-me}"
      NEO4J_DATABASE: "${NEO4J_DATABASE:-neo4j}"
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
pytest backend/tests/test_config.py engine/tests/test_config.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.prod.example docker-compose.yml docker-compose.prod.yml backend/app/config.py engine/app/config.py backend/tests/test_config.py engine/tests/test_config.py
git commit -m "chore: add neo4j graph configuration"
```

---

### Task 2: Add MySQL Entity Audit Models

**Files:**
- Create: `backend/app/models/entity.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`
- Test: `backend/tests/test_entity_models.py`

- [ ] **Step 1: Write failing model test**

Create `backend/tests/test_entity_models.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import KnowledgeEntity, EntityMention, EntityAlias, EntityRelation


def test_entity_models_persist_alias_mentions_and_relations():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    person = KnowledgeEntity(
        user_id="default-user",
        entity_type="person",
        canonical_name="Yanchao Tan",
        normalized_key="yanchaotan",
        aliases=["yanchaotan"],
        confidence=0.92,
        status="active",
    )
    paper = KnowledgeEntity(
        user_id="default-user",
        entity_type="paper",
        canonical_name="OpenViewer",
        normalized_key="openviewer",
        aliases=[],
        confidence=0.9,
        status="active",
    )
    db.add_all([person, paper])
    db.flush()

    db.add(EntityAlias(entity_id=person.id, alias="yanchaotan", normalized_key="yanchaotan", confidence=0.95))
    db.add(
        EntityMention(
            entity_id=person.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            chunk_id="chunk-1",
            surface_text="Yanchao Tan",
            normalized_key="yanchaotan",
            evidence_span="Zihan Fang, Yanchao Tan, Changwei Wang",
            confidence=0.95,
            extraction_method="rule_author_list",
        )
    )
    db.add(
        EntityRelation(
            subject_entity_id=person.id,
            predicate="authored",
            object_entity_id=paper.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            evidence_span="Yanchao Tan ... OpenViewer",
            confidence=0.88,
            extraction_method="rule_author_list",
        )
    )
    db.commit()

    assert db.query(KnowledgeEntity).count() == 2
    assert db.query(EntityAlias).first().normalized_key == "yanchaotan"
    assert db.query(EntityMention).first().surface_text == "Yanchao Tan"
    assert db.query(EntityRelation).first().predicate == "authored"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest backend/tests/test_entity_models.py -q
```

Expected: import error for `KnowledgeEntity`.

- [ ] **Step 3: Create entity models**

Create `backend/app/models/entity.py`:

```python
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entity"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "normalized_key", name="uq_entity_user_type_key"),
        Index("ix_entity_lookup", "user_id", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    canonical_name = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    aliases = Column(JSON, default=list)
    description = Column(Text)
    confidence = Column(Float, default=0.5)
    status = Column(String(32), default="active", index=True)
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    aliases_rel = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")
    mentions = relationship("EntityMention", back_populates="entity", cascade="all, delete-orphan")


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_key", name="uq_entity_alias_key"),
        Index("ix_entity_alias_lookup", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    created_at = Column(DateTime, default=local_now)

    entity = relationship("KnowledgeEntity", back_populates="aliases_rel")


class EntityMention(Base):
    __tablename__ = "entity_mention"
    __table_args__ = (
        UniqueConstraint("entity_id", "source_kind", "source_id", "surface_text", name="uq_entity_mention_source_surface"),
        Index("ix_entity_mention_source", "source_kind", "source_id"),
        Index("ix_entity_mention_key", "normalized_key"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    source_kind = Column(String(64), nullable=False, index=True)
    source_id = Column(CHAR(36), nullable=False, index=True)
    item_id = Column(CHAR(36), default="", index=True)
    chunk_id = Column(CHAR(36), default="", index=True)
    surface_text = Column(String(512), nullable=False)
    normalized_key = Column(String(512), nullable=False, index=True)
    evidence_span = Column(Text)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)

    entity = relationship("KnowledgeEntity", back_populates="mentions")


class EntityRelation(Base):
    __tablename__ = "entity_relation"
    __table_args__ = (
        UniqueConstraint(
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            "object_literal",
            "source_kind",
            "source_id",
            name="uq_entity_relation_evidence",
        ),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    subject_entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    predicate = Column(String(128), nullable=False, index=True)
    object_entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=True, index=True)
    object_literal = Column(Text)
    source_kind = Column(String(64), nullable=False, index=True)
    source_id = Column(CHAR(36), nullable=False, index=True)
    evidence_span = Column(Text)
    confidence = Column(Float, default=0.5)
    extraction_method = Column(String(128), default="")
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)
```

- [ ] **Step 4: Export models**

Modify `backend/app/models/__init__.py`:

```python
from .entity import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation
```

Add these names to `__all__`.

- [ ] **Step 5: Ensure auto migration imports models**

Open `backend/app/utils/auto_migrate.py`. If it imports `backend.app.models`, no extra table-specific code is needed. If it imports explicit model modules, add:

```python
from backend.app.models.entity import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation  # noqa: F401
```

- [ ] **Step 6: Run model test**

Run:

```bash
pytest backend/tests/test_entity_models.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/entity.py backend/app/models/__init__.py backend/app/utils/auto_migrate.py backend/tests/test_entity_models.py
git commit -m "feat: add entity audit models"
```

---

### Task 3: Implement Entity Normalization And Alias Generation

**Files:**
- Create: `backend/app/services/entity_resolution.py`
- Test: `backend/tests/test_entity_resolution.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_entity_resolution.py`:

```python
from backend.app.services.entity_resolution import normalize_entity_key, alias_keys_for_surface


def test_normalize_entity_key_compacts_latin_names():
    assert normalize_entity_key("Yanchao Tan") == "yanchaotan"
    assert normalize_entity_key(" yctan@fzu.edu.cn ") == "yctanfzueducn"


def test_alias_keys_for_latin_person_generates_name_orders():
    aliases = alias_keys_for_surface("Yanchao Tan", entity_type="person")
    assert "yanchaotan" in aliases
    assert "tanyanchao" in aliases


def test_alias_keys_for_chinese_surface_keeps_original_key():
    aliases = alias_keys_for_surface("谭谚超", entity_type="person")
    assert "谭谚超" in aliases
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
pytest backend/tests/test_entity_resolution.py -q
```

Expected: import error for `entity_resolution`.

- [ ] **Step 3: Implement normalization**

Create `backend/app/services/entity_resolution.py`:

```python
from __future__ import annotations

import re


def normalize_entity_key(text: str) -> str:
    value = (text or "").strip().lower()
    if re.fullmatch(r"[\u4e00-\u9fff]+", value):
        return value
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)


def alias_keys_for_surface(surface: str, entity_type: str = "") -> list[str]:
    surface = (surface or "").strip()
    primary = normalize_entity_key(surface)
    aliases: list[str] = []
    if primary:
        aliases.append(primary)

    words = re.findall(r"[A-Za-z][A-Za-z'.-]*", surface)
    if entity_type == "person" and len(words) == 2:
        given_family = normalize_entity_key("".join(words))
        family_given = normalize_entity_key(words[1] + words[0])
        for candidate in [given_family, family_given]:
            if candidate and candidate not in aliases:
                aliases.append(candidate)

    return aliases
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest backend/tests/test_entity_resolution.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/entity_resolution.py backend/tests/test_entity_resolution.py
git commit -m "feat: add entity normalization helpers"
```

---

### Task 4: Implement Rule-First Entity Extraction From Source Layers

**Files:**
- Create: `backend/app/services/entity_extraction.py`
- Test: `backend/tests/test_entity_extraction.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_entity_extraction.py`:

```python
from backend.app.services.entity_extraction import extract_entity_candidates_from_text


def test_extracts_paper_authors_email_and_organizations_from_paper_front_matter():
    text = (
        "OpenViewer: Openness-Aware Multi-View Learning\n"
        "Shide Du1,2, Zihan Fang1,2, Yanchao Tan1,2, Changwei Wang3, Shiping Wang1,2\n"
        "1 College of Computer and Data Science, Fuzhou University, Fuzhou, China\n"
        "dushidems@gmail.com, fzihan11@163.com, yctan@fzu.edu.cn, shipingwangphd@163.com\n"
    )

    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")
    by_name = {(item.entity_type, item.surface_text) for item in candidates}

    assert ("paper", "OpenViewer: Openness-Aware Multi-View Learning") in by_name
    assert ("person", "Yanchao Tan") in by_name
    assert ("person", "Shiping Wang") in by_name
    assert ("organization", "Fuzhou University") in by_name
    assert ("email", "yctan@fzu.edu.cn") in by_name


def test_extracts_education_relation_candidates_from_author_bio():
    text = (
        "Yanchao Tan received the Ph.D. degree from the College of Computer Science, "
        "Zhejiang University, Hangzhou, China. She is currently a Lecturer with Fuzhou University."
    )

    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")
    relations = [item for item in candidates if item.kind == "relation"]

    assert any(item.subject == "Yanchao Tan" and item.predicate == "educated_at" and item.object_surface == "Zhejiang University" for item in relations)
    assert any(item.subject == "Yanchao Tan" and item.predicate == "affiliated_with" and item.object_surface == "Fuzhou University" for item in relations)
```

- [ ] **Step 2: Run tests to verify fail**

Run:

```bash
pytest backend/tests/test_entity_extraction.py -q
```

Expected: import error for `entity_extraction`.

- [ ] **Step 3: Implement candidate dataclass and extraction rules**

Create `backend/app/services/entity_extraction.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key


@dataclass(frozen=True)
class EntityCandidate:
    kind: str
    entity_type: str = ""
    surface_text: str = ""
    normalized_key: str = ""
    aliases: list[str] | None = None
    evidence_span: str = ""
    confidence: float = 0.5
    extraction_method: str = ""
    subject: str = ""
    predicate: str = ""
    object_surface: str = ""


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_LATIN_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_ORG_RE = re.compile(r"\b(?:[A-Z][A-Za-z&.-]+\s+){0,6}(?:University|College|Institute|Laboratory|Academy|School)\b(?:\s+of\s+(?:[A-Z][A-Za-z&.-]+\s*){1,6})?")


def extract_entity_candidates_from_text(text: str, source_kind: str) -> list[EntityCandidate]:
    text = text or ""
    candidates: list[EntityCandidate] = []
    candidates.extend(_extract_title_candidate(text))
    candidates.extend(_extract_emails(text))
    candidates.extend(_extract_latin_people(text))
    candidates.extend(_extract_organizations(text))
    candidates.extend(_extract_bio_relations(text))
    return _dedupe_candidates(candidates)


def _candidate(entity_type: str, surface: str, span: str, confidence: float, method: str) -> EntityCandidate:
    return EntityCandidate(
        kind="entity",
        entity_type=entity_type,
        surface_text=surface,
        normalized_key=normalize_entity_key(surface),
        aliases=alias_keys_for_surface(surface, entity_type=entity_type),
        evidence_span=span[:800],
        confidence=confidence,
        extraction_method=method,
    )


def _extract_title_candidate(text: str) -> list[EntityCandidate]:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if ":" in first_line and len(first_line) <= 160:
        return [_candidate("paper", first_line, first_line, 0.82, "rule_first_line_title")]
    return []


def _extract_emails(text: str) -> list[EntityCandidate]:
    return [_candidate("email", match.group(0), _window(text, match.start(), match.end()), 0.98, "rule_email") for match in _EMAIL_RE.finditer(text)]


def _extract_latin_people(text: str) -> list[EntityCandidate]:
    results = []
    for match in _LATIN_NAME_RE.finditer(text):
        surface = re.sub(r"\s+", " ", match.group(0)).strip()
        if any(word in surface for word in ["College", "Science", "University", "Learning"]):
            continue
        results.append(_candidate("person", surface, _window(text, match.start(), match.end()), 0.78, "rule_latin_person"))
    return results


def _extract_organizations(text: str) -> list[EntityCandidate]:
    results = []
    for match in _ORG_RE.finditer(text):
        surface = re.sub(r"\s+", " ", match.group(0)).strip(" ,.")
        if len(surface) < 4:
            continue
        results.append(_candidate("organization", surface, _window(text, match.start(), match.end()), 0.78, "rule_organization"))
    return results


def _extract_bio_relations(text: str) -> list[EntityCandidate]:
    results: list[EntityCandidate] = []
    person_match = _LATIN_NAME_RE.search(text)
    if not person_match:
        return results
    person = person_match.group(0)

    education_match = re.search(r"received\s+the\s+Ph\.?D\.?\s+degree\s+from.*?\b([A-Z][A-Za-z&.-]+(?:\s+[A-Z][A-Za-z&.-]+)*\s+University)\b", text)
    if education_match:
        org = education_match.group(1)
        results.append(
            EntityCandidate(
                kind="relation",
                subject=person,
                predicate="educated_at",
                object_surface=org,
                evidence_span=_window(text, education_match.start(), education_match.end()),
                confidence=0.84,
                extraction_method="rule_author_bio_education",
            )
        )

    affiliation_match = re.search(r"currently\s+a\s+.+?\s+with\s+([A-Z][A-Za-z&.-]+(?:\s+[A-Z][A-Za-z&.-]+)*\s+University)\b", text)
    if affiliation_match:
        org = affiliation_match.group(1)
        results.append(
            EntityCandidate(
                kind="relation",
                subject=person,
                predicate="affiliated_with",
                object_surface=org,
                evidence_span=_window(text, affiliation_match.start(), affiliation_match.end()),
                confidence=0.82,
                extraction_method="rule_author_bio_affiliation",
            )
        )
    return results


def _window(text: str, start: int, end: int, radius: int = 160) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius): min(len(text), end + radius)]).strip()


def _dedupe_candidates(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[EntityCandidate] = []
    for item in candidates:
        key = (item.kind, item.entity_type, item.normalized_key, item.predicate + item.subject + item.object_surface)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
```

- [ ] **Step 4: Run extraction tests**

Run:

```bash
pytest backend/tests/test_entity_extraction.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/entity_extraction.py backend/tests/test_entity_extraction.py
git commit -m "feat: extract source-layer entity candidates"
```

---

### Task 5: Persist Entity Extraction Results

**Files:**
- Modify: `backend/app/services/entity_extraction.py`
- Test: `backend/tests/test_entity_extraction.py`

- [ ] **Step 1: Write failing persistence test**

Append to `backend/tests/test_entity_extraction.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import KnowledgeEntity, EntityMention, EntityRelation
from backend.app.services.entity_extraction import extract_and_settle_entities


def test_extract_and_settle_entities_persists_entities_mentions_and_relations():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    text = (
        "Yanchao Tan received the Ph.D. degree from the College of Computer Science, "
        "Zhejiang University. She is currently a Lecturer with Fuzhou University."
    )

    result = extract_and_settle_entities(
        db,
        source_kind="document_chunk",
        source_id="chunk-1",
        item_id="item-1",
        chunk_id="chunk-1",
        text=text,
    )

    assert result.entity_count >= 3
    assert result.mention_count >= 3
    assert result.relation_count >= 2
    assert db.query(KnowledgeEntity).filter(KnowledgeEntity.normalized_key == "yanchaotan").first()
    assert db.query(EntityMention).filter(EntityMention.surface_text == "Yanchao Tan").first()
    assert db.query(EntityRelation).filter(EntityRelation.predicate == "educated_at").first()
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_entity_extraction.py::test_extract_and_settle_entities_persists_entities_mentions_and_relations -q
```

Expected: import error for `extract_and_settle_entities`.

- [ ] **Step 3: Implement persistence**

Append to `backend/app/services/entity_extraction.py`:

```python
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models.entity import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation


@dataclass(frozen=True)
class EntitySettlementResult:
    entity_count: int
    mention_count: int
    relation_count: int


def extract_and_settle_entities(
    db: Session,
    *,
    source_kind: str,
    source_id: str,
    text: str,
    item_id: str = "",
    chunk_id: str = "",
    user_id: str = "default-user",
) -> EntitySettlementResult:
    candidates = extract_entity_candidates_from_text(text, source_kind=source_kind)
    entity_by_surface: dict[str, KnowledgeEntity] = {}
    entity_ids: set[str] = set()
    mention_ids: set[str] = set()
    relation_ids: set[str] = set()

    for item in candidates:
        if item.kind != "entity":
            continue
        entity = _get_or_create_entity(db, user_id=user_id, candidate=item)
        entity_by_surface[item.surface_text] = entity
        entity_ids.add(entity.id)
        for alias in item.aliases or []:
            _get_or_create_alias(db, entity=entity, alias=item.surface_text, normalized_key=alias, confidence=item.confidence, method=item.extraction_method)
        mention = _get_or_create_mention(
            db,
            entity=entity,
            source_kind=source_kind,
            source_id=source_id,
            item_id=item_id,
            chunk_id=chunk_id,
            candidate=item,
        )
        mention_ids.add(mention.id)

    for item in candidates:
        if item.kind != "relation":
            continue
        subject = entity_by_surface.get(item.subject) or _find_entity_by_surface(db, user_id, item.subject, "person")
        obj = entity_by_surface.get(item.object_surface) or _find_entity_by_surface(db, user_id, item.object_surface, "organization")
        if not subject or not obj:
            continue
        relation = _get_or_create_relation(
            db,
            subject=subject,
            predicate=item.predicate,
            obj=obj,
            source_kind=source_kind,
            source_id=source_id,
            evidence_span=item.evidence_span,
            confidence=item.confidence,
            method=item.extraction_method,
        )
        relation_ids.add(relation.id)

    db.flush()
    return EntitySettlementResult(len(entity_ids), len(mention_ids), len(relation_ids))
```

Also add helper functions in the same file:

```python
def _get_or_create_entity(db: Session, *, user_id: str, candidate: EntityCandidate) -> KnowledgeEntity:
    row = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.user_id == user_id,
            KnowledgeEntity.entity_type == candidate.entity_type,
            KnowledgeEntity.normalized_key == candidate.normalized_key,
        )
        .first()
    )
    if row:
        return row
    row = KnowledgeEntity(
        user_id=user_id,
        entity_type=candidate.entity_type,
        canonical_name=candidate.surface_text,
        normalized_key=candidate.normalized_key,
        aliases=candidate.aliases or [],
        confidence=candidate.confidence,
        status="active",
        extra_meta={"extraction_method": candidate.extraction_method},
    )
    db.add(row)
    db.flush()
    return row


def _get_or_create_alias(db: Session, *, entity: KnowledgeEntity, alias: str, normalized_key: str, confidence: float, method: str) -> EntityAlias:
    row = db.query(EntityAlias).filter(EntityAlias.entity_id == entity.id, EntityAlias.normalized_key == normalized_key).first()
    if row:
        return row
    row = EntityAlias(entity_id=entity.id, alias=alias, normalized_key=normalized_key, confidence=confidence, extraction_method=method)
    db.add(row)
    db.flush()
    return row


def _get_or_create_mention(
    db: Session,
    *,
    entity: KnowledgeEntity,
    source_kind: str,
    source_id: str,
    item_id: str,
    chunk_id: str,
    candidate: EntityCandidate,
) -> EntityMention:
    row = (
        db.query(EntityMention)
        .filter(
            EntityMention.entity_id == entity.id,
            EntityMention.source_kind == source_kind,
            EntityMention.source_id == source_id,
            EntityMention.surface_text == candidate.surface_text,
        )
        .first()
    )
    if row:
        return row
    row = EntityMention(
        entity_id=entity.id,
        source_kind=source_kind,
        source_id=source_id,
        item_id=item_id,
        chunk_id=chunk_id,
        surface_text=candidate.surface_text,
        normalized_key=candidate.normalized_key,
        evidence_span=candidate.evidence_span,
        confidence=candidate.confidence,
        extraction_method=candidate.extraction_method,
    )
    db.add(row)
    db.flush()
    return row


def _find_entity_by_surface(db: Session, user_id: str, surface: str, entity_type: str) -> KnowledgeEntity | None:
    key = normalize_entity_key(surface)
    return (
        db.query(KnowledgeEntity)
        .filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.entity_type == entity_type, KnowledgeEntity.normalized_key == key)
        .first()
    )


def _get_or_create_relation(
    db: Session,
    *,
    subject: KnowledgeEntity,
    predicate: str,
    obj: KnowledgeEntity,
    source_kind: str,
    source_id: str,
    evidence_span: str,
    confidence: float,
    method: str,
) -> EntityRelation:
    row = (
        db.query(EntityRelation)
        .filter(
            EntityRelation.subject_entity_id == subject.id,
            EntityRelation.predicate == predicate,
            EntityRelation.object_entity_id == obj.id,
            EntityRelation.source_kind == source_kind,
            EntityRelation.source_id == source_id,
        )
        .first()
    )
    if row:
        return row
    row = EntityRelation(
        subject_entity_id=subject.id,
        predicate=predicate,
        object_entity_id=obj.id,
        source_kind=source_kind,
        source_id=source_id,
        evidence_span=evidence_span,
        confidence=confidence,
        extraction_method=method,
    )
    db.add(row)
    db.flush()
    return row
```

- [ ] **Step 4: Run persistence test**

Run:

```bash
pytest backend/tests/test_entity_extraction.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/entity_extraction.py backend/tests/test_entity_extraction.py
git commit -m "feat: persist source-layer entity extraction"
```

---

### Task 6: Build Neo4j Graph Client

**Files:**
- Create: `backend/app/services/graph_client.py`
- Test: `backend/tests/test_graph_client.py`

- [ ] **Step 1: Write graph client unit test with fake driver**

Create `backend/tests/test_graph_client.py`:

```python
from backend.app.services.graph_client import GraphClient


class FakeTx:
    def __init__(self):
        self.queries = []

    def run(self, query, **params):
        self.queries.append((query, params))


class FakeSession:
    def __init__(self):
        self.tx = FakeTx()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, fn, *args, **kwargs):
        return fn(self.tx, *args, **kwargs)


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()

    def session(self, database=None):
        return self.session_obj


def test_graph_client_upserts_ckp_node():
    driver = FakeDriver()
    client = GraphClient(driver=driver, database="neo4j")

    client.upsert_ckp({"id": "ckp-1", "user_id": "default-user", "title": "多视图学习", "ckp_type": "concept", "status": "stable", "confidence": 0.9})

    query, params = driver.session_obj.tx.queries[0]
    assert "MERGE (n:CKP {id: $id})" in query
    assert params["id"] == "ckp-1"
    assert params["title"] == "多视图学习"
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_graph_client.py -q
```

Expected: import error for `graph_client`.

- [ ] **Step 3: Implement graph client**

Create `backend/app/services/graph_client.py`:

```python
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from backend.app.config import settings


class GraphClient:
    def __init__(self, driver=None, database: str | None = None) -> None:
        self.driver = driver or GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))
        self.database = database or settings.NEO4J_DATABASE

    def close(self) -> None:
        self.driver.close()

    def upsert_ckp(self, data: dict[str, Any]) -> None:
        self._write(
            """
            MERGE (n:CKP {id: $id})
            SET n.user_id = $user_id,
                n.title = $title,
                n.ckp_type = $ckp_type,
                n.status = $status,
                n.confidence = $confidence
            """,
            data,
        )

    def upsert_pku(self, data: dict[str, Any]) -> None:
        self._write(
            """
            MERGE (n:PKU {id: $id})
            SET n.user_id = $user_id,
                n.unit_type = $unit_type,
                n.statement_hash = $statement_hash,
                n.confidence = $confidence,
                n.status = $status
            """,
            data,
        )

    def upsert_source(self, data: dict[str, Any]) -> None:
        self._write(
            """
            MERGE (n:Source {id: $id})
            SET n.source_kind = $source_kind,
                n.source_id = $source_id,
                n.item_id = $item_id,
                n.title = $title
            """,
            data,
        )

    def upsert_entity(self, data: dict[str, Any]) -> None:
        self._write(
            """
            MERGE (n:Entity {id: $id})
            SET n.user_id = $user_id,
                n.entity_type = $entity_type,
                n.canonical_name = $canonical_name,
                n.normalized_key = $normalized_key,
                n.status = $status,
                n.confidence = $confidence
            """,
            data,
        )

    def relate(self, start_label: str, start_id: str, rel_type: str, end_label: str, end_id: str, props: dict[str, Any] | None = None) -> None:
        props = props or {}
        query = f"""
        MATCH (a:{start_label} {{id: $start_id}})
        MATCH (b:{end_label} {{id: $end_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += $props
        """
        self._write(query, {"start_id": start_id, "end_id": end_id, "props": props})

    def _write(self, query: str, params: dict[str, Any]) -> None:
        with self.driver.session(database=self.database) as session:
            session.execute_write(lambda tx: tx.run(query, **params))
```

- [ ] **Step 4: Run graph client test**

Run:

```bash
pytest backend/tests/test_graph_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/graph_client.py backend/tests/test_graph_client.py
git commit -m "feat: add neo4j graph client"
```

---

### Task 7: Project Existing CKP/PKU/Source Graph

**Files:**
- Create: `backend/app/services/graph_projection.py`
- Test: `backend/tests/test_graph_projection.py`

- [ ] **Step 1: Write projection test with fake graph client**

Create `backend/tests/test_graph_projection.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import CanonicalKnowledgePoint, CanonicalRelation, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink, PersonalKnowledgeUnit
from backend.app.services.graph_projection import project_ckp_graph


class FakeGraph:
    def __init__(self):
        self.ckps = []
        self.pkus = []
        self.sources = []
        self.relations = []

    def upsert_ckp(self, data):
        self.ckps.append(data)

    def upsert_pku(self, data):
        self.pkus.append(data)

    def upsert_source(self, data):
        self.sources.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append((start_label, start_id, rel_type, end_label, end_id, props or {}))


def test_project_ckp_graph_projects_hierarchy_support_and_source():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    item = KnowledgeItem(title="OpenViewer", content="Yanchao Tan authored OpenViewer.", user_id="default-user")
    db.add(item)
    db.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="Yanchao Tan authored OpenViewer.", chunk_type="parent")
    parent = CanonicalKnowledgePoint(title="多视图学习", canonical_type="concept", canonical_statement="多视图学习", user_id="default-user", status="stable")
    child = CanonicalKnowledgePoint(title="OpenViewer 方法", canonical_type="method", canonical_statement="OpenViewer 是多视图学习方法", user_id="default-user", status="stable")
    db.add_all([chunk, parent, child])
    db.flush()
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="claim",
        statement="Yanchao Tan authored OpenViewer.",
        normalized_statement="yanchao tan authored openviewer",
        normalized_statement_hash="hash-1",
        user_id="default-user",
        status="active",
    )
    db.add(pku)
    db.flush()
    db.add(PKUCanonicalLink(pku_id=pku.id, canonical_id=child.id, relation_type="supports", confidence=0.8, user_id="default-user"))
    db.add(CanonicalRelation(source_canonical_id=parent.id, target_canonical_id=child.id, relation_type="has_child", confidence=0.9, user_id="default-user"))
    db.commit()

    graph = FakeGraph()
    result = project_ckp_graph(db, graph)

    assert result.ckp_count == 2
    assert result.pku_count == 1
    assert result.source_count == 1
    assert ("CKP", parent.id, "HAS_CHILD", "CKP", child.id, {"relation_type": "has_child", "confidence": 0.9}) in graph.relations
    assert any(rel[2] == "SUPPORTED_BY" for rel in graph.relations)
    assert any(rel[2] == "EVIDENCED_BY" for rel in graph.relations)
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_graph_projection.py -q
```

Expected: import error for `graph_projection`.

- [ ] **Step 3: Implement graph projection**

Create `backend/app/services/graph_projection.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import CanonicalKnowledgePoint, CanonicalRelation, KnowledgeChunk, KnowledgeItem, PKUCanonicalLink, PKURelation, PersonalKnowledgeUnit


@dataclass(frozen=True)
class GraphProjectionResult:
    ckp_count: int
    pku_count: int
    source_count: int
    relation_count: int


def project_ckp_graph(db: Session, graph: Any, user_id: str = "default-user") -> GraphProjectionResult:
    ckp_count = 0
    pku_count = 0
    source_ids: set[str] = set()
    relation_count = 0

    ckps = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.user_id == user_id, CanonicalKnowledgePoint.status != "deprecated").all()
    for ckp in ckps:
        graph.upsert_ckp(
            {
                "id": ckp.id,
                "user_id": ckp.user_id,
                "title": ckp.title,
                "ckp_type": ckp.canonical_type,
                "status": ckp.status,
                "confidence": float(ckp.confidence or 0.0),
            }
        )
        ckp_count += 1

    pkus = db.query(PersonalKnowledgeUnit).filter(PersonalKnowledgeUnit.user_id == user_id, PersonalKnowledgeUnit.status == "active").all()
    for pku in pkus:
        graph.upsert_pku(
            {
                "id": pku.id,
                "user_id": pku.user_id,
                "unit_type": pku.unit_type,
                "statement_hash": pku.normalized_statement_hash,
                "confidence": float(pku.confidence or 0.0),
                "status": pku.status,
            }
        )
        pku_count += 1
        source = _source_payload_for_pku(db, pku)
        if source:
            graph.upsert_source(source)
            source_ids.add(source["id"])
            graph.relate("PKU", pku.id, "EVIDENCED_BY", "Source", source["id"], {"source_kind": pku.source_kind, "source_id": pku.source_id})
            relation_count += 1

    for link in db.query(PKUCanonicalLink).filter(PKUCanonicalLink.user_id == user_id).all():
        graph.relate(
            "CKP",
            link.canonical_id,
            "SUPPORTED_BY",
            "PKU",
            link.pku_id,
            {"relation_type": link.relation_type, "role": link.role, "confidence": float(link.confidence or 0.0)},
        )
        relation_count += 1

    for relation in db.query(CanonicalRelation).filter(CanonicalRelation.user_id == user_id).all():
        rel_type = "HAS_CHILD" if relation.relation_type in {"has_child", "parent_of", "subtopic_of", "part_of"} else "RELATED_TO"
        graph.relate(
            "CKP",
            relation.source_canonical_id,
            rel_type,
            "CKP",
            relation.target_canonical_id,
            {"relation_type": relation.relation_type, "confidence": float(relation.confidence or 0.0)},
        )
        relation_count += 1

    for relation in db.query(PKURelation).filter(PKURelation.user_id == user_id).all():
        graph.relate(
            "PKU",
            relation.source_pku_id,
            "RELATED_TO",
            "PKU",
            relation.target_pku_id,
            {"relation_type": relation.relation_type, "confidence": float(relation.confidence or 0.0), "reason": relation.reason or ""},
        )
        relation_count += 1

    return GraphProjectionResult(ckp_count, pku_count, len(source_ids), relation_count)


def _source_payload_for_pku(db: Session, pku: PersonalKnowledgeUnit) -> dict[str, str] | None:
    if pku.source_kind == "document_chunk":
        chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == pku.source_id).first()
        if not chunk:
            return None
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == chunk.item_id).first()
        return {
            "id": f"document_chunk:{chunk.id}",
            "source_kind": "document_chunk",
            "source_id": chunk.id,
            "item_id": chunk.item_id,
            "title": item.title if item else "",
        }
    return {"id": f"{pku.source_kind}:{pku.source_id}", "source_kind": pku.source_kind, "source_id": pku.source_id, "item_id": "", "title": ""}
```

- [ ] **Step 4: Run projection test**

Run:

```bash
pytest backend/tests/test_graph_projection.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/graph_projection.py backend/tests/test_graph_projection.py
git commit -m "feat: project ckp pku graph"
```

---

### Task 8: Project Entities, Mentions, Aliases, And Entity Relations

**Files:**
- Modify: `backend/app/services/graph_projection.py`
- Test: `backend/tests/test_graph_projection.py`

- [ ] **Step 1: Write failing entity projection test**

Append to `backend/tests/test_graph_projection.py`:

```python
from backend.app.models import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation
from backend.app.services.graph_projection import project_entity_graph


def test_project_entity_graph_projects_alias_mention_and_relation():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    person = KnowledgeEntity(user_id="default-user", entity_type="person", canonical_name="Yanchao Tan", normalized_key="yanchaotan", aliases=["yanchaotan"], status="active", confidence=0.9)
    paper = KnowledgeEntity(user_id="default-user", entity_type="paper", canonical_name="OpenViewer", normalized_key="openviewer", aliases=[], status="active", confidence=0.9)
    db.add_all([person, paper])
    db.flush()
    db.add(EntityAlias(entity_id=person.id, alias="yanchaotan", normalized_key="yanchaotan", confidence=0.95))
    db.add(EntityMention(entity_id=person.id, source_kind="document_chunk", source_id="chunk-1", item_id="item-1", chunk_id="chunk-1", surface_text="Yanchao Tan", normalized_key="yanchaotan", evidence_span="Yanchao Tan", confidence=0.9, extraction_method="rule"))
    db.add(EntityRelation(subject_entity_id=person.id, predicate="authored", object_entity_id=paper.id, source_kind="document_chunk", source_id="chunk-1", evidence_span="Yanchao Tan authored OpenViewer", confidence=0.88, extraction_method="rule"))
    db.commit()

    graph = FakeGraph()
    result = project_entity_graph(db, graph)

    assert result.entity_count == 2
    assert result.alias_count == 1
    assert result.mention_count == 1
    assert result.relation_count == 2
    assert any(rel[2] == "ALIAS_OF" for rel in graph.relations)
    assert any(rel[2] == "MENTIONED_IN" for rel in graph.relations)
    assert any(rel[2] == "AUTHORED" for rel in graph.relations)
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_graph_projection.py::test_project_entity_graph_projects_alias_mention_and_relation -q
```

Expected: import error for `project_entity_graph`.

- [ ] **Step 3: Implement entity projection**

Append to `backend/app/services/graph_projection.py`:

```python
from backend.app.models.entity import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation


@dataclass(frozen=True)
class EntityGraphProjectionResult:
    entity_count: int
    alias_count: int
    mention_count: int
    relation_count: int


def project_entity_graph(db: Session, graph: Any, user_id: str = "default-user") -> EntityGraphProjectionResult:
    entity_count = 0
    alias_count = 0
    mention_count = 0
    relation_count = 0

    for entity in db.query(KnowledgeEntity).filter(KnowledgeEntity.user_id == user_id, KnowledgeEntity.status == "active").all():
        graph.upsert_entity(
            {
                "id": entity.id,
                "user_id": entity.user_id,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "normalized_key": entity.normalized_key,
                "status": entity.status,
                "confidence": float(entity.confidence or 0.0),
            }
        )
        entity_count += 1

    for alias in db.query(EntityAlias).join(KnowledgeEntity).filter(KnowledgeEntity.user_id == user_id).all():
        alias_id = f"alias:{alias.normalized_key}"
        if hasattr(graph, "upsert_alias"):
            graph.upsert_alias({"id": alias_id, "key": alias.normalized_key, "surface_text": alias.alias})
        graph.relate("Alias", alias_id, "ALIAS_OF", "Entity", alias.entity_id, {"confidence": float(alias.confidence or 0.0), "extraction_method": alias.extraction_method or ""})
        alias_count += 1
        relation_count += 1

    for mention in db.query(EntityMention).join(KnowledgeEntity).filter(KnowledgeEntity.user_id == user_id).all():
        source_id = f"{mention.source_kind}:{mention.source_id}"
        graph.upsert_source({"id": source_id, "source_kind": mention.source_kind, "source_id": mention.source_id, "item_id": mention.item_id or "", "title": ""})
        graph.relate(
            "Entity",
            mention.entity_id,
            "MENTIONED_IN",
            "Source",
            source_id,
            {"confidence": float(mention.confidence or 0.0), "evidence_span": mention.evidence_span or "", "extraction_method": mention.extraction_method or ""},
        )
        mention_count += 1
        relation_count += 1

    predicate_map = {
        "authored": "AUTHORED",
        "affiliated_with": "AFFILIATED_WITH",
        "educated_at": "EDUCATED_AT",
        "has_email": "HAS_EMAIL",
        "co_author": "CO_AUTHOR",
    }
    for relation in db.query(EntityRelation).join(KnowledgeEntity, EntityRelation.subject_entity_id == KnowledgeEntity.id).filter(KnowledgeEntity.user_id == user_id).all():
        if not relation.object_entity_id:
            continue
        graph.relate(
            "Entity",
            relation.subject_entity_id,
            predicate_map.get(relation.predicate, "RELATED_TO"),
            "Entity",
            relation.object_entity_id,
            {
                "predicate": relation.predicate,
                "confidence": float(relation.confidence or 0.0),
                "evidence_span": relation.evidence_span or "",
                "source_kind": relation.source_kind,
                "source_id": relation.source_id,
                "extraction_method": relation.extraction_method or "",
            },
        )
        relation_count += 1

    return EntityGraphProjectionResult(entity_count, alias_count, mention_count, relation_count)
```

Add `GraphClient.upsert_alias` to `backend/app/services/graph_client.py`:

```python
    def upsert_alias(self, data: dict[str, Any]) -> None:
        self._write(
            """
            MERGE (n:Alias {id: $id})
            SET n.key = $key,
                n.surface_text = $surface_text
            """,
            data,
        )
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest backend/tests/test_graph_projection.py backend/tests/test_graph_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/graph_projection.py backend/app/services/graph_client.py backend/tests/test_graph_projection.py backend/tests/test_graph_client.py
git commit -m "feat: project entity graph"
```

---

### Task 9: Add Backfill CLI

**Files:**
- Create: `backend/scripts/backfill_entity_graph.py`
- Test: `backend/tests/test_backfill_entity_graph.py`

- [ ] **Step 1: Write backfill smoke test**

Create `backend/tests/test_backfill_entity_graph.py`:

```python
from backend.scripts.backfill_entity_graph import parse_args


def test_backfill_parse_args_supports_dry_run_and_limit():
    args = parse_args(["--dry-run", "--limit", "10"])
    assert args.dry_run is True
    assert args.limit == 10
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_backfill_entity_graph.py -q
```

Expected: import error.

- [ ] **Step 3: Implement CLI**

Create `backend/scripts/backfill_entity_graph.py`:

```python
from __future__ import annotations

import argparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import settings
from backend.app.models import KnowledgeChunk
from backend.app.services.entity_extraction import extract_and_settle_entities
from backend.app.services.graph_client import GraphClient
from backend.app.services.graph_projection import project_ckp_graph, project_entity_graph


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Backfill Prism entity extraction and Neo4j graph projection.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        query = db.query(KnowledgeChunk).order_by(KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
        if args.limit:
            query = query.limit(args.limit)
        chunks = query.all()
        for chunk in chunks:
            extract_and_settle_entities(
                db,
                source_kind="document_chunk",
                source_id=chunk.id,
                item_id=chunk.item_id,
                chunk_id=chunk.id,
                text=chunk.chunk_text or "",
            )
        if args.dry_run:
            db.rollback()
            print(f"dry-run extracted entities from {len(chunks)} chunks")
            return 0
        db.commit()
        graph = GraphClient()
        ckp_result = project_ckp_graph(db, graph)
        entity_result = project_entity_graph(db, graph)
        graph.close()
        print(f"projected ckp={ckp_result.ckp_count} pku={ckp_result.pku_count} entities={entity_result.entity_count}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test**

Run:

```bash
pytest backend/tests/test_backfill_entity_graph.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/backfill_entity_graph.py backend/tests/test_backfill_entity_graph.py
git commit -m "feat: add entity graph backfill cli"
```

---

### Task 10: Add Entity Graph Search Tool

**Files:**
- Create: `engine/app/agent/tools/entity_graph_search.py`
- Modify: `engine/app/agent/tools/__init__.py`
- Test: `engine/tests/test_entity_graph_search_tool.py`

- [ ] **Step 1: Write failing tool test with fake graph client**

Create `engine/tests/test_entity_graph_search_tool.py`:

```python
import json

from engine.app.agent.tools.base import ToolContext
from engine.app.agent.tools.entity_graph_search import build


class FakeGraphSearch:
    def search_entity_context(self, query, limit=8):
        return {
            "status": "success",
            "summary": "Found entity Yanchao Tan with 1 source.",
            "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
            "sources": [{"source_kind": "document_chunk", "source_id": "chunk-1", "snippet": "Yanchao Tan authored OpenViewer."}],
            "paths": [{"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"]}],
        }


def test_entity_graph_search_tool_returns_entities_sources_and_paths():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = build(ctx, graph_search=FakeGraphSearch())

    payload = json.loads(tool.invoke({"query": "yanchaotan", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
    assert ctx.citations == payload["sources"]
    assert ctx.stats_holder["entity_graph_search"]["entity_count"] == 1
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest engine/tests/test_entity_graph_search_tool.py -q
```

Expected: import error.

- [ ] **Step 3: Implement tool shell**

Create `engine/app/agent/tools/entity_graph_search.py`:

```python
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool


class EntityGraphSearchInput(BaseModel):
    query: str = Field(..., description="Named entity, alias, person, paper, organization, or object query.")
    limit: int = Field(8, ge=1, le=20)


class EntityGraphSearchService:
    def search_entity_context(self, query: str, limit: int = 8) -> dict[str, Any]:
        return {"status": "insufficient", "summary": "Entity graph search is not configured.", "entities": [], "sources": [], "paths": []}


def build(ctx: ToolContext, graph_search: Any | None = None) -> StructuredTool:
    service = graph_search or EntityGraphSearchService()

    def run(query: str, limit: int = 8) -> str:
        payload = service.search_entity_context(query, limit=limit)
        sources = payload.get("sources") or []
        ctx.citations.extend(sources)
        ctx.stats_holder["entity_graph_search"] = {
            "entity_count": len(payload.get("entities") or []),
            "source_count": len(sources),
            "path_count": len(payload.get("paths") or []),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name="entity_graph_search",
        description=(
            "Search the entity graph for people, organizations, papers, aliases, and entity-to-knowledge relationships. "
            "Use before declaring a named person or object absent."
        ),
        args_schema=EntityGraphSearchInput,
    )


register_tool(
    ToolSpec(
        key="entity_graph_search",
        name="entity_graph_search",
        description="Search entity graph and return source-backed paths.",
        builder=build,
        default_enabled=True,
    )
)
```

Modify `engine/app/agent/tools/__init__.py` to import it:

```python
import engine.app.agent.tools.entity_graph_search  # noqa: F401
```

- [ ] **Step 4: Run test**

Run:

```bash
pytest engine/tests/test_entity_graph_search_tool.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/app/agent/tools/entity_graph_search.py engine/app/agent/tools/__init__.py engine/tests/test_entity_graph_search_tool.py
git commit -m "feat: add entity graph search tool"
```

---

### Task 11: Implement Neo4j Entity Graph Search Service

**Files:**
- Modify: `engine/app/agent/tools/entity_graph_search.py`
- Test: `engine/tests/test_entity_graph_search_tool.py`

- [ ] **Step 1: Write service test with fake query client**

Append to `engine/tests/test_entity_graph_search_tool.py`:

```python
from engine.app.agent.tools.entity_graph_search import EntityGraphSearchService


class FakeQueryClient:
    def query_entity_context(self, normalized_keys, limit):
        assert "yanchaotan" in normalized_keys
        return {
            "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
            "sources": [{"source_kind": "document_chunk", "source_id": "chunk-1", "snippet": "Yanchao Tan authored OpenViewer."}],
            "paths": [{"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"]}],
        }


def test_entity_graph_search_service_normalizes_query_before_lookup():
    service = EntityGraphSearchService(client=FakeQueryClient())
    payload = service.search_entity_context("Yanchao Tan", limit=5)

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest engine/tests/test_entity_graph_search_tool.py::test_entity_graph_search_service_normalizes_query_before_lookup -q
```

Expected: constructor does not accept `client`.

- [ ] **Step 3: Implement service client**

Modify `EntityGraphSearchService` in `engine/app/agent/tools/entity_graph_search.py`:

```python
import re
from neo4j import GraphDatabase
from engine.app.config import settings


def _normalize_entity_key(text: str) -> str:
    value = (text or "").strip().lower()
    if re.fullmatch(r"[\u4e00-\u9fff]+", value):
        return value
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)


def _alias_keys(query: str) -> list[str]:
    primary = _normalize_entity_key(query)
    keys = [primary] if primary else []
    words = re.findall(r"[A-Za-z][A-Za-z'.-]*", query or "")
    if len(words) == 2:
        for candidate in [_normalize_entity_key("".join(words)), _normalize_entity_key(words[1] + words[0])]:
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


class Neo4jEntityQueryClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))

    def query_entity_context(self, normalized_keys: list[str], limit: int) -> dict[str, Any]:
        query = """
        MATCH (alias:Alias)-[:ALIAS_OF]->(entity:Entity)
        WHERE alias.key IN $keys OR entity.normalized_key IN $keys
        OPTIONAL MATCH (entity)-[rel]->(neighbor:Entity)
        OPTIONAL MATCH (entity)-[mention:MENTIONED_IN]->(source:Source)
        RETURN entity, collect(DISTINCT rel) AS rels, collect(DISTINCT neighbor) AS neighbors, collect(DISTINCT source) AS sources
        LIMIT $limit
        """
        with self.driver.session(database=settings.NEO4J_DATABASE) as session:
            records = session.run(query, keys=normalized_keys, limit=limit)
            entities = []
            sources = []
            paths = []
            for record in records:
                entity = dict(record["entity"])
                entities.append(entity)
                for source in record["sources"] or []:
                    src = dict(source)
                    sources.append(src)
                for neighbor in record["neighbors"] or []:
                    paths.append({"path": [entity.get("canonical_name"), "RELATED_TO", dict(neighbor).get("canonical_name")]})
            return {"entities": entities, "sources": sources, "paths": paths}


class EntityGraphSearchService:
    def __init__(self, client: Any | None = None):
        self.client = client or Neo4jEntityQueryClient()

    def search_entity_context(self, query: str, limit: int = 8) -> dict[str, Any]:
        keys = _alias_keys(query)
        result = self.client.query_entity_context(keys, limit)
        status = "success" if result.get("entities") or result.get("sources") else "insufficient"
        return {
            "status": status,
            "summary": f"Found {len(result.get('entities') or [])} entities and {len(result.get('sources') or [])} sources.",
            "entities": result.get("entities") or [],
            "sources": result.get("sources") or [],
            "paths": result.get("paths") or [],
            "normalized_keys": keys,
        }
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest engine/tests/test_entity_graph_search_tool.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/app/agent/tools/entity_graph_search.py engine/tests/test_entity_graph_search_tool.py
git commit -m "feat: query entity graph context"
```

---

### Task 12: Wire Entity Extraction Into Governance Flow

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Test: `backend/tests/test_ingestion_governance.py` or `backend/tests/test_entity_extraction.py`

- [ ] **Step 1: Write failing integration test**

Add to `backend/tests/test_entity_extraction.py`:

```python
from backend.app.services.knowledge_governance import settle_document_item_to_governance
from backend.app.models import KnowledgeChunk, KnowledgeItem, KnowledgeEntity


def test_document_governance_extracts_entities_from_chunks(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    item = KnowledgeItem(title="OpenViewer", content="Yanchao Tan authored OpenViewer.", source_type="document", user_id="default-user")
    db.add(item)
    db.flush()
    db.add(KnowledgeChunk(item_id=item.id, chunk_text="OpenViewer authors include Yanchao Tan and Shiping Wang.", chunk_type="parent"))
    db.commit()

    monkeypatch.setattr("backend.app.services.knowledge_governance._extract_document_chunk_pkus_with_llm", lambda *args, **kwargs: type("X", (), {"pkus": [], "relations": []})())

    settle_document_item_to_governance(db, item.id)

    assert db.query(KnowledgeEntity).filter(KnowledgeEntity.normalized_key == "yanchaotan").first()
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest backend/tests/test_entity_extraction.py::test_document_governance_extracts_entities_from_chunks -q
```

Expected: no entity extracted.

- [ ] **Step 3: Call extraction during chunk governance**

In `backend/app/services/knowledge_governance.py`, import:

```python
from backend.app.services.entity_extraction import extract_and_settle_entities
```

Inside `settle_document_item_to_governance`, in the loop over chunks after PKU extraction/fallback and before `db.commit()`, add:

```python
        extract_and_settle_entities(
            db,
            source_kind="document_chunk",
            source_id=chunk.id,
            item_id=item.id,
            chunk_id=chunk.id,
            text=chunk.chunk_text or "",
            user_id=item.user_id or DEFAULT_USER_ID,
        )
```

- [ ] **Step 4: Run integration test**

Run:

```bash
pytest backend/tests/test_entity_extraction.py::test_document_governance_extracts_entities_from_chunks -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/knowledge_governance.py backend/tests/test_entity_extraction.py
git commit -m "feat: extract entities during document governance"
```

---

### Task 13: Update Agent Prompt For Entity Graph Usage

**Files:**
- Modify: `engine/app/agent/prompts.py`
- Test: `engine/tests/test_agent_tools.py` or `engine/tests/test_agent_runner.py`

- [ ] **Step 1: Write failing prompt test**

Add to `engine/tests/test_agent_tools.py`:

```python
from engine.app.agent.prompts import AGENT_SYSTEM_PROMPT


def test_agent_prompt_requires_entity_graph_before_named_entity_not_found():
    assert "entity_graph_search" in AGENT_SYSTEM_PROMPT
    assert "named person" in AGENT_SYSTEM_PROMPT.lower()
    assert "before declaring" in AGENT_SYSTEM_PROMPT.lower()
```

- [ ] **Step 2: Run test to verify fail**

Run:

```bash
pytest engine/tests/test_agent_tools.py::test_agent_prompt_requires_entity_graph_before_named_entity_not_found -q
```

Expected: assertion failure.

- [ ] **Step 3: Update prompt**

Append this rule to `AGENT_SYSTEM_PROMPT` in `engine/app/agent/prompts.py`:

```text
Named entity lookup rule:
When the user asks about a named person, organization, paper, project, email, or alias-like token, call `entity_graph_search` before saying the entity is absent. If entity graph search returns no result, then use raw document/deep knowledge fallback. If all paths are insufficient, say the entity was not found in the current indexed evidence rather than claiming it does not exist.
```

- [ ] **Step 4: Run prompt test**

Run:

```bash
pytest engine/tests/test_agent_tools.py::test_agent_prompt_requires_entity_graph_before_named_entity_not_found -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/app/agent/prompts.py engine/tests/test_agent_tools.py
git commit -m "docs: require entity graph lookup for named entities"
```

---

### Task 14: Badcase Regression Test

**Files:**
- Test: `engine/tests/test_entity_graph_search_tool.py`
- Optional Test: `backend/tests/test_entity_extraction.py`

- [ ] **Step 1: Add badcase extraction regression**

Append to `backend/tests/test_entity_extraction.py`:

```python
def test_yanchaotan_badcase_extracts_person_paper_and_affiliation():
    text = (
        "OpenViewer: Openness-Aware Multi-View Learning\n"
        "Shide Du, Zihan Fang, Yanchao Tan, Changwei Wang, Shiping Wang\n"
        "College of Computer and Data Science, Fuzhou University\n"
        "yctan@fzu.edu.cn, shipingwangphd@163.com\n"
    )
    candidates = extract_entity_candidates_from_text(text, source_kind="document_chunk")
    pairs = {(item.entity_type, item.surface_text) for item in candidates if item.kind == "entity"}

    assert ("person", "Yanchao Tan") in pairs
    assert ("person", "Shiping Wang") in pairs
    assert ("paper", "OpenViewer: Openness-Aware Multi-View Learning") in pairs
    assert ("organization", "Fuzhou University") in pairs
    assert ("email", "yctan@fzu.edu.cn") in pairs
```

- [ ] **Step 2: Add badcase graph search regression**

Append to `engine/tests/test_entity_graph_search_tool.py`:

```python
def test_yanchaotan_query_resolves_to_yanchao_tan_entity_with_source():
    service = EntityGraphSearchService(client=FakeQueryClient())
    payload = service.search_entity_context("yanchaotan", limit=5)

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
```

- [ ] **Step 3: Run regression tests**

Run:

```bash
pytest backend/tests/test_entity_extraction.py engine/tests/test_entity_graph_search_tool.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_entity_extraction.py engine/tests/test_entity_graph_search_tool.py
git commit -m "test: cover yanchaotan entity graph badcase"
```

---

### Task 15: End-To-End Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run backend focused tests**

Run:

```bash
pytest backend/tests/test_entity_models.py backend/tests/test_entity_resolution.py backend/tests/test_entity_extraction.py backend/tests/test_graph_client.py backend/tests/test_graph_projection.py backend/tests/test_backfill_entity_graph.py -q
```

Expected: all pass.

- [ ] **Step 2: Run engine focused tests**

Run:

```bash
pytest engine/tests/test_entity_graph_search_tool.py engine/tests/test_deep_search_executors.py engine/tests/test_agent_tools.py -q
```

Expected: all pass.

- [ ] **Step 3: Run full relevant suites**

Run:

```bash
pytest backend/tests -q
pytest engine/tests -q
```

Expected: all pass or only documented unrelated pre-existing failures.

- [ ] **Step 4: Optional local Neo4j smoke**

Run:

```bash
docker compose up -d neo4j
python -m backend.scripts.backfill_entity_graph --limit 20
```

Expected output includes:

```text
projected ckp=
```

- [ ] **Step 5: Manual badcase smoke**

Run:

```bash
python - <<'PY'
from backend.app.database import SessionLocal
from backend.app.models import KnowledgeEntity

db = SessionLocal()
try:
    row = db.query(KnowledgeEntity).filter(KnowledgeEntity.normalized_key == "yanchaotan").first()
    print(row.canonical_name if row else "NOT_FOUND")
finally:
    db.close()
PY
```

Expected after backfill over the relevant documents:

```text
Yanchao Tan
```

- [ ] **Step 6: Final commit if needed**

```bash
git status --short
git add .
git commit -m "test: verify entity graph projection flow"
```

---

## Self-Review

Spec coverage:
- Existing CKP/PKU relation migration is covered by Tasks 7 and 8.
- CKP parent-child hierarchy is covered by `HAS_CHILD` projection in Task 7.
- Bottom-layer entity extraction from chunks/assets is covered by Tasks 4, 5, and 12. Task 12 wires document chunks first; asset item/unit wiring should be a follow-up task if the first rollout is stable.
- Graph as projection, not source of truth, is enforced by Graph Model and Tasks 7-11.
- Badcase `yanchaotan -> Yanchao Tan` is covered by Tasks 3, 4, 10, 11, and 14.

Known deliberate scope limits:
- This plan starts with deterministic rules and does not add LLM entity extraction yet.
- Chinese alias resolution such as `谭谚超 -> Yanchao Tan` is not automatically merged unless an alias candidate is created by user confirmation or future LLM resolver.
- Neo4j source snippets are references; full source text remains in MySQL.

Placeholder scan: no `TBD`, `TODO`, or undefined later-stage functions remain in task steps without a creation step.

Type consistency:
- `KnowledgeEntity`, `EntityAlias`, `EntityMention`, `EntityRelation` are introduced in Task 2 and reused later.
- `GraphClient` methods used by projection are introduced in Task 6 and extended in Task 8.
- `EntityGraphSearchService` is introduced in Task 10 and expanded in Task 11.
