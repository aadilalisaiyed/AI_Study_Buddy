"""Add owned documents and the durable document queue.

Revision ID: c38b106cc485
Revises: 07b92e8d420c
"""
import sqlalchemy as sa
from alembic import op

revision = "c38b106cc485"
down_revision = "07b92e8d420c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("storage_key", sa.String(300), unique=True, nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64)),
        sa.Column("storage_generation", sa.BigInteger()),
        sa.Column("page_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.Enum(
            "PENDING", "UPLOADING", "UPLOADED", "PROCESSING", "READY", "FAILED", "DELETING",
            native_enum=False, create_constraint=True, name="ck_documents_status", length=16,
        ), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("vector_collection", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("file_size >= 0 AND page_count >= 0 AND chunk_count >= 0 AND attempts >= 0", name="ck_documents_nonnegative"),
        sa.CheckConstraint(
            "status <> 'READY' OR (checksum IS NOT NULL AND storage_generation IS NOT NULL "
            "AND page_count > 0 AND chunk_count > 0 AND vector_collection IS NOT NULL AND processed_at IS NOT NULL)",
            name="ck_documents_ready",
        ),
    )
    op.create_index("ix_documents_owner_created", "documents", ["user_id", "created_at", "id"])
    op.create_index("ix_documents_status_due", "documents", ["status", "next_attempt_at"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])


def downgrade():
    op.drop_table("documents")
