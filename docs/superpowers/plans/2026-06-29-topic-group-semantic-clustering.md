# TopicGroup Semantic Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reviewable semantic TopicGroup clustering for atomic CKP and reviewable cross-language entity disambiguation candidates.

**Architecture:** MySQL remains the source of truth. TopicGroup and EntityResolutionCandidate are persisted audit/review records, then confirmed TopicGroups and aliases are projected into Neo4j. CKP stays atomic; parent CKP is filtered from the new grouping pipeline and can be hidden from graph projections.

**Tech Stack:** Python, SQLAlchemy, MySQL/SQLite test metadata, Neo4j projection helpers, pytest, existing Prism backend/engine patterns.

---

## File Structure

Create:

- `backend/app/models/topic_group.py` - TopicGroup, TopicGroupDraft, and membership models.
- `backend/app/services/topic_grouping.py` - CKP selection, semantic text building, deterministic/fake-friendly clustering helpers, draft creation, and draft confirmation.
- `backend/tests/test_topic_group_models.py` - model persistence tests.
- `backend/tests/test_topic_grouping.py` - service tests for candidate selection, clustering, draft dedupe, and confirmation.
- `backend/tests/test_entity_resolution_candidates.py` - reviewable entity resolution tests.

Modify:

- `backend/app/models/entity.py` - add EntityResolutionCandidate model and helper status fields.
- `backend/app/models/__init__.py` - export new models.
- `backend/app/utils/auto_migrate.py` - add unique constraint names for new models.
- `backend/app/services/graph_client.py` - allow `TopicGroup` node label and `CONTAINS` relationship.
- `backend/app/services/graph_projection.py` - project TopicGroup nodes and CONTAINS edges, and include CKP `topic_level`.
- `backend/tests/test_graph_projection.py` - FakeGraph projection tests.
- `engine/app/agent/tools/entity_graph_search.py` - surface confirmed aliases and possible pending candidates in search results.
- `engine/tests/test_entity_graph_search_tool.py` - query-layer alias/candidate tests.

Do not modify or stage unrelated files such as `requirements.txt`, `start.bat`, or `stop.bat`.

All backend test commands must set `DATABASE_URL` to a disposable SQLite URL and remove the temp db after the run.

---

### Task 1: Add TopicGroup Review Models

**Files:**

- Create: `backend/app/models/topic_group.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`
- Test: `backend/tests/test_topic_group_models.py`

- [ ] **Step 1: Write the failing model test**

Create `backend/tests/test_topic_group_models.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    TopicGroup,
    TopicGroupDraft,
    TopicGroupDraftMember,
    TopicGroupMember,
)


def test_topic_group_models_persist_drafts_confirmed_groups_and_members():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    dpo = CanonicalKnowledgePoint(
        id="ckp-dpo",
        user_id="default-user",
        canonical_type="topic",
        title="DPO",
        canonical_statement="Direct Preference Optimization optimizes from preference pairs.",
        status="stable",
        extra_meta={"topic_level": "child"},
    )
    ppo = CanonicalKnowledgePoint(
        id="ckp-ppo",
        user_id="default-user",
        canonical_type="topic",
        title="PPO",
        canonical_statement="Proximal Policy Optimization is a policy optimization algorithm.",
        status="stable",
        extra_meta={"topic_level": "child"},
    )
    draft = TopicGroupDraft(
        id="draft-1",
        user_id="default-user",
        name="强化学习算法",
        description="Preference and policy optimization methods.",
        group_type="semantic_cluster",
        algorithm="fake_embedding_threshold_v1",
        member_signature="ckp-dpo|ckp-ppo",
        status="pending_review",
        confidence=0.86,
        reason="DPO and PPO are both policy/preference optimization methods.",
        keywords=["DPO", "PPO", "RLHF"],
        extra_meta={"generation_run_id": "run-1"},
    )
    db.add_all([dpo, ppo, draft])
    db.flush()
    db.add_all(
        [
            TopicGroupDraftMember(draft_id=draft.id, ckp_id=dpo.id, confidence=0.91, reason="near DPO", rank=1),
            TopicGroupDraftMember(draft_id=draft.id, ckp_id=ppo.id, confidence=0.88, reason="near PPO", rank=2),
        ]
    )
    group = TopicGroup(
        id="group-1",
        user_id="default-user",
        name="强化学习算法",
        description="Confirmed RL algorithm group.",
        group_type="semantic_cluster",
        origin_draft_id=draft.id,
        status="active",
        confidence=0.86,
        keywords=["DPO", "PPO"],
        extra_meta={"confirmed_from": draft.id},
    )
    db.add(group)
    db.flush()
    db.add_all(
        [
            TopicGroupMember(group_id=group.id, ckp_id=dpo.id, confidence=0.91, reason="confirmed", rank=1),
            TopicGroupMember(group_id=group.id, ckp_id=ppo.id, confidence=0.88, reason="confirmed", rank=2),
        ]
    )
    db.commit()

    loaded = db.query(TopicGroup).filter_by(id="group-1").one()
    assert loaded.name == "强化学习算法"
    assert [member.ckp.title for member in loaded.members] == ["DPO", "PPO"]
    assert db.query(TopicGroupDraftMember).count() == 2
```

