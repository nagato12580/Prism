"""Create tenant-scoped knowledge evaluation datasets and runs."""

from alembic import op
import sqlalchemy as sa


revision = "20260722_02"
down_revision = "20260722_01"
branch_labels = None
depends_on = None


def _id() -> sa.CHAR:
    return sa.CHAR(36)


def upgrade() -> None:
    op.create_table(
        "evaluation_dataset",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("dataset_uid", _id(), nullable=False),
        sa.Column("tenant_id", _id(), nullable=False),
        sa.Column("kb_uid", _id(), sa.ForeignKey("knowledge_topic.kb_uid", name="fk_evaluation_dataset_topic", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by", _id(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dataset_uid", name="uq_evaluation_dataset_uid"),
        sa.UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_dataset_id_scope"),
    )
    op.create_index("ix_evaluation_dataset_scope_created", "evaluation_dataset", ["tenant_id", "kb_uid", "created_at"])
    op.create_table(
        "evaluation_dataset_item",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("dataset_id", _id(), nullable=False),
        sa.Column("tenant_id", _id(), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("gold_chunk_uids", sa.JSON(), nullable=False),
        sa.Column("gold_answer", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dataset_id", "ordinal", name="uq_evaluation_dataset_item_ordinal"),
        sa.UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_dataset_item_id_scope"),
        sa.ForeignKeyConstraint(["dataset_id", "tenant_id", "kb_uid"], ["evaluation_dataset.id", "evaluation_dataset.tenant_id", "evaluation_dataset.kb_uid"], name="fk_evaluation_dataset_item_parent_scope", ondelete="CASCADE"),
    )
    op.create_index("ix_evaluation_dataset_item_scope", "evaluation_dataset_item", ["tenant_id", "kb_uid", "dataset_id"])
    op.create_table(
        "evaluation_run",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("run_uid", _id(), nullable=False),
        sa.Column("dataset_id", _id(), nullable=False),
        sa.Column("tenant_id", _id(), nullable=False),
        sa.Column("kb_uid", _id(), sa.ForeignKey("knowledge_topic.kb_uid", name="fk_evaluation_run_topic", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", _id(), nullable=False),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("request_idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("retrieval_config", sa.JSON(), nullable=False),
        sa.Column("embedding_profile", sa.JSON(), nullable=False),
        sa.Column("graph_config", sa.JSON(), nullable=False),
        sa.Column("index_generation", _id(), nullable=True),
        sa.Column("graph_generation", _id(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_uid", name="uq_evaluation_run_uid"),
        sa.UniqueConstraint("tenant_id", "kb_uid", "request_idempotency_key", name="uq_evaluation_run_request_key"),
        sa.UniqueConstraint("id", "tenant_id", "kb_uid", name="uq_evaluation_run_id_scope"),
        sa.ForeignKeyConstraint(["dataset_id", "tenant_id", "kb_uid"], ["evaluation_dataset.id", "evaluation_dataset.tenant_id", "evaluation_dataset.kb_uid"], name="fk_evaluation_run_dataset_scope", ondelete="RESTRICT"),
    )
    op.create_index("ix_evaluation_run_scope_created", "evaluation_run", ["tenant_id", "kb_uid", "created_at"])
    op.create_index("ix_evaluation_run_dataset", "evaluation_run", ["dataset_id"])
    op.create_table(
        "evaluation_run_item",
        sa.Column("id", _id(), primary_key=True),
        sa.Column("run_id", _id(), nullable=False),
        sa.Column("dataset_item_id", _id(), nullable=True),
        sa.Column("tenant_id", _id(), nullable=False),
        sa.Column("kb_uid", _id(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("gold_chunk_uids", sa.JSON(), nullable=False),
        sa.Column("gold_answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_evaluation_run_item_ordinal"),
        sa.ForeignKeyConstraint(["run_id", "tenant_id", "kb_uid"], ["evaluation_run.id", "evaluation_run.tenant_id", "evaluation_run.kb_uid"], name="fk_evaluation_run_item_parent_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_item_id", "tenant_id", "kb_uid"], ["evaluation_dataset_item.id", "evaluation_dataset_item.tenant_id", "evaluation_dataset_item.kb_uid"], name="fk_evaluation_run_item_dataset_item_scope", ondelete="RESTRICT"),
    )
    op.create_index("ix_evaluation_run_item_scope", "evaluation_run_item", ["tenant_id", "kb_uid", "run_id"])
    op.create_index("ix_evaluation_run_item_run_status", "evaluation_run_item", ["run_id", "status"])


def downgrade() -> None:
    op.drop_table("evaluation_run_item")
    op.drop_table("evaluation_run")
    op.drop_table("evaluation_dataset_item")
    op.drop_table("evaluation_dataset")
