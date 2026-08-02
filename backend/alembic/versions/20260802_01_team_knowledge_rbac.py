"""Add team knowledge RBAC.

revision = "20260802_01"
down_revision = "20260728_01"
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_01"
down_revision = "20260728_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_topic",
        sa.Column("governance_status", sa.String(length=32), nullable=False, server_default="personal"),
    )
    op.add_column("knowledge_topic", sa.Column("transfer_requested_by", sa.CHAR(length=36), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_requested_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_message", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_reviewed_by", sa.CHAR(length=36), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("transfer_rejection_reason", sa.Text(), nullable=True))
    op.create_index("ix_knowledge_topic_governance_status", "knowledge_topic", ["governance_status"], unique=False)

    op.create_table(
        "team_member",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", sa.CHAR(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_team_member_tenant_user"),
    )
    op.create_index("ix_team_member_tenant_role", "team_member", ["tenant_id", "role"], unique=False)

    op.create_table(
        "knowledge_base_membership",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(length=36), nullable=False),
        sa.Column("user_id", sa.CHAR(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("granted_by", sa.CHAR(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "kb_uid", "user_id", name="uq_kb_membership_scope_user"),
    )
    op.create_index("ix_kb_membership_user", "knowledge_base_membership", ["tenant_id", "user_id"], unique=False)
    op.create_index("ix_kb_membership_kb", "knowledge_base_membership", ["tenant_id", "kb_uid"], unique=False)

    op.create_table(
        "knowledge_access_audit_log",
        sa.Column("id", sa.CHAR(length=36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(length=36), nullable=False),
        sa.Column("kb_uid", sa.CHAR(length=36), nullable=True),
        sa.Column("actor_id", sa.CHAR(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.CHAR(length=36), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_access_audit_scope_created",
        "knowledge_access_audit_log",
        ["tenant_id", "kb_uid", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_kb_access_audit_actor",
        "knowledge_access_audit_log",
        ["tenant_id", "actor_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_kb_access_audit_actor", table_name="knowledge_access_audit_log")
    op.drop_index("ix_kb_access_audit_scope_created", table_name="knowledge_access_audit_log")
    op.drop_table("knowledge_access_audit_log")
    op.drop_index("ix_kb_membership_kb", table_name="knowledge_base_membership")
    op.drop_index("ix_kb_membership_user", table_name="knowledge_base_membership")
    op.drop_table("knowledge_base_membership")
    op.drop_index("ix_team_member_tenant_role", table_name="team_member")
    op.drop_table("team_member")
    op.drop_index("ix_knowledge_topic_governance_status", table_name="knowledge_topic")
    op.drop_column("knowledge_topic", "transfer_rejection_reason")
    op.drop_column("knowledge_topic", "transfer_reviewed_at")
    op.drop_column("knowledge_topic", "transfer_reviewed_by")
    op.drop_column("knowledge_topic", "transfer_message")
    op.drop_column("knowledge_topic", "transfer_requested_at")
    op.drop_column("knowledge_topic", "transfer_requested_by")
    op.drop_column("knowledge_topic", "governance_status")
