"""Create the versioned knowledge schema for fresh and legacy databases."""

from collections.abc import Callable
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260722_01"
down_revision = None
branch_labels = None
depends_on = None

STATE_TABLE = "alembic_knowledge_foundation_state"
TABLE_ORDER = ["knowledge_topic", "knowledge_item", "knowledge_file", "knowledge_chunk", "knowledge_job"]


def _topic_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), nullable=True),
        sa.Column("kb_uid", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("owner_user_id", sa.CHAR(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("embedding_profile", sa.JSON(), nullable=True),
        sa.Column("parser_config", sa.JSON(), nullable=True),
        sa.Column("chunk_config", sa.JSON(), nullable=True),
        sa.Column("retrieval_config", sa.JSON(), nullable=True),
        sa.Column("graph_config", sa.JSON(), nullable=True),
        sa.Column("active_index_generation", sa.CHAR(36), nullable=False, server_default="0"),
        sa.Column("active_graph_generation", sa.CHAR(36), nullable=False, server_default="0"),
        sa.Column("mindmap", sa.JSON(), nullable=True),
        sa.Column("mindmap_version", sa.Integer(), nullable=True),
        sa.Column("mindmap_generated_at", sa.DateTime(), nullable=True),
        sa.Column("sample_questions", sa.JSON(), nullable=True),
        sa.Column("sample_questions_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]


def _item_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("normalized_markdown", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_ref", sa.String(500), nullable=True),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=True),
        sa.Column("user_id", sa.CHAR(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]


def _file_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("file_uid", sa.CHAR(36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=True),
        sa.Column("topic_id", sa.CHAR(36), nullable=True),
        sa.Column("item_id", sa.CHAR(36), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("storage_uri", sa.String(1024), nullable=True),
        sa.Column("relative_path", sa.String(1024), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("media_type", sa.String(64), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_type", sa.String(20), nullable=True),
        sa.Column("content_sha256", sa.CHAR(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("md5", sa.String(32), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("parser_config_snapshot", sa.JSON(), nullable=True),
        sa.Column("chunk_config_snapshot", sa.JSON(), nullable=True),
        sa.Column("parse_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("index_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("graph_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("parsed_content_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_index_generation", sa.CHAR(36), nullable=False, server_default="0"),
        sa.Column("parse_error", sa.JSON(), nullable=True),
        sa.Column("index_error", sa.JSON(), nullable=True),
        sa.Column("graph_error", sa.JSON(), nullable=True),
        sa.Column("parse_started_at", sa.DateTime(), nullable=True),
        sa.Column("parse_finished_at", sa.DateTime(), nullable=True),
        sa.Column("index_started_at", sa.DateTime(), nullable=True),
        sa.Column("index_finished_at", sa.DateTime(), nullable=True),
        sa.Column("graph_started_at", sa.DateTime(), nullable=True),
        sa.Column("graph_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_job_id", sa.CHAR(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("last_modified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("governance_status", sa.String(24), nullable=True),
        sa.Column("governance_progress_current", sa.Integer(), nullable=True),
        sa.Column("governance_progress_total", sa.Integer(), nullable=True),
        sa.Column("governance_error_message", sa.Text(), nullable=True),
        sa.Column("governance_started_at", sa.DateTime(), nullable=True),
        sa.Column("governance_finished_at", sa.DateTime(), nullable=True),
    ]


def _chunk_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("chunk_uid", sa.CHAR(36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(36), nullable=False),
        sa.Column("file_uid", sa.CHAR(36), nullable=False),
        sa.Column("item_id", sa.CHAR(36), nullable=True),
        sa.Column("generation", sa.CHAR(36), nullable=False, server_default="0"),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("chunk_type", sa.String(16), nullable=True),
        sa.Column("parent_id", sa.CHAR(36), nullable=True),
        sa.Column("parent_chunk_uid", sa.CHAR(36), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("token_start", sa.Integer(), nullable=True),
        sa.Column("token_end", sa.Integer(), nullable=True),
        sa.Column("title_path", sa.JSON(), nullable=True),
        sa.Column("embedding_id", sa.String(100), nullable=True),
        sa.Column("extra_meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    ]


def _job_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(36), nullable=False),
        sa.Column("file_uid", sa.CHAR(36), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("job_type", sa.String(32), nullable=True),
        sa.Column("resource_id", sa.CHAR(36), nullable=True),
        sa.Column("item_id", sa.CHAR(36), nullable=True),
        sa.Column("topic_id", sa.CHAR(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("canceled_by", sa.CHAR(36), nullable=True),
        sa.Column("stage", sa.String(64), nullable=False, server_default=""),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]


COLUMN_FACTORIES: dict[str, Callable[[], list[sa.Column]]] = {
    "knowledge_topic": _topic_columns,
    "knowledge_item": _item_columns,
    "knowledge_file": _file_columns,
    "knowledge_chunk": _chunk_columns,
    "knowledge_job": _job_columns,
}

UNIQUE_CONSTRAINTS = {
    "knowledge_topic": [("uq_knowledge_topic_kb_uid", ["kb_uid"])],
    "knowledge_file": [("uq_knowledge_file_file_uid", ["file_uid"])],
    "knowledge_chunk": [("uq_knowledge_chunk_uid_generation", ["chunk_uid", "generation"])],
    "knowledge_job": [("uq_knowledge_job_idempotency_key", ["idempotency_key"])],
}

REQUIRED_COLUMNS = {
    "knowledge_topic": ["kb_uid", "tenant_id", "owner_user_id", "status", "version", "active_index_generation", "active_graph_generation"],
    "knowledge_file": ["file_uid", "kb_uid", "tenant_id", "parse_status", "index_status", "graph_status", "parsed_content_version", "active_index_generation"],
    "knowledge_item": ["tenant_id", "kb_uid", "content_version"],
    "knowledge_chunk": ["chunk_uid", "kb_uid", "file_uid", "generation"],
    "knowledge_job": ["tenant_id", "kb_uid", "file_uid", "status", "priority", "attempt", "attempts", "max_attempts", "stage", "progress_current", "progress_total", "retryable"],
}


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _create_state_table(existing_tables: set[str]) -> None:
    op.create_table(
        STATE_TABLE,
        sa.Column("table_name", sa.String(64), primary_key=True),
        sa.Column("existed_before", sa.Boolean(), nullable=False),
        sa.Column("added_columns", sa.JSON(), nullable=False),
        sa.Column("added_constraints", sa.JSON(), nullable=False),
        sa.Column("nullability_changes", sa.JSON(), nullable=False),
    )
    state = sa.table(
        STATE_TABLE,
        sa.column("table_name", sa.String(64)),
        sa.column("existed_before", sa.Boolean()),
        sa.column("added_columns", sa.JSON()),
        sa.column("added_constraints", sa.JSON()),
        sa.column("nullability_changes", sa.JSON()),
    )
    rows = []
    inspector = _inspector()
    for table_name in TABLE_ORDER:
        existed_before = table_name in existing_tables
        existing_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        } if existed_before else {}
        existing_constraints = {
            constraint["name"] for constraint in inspector.get_unique_constraints(table_name)
        } if existed_before else set()
        rows.append(
            {
                "table_name": table_name,
                "existed_before": existed_before,
                "added_columns": [
                    column.name for column in COLUMN_FACTORIES[table_name]() if column.name not in existing_columns
                ],
                "added_constraints": [
                    name for name, _ in UNIQUE_CONSTRAINTS.get(table_name, []) if name not in existing_constraints
                ],
                "nullability_changes": {
                    name: True
                    for name in REQUIRED_COLUMNS[table_name]
                    if name in existing_columns and existing_columns[name]["nullable"]
                },
            }
        )
    op.bulk_insert(
        state,
        rows,
    )


def _add_missing_columns(table_name: str) -> None:
    existing = {column["name"] for column in _inspector().get_columns(table_name)}
    for column in COLUMN_FACTORIES[table_name]():
        if column.name in existing:
            continue
        required = not column.nullable
        if required:
            column.nullable = True
        op.add_column(table_name, column)


def _is_uuid4(value: str | None) -> bool:
    if not value:
        return False
    try:
        return uuid.UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


def _backfill_public_uuid4(table_name: str, uid_column: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, {uid_column} FROM {table_name}")).mappings()
    for row in rows:
        if _is_uuid4(row[uid_column]):
            continue
        value = row["id"] if _is_uuid4(row["id"]) else str(uuid.uuid4())
        bind.execute(
            sa.text(f"UPDATE {table_name} SET {uid_column} = :value WHERE id = :id"),
            {"value": value, "id": row["id"]},
        )


def _require_resolved(table_name: str, columns: list[str]) -> None:
    predicate = " OR ".join(f"{column} IS NULL" for column in columns)
    count = op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE {predicate}")
    ).scalar_one()
    if count:
        joined = ", ".join(columns)
        raise RuntimeError(f"Cannot migrate {table_name}: {count} row(s) lack required scope fields: {joined}")


def _reject_ambiguous_item_scope() -> None:
    count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT item_id FROM knowledge_file WHERE item_id IS NOT NULL "
            "GROUP BY item_id HAVING COUNT(DISTINCT kb_uid) > 1 OR COUNT(DISTINCT tenant_id) > 1) ambiguous"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"Cannot migrate knowledge_item: {count} item(s) map to conflicting file scopes")


def _reject_ambiguous_chunk_file() -> None:
    count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT item_id FROM knowledge_file WHERE item_id IS NOT NULL "
            "GROUP BY item_id HAVING COUNT(DISTINCT file_uid) > 1) ambiguous"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"Cannot migrate knowledge_chunk: {count} item(s) map to multiple files")


def _backfill_legacy_rows() -> None:
    _backfill_public_uuid4("knowledge_topic", "kb_uid")
    _backfill_public_uuid4("knowledge_file", "file_uid")
    _backfill_public_uuid4("knowledge_chunk", "chunk_uid")
    op.execute(
        sa.text(
            "UPDATE knowledge_topic SET "
            "tenant_id = COALESCE(tenant_id, user_id, 'default-user'), "
            "owner_user_id = COALESCE(owner_user_id, user_id, 'default-user'), "
            "status = COALESCE(status, 'active'), version = COALESCE(version, 1), "
            "active_index_generation = COALESCE(active_index_generation, '0'), "
            "active_graph_generation = COALESCE(active_graph_generation, '0')"
        )
    )
    _require_resolved("knowledge_topic", ["kb_uid", "tenant_id", "owner_user_id"])
    op.execute(
        sa.text(
            "UPDATE knowledge_file f LEFT JOIN knowledge_topic t ON f.topic_id = t.id SET "
            "f.kb_uid = COALESCE(f.kb_uid, t.kb_uid), "
            "f.tenant_id = COALESCE(f.tenant_id, f.user_id, t.tenant_id), "
            "f.storage_uri = COALESCE(f.storage_uri, f.file_path), "
            "f.original_filename = COALESCE(f.original_filename, f.original_name), "
            "f.content_sha256 = COALESCE(f.content_sha256, f.md5), "
            "f.size_bytes = COALESCE(f.size_bytes, f.file_size), "
            "f.parse_status = COALESCE(f.parse_status, 'pending'), "
            "f.index_status = COALESCE(f.index_status, 'pending'), "
            "f.graph_status = COALESCE(f.graph_status, 'pending'), "
            "f.parsed_content_version = COALESCE(f.parsed_content_version, 0), "
            "f.active_index_generation = COALESCE(f.active_index_generation, '0')"
        )
    )
    _require_resolved("knowledge_file", ["file_uid", "kb_uid", "tenant_id"])
    _reject_ambiguous_item_scope()
    op.execute(
        sa.text(
            "UPDATE knowledge_item i LEFT JOIN ("
            "SELECT item_id, MIN(kb_uid) kb_uid, MIN(tenant_id) tenant_id FROM knowledge_file "
            "WHERE item_id IS NOT NULL GROUP BY item_id) f ON f.item_id = i.id SET "
            "i.kb_uid = COALESCE(i.kb_uid, f.kb_uid), "
            "i.tenant_id = COALESCE(i.tenant_id, i.user_id, f.tenant_id), "
            "i.content_version = COALESCE(i.content_version, 1)"
        )
    )
    _require_resolved("knowledge_item", ["kb_uid", "tenant_id"])
    _reject_ambiguous_chunk_file()
    op.execute(
        sa.text(
            "UPDATE knowledge_chunk c JOIN knowledge_item i ON c.item_id = i.id "
            "LEFT JOIN (SELECT item_id, MIN(file_uid) file_uid FROM knowledge_file "
            "WHERE item_id IS NOT NULL GROUP BY item_id) f ON f.item_id = i.id SET "
            "c.kb_uid = COALESCE(c.kb_uid, i.kb_uid), "
            "c.file_uid = COALESCE(c.file_uid, f.file_uid), "
            "c.generation = COALESCE(c.generation, '0')"
        )
    )
    _require_resolved("knowledge_chunk", ["chunk_uid", "kb_uid", "file_uid", "generation"])
    op.execute(
        sa.text(
            "UPDATE knowledge_job j LEFT JOIN knowledge_file f ON j.resource_id = f.id "
            "LEFT JOIN knowledge_item i ON j.item_id = i.id "
            "LEFT JOIN knowledge_topic t ON j.topic_id = t.id SET "
            "j.tenant_id = COALESCE(j.tenant_id, f.tenant_id, i.tenant_id, t.tenant_id), "
            "j.kb_uid = COALESCE(j.kb_uid, f.kb_uid, i.kb_uid, t.kb_uid), "
            "j.file_uid = COALESCE(j.file_uid, f.file_uid), "
            "j.attempt = COALESCE(j.attempt, j.attempts, 0), "
            "j.attempts = COALESCE(j.attempts, j.attempt, 0), j.max_attempts = COALESCE(j.max_attempts, 3), "
            "j.status = COALESCE(j.status, 'queued'), j.priority = COALESCE(j.priority, 100), "
            "j.stage = COALESCE(j.stage, ''), j.progress_current = COALESCE(j.progress_current, 0), "
            "j.progress_total = COALESCE(j.progress_total, 0), j.retryable = COALESCE(j.retryable, 0)"
        )
    )
    _require_resolved("knowledge_job", ["tenant_id", "kb_uid", "file_uid"])


def _enforce_required_columns() -> None:
    for table_name, names in REQUIRED_COLUMNS.items():
        existing_columns = {column["name"]: column for column in _inspector().get_columns(table_name)}
        for name in names:
            existing = existing_columns[name]
            op.alter_column(
                table_name,
                name,
                existing_type=existing["type"],
                existing_server_default=sa.text(existing["default"]) if isinstance(existing["default"], str) else existing["default"],
                existing_comment=existing.get("comment"),
                nullable=False,
            )


def _create_unique_constraints() -> None:
    for table_name, constraints in UNIQUE_CONSTRAINTS.items():
        existing = {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)}
        for name, columns in constraints:
            if name not in existing:
                op.create_unique_constraint(name, table_name, columns)


def upgrade() -> None:
    existing_tables = set(_inspector().get_table_names())
    if STATE_TABLE not in existing_tables:
        _create_state_table(existing_tables)

    for table_name in TABLE_ORDER:
        if table_name not in existing_tables:
            constraints = [sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS.get(table_name, [])]
            op.create_table(table_name, *COLUMN_FACTORIES[table_name](), *constraints)
        else:
            _add_missing_columns(table_name)

    _backfill_legacy_rows()
    _enforce_required_columns()
    _create_unique_constraints()


def downgrade() -> None:
    bind = op.get_bind()
    if STATE_TABLE not in _inspector().get_table_names():
        raise RuntimeError(f"{STATE_TABLE} is required to safely downgrade this revision")

    state_rows = bind.execute(sa.text(f"SELECT * FROM {STATE_TABLE}")).mappings().all()
    states = {row["table_name"]: row for row in state_rows}
    for table_name in reversed(TABLE_ORDER):
        state = states[table_name]
        if not state["existed_before"]:
            op.drop_table(table_name)
            continue

        existing_columns = {column["name"] for column in _inspector().get_columns(table_name)}
        existing_unique = {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)}
        added_constraints = json.loads(state["added_constraints"]) if isinstance(state["added_constraints"], str) else state["added_constraints"]
        for name in added_constraints:
            if name in existing_unique:
                op.drop_constraint(name, table_name, type_="unique")
        nullability_changes = json.loads(state["nullability_changes"]) if isinstance(state["nullability_changes"], str) else state["nullability_changes"]
        for name, nullable in nullability_changes.items():
            if name in existing_columns:
                existing = next(column for column in _inspector().get_columns(table_name) if column["name"] == name)
                op.alter_column(
                    table_name,
                    name,
                    existing_type=existing["type"],
                    existing_server_default=sa.text(existing["default"]) if isinstance(existing["default"], str) else existing["default"],
                    existing_comment=existing.get("comment"),
                    nullable=nullable,
                )
        added_columns = json.loads(state["added_columns"]) if isinstance(state["added_columns"], str) else state["added_columns"]
        for name in reversed(added_columns):
            if name in existing_columns:
                op.drop_column(table_name, name)

    op.drop_table(STATE_TABLE)