- [ ] **Step 2: Run the model test to verify RED**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_group_models_red.db'
python -m pytest backend/tests/test_topic_group_models.py -q
Remove-Item .\_topic_group_models_red.db -ErrorAction SilentlyContinue
```

Expected: import error for `TopicGroup`.

- [ ] **Step 3: Add TopicGroup models**

Create `backend/app/models/topic_group.py`:

```python
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import CHAR, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from ..utils.time import local_now


def _uuid():
    return str(uuid.uuid4())


class TopicGroupDraft(Base):
    __tablename__ = "topic_group_draft"
    __table_args__ = (
        Index("ix_topic_group_draft_status", "user_id", "status"),
        UniqueConstraint("user_id", "algorithm", "member_signature", "status", name="uq_topic_group_draft_open_signature"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    group_type = Column(String(64), default="semantic_cluster", index=True)
    algorithm = Column(String(128), default="", index=True)
    member_signature = Column(String(64), nullable=False, index=True)
    status = Column(String(32), default="pending_review", index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    keywords = Column(JSON, default=list)
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    members = relationship("TopicGroupDraftMember", back_populates="draft", cascade="all, delete-orphan")


class TopicGroupDraftMember(Base):
    __tablename__ = "topic_group_draft_member"
    __table_args__ = (
        UniqueConstraint("draft_id", "ckp_id", name="uq_topic_group_draft_member"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    draft_id = Column(CHAR(36), ForeignKey("topic_group_draft.id", ondelete="CASCADE"), nullable=False, index=True)
    ckp_id = Column(CHAR(36), ForeignKey("canonical_knowledge_point.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    rank = Column(Integer, default=0)
    created_at = Column(DateTime, default=local_now)

    draft = relationship("TopicGroupDraft", back_populates="members")
    ckp = relationship("CanonicalKnowledgePoint")


class TopicGroup(Base):
    __tablename__ = "topic_group"
    __table_args__ = (
        Index("ix_topic_group_status", "user_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    group_type = Column(String(64), default="semantic_cluster", index=True)
    origin_draft_id = Column(CHAR(36), default="", index=True)
    status = Column(String(32), default="active", index=True)
    confidence = Column(Float, default=0.5)
    keywords = Column(JSON, default=list)
    extra_meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    members = relationship("TopicGroupMember", back_populates="group", cascade="all, delete-orphan", order_by="TopicGroupMember.rank")


class TopicGroupMember(Base):
    __tablename__ = "topic_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "ckp_id", name="uq_topic_group_member"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    group_id = Column(CHAR(36), ForeignKey("topic_group.id", ondelete="CASCADE"), nullable=False, index=True)
    ckp_id = Column(CHAR(36), ForeignKey("canonical_knowledge_point.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence = Column(Float, default=0.5)
    reason = Column(Text)
    rank = Column(Integer, default=0)
    source = Column(String(64), default="generated", index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    group = relationship("TopicGroup", back_populates="members")
    ckp = relationship("CanonicalKnowledgePoint")
```

- [ ] **Step 4: Export models and constraints**

Modify `backend/app/models/__init__.py`:

```python
from .topic_group import TopicGroup, TopicGroupDraft, TopicGroupDraftMember, TopicGroupMember
```

Add these names to `__all__`:

```python
"TopicGroup",
"TopicGroupDraft",
"TopicGroupDraftMember",
"TopicGroupMember",
```

Modify `backend/app/utils/auto_migrate.py` and add to `KNOWN_UNIQUE_CONSTRAINTS`:

```python
"uq_topic_group_draft_open_signature",
"uq_topic_group_draft_member",
"uq_topic_group_member",
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_group_models_green.db'
python -m pytest backend/tests/test_topic_group_models.py -q
Remove-Item .\_topic_group_models_green.db -ErrorAction SilentlyContinue
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/topic_group.py backend/app/models/__init__.py backend/app/utils/auto_migrate.py backend/tests/test_topic_group_models.py
git commit -m "feat: add topic group review models"
```

---

### Task 2: Add TopicGroup Clustering Service

**Files:**

- Create: `backend/app/services/topic_grouping.py`
- Test: `backend/tests/test_topic_grouping.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/test_topic_grouping.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import CanonicalKnowledgePoint, PersonalKnowledgeUnit, PKUCanonicalLink, TopicGroupDraft, TopicGroup
from backend.app.services.topic_grouping import (
    build_ckp_semantic_text,
    confirm_topic_group_draft,
    create_topic_group_drafts,
    select_atomic_topic_ckps,
)


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _ckp(id, title, *, level="child"):
    return CanonicalKnowledgePoint(
        id=id,
        user_id="default-user",
        canonical_type="topic",
        title=title,
        canonical_statement=f"{title} statement",
        keywords=[title.lower()],
        concepts=[title],
        status="stable",
        extra_meta={"topic_level": level},
    )


def test_select_atomic_topic_ckps_excludes_parent_topics():
    db = _db()
    db.add_all([_ckp("ckp-dpo", "DPO"), _ckp("ckp-parent", "RLHF methods", level="parent")])
    db.commit()

    rows = select_atomic_topic_ckps(db, user_id="default-user")

    assert [row.id for row in rows] == ["ckp-dpo"]


def test_build_ckp_semantic_text_includes_linked_pku_statements():
    db = _db()
    ckp = _ckp("ckp-dpo", "DPO")
    pku = PersonalKnowledgeUnit(
        id="pku-1",
        user_id="default-user",
        source_kind="document_chunk",
        source_id="chunk-1",
        unit_type="claim",
        statement="DPO optimizes preference pairs without a separate reward model.",
        normalized_statement="DPO optimizes preference pairs without a separate reward model.",
        normalized_statement_hash="hash-1",
        status="active",
    )
    db.add_all([ckp, pku])
    db.flush()
    db.add(PKUCanonicalLink(user_id="default-user", pku_id=pku.id, canonical_id=ckp.id, relation_type="about"))
    db.commit()

    text = build_ckp_semantic_text(db, ckp)

    assert "Title: DPO" in text
    assert "DPO optimizes preference pairs" in text


class FakeEmbedder:
    def embed(self, text):
        if "DPO" in text:
            return [1.0, 0.0]
        if "PPO" in text:
            return [0.92, 0.08]
        return [0.0, 1.0]


class FakeLabeler:
    def label(self, members):
        titles = {member["title"] for member in members}
        if {"DPO", "PPO"} <= titles:
            return {
                "name": "强化学习算法",
                "description": "Preference and policy optimization methods.",
                "keywords": ["DPO", "PPO", "RLHF"],
                "confidence": 0.9,
                "reason": "DPO and PPO are both optimization algorithms.",
            }
        return {
            "name": "相关主题",
            "description": "Related topics.",
            "keywords": [],
            "confidence": 0.5,
            "reason": "Fallback label.",
        }


def test_create_topic_group_drafts_clusters_similar_ckps_and_dedupes_open_drafts():
    db = _db()
    db.add_all([_ckp("ckp-dpo", "DPO"), _ckp("ckp-ppo", "PPO"), _ckp("ckp-import", "Python import rules")])
    db.commit()

    created = create_topic_group_drafts(
        db,
        user_id="default-user",
        embedder=FakeEmbedder(),
        labeler=FakeLabeler(),
        similarity_threshold=0.9,
        min_group_size=2,
        algorithm="fake_embedding_threshold_v1",
    )
    created_again = create_topic_group_drafts(
        db,
        user_id="default-user",
        embedder=FakeEmbedder(),
        labeler=FakeLabeler(),
        similarity_threshold=0.9,
        min_group_size=2,
        algorithm="fake_embedding_threshold_v1",
    )

    assert len(created) == 1
    assert created_again == []
    draft = db.query(TopicGroupDraft).one()
    assert draft.name == "强化学习算法"
    assert [member.ckp_id for member in draft.members] == ["ckp-dpo", "ckp-ppo"]


def test_confirm_topic_group_draft_creates_active_group_and_members():
    db = _db()
    db.add_all([_ckp("ckp-dpo", "DPO"), _ckp("ckp-ppo", "PPO")])
    db.commit()
    draft = create_topic_group_drafts(
        db,
        user_id="default-user",
        embedder=FakeEmbedder(),
        labeler=FakeLabeler(),
        similarity_threshold=0.9,
        min_group_size=2,
        algorithm="fake_embedding_threshold_v1",
    )[0]

    group = confirm_topic_group_draft(db, draft.id, name="RLHF 强化学习算法", member_ckp_ids=["ckp-dpo", "ckp-ppo"])
    db.commit()

    assert group.name == "RLHF 强化学习算法"
    assert group.status == "active"
    assert db.query(TopicGroup).count() == 1
    assert db.query(TopicGroupDraft).one().status == "confirmed"
    assert [member.ckp_id for member in group.members] == ["ckp-dpo", "ckp-ppo"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_grouping_red.db'
python -m pytest backend/tests/test_topic_grouping.py -q
Remove-Item .\_topic_grouping_red.db -ErrorAction SilentlyContinue
```

Expected: import error for `backend.app.services.topic_grouping`.

- [ ] **Step 3: Implement clustering service**

Create `backend/app/services/topic_grouping.py`:

```python
from __future__ import annotations

import hashlib
import math
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
    TopicGroup,
    TopicGroupDraft,
    TopicGroupDraftMember,
    TopicGroupMember,
)


def select_atomic_topic_ckps(db: Session, user_id: str = "default-user") -> list[CanonicalKnowledgePoint]:
    rows = (
        db.query(CanonicalKnowledgePoint)
        .filter(
            CanonicalKnowledgePoint.user_id == user_id,
            CanonicalKnowledgePoint.status != "deprecated",
            CanonicalKnowledgePoint.canonical_type == "topic",
        )
        .order_by(CanonicalKnowledgePoint.title.asc(), CanonicalKnowledgePoint.id.asc())
        .all()
    )
    return [row for row in rows if _topic_level(row) != "parent"]


def build_ckp_semantic_text(db: Session, ckp: CanonicalKnowledgePoint, *, pku_limit: int = 8) -> str:
    linked_pkus = (
        db.query(PersonalKnowledgeUnit)
        .join(PKUCanonicalLink, PKUCanonicalLink.pku_id == PersonalKnowledgeUnit.id)
        .filter(PKUCanonicalLink.canonical_id == ckp.id)
        .order_by(PersonalKnowledgeUnit.created_at.asc(), PersonalKnowledgeUnit.id.asc())
        .limit(pku_limit)
        .all()
    )
    parts = [
        f"Title: {ckp.title}",
        f"Statement: {ckp.canonical_statement or ''}",
        f"Summary: {ckp.summary or ''}",
        "Keywords: " + " ".join(ckp.keywords or []),
        "Concepts: " + " ".join(ckp.concepts or []),
        "Entities: " + " ".join(ckp.entities or []),
    ]
    for pku in linked_pkus:
        parts.append(f"PKU: {pku.normalized_statement or pku.statement or ''}")
    return "\n".join(part for part in parts if part.strip())


def create_topic_group_drafts(
    db: Session,
    *,
    user_id: str = "default-user",
    embedder: Any,
    labeler: Any,
    similarity_threshold: float = 0.78,
    min_group_size: int = 2,
    max_group_size: int = 20,
    algorithm: str = "embedding_threshold_v1",
) -> list[TopicGroupDraft]:
    ckps = select_atomic_topic_ckps(db, user_id=user_id)
    vectors = {ckp.id: embedder.embed(build_ckp_semantic_text(db, ckp)) for ckp in ckps}
    by_id = {ckp.id: ckp for ckp in ckps}
    groups = _threshold_groups(ckps, vectors, similarity_threshold, min_group_size, max_group_size)
    created: list[TopicGroupDraft] = []

    for group_ids in groups:
        signature = _member_signature(group_ids)
        existing = (
            db.query(TopicGroupDraft)
            .filter_by(user_id=user_id, algorithm=algorithm, member_signature=signature, status="pending_review")
            .first()
        )
        if existing:
            continue
        members_payload = [{"id": ckp_id, "title": by_id[ckp_id].title} for ckp_id in group_ids]
        label = labeler.label(members_payload)
        draft = TopicGroupDraft(
            user_id=user_id,
            name=str(label.get("name") or by_id[group_ids[0]].title + " 相关主题")[:255],
            description=str(label.get("description") or ""),
            group_type="semantic_cluster",
            algorithm=algorithm,
            member_signature=signature,
            status="pending_review",
            confidence=float(label.get("confidence") or 0.5),
            reason=str(label.get("reason") or ""),
            keywords=list(label.get("keywords") or []),
            extra_meta={
                "member_ckp_ids": group_ids,
                "similarity_threshold": similarity_threshold,
                "min_group_size": min_group_size,
                "max_group_size": max_group_size,
            },
        )
        db.add(draft)
        db.flush()
        for rank, ckp_id in enumerate(group_ids, 1):
            db.add(
                TopicGroupDraftMember(
                    draft_id=draft.id,
                    ckp_id=ckp_id,
                    confidence=float(label.get("confidence") or 0.5),
                    reason=str(label.get("reason") or ""),
                    rank=rank,
                )
            )
        created.append(draft)
    db.flush()
    return created


def confirm_topic_group_draft(
    db: Session,
    draft_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    member_ckp_ids: list[str] | None = None,
) -> TopicGroup:
    draft = db.query(TopicGroupDraft).filter_by(id=draft_id).one()
    selected_ids = member_ckp_ids or [member.ckp_id for member in draft.members]
    group = TopicGroup(
        user_id=draft.user_id,
        name=(name or draft.name)[:255],
        description=description if description is not None else draft.description,
        group_type=draft.group_type,
        origin_draft_id=draft.id,
        status="active",
        confidence=draft.confidence,
        keywords=draft.keywords or [],
        extra_meta={
            "original_name": draft.name,
            "original_description": draft.description,
            "generation_run": draft.extra_meta or {},
        },
    )
    db.add(group)
    db.flush()
    member_by_id = {member.ckp_id: member for member in draft.members}
    for rank, ckp_id in enumerate(selected_ids, 1):
        draft_member = member_by_id[ckp_id]
        db.add(
            TopicGroupMember(
                group_id=group.id,
                ckp_id=ckp_id,
                confidence=draft_member.confidence,
                reason=draft_member.reason,
                rank=rank,
                source="generated",
            )
        )
    draft.status = "confirmed"
    db.flush()
    return group


def _topic_level(ckp: CanonicalKnowledgePoint) -> str:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    return str(meta.get("topic_level") or "child")


def _threshold_groups(ckps, vectors, threshold, min_group_size, max_group_size):
    remaining = [ckp.id for ckp in ckps]
    groups = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        for candidate in list(remaining):
            if _cosine(vectors[seed], vectors[candidate]) >= threshold:
                group.append(candidate)
                remaining.remove(candidate)
            if len(group) >= max_group_size:
                break
        if len(group) >= min_group_size:
            groups.append(group)
    return groups


def _cosine(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _member_signature(member_ids: list[str]) -> str:
    raw = "\n".join(sorted(member_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run GREEN**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_grouping_green.db'
python -m pytest backend/tests/test_topic_grouping.py -q
Remove-Item .\_topic_grouping_green.db -ErrorAction SilentlyContinue
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/topic_grouping.py backend/tests/test_topic_grouping.py
git commit -m "feat: generate reviewable topic group drafts"
```

---

### Task 3: Project TopicGroups and CKP Topic Level to Neo4j

**Files:**

- Modify: `backend/app/services/graph_client.py`
- Modify: `backend/app/services/graph_projection.py`
- Test: `backend/tests/test_graph_projection.py`

- [ ] **Step 1: Write failing graph projection tests**

Append to `backend/tests/test_graph_projection.py`:

```python
from backend.app.models import TopicGroup, TopicGroupMember


def test_project_ckp_graph_includes_topic_level_and_projects_topic_groups():
    db = _db_session()
    try:
        dpo = _ckp("ckp-dpo", "DPO", canonical_type="topic")
        dpo.extra_meta = {"topic_level": "child"}
        ppo = _ckp("ckp-ppo", "PPO", canonical_type="topic")
        ppo.extra_meta = {"topic_level": "child"}
        parent = _ckp("ckp-parent", "DPO 与 PPO", canonical_type="topic")
        parent.extra_meta = {"topic_level": "parent"}
        group = TopicGroup(
            id="group-rl",
            user_id="default-user",
            name="强化学习算法",
            description="Confirmed RL algorithm group.",
            group_type="semantic_cluster",
            status="active",
            confidence=0.92,
            keywords=["DPO", "PPO"],
        )
        db.add_all([dpo, ppo, parent, group])
        db.flush()
        db.add_all(
            [
                TopicGroupMember(group_id=group.id, ckp_id=dpo.id, confidence=0.91, reason="DPO belongs", rank=1),
                TopicGroupMember(group_id=group.id, ckp_id=ppo.id, confidence=0.89, reason="PPO belongs", rank=2),
            ]
        )
        db.commit()

        graph = FakeGraph()
        result = project_ckp_graph(db, graph)

        assert result.ckp_count == 3
        assert any(node["id"] == "ckp-dpo" and node["topic_level"] == "child" for node in graph.ckps)
        assert any(node["id"] == "ckp-parent" and node["topic_level"] == "parent" for node in graph.ckps)
        assert graph.topic_groups == [
            {
                "id": "group-rl",
                "user_id": "default-user",
                "name": "强化学习算法",
                "description": "Confirmed RL algorithm group.",
                "group_type": "semantic_cluster",
                "status": "active",
                "confidence": 0.92,
            }
        ]
        assert (
            "TopicGroup",
            "group-rl",
            "CONTAINS",
            "CKP",
            "ckp-dpo",
            {"confidence": 0.91, "reason": "DPO belongs", "rank": 1, "source": "generated"},
        ) in graph.relations
    finally:
        db.close()
```

Modify `FakeGraph.__init__` in `backend/tests/test_graph_projection.py` to include:

```python
self.topic_groups = []
```

Add method:

```python
def upsert_topic_group(self, data):
    self.topic_groups.append(data)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_group_projection_red.db'
python -m pytest backend/tests/test_graph_projection.py::test_project_ckp_graph_includes_topic_level_and_projects_topic_groups -q
Remove-Item .\_topic_group_projection_red.db -ErrorAction SilentlyContinue
```

Expected: missing `upsert_topic_group` support in projection or missing `topic_level` in CKP node.

- [ ] **Step 3: Add GraphClient support**

Modify `backend/app/services/graph_client.py`.

Add to `ALLOWED_NODE_LABELS`:

```python
"TopicGroup",
```

Add to `ALLOWED_RELATIONSHIP_TYPES`:

```python
"CONTAINS",
```

Add method:

```python
def upsert_topic_group(self, data: dict[str, Any]) -> None:
    self._upsert_node(
        "TopicGroup",
        data,
        ["user_id", "name", "description", "group_type", "status", "confidence"],
    )
```

- [ ] **Step 4: Project TopicGroup and CKP topic_level**

Modify `backend/app/services/graph_projection.py`.

Import:

```python
TopicGroup,
TopicGroupMember,
```

Add helper:

```python
def _topic_level(ckp: CanonicalKnowledgePoint) -> str:
    meta = ckp.extra_meta if isinstance(ckp.extra_meta, dict) else {}
    return str(meta.get("topic_level") or "child")
```

Add `"topic_level": _topic_level(ckp)` to `graph.upsert_ckp(...)`.

After CKP nodes are upserted and before returning from `project_ckp_graph`, project active groups:

```python
groups = (
    db.query(TopicGroup)
    .filter(TopicGroup.user_id == user_id, TopicGroup.status == "active")
    .all()
)
for group in groups:
    graph.upsert_topic_group(
        {
            "id": group.id,
            "user_id": group.user_id,
            "name": group.name,
            "description": group.description or "",
            "group_type": group.group_type,
            "status": group.status,
            "confidence": group.confidence,
        }
    )
    for member in group.members:
        if member.ckp_id not in active_ckp_ids:
            continue
        graph.relate(
            "TopicGroup",
            group.id,
            "CONTAINS",
            "CKP",
            member.ckp_id,
            {
                "confidence": member.confidence,
                "reason": member.reason,
                "rank": member.rank,
                "source": member.source,
            },
        )
        result.relation_count += 1
```

- [ ] **Step 5: Run GREEN and focused graph tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_group_projection_green.db'
python -m pytest backend/tests/test_graph_projection.py -q
Remove-Item .\_topic_group_projection_green.db -ErrorAction SilentlyContinue
```

Expected: all graph projection tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/graph_client.py backend/app/services/graph_projection.py backend/tests/test_graph_projection.py
git commit -m "feat: project topic groups to neo4j"
```

---

### Task 4: Add Entity Resolution Candidate Model and Confirmation Service

**Files:**

- Modify: `backend/app/models/entity.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/utils/auto_migrate.py`
- Create: `backend/app/services/entity_resolution_candidates.py`
- Test: `backend/tests/test_entity_resolution_candidates.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_entity_resolution_candidates.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityAlias, EntityResolutionCandidate, KnowledgeEntity
from backend.app.services.entity_resolution_candidates import confirm_entity_resolution_candidate, create_resolution_candidate


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_create_resolution_candidate_persists_pending_cross_language_alias():
    db = _db()
    entity = KnowledgeEntity(
        id="entity-yanchao",
        user_id="default-user",
        entity_type="person",
        canonical_name="Yanchao Tan",
        normalized_key="yanchaotan",
        aliases=["yanchaotan"],
        status="active",
    )
    db.add(entity)
    db.commit()

    candidate = create_resolution_candidate(
        db,
        user_id="default-user",
        alias_surface="谭彦超",
        alias_normalized_key="谭彦超",
        candidate_entity_id=entity.id,
        confidence=0.82,
        evidence_summary='same paper "OpenViewer" and affiliation "Fuzhou University"',
        evidence={"shared_paper": "OpenViewer", "shared_affiliation": "Fuzhou University"},
        resolution_method="graph_evidence",
    )
    db.commit()

    assert candidate.status == "pending_review"
    assert candidate.candidate_entity_name == "Yanchao Tan"
    assert db.query(EntityResolutionCandidate).count() == 1


def test_confirm_entity_resolution_candidate_creates_alias_of_canonical_entity():
    db = _db()
    entity = KnowledgeEntity(
        id="entity-yanchao",
        user_id="default-user",
        entity_type="person",
        canonical_name="Yanchao Tan",
        normalized_key="yanchaotan",
        aliases=["yanchaotan"],
        status="active",
    )
    db.add(entity)
    db.commit()
    candidate = create_resolution_candidate(
        db,
        user_id="default-user",
        alias_surface="谭彦超",
        alias_normalized_key="谭彦超",
        candidate_entity_id=entity.id,
        confidence=0.82,
        evidence_summary="same source evidence",
        evidence={"source_ids": ["chunk-1"]},
        resolution_method="graph_evidence",
    )

    alias = confirm_entity_resolution_candidate(db, candidate.id)
    db.commit()

    assert candidate.status == "confirmed"
    assert alias.entity_id == entity.id
    assert alias.alias == "谭彦超"
    assert alias.normalized_key == "谭彦超"
    assert db.query(EntityAlias).filter_by(entity_id=entity.id, normalized_key="谭彦超").count() == 1
    assert "谭彦超" in db.query(KnowledgeEntity).filter_by(id=entity.id).one().aliases
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_entity_resolution_candidates_red.db'
python -m pytest backend/tests/test_entity_resolution_candidates.py -q
Remove-Item .\_entity_resolution_candidates_red.db -ErrorAction SilentlyContinue
```

Expected: import error for `EntityResolutionCandidate`.

- [ ] **Step 3: Add EntityResolutionCandidate model**

Modify `backend/app/models/entity.py`.

Add class after `EntityRelation`:

```python
class EntityResolutionCandidate(Base):
    __tablename__ = "entity_resolution_candidate"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "alias_normalized_key",
            "candidate_entity_id",
            "status",
            name="uq_entity_resolution_candidate_status",
        ),
        Index("ix_entity_resolution_candidate_status", "user_id", "status"),
    )

    id = Column(CHAR(36), primary_key=True, default=_uuid)
    user_id = Column(CHAR(36), default="default-user", nullable=False, index=True)
    alias_surface = Column(String(512), nullable=False)
    alias_normalized_key = Column(String(512), nullable=False, index=True)
    candidate_entity_id = Column(CHAR(36), ForeignKey("knowledge_entity.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_entity_name = Column(String(512), nullable=False)
    entity_type = Column(String(64), nullable=False, index=True)
    confidence = Column(Float, default=0.5)
    status = Column(String(32), default="pending_review", index=True)
    evidence_summary = Column(Text)
    evidence = Column(JSON, default=dict)
    resolution_method = Column(String(64), default="graph_evidence", index=True)
    created_at = Column(DateTime, default=local_now)
    updated_at = Column(DateTime, default=local_now, onupdate=local_now)

    candidate_entity = relationship("KnowledgeEntity")
```

Modify `backend/app/models/__init__.py` to export `EntityResolutionCandidate`.

Modify `backend/app/utils/auto_migrate.py` and add:

```python
"uq_entity_resolution_candidate_status",
```

- [ ] **Step 4: Implement confirmation service**

Create `backend/app/services/entity_resolution_candidates.py`:

```python
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.models import EntityAlias, EntityResolutionCandidate, KnowledgeEntity


def create_resolution_candidate(
    db: Session,
    *,
    user_id: str,
    alias_surface: str,
    alias_normalized_key: str,
    candidate_entity_id: str,
    confidence: float,
    evidence_summary: str,
    evidence: dict,
    resolution_method: str = "graph_evidence",
) -> EntityResolutionCandidate:
    entity = db.query(KnowledgeEntity).filter_by(id=candidate_entity_id, user_id=user_id).one()
    existing = (
        db.query(EntityResolutionCandidate)
        .filter_by(
            user_id=user_id,
            alias_normalized_key=alias_normalized_key,
            candidate_entity_id=candidate_entity_id,
            status="pending_review",
        )
        .first()
    )
    if existing:
        return existing
    candidate = EntityResolutionCandidate(
        user_id=user_id,
        alias_surface=alias_surface,
        alias_normalized_key=alias_normalized_key,
        candidate_entity_id=entity.id,
        candidate_entity_name=entity.canonical_name,
        entity_type=entity.entity_type,
        confidence=confidence,
        status="pending_review",
        evidence_summary=evidence_summary,
        evidence=evidence,
        resolution_method=resolution_method,
    )
    db.add(candidate)
    db.flush()
    return candidate


def confirm_entity_resolution_candidate(db: Session, candidate_id: str) -> EntityAlias:
    candidate = db.query(EntityResolutionCandidate).filter_by(id=candidate_id).one()
    entity = db.query(KnowledgeEntity).filter_by(id=candidate.candidate_entity_id).one()
    alias = (
        db.query(EntityAlias)
        .filter_by(entity_id=entity.id, normalized_key=candidate.alias_normalized_key)
        .first()
    )
    if alias is None:
        alias = EntityAlias(
            entity_id=entity.id,
            alias=candidate.alias_surface,
            normalized_key=candidate.alias_normalized_key,
            confidence=candidate.confidence,
            extraction_method="user_confirmed_resolution",
        )
        db.add(alias)
    aliases = list(entity.aliases or [])
    if candidate.alias_normalized_key not in aliases:
        aliases.append(candidate.alias_normalized_key)
        entity.aliases = aliases
    candidate.status = "confirmed"
    db.flush()
    return alias
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_entity_resolution_candidates_green.db'
python -m pytest backend/tests/test_entity_resolution_candidates.py -q
Remove-Item .\_entity_resolution_candidates_green.db -ErrorAction SilentlyContinue
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/entity.py backend/app/models/__init__.py backend/app/utils/auto_migrate.py backend/app/services/entity_resolution_candidates.py backend/tests/test_entity_resolution_candidates.py
git commit -m "feat: add reviewable entity resolution candidates"
```

---

### Task 5: Surface Confirmed Aliases and Pending Candidates in Entity Graph Search

**Files:**

- Modify: `engine/app/agent/tools/entity_graph_search.py`
- Test: `engine/tests/test_entity_graph_search_tool.py`

- [ ] **Step 1: Write failing engine tests**

Append to `engine/tests/test_entity_graph_search_tool.py`:

```python
def test_entity_graph_search_service_returns_possible_matches_from_pending_candidates():
    class CandidateClient:
        def query_entity_context(self, normalized_keys, limit):
            assert "谭彦超" in normalized_keys
            return {
                "entities": [],
                "sources": [],
                "paths": [],
                "candidates": [
                    {
                        "alias_surface": "谭彦超",
                        "candidate_entity_name": "Yanchao Tan",
                        "confidence": 0.82,
                        "evidence_summary": "same OpenViewer source and Fuzhou University affiliation",
                    }
                ],
            }

    service = EntityGraphSearchService(client=CandidateClient())
    payload = service.search_entity_context("谭彦超", limit=5)

    assert payload["status"] == "candidate"
    assert payload["candidates"][0]["candidate_entity_name"] == "Yanchao Tan"


def test_neo4j_query_client_queries_aliases_before_entities():
    driver = FakeNeo4jDriver()
    client = Neo4jEntityQueryClient(driver=driver, database="neo4j")

    client.query_entity_context(["谭彦超"], limit=3)

    query, params = driver.session_obj.calls[0]
    assert "Alias" in query
    assert "ALIAS_OF" in query
    assert params == {"keys": ["谭彦超"], "limit": 3}
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest engine/tests/test_entity_graph_search_tool.py::test_entity_graph_search_service_returns_possible_matches_from_pending_candidates engine/tests/test_entity_graph_search_tool.py::test_neo4j_query_client_queries_aliases_before_entities -q
```

Expected: service returns `insufficient` instead of `candidate` or payload drops candidates.

- [ ] **Step 3: Update EntityGraphSearchService**

Modify `engine/app/agent/tools/entity_graph_search.py`.

In `EntityGraphSearchService.search_entity_context`, preserve `candidates`:

```python
candidates = result.get("candidates") or []
if result.get("entities") or result.get("sources"):
    status = "success"
elif candidates:
    status = "candidate"
else:
    status = "insufficient"
return {
    "status": status,
    "summary": f"Found {len(result.get('entities') or [])} entities, {len(result.get('sources') or [])} sources, and {len(candidates)} possible matches.",
    "entities": result.get("entities") or [],
    "sources": result.get("sources") or [],
    "paths": result.get("paths") or [],
    "candidates": candidates,
    "normalized_keys": keys,
}
```

Ensure `Neo4jEntityQueryClient.query_entity_context` returns `candidates` with an empty list by default. If Cypher is expanded in this task, keep all keys/limits parameterized.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest engine/tests/test_entity_graph_search_tool.py -q
```

Expected: all entity graph search tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/app/agent/tools/entity_graph_search.py engine/tests/test_entity_graph_search_tool.py
git commit -m "feat: surface entity resolution candidates in graph search"
```

---

### Task 6: Focused Verification

**Files:**

- No code changes expected.

- [ ] **Step 1: Run backend focused tests**

Run:

```powershell
$env:DATABASE_URL='sqlite:///./_topic_group_final_backend.db'
python -m pytest backend/tests/test_topic_group_models.py backend/tests/test_topic_grouping.py backend/tests/test_entity_resolution_candidates.py backend/tests/test_entity_models.py backend/tests/test_entity_resolution.py backend/tests/test_graph_client.py backend/tests/test_graph_projection.py backend/tests/test_backfill_entity_graph.py backend/tests/test_config.py backend/tests/test_knowledge_governance_models.py -q
Remove-Item .\_topic_group_final_backend.db -ErrorAction SilentlyContinue
```

Expected: all tests pass.

- [ ] **Step 2: Run engine focused tests**

Run:

```powershell
python -m pytest engine/tests/test_entity_graph_search_tool.py engine/tests/test_agent_tools.py engine/tests/test_config.py engine/tests/test_deep_search_executors.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short --branch
```

Expected: clean worktree on `feature/entity-graph-projection`, ahead of origin by the new commits.

- [ ] **Step 4: Report known not-run items**

Report that real MySQL/Neo4j smoke is not run unless the user explicitly asks to run it. If it is run, use the existing container credentials:

```text
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
```

Do not run backend and engine full suites concurrently.
