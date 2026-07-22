# Knowledge Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish versioned MySQL schema, stable knowledge IDs, one actor/policy boundary, replaceable file storage, durable lease-based Jobs, and uniform API errors without changing the existing RAG answer behavior.

**Architecture:** Add Alembic as the production migration source while retaining SQLite `create_all` for unit tests. Introduce small domain modules around existing models; the new `/api/v1/knowledge-bases` control-plane router coexists with legacy `/knowledge` until the cutover plan.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, MySQL 8, SQLite, Redis 7, pytest

---

## File Structure

- Modify: `requirements.txt` — add pinned Alembic dependency.
- Create: `alembic.ini` — migration CLI configuration.
- Create: `backend/alembic/env.py` — load Prism Base/settings for online migrations.
- Create: `backend/alembic/script.py.mako` — migration template.
- Create: `backend/alembic/versions/20260722_01_knowledge_foundation.py` — additive/backfill migration.
- Modify: `backend/app/main.py` — stop `auto_migrate` after Alembic cutover flag is enabled.
- Create: `backend/app/models/knowledge_types.py` — controlled statuses and UUID helper.
- Modify: `backend/app/models/knowledge_item.py` — stable IDs, scope, configs, stage/generation fields.
- Modify: `backend/app/models/knowledge_job.py` — durable command/lease/cancel/idempotency fields.
- Modify: `backend/app/models/__init__.py` — register changed/new models.
- Create: `backend/app/security/__init__.py`
- Create: `backend/app/security/actor.py` — `ActorContext` and FastAPI dependency.
- Create: `backend/app/services/knowledge_access.py` — one knowledge authorization policy.
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/files.py` — `FileStorage` protocol and local-volume adapter.
- Create: `backend/app/services/knowledge_jobs.py` — Job transition/lease API.
- Modify: `backend/app/services/knowledge_job_queue.py` — enqueue only committed Job IDs.
- Create: `backend/app/api/errors.py` — typed domain/API errors.
- Create: `backend/app/api/knowledge_bases.py` — initial authorized KB CRUD.
- Modify: `backend/app/api/__init__.py` and `backend/app/main.py` — register v1 router.
- Create: `backend/tests/test_actor_context.py`
- Create: `backend/tests/test_knowledge_access.py`
- Create: `backend/tests/test_file_storage.py`
- Create: `backend/tests/test_knowledge_job_state.py`
- Create: `backend/tests/test_knowledge_bases_v1_api.py`
- Create: `backend/tests/integration/test_knowledge_migrations.py`
- Create: `backend/tests/integration/test_knowledge_job_mysql.py`

## Task 1: Introduce Alembic and a Real Knowledge Migration

**Files:**
- Modify: `requirements.txt`
- Create: `alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/20260722_01_knowledge_foundation.py`
- Create: `backend/tests/integration/test_knowledge_migrations.py`

- [ ] **Step 1: Add the failing migration smoke test**

```python
# backend/tests/integration/test_knowledge_migrations.py
import os
import subprocess

from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrades_legacy_knowledge_schema(mysql_database_url: str):
    engine = create_engine(mysql_database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_job"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_chunk"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_file"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_item"))
        conn.execute(text("DROP TABLE IF EXISTS knowledge_topic"))
        conn.execute(text("CREATE TABLE knowledge_topic (id CHAR(36) PRIMARY KEY, user_id CHAR(36), name VARCHAR(255))"))

    env = {**os.environ, "DATABASE_URL": mysql_database_url}
    subprocess.run(["alembic", "upgrade", "head"], cwd=".", env=env, check=True)

    columns = {column["name"] for column in inspect(engine).get_columns("knowledge_topic")}
    assert {"kb_uid", "tenant_id", "owner_user_id", "active_index_generation"} <= columns
```

- [ ] **Step 2: Run it and confirm the migration tool is absent**

Run:

```bash
python -m pytest backend/tests/integration/test_knowledge_migrations.py -v
```

Expected: FAIL because Alembic/config/migration does not exist.

- [ ] **Step 3: Add Alembic and configuration**

Append to `requirements.txt`:

```text
alembic==1.14.1
```

Create `alembic.ini`:

```ini
[alembic]
script_location = backend/alembic
prepend_sys_path = .
sqlalchemy.url = driver://unused

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Create `backend/alembic/env.py`:

