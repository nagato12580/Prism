"""Create the versioned knowledge schema for fresh and legacy databases."""

from collections.abc import Callable

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
        sa.Column("active_index_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_graph_generation", sa.Integer(), nullable=False, server_default="0"),
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
        sa.Column("tenant_id", sa.CHAR(36), nullable=True),
        sa.Column("kb_uid", sa.CHAR(36), nullable=True),
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
        sa.Column("kb_uid", sa.CHAR(36), nullable=True),
        sa.Column("tenant_id", sa.CHAR(36), nullable=True),
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
        sa.Column("active_index_generation", sa.Integer(), nullable=False, server_default="0"),
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
        sa.Column("kb_uid", sa.CHAR(36), nullable=True),
        sa.Column("file_uid", sa.CHAR(36), nullable=True),
        sa.Column("item_id", sa.CHAR(36), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
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
        sa.Column("tenant_id", sa.CHAR(36), nullable=True),
        sa.Column("kb_uid", sa.CHAR(36), nullable=True),
        sa.Column("file_uid", sa.CHAR(36), nullable=True),
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


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _create_state_table(existing_tables: set[str]) -> None:
    op.create_table(
        STATE_TABLE,
        sa.Column("table_name", sa.String(64), primary_key=True),
        sa.Column("existed_before", sa.Boolean(), nullable=False),
    )
    state = sa.table(
        STATE_TABLE,
        sa.column("table_name", sa.String(64)),
        sa.column("existed_before", sa.Boolean()),
    )
    op.bulk_insert(
        state,
        [{"table_name": name, "existed_before": name in existing_tables} for name in TABLE_ORDER],
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


def _backfill_legacy_rows() -> None:
    op.execute(
        sa.text(
            "UPDATE knowledge_topic SET "
            "kb_uid = COALESCE(kb_uid, UUID()), "
            "tenant_id = COALESCE(tenant_id, user_id), "
            "owner_user_id = COALESCE(owner_user_id, user_id), "
            "status = COALESCE(status, 'active'), version = COALESCE(version, 1), "
            "active_index_generation = COALESCE(active_index_generation, 0), "
            "active_graph_generation = COALESCE(active_graph_generation, 0)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE knowledge_file f LEFT JOIN knowledge_topic t ON f.topic_id = t.id SET "
            "f.file_uid = COALESCE(f.file_uid, UUID()), "
            "f.kb_uid = COALESCE(f.kb_uid, t.kb_uid), "
            "f.tenant_id = COALESCE(f.tenant_id, f.user_id), "
            "f.storage_uri = COALESCE(f.storage_uri, f.file_path), "
            "f.original_filename = COALESCE(f.original_filename, f.original_name), "
            "f.content_sha256 = COALESCE(f.content_sha256, f.md5), "
            "f.size_bytes = COALESCE(f.size_bytes, f.file_size), "
            "f.parse_status = COALESCE(f.parse_status, 'pending'), "
            "f.index_status = COALESCE(f.index_status, 'pending'), "
            "f.graph_status = COALESCE(f.graph_status, 'pending'), "
            "f.parsed_content_version = COALESCE(f.parsed_content_version, 0), "
            "f.active_index_generation = COALESCE(f.active_index_generation, 0)"
        )
    )
    op.execute(sa.text("UPDATE knowledge_item SET content_version = COALESCE(content_version, 1), tenant_id = COALESCE(tenant_id, user_id)"))
    op.execute(sa.text("UPDATE knowledge_chunk SET chunk_uid = COALESCE(chunk_uid, UUID()), generation = COALESCE(generation, 0)"))
    op.execute(
        sa.text(
            "UPDATE knowledge_job SET attempt = COALESCE(attempt, attempts, 0), "
            "attempts = COALESCE(attempts, attempt, 0), max_attempts = COALESCE(max_attempts, 3), "
            "status = COALESCE(status, 'queued'), priority = COALESCE(priority, 100), "
            "stage = COALESCE(stage, ''), progress_current = COALESCE(progress_current, 0), "
            "progress_total = COALESCE(progress_total, 0), retryable = COALESCE(retryable, 0)"
        )
    )


def _enforce_required_columns() -> None:
    required = {
        "knowledge_topic": ["kb_uid", "tenant_id", "owner_user_id", "status", "version", "active_index_generation", "active_graph_generation"],
        "knowledge_file": ["file_uid", "parse_status", "index_status", "graph_status", "parsed_content_version", "active_index_generation"],
        "knowledge_item": ["content_version"],
        "knowledge_chunk": ["chunk_uid", "generation"],
        "knowledge_job": ["status", "priority", "attempt", "attempts", "max_attempts", "stage", "progress_current", "progress_total", "retryable"],
    }
    for table_name, names in required.items():
        columns = {column.name: column for column in COLUMN_FACTORIES[table_name]()}
        for name in names:
            op.alter_column(table_name, name, existing_type=columns[name].type, nullable=False)


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

    states = dict(bind.execute(sa.text(f"SELECT table_name, existed_before FROM {STATE_TABLE}")).all())
    for table_name in reversed(TABLE_ORDER):
        if not states.get(table_name):
            op.drop_table(table_name)
            continue

        existing_columns = {column["name"] for column in _inspector().get_columns(table_name)}
        existing_unique = {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)}
        for name, _ in UNIQUE_CONSTRAINTS.get(table_name, []):
            if name in existing_unique:
                op.drop_constraint(name, table_name, type_="unique")
        original_names = {
            "knowledge_topic": {"id", "user_id", "name"},
            "knowledge_item": {"id", "title", "content", "summary", "source_type", "source_ref", "tags", "category", "status", "user_id", "created_at", "updated_at"},
            "knowledge_file": {"id", "user_id", "topic_id", "item_id", "title", "original_name", "media_type", "mime_type", "file_type", "file_size", "md5", "file_path", "parse_status", "description", "tags", "source_type", "page_count", "content_text", "uploaded_at", "last_modified_at", "created_at", "updated_at", "error_message", "governance_status", "governance_progress_current", "governance_progress_total", "governance_error_message", "governance_started_at", "governance_finished_at"},
            "knowledge_chunk": {"id", "item_id", "chunk_text", "chunk_index", "chunk_type", "parent_id", "embedding_id", "extra_meta", "created_at"},
            "knowledge_job": {"id", "job_type", "resource_id", "item_id", "topic_id", "status", "priority", "attempts", "max_attempts", "progress_current", "progress_total", "stage", "error_code", "error_message", "locked_by", "locked_at", "available_at", "started_at", "finished_at", "created_at", "updated_at"},
        }[table_name]
        for column in reversed(COLUMN_FACTORIES[table_name]()):
            if column.name in existing_columns and column.name not in original_names:
                op.drop_column(table_name, column.name)

    op.drop_table(STATE_TABLE)
