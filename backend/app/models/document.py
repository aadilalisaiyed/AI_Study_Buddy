from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Enum, ForeignKey,
    Index, Integer, String, Text, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    DELETING = "DELETING"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("file_size >= 0 AND page_count >= 0 AND chunk_count >= 0 AND attempts >= 0", name="ck_documents_nonnegative"),
        CheckConstraint(
            "status <> 'READY' OR (checksum IS NOT NULL AND (storage_provider = 'supabase' OR storage_generation IS NOT NULL) "
            "AND page_count > 0 AND chunk_count > 0 AND vector_collection IS NOT NULL AND processed_at IS NOT NULL)",
            name="ck_documents_ready",
        ),
        Index("ix_documents_owner_created", "user_id", "created_at", "id"),
        Index("ix_documents_status_due", "status", "next_attempt_at"),
        Index("ix_documents_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL", name="fk_document_subject"))
    filename: Mapped[str] = mapped_column(String(240))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    content_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(64))
    storage_provider: Mapped[str] = mapped_column(String(16), server_default="supabase")
    storage_generation: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer, server_default="0")
    chunk_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False, create_constraint=True, name="ck_documents_status", length=16),
        server_default=DocumentStatus.PENDING.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vector_collection: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