```python
from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app.config import settings
from backend.app.database import Base
from backend.app import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.DATABASE_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
```

- [ ] **Step 4: Create the additive/backfill migration**

Use `op.get_bind()` + SQLAlchemy inspector so the migration handles both fresh and legacy schemas. The migration must create missing tables from the final ORM metadata, add the approved columns, backfill UUID/scope values, then add non-null/unique indexes. Implement these exact column groups:

```python
# backend/alembic/versions/20260722_01_knowledge_foundation.py
from alembic import op
import sqlalchemy as sa

revision = "20260722_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_topic" not in inspector.get_table_names():
        from backend.app.database import Base
        from backend.app import models  # noqa: F401
        Base.metadata.create_all(bind)
        return

    existing = {column["name"] for column in inspector.get_columns("knowledge_topic")}
    additions = {
        "kb_uid": sa.Column("kb_uid", sa.CHAR(36), nullable=True),
        "tenant_id": sa.Column("tenant_id", sa.CHAR(36), nullable=True),
        "owner_user_id": sa.Column("owner_user_id", sa.CHAR(36), nullable=True),
        "status": sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        "version": sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        "configs": sa.Column("configs", sa.JSON(), nullable=True),
        "active_index_generation": sa.Column("active_index_generation", sa.CHAR(36), nullable=True),
        "active_graph_generation": sa.Column("active_graph_generation", sa.CHAR(36), nullable=True),
        "deleted_at": sa.Column("deleted_at", sa.DateTime(), nullable=True),
    }
    for name, column in additions.items():
        if name not in existing:
            op.add_column("knowledge_topic", column)

    op.execute("UPDATE knowledge_topic SET kb_uid=id WHERE kb_uid IS NULL")
    op.execute("UPDATE knowledge_topic SET tenant_id=COALESCE(user_id, 'default-user') WHERE tenant_id IS NULL")
    op.execute("UPDATE knowledge_topic SET owner_user_id=COALESCE(user_id, 'default-user') WHERE owner_user_id IS NULL")
    op.alter_column("knowledge_topic", "kb_uid", nullable=False)
    op.alter_column("knowledge_topic", "tenant_id", nullable=False)
    op.alter_column("knowledge_topic", "owner_user_id", nullable=False)
    op.create_unique_constraint("uq_knowledge_topic_kb_uid", "knowledge_topic", ["kb_uid"])


def downgrade() -> None:
    op.drop_constraint("uq_knowledge_topic_kb_uid", "knowledge_topic", type_="unique")
    for name in [
        "deleted_at", "active_graph_generation", "active_index_generation", "configs",
        "version", "status", "owner_user_id", "tenant_id", "kb_uid",
    ]:
        op.drop_column("knowledge_topic", name)
```

The same revision must add the exact fields defined in Tasks 2 and 5 to `knowledge_file`, `knowledge_chunk`, and `knowledge_job`; do not rely on `auto_migrate` for them.

- [ ] **Step 5: Run migration tests against fresh and legacy MySQL schemas**

Run:

```bash
python -m pytest backend/tests/integration/test_knowledge_migrations.py -v
```

Precondition: `MYSQL_TEST_DATABASE_URL` is already set to the dedicated `prism_test` database by the local test environment; never embed its password in the plan or test source.

Expected: PASS for fresh and legacy fixtures.

- [ ] **Step 6: Commit the migration checkpoint**

```bash
git add requirements.txt alembic.ini backend/alembic backend/tests/integration/test_knowledge_migrations.py
git commit -m "feat(knowledge): 引入 Alembic 知识库迁移"
```

## Task 2: Make Knowledge IDs, Scope, and Status Explicit

