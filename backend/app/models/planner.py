from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"
    __table_args__ = (CheckConstraint("status IN ('connected','disconnected','reconnect_required')", name="ck_calendar_connection_status"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(25))
    google_account_id: Mapped[str | None] = mapped_column(String(180))
    google_email: Mapped[str | None] = mapped_column(String(320))
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    selected_calendar: Mapped[dict | None] = mapped_column(JSONB)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OAuthState(Base):
    __tablename__ = "calendar_oauth_states"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticket_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    state_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    browser_digest: Mapped[str | None] = mapped_column(String(64))
    encrypted_verifier: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RevisionPreferences(Base):
    __tablename__ = "revision_preferences"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RevisionSession(Base):
    __tablename__ = "revision_sessions"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_revision_duration"),
        CheckConstraint("status IN ('scheduled','completed','cancelled')", name="ck_revision_status"),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="ck_revision_completed"),
        Index("ix_revision_owner_start", "user_id", "start_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(100))
    topic: Mapped[str] = mapped_column(String(100))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(100))
    reminder_minutes: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    source_quiz_id: Mapped[UUID | None] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RevisionDocument(Base):
    __tablename__ = "revision_session_documents"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("revision_sessions.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True)


class CalendarEventLink(Base):
    __tablename__ = "calendar_event_links"
    __table_args__ = (UniqueConstraint("account_id", "calendar_id", "event_id", name="uq_calendar_event"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("revision_sessions.id", ondelete="CASCADE"), unique=True)
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("calendar_connections.id", ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(String(180))
    calendar_id: Mapped[str] = mapped_column(String(500))
    event_id: Mapped[str] = mapped_column(String(200))
    etag: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(240))


class RevisionProposal(Base):
    __tablename__ = "revision_proposals"
    __table_args__ = (
        CheckConstraint("action IN ('create','update','cancel','sync')", name="ck_revision_proposal_action"),
        CheckConstraint("status IN ('pending','approved','failed','done')", name="ck_revision_proposal_status"),
        UniqueConstraint("user_id", "request_id", name="uq_revision_proposal_request"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    request_id: Mapped[UUID]
    fingerprint: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("revision_sessions.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(12))
    before_version: Mapped[int | None]
    applied_version: Mapped[int | None]
    payload: Mapped[dict] = mapped_column(JSONB)
    destination: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(240))


class CalendarRate(Base):
    __tablename__ = "calendar_rate"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int]
