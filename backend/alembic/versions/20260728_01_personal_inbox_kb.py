"""Add personal inbox system and source markers.

revision = "20260728_01"
down_revision = "20260722_03"
"""

from alembic import op
import sqlalchemy as sa


revision = "20260728_01"
down_revision = "20260722_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_topic", sa.Column("system_type", sa.String(length=64), nullable=True))
    op.add_column(
        "knowledge_topic",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_topic",
        sa.Column("delete_disabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_index("ix_knowledge_topic_system_type", "knowledge_topic", ["system_type"], unique=False)

    op.add_column("knowledge_file", sa.Column("source_kind", sa.String(length=64), nullable=True))
    op.add_column("knowledge_file", sa.Column("source_id", sa.String(length=128), nullable=True))
    op.add_column("knowledge_file", sa.Column("system_type", sa.String(length=64), nullable=True))
    op.create_index("ix_knowledge_file_source_kind", "knowledge_file", ["source_kind"], unique=False)
    op.create_index("ix_knowledge_file_source_id", "knowledge_file", ["source_id"], unique=False)
    op.create_index("ix_knowledge_file_system_type", "knowledge_file", ["system_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_knowledge_file_system_type", table_name="knowledge_file")
    op.drop_index("ix_knowledge_file_source_id", table_name="knowledge_file")
    op.drop_index("ix_knowledge_file_source_kind", table_name="knowledge_file")
    op.drop_column("knowledge_file", "system_type")
    op.drop_column("knowledge_file", "source_id")
    op.drop_column("knowledge_file", "source_kind")

    op.drop_index("ix_knowledge_topic_system_type", table_name="knowledge_topic")
    op.drop_column("knowledge_topic", "delete_disabled")
    op.drop_column("knowledge_topic", "is_system")
    op.drop_column("knowledge_topic", "system_type")