**Files:**
- Create: `backend/app/models/knowledge_types.py`
- Modify: `backend/app/models/knowledge_item.py`
- Modify: `backend/app/models/knowledge_job.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Write failing ORM contract tests**

```python
def test_knowledge_topic_has_stable_scope_and_config(db_session):
    from backend.app.models import KnowledgeTopic

    topic = KnowledgeTopic(name="Manuals", tenant_id="tenant-a", owner_user_id="user-a")
    db_session.add(topic)
    db_session.commit()
    assert topic.kb_uid
    assert topic.status == "active"
    assert topic.version == 1


def test_chunk_and_file_have_generation_aware_fields(db_session):
    from backend.app.models import KnowledgeChunk, KnowledgeFile, KnowledgeItem, KnowledgeTopic

    topic = KnowledgeTopic(name="Manuals", tenant_id="tenant-a", owner_user_id="user-a")
    item = KnowledgeItem(title="A", tenant_id="tenant-a", kb_uid=topic.kb_uid)
    file = KnowledgeFile(title="A", original_filename="a.md", tenant_id="tenant-a", kb_uid=topic.kb_uid, content_sha256="a" * 64)
    chunk = KnowledgeChunk(item=item, chunk_text="text", tenant_id="tenant-a", kb_uid=topic.kb_uid, file_uid=file.file_uid, generation="g1")
    db_session.add_all([topic, item, file, chunk])
    db_session.commit()
    assert file.parse_status == "pending"
    assert file.index_status == "pending"
    assert chunk.chunk_uid
```

- [ ] **Step 2: Verify tests fail on missing fields**

Run:

```bash
$env:DATABASE_URL='sqlite:///./_test.db'
python -m pytest backend/tests/test_models.py -v
```

Expected: FAIL on unknown constructor arguments/attributes.

- [ ] **Step 3: Add controlled types and fields**

Create `knowledge_types.py`:

```python
import enum
import uuid


def uuid4_str() -> str:
    return str(uuid.uuid4())


class ResourceStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETING = "deleting"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"
    SKIPPED = "skipped"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
```

Add the exact approved columns to existing models using `CHAR(36)`, `JSON`, `DateTime`, and controlled string defaults. Keep synonyms only for legacy read compatibility; all new code uses `kb_uid/file_uid/chunk_uid/storage_uri/parse_status/index_status/graph_status`.

- [ ] **Step 4: Run ORM tests**

Run: `python -m pytest backend/tests/test_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the model checkpoint**

```bash
git add backend/app/models backend/tests/test_models.py
git commit -m "feat(knowledge): 增加稳定标识与阶段状态"
```

## Task 3: Centralize Actor Context and Knowledge Authorization

**Files:**
- Create: `backend/app/security/__init__.py`
- Create: `backend/app/security/actor.py`
- Create: `backend/app/services/knowledge_access.py`
- Create: `backend/tests/test_actor_context.py`
- Create: `backend/tests/test_knowledge_access.py`

- [ ] **Step 1: Write failing actor/policy tests**

```python
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


def test_actor_dependency_supplies_compatibility_actor():
    from backend.app.security.actor import ActorContext, get_actor_context

    app = FastAPI()

    @app.get("/actor")
    def actor(actor: ActorContext = Depends(get_actor_context)):
        return actor.model_dump()

    body = TestClient(app).get("/actor").json()
    assert body["actor_id"] == "default-user"
    assert body["tenant_id"] == "default-user"


def test_policy_rejects_non_owner(db_session):
    from backend.app.models import KnowledgeTopic
    from backend.app.security.actor import ActorContext
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = KnowledgeTopic(name="Private", tenant_id="tenant-a", owner_user_id="owner")
    db_session.add(topic)
    db_session.commit()
    actor = ActorContext(actor_id="other", tenant_id="tenant-a", roles=())
    try:
        KnowledgeAccessPolicy(db_session).require_read(actor, topic.kb_uid)
    except KnowledgeAccessDenied:
        pass
    else:
        raise AssertionError("non-owner was allowed")
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest backend/tests/test_actor_context.py backend/tests/test_knowledge_access.py -v`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement ActorContext and Policy**

