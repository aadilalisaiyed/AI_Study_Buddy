from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_updated", "user_id", "updated_at", "id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationDocument(Base):
    __tablename__ = "conversation_documents"
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_messages_status"),
        CheckConstraint("(status = 'pending') = (expires_at IS NOT NULL)", name="ck_messages_pending"),
        UniqueConstraint("conversation_id", "request_id", "role", name="uq_messages_request_role"),
        Index("ix_messages_conversation_ordinal", "conversation_id", "ordinal"),
        Index("ix_messages_pending", "conversation_id", "expires_at", postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    request_id: Mapped[UUID]
    ordinal: Mapped[int] = mapped_column(BigInteger, Identity())
    role: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text, default="")
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ChatUsage(Base):
    __tablename__ = "chat_usage"
    __table_args__ = (Index("ix_chat_usage_owner_created", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
