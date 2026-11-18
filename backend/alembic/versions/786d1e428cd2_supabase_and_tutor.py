"""Tag original storage and add conversations, messages, and request limits."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "786d1e428cd2"
down_revision = "c38b106cc485"
branch_labels = None
depends_on = None

READY = (
    "status <> 'READY' OR (checksum IS NOT NULL AND {storage} "
    "AND page_count > 0 AND chunk_count > 0 AND vector_collection IS NOT NULL AND processed_at IS NOT NULL)"
)


def upgrade():
    op.add_column("documents", sa.Column("storage_provider", sa.String(16), nullable=False, server_default="gcs"))
    op.alter_column("documents", "storage_provider", server_default="supabase")
    op.drop_constraint("ck_documents_ready", "documents", type_="check")
    op.create_check_constraint("ck_documents_ready", "documents", READY.format(
        storage="(storage_provider = 'supabase' OR storage_generation IS NOT NULL)",
    ))
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_conversations_owner_updated", "conversations", ["user_id", "updated_at", "id"])
    op.create_table(
        "conversation_documents",
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_conversation_documents_document_id", "conversation_documents", ["document_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("token_usage", postgresql.JSONB()),
        sa.Column("model", sa.String(80)),
        sa.Column("error_code", sa.String(40)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_messages_status"),
        sa.CheckConstraint("(status = 'pending') = (expires_at IS NOT NULL)", name="ck_messages_pending"),
        sa.UniqueConstraint("conversation_id", "request_id", "role", name="uq_messages_request_role"),
    )
    op.create_index("ix_messages_conversation_ordinal", "messages", ["conversation_id", "ordinal"])
    op.create_index("ix_messages_pending", "messages", ["conversation_id", "expires_at"], postgresql_where=sa.text("status = 'pending'"))
    op.create_table(
        "chat_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_usage_owner_created", "chat_usage", ["user_id", "created_at"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM documents WHERE storage_provider = 'supabase')")).scalar():
        raise RuntimeError("Export Supabase documents before downgrading their storage metadata.")
    op.drop_table("chat_usage")
    op.drop_table("messages")
    op.drop_table("conversation_documents")
    op.drop_table("conversations")
    op.drop_constraint("ck_documents_ready", "documents", type_="check")
    op.create_check_constraint("ck_documents_ready", "documents", READY.format(storage="storage_generation IS NOT NULL"))
    op.drop_column("documents", "storage_provider")