```python
# backend/app/security/actor.py
from typing import Annotated
from fastapi import Header
from pydantic import BaseModel, ConfigDict


class ActorContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    request_id: str = ""


def get_actor_context(
    x_prism_actor: Annotated[str | None, Header()] = None,
    x_prism_tenant: Annotated[str | None, Header()] = None,
) -> ActorContext:
    actor_id = x_prism_actor or "default-user"
    return ActorContext(actor_id=actor_id, tenant_id=x_prism_tenant or actor_id)
```

```python
# backend/app/services/knowledge_access.py
from sqlalchemy.orm import Session
from backend.app.models import KnowledgeTopic
from backend.app.security.actor import ActorContext


class KnowledgeNotFound(LookupError):
    pass


class KnowledgeAccessDenied(PermissionError):
    pass


class KnowledgeAccessPolicy:
    def __init__(self, db: Session):
        self.db = db

    def require_read(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = self.db.query(KnowledgeTopic).filter_by(kb_uid=kb_uid, deleted_at=None).one_or_none()
        if topic is None:
            raise KnowledgeNotFound(kb_uid)
        if topic.tenant_id != actor.tenant_id or topic.owner_user_id != actor.actor_id:
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    require_manage = require_read
```

- [ ] **Step 4: Run actor/policy tests**

Run: `python -m pytest backend/tests/test_actor_context.py backend/tests/test_knowledge_access.py -v`

Expected: PASS.

- [ ] **Step 5: Commit authorization boundary**

```bash
git add backend/app/security backend/app/services/knowledge_access.py backend/tests/test_actor_context.py backend/tests/test_knowledge_access.py
git commit -m "feat(knowledge): 收敛主体与知识库授权边界"
```

## Task 4: Add Replaceable Local FileStorage

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/files.py`
- Modify: `backend/app/config.py`
- Create: `backend/tests/test_file_storage.py`

- [ ] **Step 1: Write failing staging/containment tests**

```python
from pathlib import Path
import pytest


def test_local_storage_stage_commit_read_delete(tmp_path: Path):
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    staged = storage.stage("tenant-a", "kb-a", "file-a", "a.md", b"hello")
    assert staged.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    final_uri = storage.commit(staged)
    assert storage.read_bytes(final_uri) == b"hello"
    storage.delete(final_uri)
    assert not storage.exists(final_uri)


def test_local_storage_rejects_path_traversal(tmp_path: Path):
    from backend.app.storage.files import InvalidStorageUri, LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    with pytest.raises(InvalidStorageUri):
        storage.read_bytes("local://../../secret")
```

- [ ] **Step 2: Run tests and verify missing module**

Run: `python -m pytest backend/tests/test_file_storage.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement protocol and local adapter**

```python
# backend/app/storage/files.py
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import os


class InvalidStorageUri(ValueError):
    pass


@dataclass(frozen=True)
class StagedFile:
    path: Path
    final_path: Path
    sha256: str
    size_bytes: int


class FileStorage(Protocol):
    def stage(self, tenant_id: str, kb_uid: str, file_uid: str, filename: str, content: bytes) -> StagedFile: ...
    def commit(self, staged: StagedFile) -> str: ...
    def read_bytes(self, storage_uri: str) -> bytes: ...
    def delete(self, storage_uri: str) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.staging = self.root / ".staging"

    def stage(self, tenant_id: str, kb_uid: str, file_uid: str, filename: str, content: bytes) -> StagedFile:
        safe_name = Path(filename).name
        staged_path = self.staging / f"{file_uid}.part"
        final_path = self.root / tenant_id / kb_uid / file_uid / safe_name
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(content)
        return StagedFile(staged_path, final_path, sha256(content).hexdigest(), len(content))

    def commit(self, staged: StagedFile) -> str:
        staged.final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged.path, staged.final_path)
        return f"local://{staged.final_path.relative_to(self.root).as_posix()}"

    def _resolve(self, storage_uri: str) -> Path:
        if not storage_uri.startswith("local://"):
            raise InvalidStorageUri(storage_uri)
        path = (self.root / storage_uri.removeprefix("local://")).resolve()
        if path != self.root and self.root not in path.parents:
            raise InvalidStorageUri(storage_uri)
        return path

    def read_bytes(self, storage_uri: str) -> bytes:
        return self._resolve(storage_uri).read_bytes()

    def delete(self, storage_uri: str) -> None:
        self._resolve(storage_uri).unlink(missing_ok=True)

    def exists(self, storage_uri: str) -> bool:
        return self._resolve(storage_uri).exists()
```

