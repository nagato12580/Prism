"""Scoped graph facts, generations, and outbox governance.

revision = "20260722_03"
down_revision = "20260722_02"

Adds the authoritative scoped graph fact store + transactional Outbox tables,
and scopes Entity/Alias/Mention/Relation identity under
``tenant_id + kb_uid + graph_generation``. Scope columns are NOT NULL with
``server_default=""`` so legacy rows fall into an empty-scope bucket (preserving
prior dedup semantics) until the scoped graph fact writer (Task 2) populates
real scope. Neo4j and Milvus are disposable projections of this MySQL store.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_03"
down_revision = "20260722_02"
branch_labels = None
depends_on = None


def _id() -> sa.CHAR:
    return sa.CHAR(36)


# Tables created by this migration.
_NEW_TABLES = (
    "knowledge_graph_generation",
    "graph_extraction_revision",
    "graph_outbox_event",
    "graph_projection_receipt",
    "graph_projection_cursor",
    "graph_scope_migration_audit",
)

# Scoped columns added to existing entity fact tables. (column, type)
_ENTITY_SCOPE = (
    ("tenant_id", sa.String(64)),
    ("kb_uid", _id()),
    ("graph_generation", _id()),
)
_MENTION_EXTRA = (
    ("file_uid", _id()),
    ("chunk_uid", _id()),
    ("revision_id", _id()),
    ("active", sa.String(8)),
    ("char_start", sa.Integer()),
    ("char_end", sa.Integer()),
)
_RELATION_EXTRA = (
    ("file_uid", _id()),
    ("revision_id", _id()),
    ("active", sa.String(8)),
)


def _add_scope_columns(table: str, columns) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns(table)}
    for name, type_ in columns:
        if name in existing:
            continue
        server_default = "true" if name == "active" else ""
        op.add_column(
            table,
            sa.Column(name, type_, nullable=False, server_default=server_default),
        )


def upgrade() -> None:
    # 1) Outbox / generation / projection tables.
    op.create_table(
        "knowledge_graph_generation",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("generation", _id(), nullable=False),
        sa.Column("extractor_config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="building"),
        sa.Column("barrier_sequence", sa.BigInteger(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "kb_uid", "generation", name="uq_graph_generation_scope"),
    )
    op.create_index("ix_graph_generation_scope", "knowledge_graph_generation", ["tenant_id", "kb_uid"])

    op.create_table(
        "graph_extraction_revision",
        sa.Column("revision_id", _id(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("file_uid", _id(), nullable=False),
        sa.Column("item_id", _id(), nullable=False),
        sa.Column("chunk_uid", _id(), nullable=False),
        sa.Column("graph_generation", _id(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("extractor_config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("model_version", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "kb_uid", "chunk_uid", "content_hash", "extractor_config_hash",
            name="uq_graph_extraction_key",
        ),
    )
    op.create_index("ix_graph_extraction_scope", "graph_extraction_revision", ["tenant_id", "kb_uid", "chunk_uid"])

    op.create_table(
        "graph_outbox_event",
        sa.Column("sequence", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("event_id", _id(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("graph_generation", _id(), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", _id(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_graph_outbox_event_id"),
    )
    op.create_index("ix_graph_outbox_scope_sequence", "graph_outbox_event", ["tenant_id", "kb_uid", "graph_generation", "sequence"])
    op.create_index("ix_graph_outbox_tenant", "graph_outbox_event", ["tenant_id"])

    op.create_table(
        "graph_projection_receipt",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("event_id", _id(), nullable=False),
        sa.Column("projector", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("applied_sequence", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["graph_outbox_event.event_id"], name="fk_graph_receipt_event", ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", "projector", name="uq_graph_projection_event_target"),
    )
    op.create_index("ix_graph_projection_due", "graph_projection_receipt", ["projector", "status", "next_attempt_at"])

    op.create_table(
        "graph_projection_cursor",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("graph_generation", _id(), nullable=False),
        sa.Column("projector", sa.String(32), nullable=False),
        sa.Column("applied_through_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "kb_uid", "graph_generation", "projector", name="uq_graph_projection_cursor_scope"),
    )

    # Audit table for rows that cannot be assigned to a KB during backfill.
    # Must stay empty: a non-empty table means a fact would be silently discarded.
    op.create_table(
        "graph_scope_migration_audit",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("row_id", _id(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # 2) Scope the entity fact tables. These tables are normally created by the
    #    app's auto_migrate/create_all at startup (alembic 01 does not create
    #    them), so only alter them when they already exist; otherwise the scoped
    #    schema is created later by create_all from the ORM metadata.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "knowledge_entity" in existing_tables:
        _add_scope_columns("knowledge_entity", _ENTITY_SCOPE)
        if "entity_alias" in existing_tables:
            _add_scope_columns("entity_alias", _ENTITY_SCOPE)
        if "entity_mention" in existing_tables:
            _add_scope_columns("entity_mention", _ENTITY_SCOPE + _MENTION_EXTRA)
        if "entity_relation" in existing_tables:
            _add_scope_columns("entity_relation", _ENTITY_SCOPE + _RELATION_EXTRA)

        # 3) Replace the legacy user-only Entity unique key with the scoped identity.
        entity_constraints = {c["name"] for c in inspector.get_unique_constraints("knowledge_entity")}
        if "uq_entity_user_type_key" in entity_constraints:
            op.drop_constraint("uq_entity_user_type_key", "knowledge_entity", type_="unique")
        if "uq_entity_scope_type_key" not in entity_constraints:
            op.create_unique_constraint(
                "uq_entity_scope_type_key",
                "knowledge_entity",
                ["tenant_id", "kb_uid", "graph_generation", "entity_type", "normalized_key"],
            )
        op.create_index(
            "ix_entity_scope",
            "knowledge_entity",
            ["tenant_id", "kb_uid", "graph_generation", "normalized_key"],
            unique=False,
        )

    # 4) Backfill note: legacy rows keep the empty-scope bucket ("") so existing
    #    dedup is preserved. Real tenant/kb/generation scope is populated by the
    #    scoped graph fact writer (Task 2) on subsequent extraction. This
    #    migration intentionally does NOT move or discard any existing fact.


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.drop_index("ix_entity_scope", table_name="knowledge_entity")
    entity_constraints = {c["name"] for c in inspector.get_unique_constraints("knowledge_entity")}
    if "uq_entity_scope_type_key" in entity_constraints:
        op.drop_constraint("uq_entity_scope_type_key", "knowledge_entity", type_="unique")
    if "uq_entity_user_type_key" not in entity_constraints:
        op.create_unique_constraint(
            "uq_entity_user_type_key", "knowledge_entity", ["user_id", "entity_type", "normalized_key"]
        )

    def _drop_cols(table: str, columns) -> None:
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, _ in columns:
            if name in existing:
                op.drop_column(table, name)

    _drop_cols("entity_relation", reversed(_ENTITY_SCOPE + _RELATION_EXTRA))
    _drop_cols("entity_mention", reversed(_ENTITY_SCOPE + _MENTION_EXTRA))
    _drop_cols("entity_alias", reversed(_ENTITY_SCOPE))
    _drop_cols("knowledge_entity", reversed(_ENTITY_SCOPE))

    for table in _NEW_TABLES:
        existing_tables = inspector.get_table_names()
        if table in existing_tables:
            op.drop_table(table)