- [ ] **Step 4: Add `KNOWLEDGE_STORAGE_ROOT` to settings and run tests**

Run: `python -m pytest backend/tests/test_file_storage.py -v`

Expected: PASS.

- [ ] **Step 5: Commit storage boundary**

```bash
git add backend/app/storage backend/app/config.py backend/tests/test_file_storage.py
git commit -m "feat(knowledge): 抽象本地文件存储"
```

## Task 5: Implement Durable Job State, Lease, and Idempotency

**Files:**
- Create: `backend/app/services/knowledge_jobs.py`
- Modify: `backend/app/services/knowledge_job_queue.py`
- Create: `backend/tests/test_knowledge_job_state.py`
- Create: `backend/tests/integration/test_knowledge_job_mysql.py`

- [ ] **Step 1: Write failing transition tests**

```python
from datetime import timedelta


def test_job_claim_is_single_winner(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    job = service.create(JobCommand("parse", "tenant-a", "kb-a", "file-a", {"content_version": 1}), "idem-a")
    assert service.claim(job.id, "worker-1", timedelta(seconds=30)) is not None
    assert service.claim(job.id, "worker-2", timedelta(seconds=30)) is None


def test_duplicate_idempotency_key_returns_existing_job(db_session):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    service = KnowledgeJobService(db_session)
    command = JobCommand("parse", "tenant-a", "kb-a", "file-a", {})
    first = service.create(command, "same-key")
    second = service.create(command, "same-key")
    assert first.id == second.id
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `python -m pytest backend/tests/test_knowledge_job_state.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement Job command and transition service**

```python
# backend/app/services/knowledge_jobs.py
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeJob
from backend.app.models.knowledge_types import JobStatus
from backend.app.utils.time import local_now


@dataclass(frozen=True)
class JobCommand:
    job_type: str
    tenant_id: str
    kb_uid: str
    file_uid: str | None
    payload: dict[str, Any]


class KnowledgeJobService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, command: JobCommand, idempotency_key: str) -> KnowledgeJob:
        existing = self.db.query(KnowledgeJob).filter_by(idempotency_key=idempotency_key).one_or_none()
        if existing:
            return existing
        job = KnowledgeJob(
            job_type=command.job_type, tenant_id=command.tenant_id, kb_uid=command.kb_uid,
            file_uid=command.file_uid, payload=command.payload, idempotency_key=idempotency_key,
            status=JobStatus.QUEUED.value,
        )
        self.db.add(job)
        self.db.commit()
        return job

    def claim(self, job_id: str, worker_id: str, lease: timedelta) -> KnowledgeJob | None:
        now = local_now()
        result = self.db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id == job_id, KnowledgeJob.status == JobStatus.QUEUED.value)
            .values(status=JobStatus.CLAIMED.value, lease_owner=worker_id, heartbeat_at=now, lease_expires_at=now + lease)
        )
        self.db.commit()
        return self.db.get(KnowledgeJob, job_id) if result.rowcount == 1 else None
```

Add `heartbeat`, `start`, `progress`, `succeed`, `fail`, `request_cancel`, and `cancel` methods. Each method must use a conditional `UPDATE ... WHERE status IN (...)` and raise `InvalidJobTransition` when `rowcount != 1`.

- [ ] **Step 4: Make Redis enqueue post-commit and ID-only**

Change `_enqueue_job_message` to push only `job.id` after the Job transaction commits. A Redis failure leaves the Job queued; a reconciliation task republishes queued Jobs whose `available_at <= now`.

- [ ] **Step 5: Run SQLite and real MySQL concurrency tests**

Run:

```bash
python -m pytest backend/tests/test_knowledge_job_state.py -v
python -m pytest backend/tests/integration/test_knowledge_job_mysql.py -v
```

Precondition: `MYSQL_TEST_DATABASE_URL` targets the dedicated `prism_test` database.

Expected: one claimant wins under concurrent MySQL sessions; duplicate idempotency returns one Job.

- [ ] **Step 6: Commit durable Jobs**

```bash
git add backend/app/models/knowledge_job.py backend/app/services/knowledge_jobs.py backend/app/services/knowledge_job_queue.py backend/tests/test_knowledge_job_state.py backend/tests/integration/test_knowledge_job_mysql.py
git commit -m "feat(knowledge): 增强任务幂等与租约状态机"
```

## Task 6: Add Uniform Errors and Authorized v1 Knowledge CRUD

**Files:**
- Create: `backend/app/api/errors.py`
- Create: `backend/app/api/knowledge_bases.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/knowledge.py`
- Create: `backend/tests/test_knowledge_bases_v1_api.py`

- [ ] **Step 1: Write failing API tests**

```python
def test_v1_create_and_list_use_actor_scope(client):
    created = client.post(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
        json={"name": "Manuals", "description": "Product manuals"},
    )
    assert created.status_code == 201
    assert created.json()["owner_user_id"] == "alice"

    other = client.get(
        "/api/v1/knowledge-bases",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"},
    )
    assert other.json()["items"] == []


def test_v1_error_envelope_is_structured(client):
    response = client.get("/api/v1/knowledge-bases/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert response.json()["error"]["retryable"] is False
    assert response.json()["error"]["trace_id"]
```

- [ ] **Step 2: Run tests and confirm 404/router failure**

Run: `python -m pytest backend/tests/test_knowledge_bases_v1_api.py -v`

Expected: FAIL because the v1 router is absent.

- [ ] **Step 3: Implement error contract**

```python
# backend/app/api/errors.py
from fastapi import Request
from fastapi.responses import JSONResponse


class ApiProblem(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, retryable: bool = False, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "retryable": exc.retryable, "details": exc.details, "trace_id": trace_id}},
    )
```

- [ ] **Step 4: Implement authorized CRUD router**

Create `knowledge_bases.py` with Pydantic request/response schemas, cursor/page response, and routes for create/list/get/update/delete. Every `{kb_uid}` route obtains `ActorContext` and calls `KnowledgeAccessPolicy` before repository work. Delete in this plan only sets `status=deleting/deleted_at`; physical cleanup is Plan 2.

- [ ] **Step 5: Register router and handlers**

Register under `/api/v1`. Add request trace middleware if none exists; the middleware creates UUID v4 `request.state.trace_id` and sends `X-Trace-ID`.

- [ ] **Step 6: Remove hardcoded default user from new code**

Run:

```bash
rg -n "DEFAULT_USER_ID|default-user" backend/app/api/knowledge_bases.py backend/app/services/knowledge_access.py
```

Expected: only the compatibility value in `security/actor.py`; no route/repository hardcode.

- [ ] **Step 7: Run focused and backend tests**

Run:

```bash
python -m pytest backend/tests/test_knowledge_bases_v1_api.py backend/tests/test_actor_context.py backend/tests/test_knowledge_access.py -v
python -m pytest backend/tests -q
```

Expected: focused tests PASS; pre-existing failures, if any, must be recorded and shown to predate this plan.

- [ ] **Step 8: Commit v1 foundation**

```bash
git add backend/app/api backend/app/main.py backend/app/schemas/knowledge.py backend/tests/test_knowledge_bases_v1_api.py
git commit -m "feat(knowledge): 新增授权知识库 v1 接口"
```

## Plan Verification

- [ ] Run `alembic upgrade head` on fresh and legacy-shaped MySQL.
- [ ] Run `python -m pytest backend/tests/test_actor_context.py backend/tests/test_knowledge_access.py backend/tests/test_file_storage.py backend/tests/test_knowledge_job_state.py backend/tests/test_knowledge_bases_v1_api.py -v`.
- [ ] Run MySQL integration tests.
- [ ] Run `git diff --check` and confirm no secrets/test passwords were committed.
- [ ] Record the six task commit hashes in `2026-07-22-knowledge-system-roadmap.md`.
